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

FUNNEL_STAGES = ["TOF", "MOF", "BOF"]

# What the dashboard's per-queued-topic dropdowns use for "let this field decide
# automatically" - not "standard", since LENGTH_BUCKETS already has a real, distinct
# "standard" value (see assign_rotation's docstring for the collision this avoided).
AUTO_SENTINEL = "auto"
HOOK_POSTURES = [
    "answer_first",
    "react_first",
    "empirical",
    "aspirational_contrast",
    "cost_arbitrage",
    "authority_listicle",
    "in_medias_res",
]
LENGTH_BUCKETS = ["micro", "standard", "deep"]
# The kinds of post (shape.py::KINDS decides which, per topic). The first three are the
# original fixed formats; the rest come from how James actually talks (VOICE-ANALYSIS.md).
STRUCTURAL_FORMATS = [
    "narrative",
    "skimmable_index",
    "binary_contrast",
    "quick_take",
    "observation",
    "argument",
    "it_depends",
    "repeat_and_undercut",
]
MEDIA_PAIRINGS = ["candid_photo", "carousel", "infographic", "screenshot", "chart", "text_only"]

# Plain-English meaning of every option, shown under the Topic Bank queue's dropdowns
# (request: "impossible to remember what all the keys mean"). Short versions of what
# draft.py actually tells the model for each one.
STYLE_HELP = {
    "funnel_stage": {
        AUTO_SENTINEL: "Picked for you, balancing the week.",
        "TOF": "Top of funnel - reach. Human, reflective or contrarian. No selling.",
        "MOF": "Middle - trust. A practical how-to, workflow or teardown people can use.",
        "BOF": "Bottom - proof. Real results and numbers; a soft call to action is allowed.",
    },
    "hook_posture": {
        AUTO_SENTINEL: "Picked for you, avoiding your last 3 openings.",
        "answer_first": "Opens with your actual view, straight away, no build-up.",
        "react_first": "Opens with your honest first reaction to the thing.",
        "empirical": "Opens on a specific, unrounded number or data point.",
        "aspirational_contrast": "States a common belief, then flips it.",
        "cost_arbitrage": "Old, slow/expensive way vs the new, cheap/fast way.",
        "authority_listicle": "Opens on your own observation, then promises a numbered list.",
        "in_medias_res": "Drops straight into the moment something changed or broke.",
    },
    "length_bucket": {
        AUTO_SENTINEL: "Picked for you from how much there is to say, varied from your recent posts.",
        "micro": "Short: under 150 words. Say it and stop.",
        "standard": "Medium: 150-300 words. Room for a story or an argument.",
        "deep": "Long: 300-420 words. Only when there's genuinely that much (max twice a month).",
    },
    "structural_format": {
        AUTO_SENTINEL: "Picked for you to suit the topic, avoiding your last 2 kinds.",
        "narrative": "A story told in order, building to the point.",
        "skimmable_index": "A short list of the points, one line each (only when there are several).",
        "binary_contrast": "'The old way' vs 'the better way', then a 2-3 step fix.",
        "quick_take": "A quick reaction: your view, one reason, done.",
        "observation": "Something you noticed, and what's really going on underneath.",
        "argument": "Your view, a fair nod to the other side, then why you still hold it.",
        "it_depends": "\"It depends\" - on what, the rule for each case, then your call.",
        "repeat_and_undercut": "A repeated line knocked down each time, then what it actually was.",
    },
    "media_pairing": {
        AUTO_SENTINEL: "Picked for you to suit the post type.",
        "candid_photo": "A real, unposed photo.",
        "carousel": "Swipeable slides (PDF).",
        "infographic": "One designed graphic summing it up.",
        "screenshot": "A screenshot of the thing being discussed.",
        "chart": "A chart of the key numbers.",
        "text_only": "No image - just the post.",
    },
}

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


# How James actually opens (VOICE-ANALYSIS.md rule 1): with the answer or with his reaction.
# These lead; the framework's postures stay in the mix for variety.
_HOOK_WEIGHTS = {"answer_first": 3.0, "react_first": 2.0}


def _pick_hook(used: set[str]) -> str:
    remaining = [h for h in HOOK_POSTURES if h not in used] or HOOK_POSTURES
    return random.choices(remaining, weights=[_HOOK_WEIGHTS.get(h, 1.0) for h in remaining], k=1)[0]


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


