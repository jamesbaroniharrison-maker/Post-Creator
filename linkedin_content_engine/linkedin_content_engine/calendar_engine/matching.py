"""Links a ticked occasion to a real Topic Bank finding by meaning, using the same
local embeddings as voice retrieval (nomic-embed-text via Ollama). Ported from the
Ben Holmes calendar engine.

Candidate embeddings are computed the first time they're needed and cached on the
row (TopicBank.embedding), so each finding is only ever embedded once. Only recent
findings are considered - an occasion should link to current news, not a month-old
story - which also keeps the first run's embedding cost bounded.
"""

import json
from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import CalendarEvent, TopicBank
from linkedin_content_engine.voice_engine.embeddings import cosine, embed

# Cosine similarity below this counts as "not actually related". A starting point,
# not calibrated - same "revisit once there's real data" stance as the original.
MATCH_THRESHOLD = 0.55
CANDIDATE_WINDOW_DAYS = 21
MAX_CANDIDATES = 120


def _candidates(now: datetime) -> list[TopicBank]:
    since = now - timedelta(days=CANDIDATE_WINDOW_DAYS)
    with rx.session(url=config.db_url) as session:
        return list(
            session.exec(
                sqlmodel.select(TopicBank)
                .where(
                    TopicBank.used == False,  # noqa: E712
                    TopicBank.tier != "discard",
                    TopicBank.calendar_event_id == None,  # noqa: E711
                    sqlmodel.col(TopicBank.date_found) >= since,
                )
                .order_by(sqlmodel.col(TopicBank.date_found).desc())
                .limit(MAX_CANDIDATES)
            )
        )


def _vector_for(row: TopicBank) -> list[float] | None:
    """Cached embedding, or compute + cache it now."""
    if row.embedding:
        try:
            return json.loads(row.embedding)
        except json.JSONDecodeError:
            pass
    vector = embed(row.summary)
    if vector is None:
        return None
    with rx.session(url=config.db_url) as session:
        stored = session.get(TopicBank, row.id)
        if stored:
            stored.embedding = json.dumps(vector)
            session.add(stored)
            session.commit()
    return vector


def find_best_topic_bank_match(event: CalendarEvent, now: datetime | None = None) -> TopicBank | None:
    """The closest recent unused finding to this occasion, or None if nothing clears
    MATCH_THRESHOLD (or embeddings are unreachable - the caller then banks the
    occasion's own angle instead of guessing a link)."""
    now = now or datetime.now(timezone.utc)
    query_vec = embed(f"{event.name}. {event.angle_notes}")
    if query_vec is None:
        return None
    best, best_score = None, MATCH_THRESHOLD
    for candidate in _candidates(now):
        vec = _vector_for(candidate)
        if vec is None:
            continue
        score = cosine(query_vec, vec)
        if score > best_score:
            best, best_score = candidate, score
    return best
