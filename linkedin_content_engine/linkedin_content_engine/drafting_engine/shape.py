"""Post shape planning: how long, how many paragraphs, and what kind of post, decided per topic.

Why this exists (request: "they feel like they follow a pattern of style, not like a human who changes
lengths and paragraphs depending on topic"): before this, rotation.py picked length and format at random
from three fixed buckets and three fixed templates, and the prompt pushed every post through the same
Hook -> Context -> Value -> Proof -> Ending arc. A quick reaction and a personal story came out with the
same skeleton.

Now the shape follows the material:
- how much there actually is to say (research findings, length of your note, post type) sets the length,
  as a specific word target rather than a bucket;
- the kind of post (a quick take, a story, an "it depends", a concede-then-hold argument...) comes from a
  library built from how James actually talks (VOICE-ANALYSIS.md), not from LinkedIn templates;
- paragraph rhythm is planned unevenly, the way people really write;
- recent posts are measured from their actual text, and the plan steers away from repeating their
  length, paragraph count and kind.

Everything here is plain code (no model call), for the same reason rotation.py gives: the model is bad at
remembering "don't repeat what you did last time" alongside everything else, so code decides.
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass

# --------------------------------------------------------------------------- the library of post kinds
# words: (min, max) for this kind; paras: (min, max) paragraphs; exemplars: which persona exemplar
# shapes suit it (persona.PERSONA_EXEMPLARS tags); needs_points: only when the material has several
# separate points.
KINDS: dict[str, dict] = {
    "quick_take": {
        "words": (45, 120), "paras": (1, 2), "exemplars": ["narrative", "binary_contrast"],
        "guide": "A quick reaction. Say what you think in the very first line, give the one reason or "
        "example that matters, and stop. No setup, no lesson, no recap. It's fine to be one paragraph.",
    },
    "observation": {
        "words": (90, 190), "paras": (2, 4), "exemplars": ["narrative", "binary_contrast"],
        "guide": "Something you noticed. Say it plainly, then what's really going on underneath it (how "
        "it looks versus how it actually is), and land on one short, plain verdict.",
    },
    "narrative": {
        "words": (150, 320), "paras": (3, 6), "exemplars": ["narrative"],
        "guide": "A story told in order. Start in the moment or with one line of context, let it unfold, "
        "and let the point arrive at the end in plain words. Some paragraphs long, some a single line.",
    },
    "argument": {
        "words": (120, 260), "paras": (2, 5), "exemplars": ["binary_contrast", "narrative"],
        "guide": "Your concede-then-hold move. State your position first. Give the other side its due in "
        "a sentence (e.g. \"I get why people think X, but...\"), then hold the line with one concrete, "
        "small-scale example. No lecture.",
    },
    "it_depends": {
        "words": (110, 240), "paras": (2, 5), "exemplars": ["binary_contrast", "narrative"],
        "guide": "Your \"it depends\" move. Say it depends and exactly on what, give the plain rule for "
        "each case (\"If..., then... If..., then...\"), and finish with your own call.",
    },
    "repeat_and_undercut": {
        "words": (100, 220), "paras": (3, 6), "exemplars": ["narrative"],
        "guide": "Set up a repeated line and knock it down each time (like \"Was it the mastermind behind "
        "it... no. Was it running the whole thing... no.\"), then say what it actually was. Short lines "
        "are right here; use the repetition once, not as a gimmick throughout.",
    },
    "binary_contrast": {
        "words": (130, 280), "paras": (3, 5), "exemplars": ["binary_contrast"],
        "guide": "The old way versus the better way, shown through something concrete, then how to get "
        "from one to the other in a couple of plain steps.",
    },
    "skimmable_index": {
        "words": (170, 380), "paras": (4, 8), "exemplars": ["skimmable_index"], "needs_points": True,
        "guide": "A short intro, then the points as short items, each with one line of explanation. Only "
        "as many points as the material genuinely has (2 to 5), not always 3.",
    },
}

# How each post type leans (weights per kind). Personal posts lean to stories and observations,
# commentary to quick takes and arguments. Every kind stays possible somewhere.
_TYPE_WEIGHTS: dict[str, dict[str, float]] = {
    "personal_reflection": {"narrative": 0.30, "observation": 0.24, "quick_take": 0.16, "argument": 0.10,
                            "repeat_and_undercut": 0.10, "it_depends": 0.05, "binary_contrast": 0.05,
                            "skimmable_index": 0.0},
    "default": {"quick_take": 0.20, "observation": 0.15, "argument": 0.17, "it_depends": 0.12,
                "binary_contrast": 0.10, "narrative": 0.08, "repeat_and_undercut": 0.08,
                "skimmable_index": 0.10},
}

# Length buckets the dashboard and statistics already use, derived from the planned word count.
BUCKET_RANGES = {"micro": (45, 150), "standard": (150, 300), "deep": (300, 420)}

# How a post ends, varied rather than always the same kind of closing line.
_ENDINGS = [
    ("verdict", 0.55, "End on one short, plain verdict: a rule or a value, not a call to action."),
    ("you_rule", 0.20, "End with the plain rule you'd give someone in the same spot (\"If you..., just...\")."),
    ("aside", 0.12, "End with a dry, slightly self-deprecating aside rather than a lesson."),
    ("stop", 0.13, "Stop when the point is made. No closing line, no wrap-up."),
]


@dataclass
class ShapePlan:
    kind: str
    target_words: int
    low_words: int
    high_words: int
    paragraph_sizes: list[int]  # rough sentences per paragraph, in order
    ending: str
    length_bucket: str
    guidance: str
    ending_guidance: str
    rhythm_guidance: str

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- measuring real posts


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def signature(text: str) -> dict:
    """What a post looks like on the page: length, paragraph count, and how uneven the paragraphs are."""
    paras = paragraphs(text)
    words = [len(re.findall(r"[A-Za-z0-9'£$%]+", p)) for p in paras] or [0]
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0] if text.strip() else ""
    return {
        "words": sum(words),
        "paras": len(paras),
        "spread": (max(words) - min(words)) if words else 0,
        "has_list": bool(re.search(r"^\s*(?:[-•*]|\d+[.)])\s", text, re.M)),
        "first_sentence_words": len(first.split()),
    }


def _too_similar(a: dict, b: dict) -> bool:
    """Two posts that look alike at a glance: same paragraph count and within 20% of each other's length."""
    if not a["words"] or not b["words"]:
        return False
    return a["paras"] == b["paras"] and abs(a["words"] - b["words"]) <= 0.2 * max(a["words"], b["words"])