# Media pairing is weighted by post type, not picked evenly from 6 (which made "no
# picture" only 1 post in 6). A personal story without your own photo usually lands
# better as plain text; commentary leans toward a visual. Request: "sometimes
# recommend no pic... for certain ones". Roughly 30-40% text-only overall.
_MEDIA_WEIGHTS = {
    "personal_reflection": {"text_only": 0.55, "carousel": 0.10, "infographic": 0.10,
                            "screenshot": 0.15, "chart": 0.0, "candid_photo": 0.10},
    "default": {"text_only": 0.20, "carousel": 0.20, "infographic": 0.25,
                "screenshot": 0.15, "chart": 0.15, "candid_photo": 0.05},
}


def _pick_media(post_type: str | None, has_photo: bool, used: set[str]) -> str:
    """Your own photo always wins. Otherwise a weighted pick, excluding the last 3
    posts' pairings - except text-only, which is a resting state, not a "look" that
    gets stale, so it's never excluded."""
    if has_photo:
        return "candid_photo"
    weights = _MEDIA_WEIGHTS.get(post_type or "", _MEDIA_WEIGHTS["default"])
    options = [m for m, w in weights.items() if w > 0 and (m == "text_only" or m not in used)]
    return random.choices(options, weights=[weights[m] for m in options], k=1)[0]


def assign_rotation(
    scheduled_week: str | None = None,
    overrides: dict[str, str] | None = None,
    post_type: str | None = None,
    has_photo: bool = False,
    also_exclude: list[dict] | None = None,
) -> dict:
    """Pick this post's funnel stage + THBM execution variables, excluding whatever the
    last 3 posts used, per the framework's anti-fatigue rule (length is handled
    separately - see _pick_length_bucket).

    `overrides` (request: "if I don't put an option, it just becomes a standard post...
    but I want to actually be able to choose for certain ones what kind of style I
    want") lets a caller force specific fields instead of letting this function pick
    them - e.g. queuing a topic with "Hook posture: in medias res" chosen explicitly
    while leaving everything else on auto. Any field left out of `overrides` (or set
    to the AUTO_SENTINEL the dashboard uses for "let it decide as normal") is picked
    exactly as before - this never changes the default, no-override behaviour.

    AUTO_SENTINEL is deliberately not the string "standard" - LENGTH_BUCKETS already
    has a real, different "standard" value (the sweet-spot length choice), so reusing
    that word as the dashboard's "auto-decide" sentinel would make a length-bucket
    dropdown show "Standard" twice with no way to tell them apart, and would silently
    treat "force standard length" the same as "don't force anything" - confirmed live
    while testing this, not a hypothetical."""
    recent = _recent_posts()
    used_hooks = {p.hook_posture for p in recent if p.hook_posture}
    used_formats = {p.structural_format for p in recent if p.structural_format}
    used_media = {p.media_pairing for p in recent if p.media_pairing}
    # Rotations already picked for posts not saved yet (prepare_week drafts several days
    # at once, so they'd otherwise all see the same "last 3 posts" and match each other).
    for r in also_exclude or []:
        used_hooks.add(r.get("hook_posture"))
        used_formats.add(r.get("structural_format"))
        used_media.add(r.get("media_pairing"))

    funnel_stage = random.choice(_week_ratio(scheduled_week) if scheduled_week else FUNNEL_STAGES)

    result = {
        "funnel_stage": funnel_stage,
        "hook_posture": _pick_hook(used_hooks),
        "length_bucket": _pick_length_bucket(),
        "structural_format": _pick_excluding(STRUCTURAL_FORMATS, used_formats),
        "media_pairing": _pick_media(post_type, has_photo, used_media),
    }
    # A rotation dict passed back in (planning.py drafts a pre-assigned week this way) carries
    # "_auto": the fields that were picked automatically and should stay free, so the shape
    # planner can still fit length and kind to the topic instead of treating them as forced.
    overrides = overrides or {}
    still_auto = set(overrides.get("_auto", []))
    forced = set()
    for key, value in overrides.items():
        if key.startswith("_"):
            continue
        if key in still_auto:  # keep the week's pre-picked value, but leave it free
            if value and value != AUTO_SENTINEL:
                result[key] = value
            continue
        if value and value != AUTO_SENTINEL:
            result[key] = value
            forced.add(key)
    # Which fields nobody chose: draft.py's shape planner decides length and kind for these.
    result["_auto"] = [k for k in list(result) if k not in forced]
    result["_post_type"] = post_type
    return result
