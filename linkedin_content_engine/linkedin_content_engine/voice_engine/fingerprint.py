""""Sounds like you" score: how close a piece of text is to how James actually writes and talks,
0-100, with the specific reasons it falls short.

Why this exists: best-of-N picked drafts by Burrows' Delta, which barely tells his writing from a
machine's at this corpus size (approved drafts scored ~1.49, the rejected one 1.39). Measured on
his own samples against AI-written text (the suspected-AI samples, the persona's AI-written
examples and the generated posts), a handful of plain features separate them clearly:

    per 100 words          his speech   generated drafts
    contractions               5.1          0.0
    I / me / my                6.3          0.0
    hedges ("I think")         0.85         0.0
    AI-typical phrases         0.07         3.9
    sentence-length variety    0.56         0.35

The reference values are recomputed from his own samples (origin "own") every time the corpus
changes, so the score keeps learning as samples are added. A phrase on the AI list that he
genuinely uses in his own samples is dropped from the list automatically.
"""

from __future__ import annotations

import functools
import hashlib
import math
import re
import statistics
from dataclasses import dataclass, field

from linkedin_content_engine.voice_engine.textnorm import contractable_count

_APOS = "['’]"
_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_CONTRACTION = re.compile(rf"\b\w+{_APOS}(?:t|s|re|m|ll|ve|d)\b", re.IGNORECASE)
_FIRST_PERSON = re.compile(rf"\b(?:i|me|my|mine|myself|i{_APOS}(?:m|ve|d|ll))\b", re.IGNORECASE)
_HEDGES = re.compile(
    r"\b(?:i think|i mean|i feel|i guess|kind of|sort of|to be honest|honestly|for me|i'd say|"
    r"i would say|i reckon|you know|a bit|pretty much|basically)\b",
    re.IGNORECASE,
)
_NOMINAL = re.compile(r"\b[a-z]{4,}(?:tion|tions|ment|ments|ity|ities|ness|ance|ence|ism)\b", re.IGNORECASE)

# Phrases that mark text as machine-written LinkedIn copy. Each is checked against his own
# samples before use (see _usable_tells), so anything he really says is never penalised.
AI_PHRASES = [
    "landscape", "navigate", "navigating", "leverage", "leveraging", "crucial", "robust",
    "seamless", "seamlessly", "foster", "fostering", "delve", "realm", "tapestry", "pivotal",
    "game-changer", "game changer", "game-changing", "unlock", "unlocking", "empower",
    "empowering", "elevate", "streamline", "streamlining", "holistic", "synergy", "paradigm",
    "cutting-edge", "ever-evolving", "fast-paced", "moreover", "furthermore", "additionally",
    "ultimately", "in essence", "a testament to", "underscores", "operationalize",
    "operationalise", "actionable", "stakeholders", "friction", "guardrails", "frontier",
    "at scale", "core architecture", "the reality on the ground", "tells you everything",
    "tells you a lot", "speaks volumes", "key takeaway", "the bottom line", "here is how",
    "here's how", "here is what", "here's what", "the better way", "the better approach",
    "the old way", "the old playbook", "from day one", "bolted on", "an afterthought",
    "mission-critical", "transformative", "unprecedented", "ecosystem", "move the needle",
    "deep dive", "double-edged sword", "in today's", "the future of", "it's no secret",
    "let that sink in", "read that again", "the real question", "the real story",
    "the real frontier", "the real bottleneck", "the uncomfortable truth", "make no mistake",
    "at the end of the day", "not just about", "isn't just about", "is no longer",
]


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase).replace("'", _APOS).replace("\\'", _APOS)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


_PHRASE_PATTERNS = {p: _phrase_pattern(p) for p in AI_PHRASES}

# "It's not X. It's Y." / "This isn't about X, it's about Y" - the single most recognisable
# machine-written move on LinkedIn.
_NOT_X_BUT_Y = re.compile(
    rf"\b(?:it|this|that)(?:{_APOS}s| is| was)? ?(?:not|n{_APOS}t)\b[^.!?\n]{{0,80}}[.,;]\s*"
    rf"(?:it|this|that)(?:{_APOS}s| is| was)\b",
    re.IGNORECASE,
)


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if _WORD.search(s)]


def features(text: str) -> dict[str, float]:
    words = _words(text)
    n = len(words) or 1
    lengths = [len(_words(s)) for s in _sentences(text)] or [0]
    mean_len = statistics.mean(lengths)
    return {
        "contractions": 100 * len(_CONTRACTION.findall(text)) / n,
        "expanded": 100 * contractable_count(text) / n,
        "first_person": 100 * len(_FIRST_PERSON.findall(text)) / n,
        "hedges": 100 * len(_HEDGES.findall(text)) / n,
        "nominalisations": 100 * len(_NOMINAL.findall(text)) / n,
        "sentence_variety": (statistics.pstdev(lengths) / mean_len) if mean_len else 0.0,
        "sentence_length": mean_len,
        "long_words": 100 * sum(1 for w in words if len(w) >= 9) / n,
    }


