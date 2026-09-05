"""Orchestrates the pattern: research a topic, assign this post's THBM rotation
variables, then draft a post in the author's voice.

Level 4 scope: topic in, structured draft out, saved to `posts`. Level 5 wires this up
to the daily research cron + topic bank so topics don't have to be supplied by hand.
"""

import json
from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.drafting_engine.draft import best_of_n_draft_post
from linkedin_content_engine.drafting_engine.research import ResearchResult, research_topic
from linkedin_content_engine.drafting_engine.rotation import assign_rotation
from linkedin_content_engine.models import Post, VoiceProfile


def load_voice_profile() -> dict:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(VoiceProfile)).first()
    if row is None:
        msg = "No voice_profile row yet - run the level 3 voice engine first."
        raise RuntimeError(msg)
    return json.loads(row.profile_json)


def generate_draft_with_research(
    topic: str,
    post_type: str,
    research: ResearchResult,
    source_bank_id: int | None = None,
) -> Post:
    """Draft and save one post, given research that's already been gathered.

    Used directly by the dashboard's "generate from topic bank" action (spec Â§3d),
    where the bank row's own summary/source already is the research - no need to
    re-search.
    """
    voice_profile = load_voice_profile()
    rotation = assign_rotation()
    # Drafts DRAFT_BEST_OF_N independent candidates (default 3) and keeps whichever
    # one measures closest to the real corpus, rather than just the first attempt -
    # request: "I don't care if generation takes a while. As long as it is what I
    # want." voice_delta comes back already computed by the selection itself, not
    # recalculated here against a possibly-different corpus snapshot.
    draft, voice_delta = best_of_n_draft_post(topic, voice_profile, research, rotation)

    post = Post(
        post_type=post_type,
        status="drafted",
        draft_text=draft.text,
        hashtags=json.dumps(draft.hashtags),
        tags=json.dumps(draft.tags),
        suggested_day=draft.suggested_day,
        sources=json.dumps([s.model_dump() for s in draft.sources]),
        compliance_note=draft.compliance_note,
        source_bank_id=source_bank_id,
        created_at=datetime.now(timezone.utc),
        funnel_stage=rotation["funnel_stage"],
        hook_posture=rotation["hook_posture"],
        length_bucket=rotation["length_bucket"],
        structural_format=rotation["structural_format"],
        media_pairing=rotation["media_pairing"],
        media_note=draft.media_note,
        voice_delta=voice_delta,
    )
    with rx.session(url=config.db_url) as session:
        session.add(post)
        session.commit()
        session.refresh(post)
    return post


def generate_and_save_draft(
    topic: str,
    post_type: str,
    source_bank_id: int | None = None,
    skip_research: bool = False,
) -> Post:
    """Research (unless skipped) and draft one post, then save it as a `posts` row."""
    research = (
        research_topic(topic)
        if not skip_research
        else ResearchResult(topic=topic, status="ok", findings=[])
    )
    return generate_draft_with_research(topic, post_type, research, source_bank_id)