# --------------------------------------------------------------------------- planning


def substance(topic: str, research_texts: list[str], post_type: str | None) -> float:
    """0..1: how much there is to say. More findings and a longer note justify a longer post; a single
    headline or a one-line thought does not."""
    research_words = sum(len(t.split()) for t in research_texts)
    topic_words = len(topic.split())
    score = 0.15
    score += min(len(research_texts), 5) * 0.08
    score += min(research_words / 800, 0.3)
    score += min(topic_words / 250, 0.25)
    if post_type == "personal_reflection" and topic_words > 120:
        score += 0.1
    return max(0.0, min(1.0, score))


def word_cap(subst: float, note_words: int | None = None) -> int:
    """The longest a post should be for this much material: about 150 words for a one-line thought,
    up to 420 for several solid findings. Longer than the material supports means padding, or worse,
    the model inventing detail to fill the space.

    A post written only from his own note (`note_words`, no research) is capped at roughly three
    times the note: a 20-word note was being stretched to 100-150 words in testing, and the model
    filled the gap with scenes he never described ("shutting a laptop lid at the kitchen table")."""
    cap = int(100 + 320 * subst)
    if note_words is not None:
        cap = min(cap, 40 + 3 * note_words)
    return max(cap, 45)


def _distinct_points(research_texts: list[str], topic: str) -> int:
    """Rough count of separate points available: findings, plus numbered/bulleted lines in the note."""
    listed = len(re.findall(r"^\s*(?:[-•*]|\d+[.)])\s", topic, re.M))
    return len([t for t in research_texts if t.strip()]) + listed