# How each feature counts. "low": only falling below his range is penalised; "high": only going
# above; "both": either way. Weight = how much it says about the writer. The minimum spread
# stops a feature he happens to use very consistently from punishing tiny differences.
_RULES: dict[str, tuple[str, float, float]] = {
    "contractions": ("low", 1.6, 1.0),
    "expanded": ("high", 1.0, 0.4),
    "first_person": ("low", 1.3, 1.5),
    "hedges": ("low", 0.7, 0.3),
    "nominalisations": ("high", 0.9, 0.8),
    "sentence_variety": ("low", 0.9, 0.1),
    "sentence_length": ("both", 0.5, 2.5),
    "long_words": ("high", 0.7, 1.5),
}

_EXPLAIN = {
    "contractions": "too few contractions ({value:.1f} per 100 words; you use about {mean:.1f}) - "
    "'it is', 'do not' instead of 'it's', 'don't'",
    "expanded": "spells out 'it is', 'do not' and the like more than you do",
    "first_person": "hardly speaks as you ({value:.1f} I/me/my per 100 words; you use about {mean:.1f})",
    "hedges": "none of your natural softeners ('I think', 'kind of', 'honestly')",
    "nominalisations": "too many abstract -tion/-ment/-ity nouns ({value:.1f} per 100 words; you use "
    "about {mean:.1f}) - reads like a report",
    "sentence_variety": "sentences are all much the same length; yours vary a lot more",
    "sentence_length": "sentence length is off from yours ({value:.0f} words on average; yours "
    "about {mean:.0f})",
    "long_words": "more long, formal words than you use",
}


@dataclass
class VoiceScore:
    score: int  # 0-100, higher sounds more like him
    issues: list[str] = field(default_factory=list)  # plain-English reasons, worst first
    ai_phrases: list[str] = field(default_factory=list)
    features: dict[str, float] = field(default_factory=dict)

    def summary(self, limit: int = 3) -> str:
        parts = []
        if self.ai_phrases:
            parts.append("AI-sounding phrases: " + ", ".join(f'"{p}"' for p in self.ai_phrases[:5]))
        parts.extend(self.issues[:limit])
        return "; ".join(parts)


@dataclass(frozen=True)
class Reference:
    stats: dict[str, tuple[float, float]]  # feature -> (mean, spread)
    tells: tuple[str, ...]  # AI phrases he never uses himself
    sample_count: int
    markers: tuple[str, ...] = ()  # the everyday words he leans on (his_markers)
    marker_rate: float = 0.0  # how often he uses them, per 100 words
    marker_rates: tuple[tuple[str, float], ...] = ()  # each one, per 100 words


def build_reference(own_texts: list[str]) -> Reference:
    """His typical value and spread for each feature, from his own samples."""
    rows = [features(t) for t in own_texts if len(_words(t)) >= 30]
    stats: dict[str, tuple[float, float]] = {}
    for name, (_direction, _weight, min_spread) in _RULES.items():
        values = [r[name] for r in rows] or [0.0]
        mean = statistics.mean(values)
        spread = max(statistics.pstdev(values) if len(values) > 1 else 0.0, min_spread)
        stats[name] = (mean, spread)
    joined = "\n".join(own_texts)
    tells = tuple(p for p, pattern in _PHRASE_PATTERNS.items() if not pattern.search(joined))
    markers = his_markers(own_texts)
    return Reference(
        stats=stats,
        tells=tells,
        sample_count=len(rows),
        markers=tuple(m for m, _rate in markers),
        marker_rate=sum(rate for _m, rate in markers) / 10,  # per 1,000 words -> per 100
        marker_rates=tuple((m, rate / 10) for m, rate in markers),
    )


def _marker_rate(text: str, markers: tuple[str, ...]) -> float:
    n = len(_words(text)) or 1
    return 100 * sum(len(_MARKER_PATTERNS[m].findall(text)) for m in markers) / n


@functools.lru_cache(maxsize=4)
def _cached_reference(key: str, texts: tuple[str, ...]) -> Reference:  # noqa: ARG001 - key busts the cache
    return build_reference(list(texts))


def reference_from_corpus() -> Reference:
    """Reference built from the live corpus (his own samples only), cached until it changes."""
    from linkedin_content_engine.voice_engine.ingestion import get_all_sample_texts

    texts = tuple(get_all_sample_texts())
    key = hashlib.sha1("\x00".join(texts).encode("utf-8")).hexdigest()
    return _cached_reference(key, texts)


