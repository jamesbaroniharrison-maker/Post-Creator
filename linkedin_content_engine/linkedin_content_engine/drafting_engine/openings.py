"""Openings: score how well a post's first line makes someone stop scrolling, and
sharpen it before the draft reaches Review (request: "nothing distinctly punchy about
openings that would make people want to stay and read... I don't want it to sound AI
at all, but you don't want it to be void of any life or interest").

Two narrow model calls, following this codebase's own lesson that a single rule does
better in its own call than buried in a busy drafting prompt:

1. `sharpen_opening` asks for a few alternative first lines built only from what the
   post already says, then one scoring call rates the original and the alternatives
   together. The best one replaces the first line only if it scores clearly higher.
   Anything with a number that isn't already in the post is thrown out (no invented
   facts), and the em dash / AI-cliche checks run on the result.
2. `score_opening` rates one opening 1-10 with a one-line reason. Deterministic checks
   cap an opening that uses a known AI tell or a question, whatever the model says.

Both fail soft: if a call errors, the draft keeps its original opening and simply has
no score - an opening tweak must never cost the draft.
"""

import json
import re

from linkedin_content_engine.drafting_engine.persona import PROHIBITED_PATTERNS

# Openings that read as machine-written or as filler before the point. Matched at the
# start of the first line, case-insensitive.
AI_TELLS = [
    "in today's", "in a world", "let's talk", "let's dive", "here's the thing", "the thing is",
    "it's no secret", "as ai continues", "ai is transforming", "ai is changing", "in the ever",
    "imagine a world", "picture this", "have you ever", "what if i told you", "did you know",
    "we need to talk", "unpopular opinion", "hot take", "game changer", "game-changer",
    "the future of", "buckle up", "spoiler", "here's why", "here is why", "let me explain",
    "i've been thinking", "i have been thinking", "big news", "exciting news", "thrilled",
]
MAX_OPENING_WORDS = 22
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

_SCORE_PROMPT = """You are a blunt, experienced LinkedIn editor. You judge ONLY the \
opening line of a post: would a busy professional, scrolling fast, stop and read the next \
line?

Score each opening from 1 to 10:
- 8-10: concrete and specific (a real number, a named thing, a specific moment, or a \
sharp claim with some tension or stakes), sounds like a real person talking, and makes \
you want the next line.
- 5-7: clear and accurate but flat - a plain statement of fact with no tension, stakes \
or surprise.
- 1-4: generic, abstract, throat-clearing, preachy, or machine-sounding (e.g. "In \
today's...", "Let's talk about...", "AI is transforming...", a question aimed at the \
reader, a vague claim anyone could make).

Judge the opening in the context of the rest of the post it introduces. If it just says \
the same thing as the line straight after it, it wastes the reader's first glance - score \
it 5 at most. Be strict: most openings are a 5 or 6.

Respond with strict JSON only, no markdown fences:
{"scores": [{"score": 6, "reason": "one short plain-English sentence"}]}
with exactly one entry per opening, in the order given."""

_SHARPEN_PROMPT = f"""You rewrite ONLY the opening line of a LinkedIn post, in the \
author's own voice: plain, conversational British English, contractions, like someone \
talking across a table - never like a copywriter, a consultant, or an AI.

Write 4 different alternative opening lines for the post you're given. Each one must:
- be one sentence, under {MAX_OPENING_WORDS} words;
- lead with something concrete that is ALREADY in the post: a number from it, a named \
thing from it, a specific moment from it, or a blunt claim the post goes on to back up;
- give the reader a reason to read the next line (tension, stakes, a surprise, a \
consequence) without overselling it;
- never introduce a fact, number, name or event that isn't in the post;
- never be a question, never use an em dash, a hashtag or an emoji;
- never start with any of these: {", ".join(f'"{t}"' for t in AI_TELLS[:16])};
- avoid everything in this list:
{PROHIBITED_PATTERNS}

Your line REPLACES the post's current first sentence; everything after it stays exactly as \
it is. So it must lead straight into the sentence that follows it, and must not repeat \
what that sentence says.

Make the four genuinely different from each other (e.g. one leads with the number, one \
with the consequence, one with the blunt claim, one with the moment).

Respond with strict JSON only, no markdown fences:
{{"openings": ["...", "...", "...", "..."]}}"""


_NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "twenty", "thirty", "forty", "fifty", "hundred", "hundreds", "thousand", "thousands", "million",
    "millions", "billion", "billions", "percent", "half", "double", "triple", "quarter", "dozen",
}
_WORD = re.compile(r"[A-Za-z][A-Za-z'&-]*")


def _introduces_new_facts(candidate: str, source: str) -> bool:
    """True if the candidate names something (a capitalised word after the first) or
    uses a spelled-out number that the post itself never mentions."""
    source_lower = source.lower()
    words = _WORD.findall(candidate)
    for i, w in enumerate(words):
        lw = w.lower()
        if lw in _NUMBER_WORDS and not re.search(rf"\b{re.escape(lw)}\b", source_lower):
            return True
        if not w[0].isupper() or lw == "i" or re.search(rf"\b{re.escape(lw)}\b", source_lower):
            continue
        # A capital after the first word is a name. The first word is capitalised anyway,
        # so it only counts as a name when it isn't a very common English word.
        if i > 0 or _zipf(lw) < 6.0:
            return True
    return False


