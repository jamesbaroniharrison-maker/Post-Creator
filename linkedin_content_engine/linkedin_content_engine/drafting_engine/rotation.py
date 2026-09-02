"""Deterministic THBM anti-fatigue rotation.

Picks this post's funnel stage and execution variables (hook posture, length, structural
format, media pairing) as *code*, not as an instruction bundled into the drafting prompt.
The one thing that reliably breaks the local model on this codebase is asking it to
remember a rule like "don't repeat what you just did" alongside everything else it's
already juggling (the same lesson that split the PII scrub into its own narrow call) - so
the rotation itself never touches the LLM.
"""

import random
from datetime import date, datetime, timezone

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

# Length isn't rotated on the same "never repeat the last one" anti-fatigue basis as
# the other variables - that would fight against actually landing in the sweet spot
# most of the time. Instead it's weighted (request: "ideally sit in the sweet spot but
# also have long and short ones... long on very occasion") plus a hard monthly cap on
# "deep" (request: "once to max twice a month"), checked against real post history,
# not just excluded from the last 3.
_LENGTH_WEIGHTS = {"micro": 0.25, "standard": 0.68, "deep": 0.07}
_DEEP_MONTHLY_CAP = 2

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


def _deep_posts_this_month() -> int:
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(Post).where(
                Post.length_bucket == "deep",
                sqlmodel.col(Post.created_at) >= month_start,
            )
        ).all()
    return len(rows)


def _pick_length_bucket() -> str:
    """Weighted toward the "sweet spot" (standard), with short posts as a regular but
    less frequent change of pace, and long posts deliberately rare - hard-capped at
    _DEEP_MONTHLY_CAP for the calendar month, not just left to chance."""
    options = list(LENGTH_BUCKETS)
    if _deep_posts_this_month() >= _DEEP_MONTHLY_CAP:
        options.remove("deep")
    weights = [_LENGTH_WEIGHTS[o] for o in options]
    return random.choices(options, weights=weights, k=1)[0]


def assign_rotation(scheduled_week: str | None = None) -> dict:
    """Pick this post's funnel stage + THBM execution variables, excluding whatever the
    last 3 posts used, per the framework's anti-fatigue rule (length is handled
    separately - see _pick_length_bucket)."""
    recent = _recent_posts()
    used_hooks = {p.hook_posture for p in recent if p.hook_posture}
    used_formats = {p.structural_format for p in recent if p.structural_format}
    used_media = {p.media_pairing for p in recent if p.media_pairing}

    funnel_stage = random.choice(_week_ratio(scheduled_week) if scheduled_week else ["TOF", "MOF", "BOF"])

    return {
        "funnel_stage": funnel_stage,
        "hook_posture": _pick_excluding(HOOK_POSTURES, used_hooks),
        "length_bucket": _pick_length_bucket(),
        "structural_format": _pick_excluding(STRUCTURAL_FORMATS, used_formats),
        "media_pairing": _pick_excluding(MEDIA_PAIRINGS, used_media),
    }