# Everyday words people lean on to sound like themselves: softeners, intensifiers, discourse
# markers. Which ones he actually uses, and how often, is measured from his own samples
# (his_markers) - this list is only the set of candidates to look for, not a claim about him.
MARKER_CANDIDATES = [
    "really", "actually", "genuinely", "properly", "proper", "completely", "absolutely",
    "massive", "massively", "honestly", "literally", "basically", "obviously", "definitely",
    "probably", "pretty", "quite", "super", "loads", "a lot", "a bit", "kind of", "sort of",
    "i think", "i feel", "i mean", "i guess", "i reckon", "i'd say", "you know", "to be honest",
    "for me", "it depends", "at the end of the day", "the thing is", "to be fair", "fair enough",
    "at least", "even if", "just", "stuff", "things like that", "and that", "anyway", "mate",
    "brilliant", "rubbish", "nightmare", "sick of", "fed up", "love", "hate", "crazy", "mad",
    "insane", "huge", "tough", "weird", "nuts",
]
_MARKER_PATTERNS = {m: _phrase_pattern(m) for m in MARKER_CANDIDATES}


def his_markers(own_texts: list[str], top_n: int = 14) -> list[tuple[str, float]]:
    """The everyday words he actually leans on, most-used first, as uses per 1,000 words of
    his own samples. Only ones he used in at least two different samples count, so a word
    that turned up once in one story doesn't get passed off as a habit."""
    total_words = sum(len(_words(t)) for t in own_texts) or 1
    rates = []
    for marker, pattern in _MARKER_PATTERNS.items():
        in_samples = sum(1 for t in own_texts if pattern.search(t))
        if in_samples < 2:
            continue
        uses = sum(len(pattern.findall(t)) for t in own_texts)
        rates.append((marker, 1000 * uses / total_words))
    rates.sort(key=lambda r: -r[1])
    return rates[:top_n]


def validate_score(own_texts: list[str], ai_texts: list[str]) -> dict:
    """Can the score tell his writing from AI-written text? Each of his samples is scored against
    a reference built without it (so it isn't marking its own homework); AI-written texts against
    the full reference. A wide gap means the score is measuring something real."""
    own = [t for t in own_texts if len(_words(t)) >= 30]
    if len(own) < 4:
        return {"status": "not enough samples"}
    held_out = [score_text(t, build_reference([o for o in own if o is not t])).score for t in own]
    full = build_reference(own)
    ai = [score_text(t, full).score for t in ai_texts if len(_words(t)) >= 30]
    return {
        "status": "ok",
        "own_mean": statistics.mean(held_out),
        "ai_mean": statistics.mean(ai) if ai else None,
        "n_own": len(held_out),
        "n_ai": len(ai),
    }


def find_ai_phrases(text: str, reference: Reference) -> list[str]:
    found = [p for p in reference.tells if _PHRASE_PATTERNS[p].search(text)]
    if _NOT_X_BUT_Y.search(text):
        found.append("it's not X, it's Y")
    return found


def score_text(text: str, reference: Reference | None = None) -> VoiceScore:
    """0-100: how much this reads like him. Each feature outside his normal range costs points
    in proportion to how far outside it is; each AI-typical phrase costs a flat 6."""
    reference = reference or reference_from_corpus()
    values = features(text)
    penalties: list[tuple[float, str]] = []
    for name, (direction, weight, _min_spread) in _RULES.items():
        mean, spread = reference.stats[name]
        z = (values[name] - mean) / spread
        if direction == "low":
            excess = max(0.0, -z - 1.0)
            # Overdoing it is as much a giveaway as never doing it: a draft stuffed with
            # "I think" and "honestly" reads as an impression of him, not as him.
            if z > 3.5:
                penalties.append((10 * weight * min(z - 3.5, 3.0), f"overdoes it: {name.replace('_', ' ')} "
                                  f"well above how you write ({values[name]:.1f} per 100 words; you use about {mean:.1f})"))
        elif direction == "high":
            excess = max(0.0, z - 1.0)
        else:
            excess = max(0.0, abs(z) - 1.5)
        if excess > 0:
            cost = 10 * weight * min(excess, 3.0)
            penalties.append((cost, _EXPLAIN[name].format(value=values[name], mean=mean)))
    if reference.markers:
        rate = _marker_rate(text, reference.markers)
        values["markers"] = rate
        ceiling = max(2 * reference.marker_rate, reference.marker_rate + 2.0)
        if rate > ceiling:
            penalties.append((
                min(30.0, 8 * (rate - ceiling)),
                f"leans on your everyday words too hard ({rate:.1f} per 100 words; you use about "
                f"{reference.marker_rate:.1f}) - it reads like an impression of you",
            ))
        # One pet word used over and over is its own giveaway: "completely" turned up five
        # times in four test posts, against about once in 600 of his own words.
        words = len(_words(text)) or 1
        for marker, per_100 in reference.marker_rates:
            uses = len(_MARKER_PATTERNS[marker].findall(text))
            allowed = 1 + 3 * per_100 * words / 100
            if uses > allowed:
                penalties.append((
                    min(20.0, 7 * (uses - allowed)),
                    f'uses "{marker}" {uses} times - far more than you would in a post this long',
                ))
    phrases = find_ai_phrases(text, reference)
    total = sum(c for c, _ in penalties) + 6 * len(phrases)
    score = int(round(100 * math.exp(-total / 60)))
    penalties.sort(key=lambda p: -p[0])
    return VoiceScore(score=score, issues=[why for _, why in penalties], ai_phrases=phrases, features=values)