def _zipf(word: str) -> float:
    try:
        from wordfreq import zipf_frequency

        return zipf_frequency(word, "en")
    except Exception:  # noqa: BLE001 - without wordfreq, treat the first word as common
        return 7.0


def _chat(system_prompt: str, user: str) -> str:
    # Imported lazily: draft.py imports this module, so a top-level import would loop.
    from linkedin_content_engine.drafting_engine.draft import _chat as draft_chat

    return draft_chat(system_prompt, user)


def _json(content: str) -> dict:
    return json.loads(_FENCE.sub("", content.strip()))


def split_opening(text: str) -> tuple[str, str, str]:
    """(before, opening, after): the opening is the first sentence of the first
    non-empty line. Joining the three gives back the original text exactly."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip():
            parts = _SENTENCE_END.split(line.strip(), maxsplit=1)
            lead = line[: len(line) - len(line.lstrip())]
            first = parts[0]
            rest_of_line = line.strip()[len(first):]
            before = "\n".join(lines[:i]) + ("\n" if i else "") + lead
            after = rest_of_line + ("\n" if i < len(lines) - 1 else "") + "\n".join(lines[i + 1:])
            return before, first, after
    return "", "", text


def opening_flags(opening: str) -> list[str]:
    """Deterministic problems with an opening - each one caps its score."""
    o = opening.strip().lower()
    flags = []
    if any(o.startswith(t) for t in AI_TELLS):
        flags.append("starts with a stock phrase that reads as AI-written")
    if "?" in o:
        flags.append("asks the reader a question")
    if "—" in opening:
        flags.append("uses an em dash")
    if len(o.split()) > MAX_OPENING_WORDS + 6:
        flags.append("too long to land in one glance")
    return flags


def score_openings(openings: list[str], rest_of_post: str) -> list[tuple[int, str]]:
    """One model call scoring several candidate openings for the same post. Returns
    [(score, reason)] in the same order; raises if the call fails."""
    listing = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(openings))
    user = f"OPENINGS TO SCORE:\n{listing}\n\nTHE REST OF THE POST (after the opening):\n{rest_of_post[:1800]}"
    data = _json(_chat(_SCORE_PROMPT, user))
    out = []
    for i, opening in enumerate(openings):
        item = (data.get("scores") or [])[i] if i < len(data.get("scores") or []) else {}
        score = max(1, min(10, int(item.get("score", 5))))
        reason = str(item.get("reason", "")).strip()
        flags = opening_flags(opening)
        if flags:
            score = min(score, 4)
            reason = f"{reason} Flagged: {'; '.join(flags)}.".strip()
        out.append((score, reason))
    return out


def score_opening(text: str) -> tuple[int | None, str]:
    """Score one post's opening. (None, "") if the scoring call fails."""
    _before, opening, after = split_opening(text)
    if not opening:
        return None, ""
    try:
        return score_openings([opening], after)[0]
    except Exception:  # noqa: BLE001 - a score is nice to have, never required
        return None, ""


def sharpen_opening(text: str, topic: str = "", min_gain: int = 2) -> tuple[str, int | None, str]:
    """Try better first lines for `text`. Returns (text, opening_score, opening_note):
    the text with the best opening swapped in when it beats the original by at least
    `min_gain` points, otherwise the original text. Never raises."""
    before, original, after = split_opening(text)
    if not original:
        return text, None, ""
    try:
        next_sentence = _SENTENCE_END.split(after.strip(), maxsplit=1)[0] if after.strip() else ""
        data = _json(
            _chat(
                _SHARPEN_PROMPT,
                f"CURRENT FIRST SENTENCE (to replace):\n{original}\n\n"
                f"THE SENTENCE THAT FOLLOWS IT (keep in mind, don't repeat it):\n{next_sentence}\n\n"
                f"THE WHOLE POST:\n{text}",
            )
        )
        allowed_numbers = set(_NUMBER.findall(f"{text} {topic}"))
        candidates = []
        for c in data.get("openings") or []:
            c = re.sub(r"\s+", " ", str(c)).strip().strip('"')
            if not c or c.lower() == original.lower():
                continue
            if any(n not in allowed_numbers for n in _NUMBER.findall(c)):
                continue  # a number the post never said - invented, so out
            if _introduces_new_facts(c, f"{text} {topic}"):
                continue  # a name or spelled-out figure the post never said
            if opening_flags(c):
                continue
            if not c.endswith((".", "!")):
                c += "."
            candidates.append(c)
        scores = score_openings([original, *candidates], after)
    except Exception:  # noqa: BLE001 - keep the draft as it was
        return text, *score_opening(text)

    orig_score, orig_reason = scores[0]
    best_i = max(range(len(scores)), key=lambda i: scores[i][0])
    best_score, best_reason = scores[best_i]
    if best_i == 0 or best_score < orig_score + min_gain:
        return text, orig_score, orig_reason
    new_opening = candidates[best_i - 1]
    # The opening may have been followed by more of the same line; keep the spacing.
    joiner = "" if after.startswith(("\n", " ")) or not after else " "
    return f"{before}{new_opening}{joiner}{after}", best_score, f"{best_reason} (opening sharpened from a {orig_score})"
