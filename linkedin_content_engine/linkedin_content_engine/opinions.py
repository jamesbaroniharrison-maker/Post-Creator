"""Your take: every few days, offer a few strong research findings for James's own
opinion, and draft each answer into an "opinion" post (request: "every few days you
give me a couple of topics and I give my opinion on them and they get turned into a
post").

His answer is real material from him, so it meets the no-made-up-posts rule; the
finding itself is passed as research, so any fact in the post can be traced to it. An
opinion is never planned automatically - it only exists once he's given a take.
"""

from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.drafting_engine.research import ResearchFinding, ResearchResult
from linkedin_content_engine.models import OpinionPrompt, Post, TopicBank
from linkedin_content_engine.utils import as_utc
from linkedin_content_engine.voice_engine.ingestion import add_own_words

OPINION_EVERY_DAYS = 3
PROMPTS_PER_ROUND = 3
FRESH_WITHIN_DAYS = 14
OPINION_POST_TYPE = "opinion"


def open_prompts() -> list[tuple[OpinionPrompt, TopicBank]]:
    """Prompts waiting for an answer, newest first, with their findings."""
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(OpinionPrompt, TopicBank)
            .where(
                OpinionPrompt.bank_id == TopicBank.id,
                sqlmodel.col(OpinionPrompt.post_id).is_(None),
                sqlmodel.col(OpinionPrompt.skipped_at).is_(None),
            )
            .order_by(sqlmodel.col(OpinionPrompt.created_at).desc())
        ).all()
    return list(rows)


def offer_new_prompts(force: bool = False, now: datetime | None = None) -> int:
    """Adds up to PROMPTS_PER_ROUND new prompts: the best fresh high-tier findings not
    offered before, one per angle where possible. Without `force`, only runs when the
    last round is OPINION_EVERY_DAYS old (so the daily job can call it every day).
    Returns how many were added."""
    now = now or datetime.now(timezone.utc)
    with rx.session(url=config.db_url) as session:
        if not force:
            last = session.exec(
                sqlmodel.select(OpinionPrompt).order_by(sqlmodel.col(OpinionPrompt.created_at).desc())
            ).first()
            if last and now - as_utc(last.created_at) < timedelta(days=OPINION_EVERY_DAYS):
                return 0
        offered = set(session.exec(sqlmodel.select(OpinionPrompt.bank_id)).all())
        candidates = session.exec(
            sqlmodel.select(TopicBank)
            .where(
                TopicBank.used == False,  # noqa: E712
                TopicBank.tier == "high",
                sqlmodel.col(TopicBank.calendar_event_id).is_(None),
                TopicBank.date_found >= (now - timedelta(days=FRESH_WITHIN_DAYS)).replace(tzinfo=None),
                sqlmodel.col(TopicBank.id).not_in(offered or {-1}),
            )
            .order_by(sqlmodel.col(TopicBank.date_found).desc())
            .limit(60)
        ).all()
        picked, angles = [], set()
        for row in candidates:  # one per angle first
            if row.topic_angle not in angles:
                picked.append(row)
                angles.add(row.topic_angle)
            if len(picked) == PROMPTS_PER_ROUND:
                break
        for row in candidates:  # then top up if there weren't enough angles
            if len(picked) == PROMPTS_PER_ROUND:
                break
            if row not in picked:
                picked.append(row)
        for row in picked:
            session.add(OpinionPrompt(bank_id=row.id, created_at=now))
        session.commit()
    return len(picked)


def skip_prompt(prompt_id: int) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.get(OpinionPrompt, prompt_id)
        if row:
            row.skipped_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()


def draft_from_take(prompt_id: int, answer: str) -> Post:
    """Drafts an opinion post from his answer, grounded in the finding. Saves the
    answer first, so it isn't lost if drafting fails. Raises on failure."""
    from linkedin_content_engine.drafting_engine.pipeline import generate_draft_with_research

    answer = answer.strip()
    if not answer:
        raise ValueError("Write your take first.")
    with rx.session(url=config.db_url) as session:
        prompt = session.get(OpinionPrompt, prompt_id)
        bank = session.get(TopicBank, prompt.bank_id) if prompt else None
        if prompt is None or bank is None:
            raise ValueError("That topic no longer exists.")
        prompt.answer_text = answer
        session.add(prompt)
        session.commit()
        summary, title, url, bank_id = bank.summary, bank.source_title, bank.source_url, bank.id

    # His take is his own words on exactly the kind of topic the posts cover - the thing the
    # voice samples are shortest of - so it's kept as a sample too (voice_engine/ingestion.py).
    try:
        add_own_words(answer, question=f"Your take on: {title or summary[:120]}")
    except Exception:  # noqa: BLE001 - a sample that didn't save must never stop the draft
        pass

    topic = (
        f"James's own opinion - this is the point of the post. Keep his stance and his "
        f"reasons, in his words where possible; don't soften it or add claims he didn't "
        f"make:\n{answer}\n\nWhat he's reacting to: {summary}"
    )
    research = ResearchResult(
        topic=summary, status="ok", findings=[ResearchFinding(title=title, url=url, content=summary)]
    )
    post = generate_draft_with_research(topic, OPINION_POST_TYPE, research, source_bank_id=bank_id)

    with rx.session(url=config.db_url) as session:
        prompt = session.get(OpinionPrompt, prompt_id)
        prompt.post_id = post.id
        prompt.answered_at = datetime.now(timezone.utc)
        session.add(prompt)
        bank = session.get(TopicBank, bank_id)
        bank.used = True
        bank.date_used = datetime.now(timezone.utc)
        session.add(bank)
        session.commit()
    return post