def _pick_kind(
    post_type: str | None,
    points: int,
    recent_kinds: list[str],
    subst: float,
    rng: random.Random,
    note_words: int | None = None,
) -> str:
    weights = dict(_TYPE_WEIGHTS.get(post_type or "", _TYPE_WEIGHTS["default"]))
    if points < 3:
        weights["skimmable_index"] = 0.0  # a list needs real separate points behind it
    cap = word_cap(subst, note_words)
    for k in weights:  # a kind that needs more words than the material has is off the table
        if KINDS[k]["words"][0] > cap - 10:
            weights[k] = 0.0
    if subst < 0.3:  # thin material: a quick take or an observation is the honest shape
        weights["quick_take"] *= 2.0
        weights["observation"] *= 1.5
    for k in recent_kinds[:2]:  # don't repeat either of the last two kinds
        if k in weights:
            weights[k] *= 0.1
    kinds = [k for k, w in weights.items() if w > 0]
    return rng.choices(kinds, weights=[weights[k] for k in kinds], k=1)[0]


def _pick_words(lo: int, hi: int, subst: float, recent: list[dict], rng: random.Random) -> int:
    """A specific target inside the kind's range, nudged up by substance, and kept clear of the last two
    posts' lengths so consecutive posts don't land at the same size."""
    for _ in range(20):
        centre = lo + (hi - lo) * (0.25 + 0.6 * subst)
        target = int(rng.triangular(lo, hi, centre))
        if all(abs(target - r["words"]) > 0.2 * max(target, r["words"] or 1) for r in recent[:2] if r["words"]):
            return target
    return target


WORDS_PER_SENTENCE = 14  # his median sentence length (VOICE-ANALYSIS.md)


def _split_unevenly(total: int, n: int, rng: random.Random) -> list[int]:
    """Share `total` sentences across `n` paragraphs, at least one each, deliberately uneven."""
    if n <= 1:
        return [max(1, total)]
    total = max(total, n)
    weights = [rng.choice([0.5, 1, 1, 1.5, 2, 3]) for _ in range(n)]
    sizes = [1] * n
    for _ in range(total - n):
        sizes[rng.choices(range(n), weights=weights, k=1)[0]] += 1
    return [min(s, 6) for s in sizes]  # past ~6 sentences a paragraph is a wall on a phone


def _pick_paragraphs(kind: str, target_words: int, recent: list[dict], rng: random.Random) -> list[int]:
    """Sentences per paragraph, adding up to roughly the word target, in a rhythm that isn't even."""
    lo, hi = KINDS[kind]["paras"]
    sentences = max(2, round(target_words / WORDS_PER_SENTENCE))
    natural = max(lo, min(hi, round(target_words / 55)))
    sizes = [sentences]
    for _ in range(20):
        n = max(lo, min(hi, natural + rng.choice([-1, 0, 0, 1])))
        n = min(n, sentences)
        sizes = _split_unevenly(sentences, n, rng)
        if n >= 3 and len(set(sizes)) == 1:  # never every paragraph the same size
            continue
        if not any(r["paras"] == n for r in recent[:2]):
            return sizes
    return sizes


def _rhythm_text(sizes: list[int]) -> str:
    if len(sizes) == 1:
        return f"One single paragraph of about {sizes[0]} sentences. Don't break it up."
    parts = " / ".join(f"{n} sentence{'s' if n > 1 else ''}" for n in sizes)
    return (
        f"{len(sizes)} paragraphs, roughly: {parts}. A guide to the rhythm, not an exact count, but keep "
        "the paragraphs uneven like this rather than evening them out, and do split it: separate "
        "paragraphs with a blank line (a double newline in the JSON text)."
    )


