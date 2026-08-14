"""Merges keyness + structural + LLM close-read into the single voice_profile row (spec Â§3c, Â§9)."""

import json
from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.models import VoiceProfile
from wpa_content_engine.voice_engine.close_read import llm_close_read
from wpa_content_engine.voice_engine.ingestion import get_all_sample_texts
from wpa_content_engine.voice_engine.keyness import compute_keyness
from wpa_content_engine.voice_engine.structural import compute_structural_stats

# Picking the shortest posts would mostly surface one-line reactions ("Very proud of
# this girl!") which don't show the drafting engine what a full post looks like. Posts
# closest to the corpus's own median length are more representative of an actual post.
_FEW_SHOT_COUNT = 3


def _pick_few_shot_examples(texts: list[str]) -> list[str]:
    if not texts:
        return []
    lengths = sorted(len(t) for t in texts)
    median_len = lengths[len(lengths) // 2]
    return sorted(texts, key=lambda t: abs(len(t) - median_len))[:_FEW_SHOT_COUNT]


def build_profile() -> dict:
    """Run the full voice-profile pipeline against every banked sample. Does not save."""
    texts = get_all_sample_texts()

    profile = {
        "sample_count": len(texts),
        "keyness": compute_keyness(texts),
        "structural": compute_structural_stats(texts),
        "llm_close_read": llm_close_read(texts),
        "few_shot_examples": _pick_few_shot_examples(texts),
    }
    return profile


def save_profile(profile: dict) -> VoiceProfile:
    """Regenerate the single voice_profile row (spec Â§9: one row, replaced as the corpus grows)."""
    row = VoiceProfile(
        generated_at=datetime.now(timezone.utc),
        profile_json=json.dumps(profile, ensure_ascii=False),
    )
    with rx.session(url=config.db_url) as session:
        session.exec(sqlmodel.delete(VoiceProfile))
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def build_and_save_profile() -> VoiceProfile:
    """Convenience entrypoint: build the profile from whatever's currently banked, then save it."""
    return save_profile(build_profile())
