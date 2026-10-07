"""Orchestrates the pattern: research a topic, assign this post's THBM rotation
variables, then draft a post in the author's voice.

Level 4 scope: topic in, structured draft out, saved to `posts`. Level 5 wires this up
to the daily research cron + topic bank so topics don't have to be supplied by hand.
"""

import json
import os
from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.angles import classify_angle
from linkedin_content_engine.drafting_engine.draft import (
    _HOW_JAMES_WRITES as HOW_JAMES_WRITES,
    _redact_money,
    _strip_em_dash,
    best_of_n_draft_post,
    grounding_sources,
    invented_specifics,
    remember_draft,
)
from linkedin_content_engine.drafting_engine.grounding import new_scene_details, unsupported_personal_claims
from linkedin_content_engine.drafting_engine.openings import sharpen_opening
from linkedin_content_engine.drafting_engine.voice_pass import voice_pass
from linkedin_content_engine.drafting_engine.research import ResearchResult, research_topic
from linkedin_content_engine.drafting_engine.rotation import assign_rotation
from linkedin_content_engine.models import Post, TopicBank, VoiceProfile
from linkedin_content_engine.voice_engine.fingerprint import reference_from_corpus as voice_reference_from_corpus
from linkedin_content_engine.voice_engine.fingerprint import score_text as score_voice
from linkedin_content_engine.voice_engine.ingestion import get_weighted_samples_by_register
from linkedin_content_engine.voice_engine.similarity import primary_voice_delta


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
    rotation_overrides: dict[str, str] | None = None,
    source_photo: str | None = None,
) -> Post:
    """Draft and save one post, given research that's already been gathered.

    Used directly by the dashboard's "generate from topic bank" action (spec Â§3d),
    where the bank row's own summary/source already is the research - no need to
    re-search. `rotation_overrides` (request: per-queued-topic style dropdowns on
    the Topic Bank's batch-draft queue) forces specific THBM fields instead of
    letting assign_rotation pick them - anything left unset stays fully automatic.
    """
    voice_profile = load_voice_profile()
    rotation = assign_rotation(overrides=rotation_overrides, post_type=post_type, has_photo=bool(source_photo))
    # Drafts DRAFT_BEST_OF_N independent candidates (default 3) and keeps whichever
    # one measures closest to the real corpus, rather than just the first attempt -
    # request: "I don't care if generation takes a while. As long as it is what I
    # want." voice_delta comes back already computed by the selection itself, not
    # recalculated here against a possibly-different corpus snapshot.
    draft, voice_delta = best_of_n_draft_post(topic, voice_profile, research, rotation)

    # Sharpen the first line (openings.py): a better opening only replaces the old one
    # when it scores clearly higher and doesn't pull the post away from your voice.
    reference = voice_reference_from_corpus()

    # Voice pass (voice_pass.py): one focused rewrite into his voice, kept only if it passes
    # every fact guard and sounds clearly more like him.
    research_texts = [f.content for f in research.findings] if research.findings else []
    new_text, voice_pass_note = voice_pass(draft.text, topic, research_texts, HOW_JAMES_WRITES, reference)
    if new_text != draft.text:
        draft.text = new_text if research.findings else _redact_money(new_text)
        voice_delta = primary_voice_delta(draft.text, get_weighted_samples_by_register())

    opening_score, opening_note = None, ""
    if os.environ.get("SHARPEN_OPENINGS", "1") != "0":
        new_text, opening_score, opening_note = sharpen_opening(draft.text, topic)
        if new_text != draft.text:
            new_text = _strip_em_dash(new_text if research.findings else _redact_money(new_text))
            new_delta = primary_voice_delta(new_text, get_weighted_samples_by_register())
            # The sharper opening has to keep the post sounding like you: judged on the
            # "sounds like you" score, which tells his writing from machine copy far better
            # than Delta does.
            if score_voice(new_text, reference).score < score_voice(draft.text, reference).score - 5:
                opening_note = "Kept the original opening - the sharper one didn't sound like you."
                opening_score = None
            else:
                draft.text, voice_delta = new_text, new_delta if new_delta is not None else voice_delta

    voice = score_voice(draft.text, reference)

    # Any personal story still in the final text that nothing you gave supports (grounding.py)
    # goes to the top of the compliance note, so it can't be missed in Review.
    sources = grounding_sources(topic, research)
    invented = invented_specifics(draft.text, sources, personal=not research.findings)
    if invented:
        draft.compliance_note = (
            f"CHECK THESE - not in anything you gave it: {', '.join(dict.fromkeys(invented[:6]))}. "
            + (draft.compliance_note or "")
        ).strip()
    unsupported = unsupported_personal_claims(draft.text, sources)
    if unsupported:
        lines = " / ".join(f'"{s}"' for s in unsupported[:3])
        draft.compliance_note = (
            f"CHECK THIS IS TRUE - nothing you gave mentions it: {lines}. "
            + (draft.compliance_note or "")
        ).strip()
    if not research.findings:
        # A post from his own note: scene details the note never mentioned (laptop, room...)
        # may be the model filling in the picture. Harmless if right, invented if not.
        scene = new_scene_details(draft.text, sources)
        if scene:
            draft.compliance_note = (
                f"Details not in your note ({', '.join(scene[:6])}) - check they're right. "
                + (draft.compliance_note or "")
            ).strip()
    remember_draft(draft.text)

    post = Post(
        post_type=post_type,
        status="drafted",
        draft_text=draft.text,
        original_text=draft.text,  # kept as written; edits in Review only change draft_text
        voice_score=voice.score,
        voice_notes=" ".join(
            part for part in (voice_pass_note, f"Still off: {voice.summary()}." if voice.summary() else "") if part
        )
        or None,
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
        source_photo=source_photo,
        opening_score=opening_score,
        opening_note=opening_note or None,
    )
    category = {"ai_commentary": "ai", "market_commentary": "market", "opinion": "ai"}.get(post_type)
    if category:
        with rx.session(url=config.db_url) as session:
            bank = session.get(TopicBank, source_bank_id) if source_bank_id else None
        post.topic_angle = (bank.topic_angle if bank and bank.topic_angle else None) or classify_angle(
            f"{topic} {draft.text}", bank.category if bank else category
        )

    with rx.session(url=config.db_url) as session:
        session.add(post)
        session.commit()
        session.refresh(post)

    # Two-step generation (request: "post first then designs after, if I don't like
    # the post I don't want to waste on the designs"): no visual here. It's made when
    # the post is accepted (DashboardState.accept), or on demand with "Make a visual".
    return post


def generate_and_save_draft(
    topic: str,
    post_type: str,
    source_bank_id: int | None = None,
    skip_research: bool = False,
    source_photo: str | None = None,
    rotation_overrides: dict[str, str] | None = None,
) -> Post:
    """Research (unless skipped) and draft one post, then save it as a `posts` row."""
    research = (
        research_topic(topic)
        if not skip_research
        else ResearchResult(topic=topic, status="ok", findings=[])
    )
    return generate_draft_with_research(
        topic, post_type, research, source_bank_id, rotation_overrides=rotation_overrides, source_photo=source_photo
    )