def plan_shape(
    topic: str,
    research_texts: list[str],
    post_type: str | None,
    recent_texts: list[str],
    forced_kind: str | None = None,
    forced_bucket: str | None = None,
    allow_deep: bool = True,
    recent_kinds: list[str] | None = None,
    rng: random.Random | None = None,
    extra_recent: list[dict] | None = None,
) -> ShapePlan:
    """Plan this post's shape. `forced_kind` / `forced_bucket` are dashboard choices (anything set there
    wins); `allow_deep` is False when this month's long-post cap has been reached; `recent_kinds` are
    the stored kinds of the latest posts, newest first; `extra_recent` are {"words", "paras"} of
    shapes planned for posts not written yet (a week being drafted in one go), newest first."""
    rng = rng or random.Random()
    recent = list(extra_recent or []) + [signature(t) for t in recent_texts if t and t.strip()]
    recent_kinds = recent_kinds or []
    subst = substance(topic, research_texts, post_type)
    points = _distinct_points(research_texts, topic)
    # Written only from his own note: the note is all the material there is.
    note_words = len(topic.split()) if not research_texts else None

    kind = (
        forced_kind
        if forced_kind in KINDS
        else _pick_kind(post_type, points, recent_kinds, subst, rng, note_words)
    )
    lo, hi = KINDS[kind]["words"]
    if forced_bucket in BUCKET_RANGES:
        b_lo, b_hi = BUCKET_RANGES[forced_bucket]
        lo, hi = max(lo, b_lo), min(hi, b_hi)
        if lo >= hi:  # the forced length wins over the kind's natural range
            lo, hi = b_lo, b_hi
    else:
        hi = min(hi, max(word_cap(subst, note_words), 60))
        lo = min(lo, hi - 20)
    if not allow_deep:
        hi = min(hi, BUCKET_RANGES["standard"][1])
        lo = min(lo, hi - 20)
    target = _pick_words(lo, hi, subst, recent, rng)
    sizes = _pick_paragraphs(kind, target, recent, rng)
    ending, _, ending_text = rng.choices(_ENDINGS, weights=[w for _, w, _ in _ENDINGS], k=1)[0]
    if kind == "quick_take" and ending == "you_rule":
        ending, ending_text = "verdict", _ENDINGS[0][2]

    bucket = "micro" if target < 150 else "standard" if target <= 300 else "deep"
    return ShapePlan(
        kind=kind,
        target_words=target,
        low_words=max(30, int(target * 0.8)),
        high_words=int(target * 1.2),
        paragraph_sizes=sizes,
        ending=ending,
        length_bucket=bucket,
        guidance=KINDS[kind]["guide"],
        ending_guidance=ending_text,
        rhythm_guidance=_rhythm_text(sizes),
    )


def fits_plan(text: str, plan: dict) -> bool:
    """Did a draft land roughly on its planned shape (length in range, paragraph count within one)?"""
    sig = signature(text)
    planned = len(plan["paragraph_sizes"])
    if planned >= 2 and sig["paras"] == 1:  # one solid block where paragraphs were planned
        return False
    # Short posts must hit the planned paragraph count exactly: allowing one either way let the
    # model settle on its favourite 3 paragraphs every time (5 of 5 in the first test).
    slack = 0 if planned <= 3 else 1
    return plan["low_words"] <= sig["words"] <= plan["high_words"] and abs(sig["paras"] - planned) <= slack


def repeats_recent(text: str, recent_texts: list[str]) -> bool:
    """Does this draft look like either of the last two posts at a glance?"""
    sig = signature(text)
    return any(_too_similar(sig, signature(t)) for t in recent_texts[:2] if t)
