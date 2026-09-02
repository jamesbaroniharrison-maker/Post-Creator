"""Deterministic THBM anti-fatigue rotation.

Picks this post's funnel stage and execution variables (hook posture, length, structural
format, media pairing) as *code*, not as an instruction bundled into the drafting prompt.
The one thing that reliably breaks the local model on this codebase is asking it to
remember a rule like "don't repeat what you just did" alongside everything else it's
already juggling (the same lesson that split the PII scrub into its own narrow call) - so
the rotation itself never touches the LLM.
"""

import random
from datetime import date

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import Post

HOOK_POSTURES = [
    "empirical",
    "aspirational_contrast",
    "cost_arbitrage",
    "authority_listicle",
    "in_medias_res",
]
LENGTH_BUCKETS = ["micro", "standard", "deep"]
STRUCTURAL_FORMATS = ["narrative", "skimmable_index", "binary_contrast"]
MEDIA_PAIRINGS = ["candid_photo", "carousel", "infographic", "screenshot", "chart", "text_only"]

# Weekly funnel ratio rotation (Alpha/Beta/Gamma), so weeks lean differently toward
# visibility/trust/credibility rather than every week looking the same.
_RATIOS = {
    "alpha": ["TOF", "TOF", "MOF", "BOF"],
    "beta": ["TOF", "MOF", "MOF", "BOF"],
    "gamma": ["TOF", "MOF", "BOF", "BOF"],
}
_RATIO_ORDER = ["alpha", "beta", "gamma"]


def _week_ratio(scheduled_week: str) -> list[str]:
    """Deterministic per-week ratio pick, cycling alpha -> beta -> gamma -> alpha... keyed
    off the ISO week number so it's stable without needing to store anything extra."""
    iso_week = date.fromisoformat(scheduled_week).isocalendar()[1]
    return _RATIOS[_RATIO_ORDER[iso_week % len(_RATIO_ORDER)]]


def _recent_posts(limit: int = 3) -> list[Post]:
    with rx.session(url=config.db_url) as session:
        return list(
            session.exec(sqlmodel.select(Post).order_by(Post.created_at.desc()).limit(limit))
        )


def _pick_excluding(options: list[str], used: set[str]) -> str:
    remaining = [o for o in options if o not in used] or options
    return random.choice(remaining)


def assign_rotation(scheduled_week: str | None = None) -> dict:
    """Pick this post's funnel stage + THBM execution variables, excluding whatever the
    last 3 posts used, per the framework's anti-fatigue rule."""
    recent = _recent_posts()
    used_hooks = {p.hook_posture for p in recent if p.hook_posture}
    used_lengths = {p.length_bucket for p in recent if p.length_bucket}
    used_formats = {p.structural_format for p in recent if p.structural_format}
    used_media = {p.media_pairing for p in recent if p.media_pairing}

    funnel_stage = random.choice(_week_ratio(scheduled_week) if scheduled_week else ["TOF", "MOF", "BOF"])

    return {
        "funnel_stage": funnel_stage,
        "hook_posture": _pick_excluding(HOOK_POSTURES, used_hooks),
        "length_bucket": _pick_excluding(LENGTH_BUCKETS, used_lengths),
        "structural_format": _pick_excluding(STRUCTURAL_FORMATS, used_formats),
        "media_pairing": _pick_excluding(MEDIA_PAIRINGS, used_media),
    }
