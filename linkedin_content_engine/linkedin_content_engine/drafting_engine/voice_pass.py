"""Voice pass: one focused rewrite of the chosen draft so it sounds like James wrote it.

Why a separate step: the drafting prompt has to juggle research, facts, shape, privacy, funnel
and hook all at once, and the voice gets averaged out into generic LinkedIn prose (the drafts in
the database before this scored 16-34 on "sounds like you", against ~95 for his own words). This
call has one job only - change how things are said, never what is said - with five of his real
answers in front of it and the exact problems the voice score found in this draft.

It is guarded so it can only help:
- every number and every name in the rewrite must already be in the draft or its sources;
- length and paragraph count must stay close to the draft's;
- the fabrication audit runs again on the rewrite;
- the rewrite must score clearly higher on "sounds like you", or the draft is kept as it was.

Model: VOICE_PASS_MODEL (e.g. gemini-3.8-flash, the strongest Gemini on the free tier, run with
low thinking so it takes seconds rather than a minute) - one call per post, so a small free daily
allowance goes a long way. If it's unset, rate-limited or down, the normal drafting model is used.
VOICE_PASS=0 turns the pass off.
"""

from __future__ import annotations

import json
import os
import random
import re
import time

import httpx

from linkedin_content_engine.drafting_engine.grounding import unsupported_personal_claims
from linkedin_content_engine.voice_engine.edits import edit_lessons_block
from linkedin_content_engine.voice_engine.embeddings import most_similar_by_embedding
from linkedin_content_engine.voice_engine.fingerprint import (
    Reference,
    his_markers,
    reference_from_corpus,
    score_text,
)
from linkedin_content_engine.voice_engine.ingestion import get_all_sample_texts, get_embedded_samples
from linkedin_content_engine.voice_engine.textnorm import naturalise

MIN_GAIN = 3  # points of "sounds like you" a rewrite must add to be kept
SKIP_ABOVE = 90  # a draft already this close to him is left alone

_PROMPT = """You edit LinkedIn posts so they sound exactly like James wrote them himself: not a \
ghostwriter, not a copywriter, not an AI. You change HOW things are said, never WHAT is said.

HOW JAMES TALKS - his own words, transcribed from him answering questions out loud:
---
{examples}
---

What his writing measurably does:
{how_he_writes}
- Everyday words he leans on (measured from his samples, most-used first): {markers}. A few \
per post, never one in every sentence.

{edit_lessons}

KEEP EXACTLY: every fact, number, name, source and claim; the point the post makes; the order \
of the ideas; roughly the same paragraphs (same number, give or take one); the length (within \
about 10%).

CHANGE whatever a machine would write and he wouldn't. In this draft specifically:
{issues}
- Never use any of these: {ai_phrases}.
- Write as him, in the first person where it's natural ("I think", "for me", "I'd").
- Contractions the way he talks (it's, don't, I'm). British spelling. No em dashes, hashtags, \
emojis, or questions aimed at the reader.
- Never add an experience, event, person, number or detail he didn't give. If the draft has \
no personal story, don't invent one. Opinion words ("honestly", "I think") are fine.

Respond with strict JSON only, no markdown fences: {{"text": "the rewritten post"}}"""


class _Unavailable(Exception):
    """The voice-pass model can't be used right now (quota, outage); fall back."""


def _instructions(features: dict[str, float], reference: Reference, ai_phrases: list[str]) -> list[str]:
    """What to change, as instructions with numbers rather than a diagnosis. Told "hardly speaks
    as you", a small model rewrote nothing (60 -> 60, three times in one test run); told exactly
    what to do and how much, it has something it can act on."""
    stats = reference.stats
    out = []
    if ai_phrases:
        out.append("Replace these machine-sounding phrases with plain words he'd say: "
                   + ", ".join(repr(p) for p in ai_phrases) + ".")
    mean_fp = stats["first_person"][0]
    if features.get("first_person", 0) < mean_fp - stats["first_person"][1]:
        out.append(f"Make it him talking: in at least three places, say what he thinks or would do, in the "
                   f"first person (\"I think\", \"for me\", \"I'd\", \"I reckon\"). Right now it has "
                   f"{features.get('first_person', 0):.1f} I/me/my per 100 words; he uses about {mean_fp:.0f}. "
                   "Turn general \"you\"/\"we\" statements into his own view where it reads naturally.")
    if features.get("contractions", 0) < stats["contractions"][0] - stats["contractions"][1]:
        out.append("Use contractions the way he talks (it's, don't, that's, I'd, they're) - he uses about "
                   f"{stats['contractions'][0]:.0f} per 100 words.")
    if features.get("sentence_variety", 0) < stats["sentence_variety"][0] - stats["sentence_variety"][1]:
        out.append("Vary the sentence lengths like he does: add two or three very short sentences (3-8 words) "
                   "and let one thought run on longer, joined with \"and\" or \"but\".")
    if features.get("nominalisations", 0) > stats["nominalisations"][0] + stats["nominalisations"][1]:
        out.append("Swap abstract nouns (-tion, -ment, -ity) and any report or news wording for plain "
                   "verbs and everyday words - the way he'd say the same fact out loud (\"graduate "
                   "intake\" -> \"taking on grads\").")
    if features.get("long_words", 0) > stats["long_words"][0] + stats["long_words"][1]:
        out.append("Use shorter, everyday words where a long formal one is used.")
    if features.get("hedges", 0) < 0.2:
        out.append("Let one or two of his natural softeners in (\"honestly\", \"kind of\", \"I think\").")
    return out


def _examples(topic: str, n: int = 5) -> str:
    """Five of his own answers: three closest to the topic, two others for range."""
    embedded = get_embedded_samples()
    texts = [t for t, _w, _v in embedded]
    if not texts:
        return "(no samples yet)"
    close = most_similar_by_embedding(topic, embedded, n=min(3, len(texts))) or []
    rest = [t for t in texts if t not in close]
    chosen = close + random.sample(rest, min(n - len(close), len(rest)))

    def trim(t: str, max_words: int = 180) -> str:
        words = t.split()
        if len(words) <= max_words:
            return t
        cut = " ".join(words[:max_words])
        end = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        return cut[: end + 1] if end > len(cut) // 2 else cut

    return "\n\n---\n\n".join(trim(t) for t in chosen)


def _gemini_generate(model: str, system: str, user: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise _Unavailable("no GEMINI_API_KEY")
    body: dict = {"contents": [{"role": "user", "parts": [{"text": user}]}]}
    if model.startswith("gemma"):
        # Gemma takes no separate system instruction: put it in front of the request.
        body["contents"][0]["parts"][0]["text"] = f"{system}\n\n{user}"
    else:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    config: dict = {}
    if model.startswith("gemini-3"):
        # Default thinking took 75s for a one-word reply on gemini-3.8-flash; "low" took ~6s.
        config["thinkingConfig"] = {"thinkingLevel": os.environ.get("VOICE_PASS_THINKING", "low")}
    if config:
        body["generationConfig"] = config
    # Short leash: a "busy" model held one test run for 17+ minutes at 180s x 3 attempts. Two
    # tries of 60s, then the next model in VOICE_PASS_MODEL gets its turn.
    for attempt in range(2):
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": api_key},
                json=body,
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise _Unavailable(f"{type(exc).__name__}") from exc
        if response.status_code == 429:
            raise _Unavailable("rate limit / daily quota")  # don't wait out a daily quota
        if response.status_code in (500, 503) and attempt < 1:
            time.sleep(4)
            continue
        if response.status_code != 200:
            raise _Unavailable(f"HTTP {response.status_code}")
        parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise _Unavailable("empty reply")
        return text
    raise _Unavailable("model busy")


def _generate(system: str, user: str) -> tuple[str, str]:
    """(reply, which model wrote it). VOICE_PASS_MODEL is a comma-separated list tried in order
    (e.g. "gemini-3.8-flash,gemma-4-31b-it" - the free 3.8 Flash is sometimes "busy", Gemma has a
    far bigger free allowance), then the drafting model as the last resort."""
    from linkedin_content_engine.drafting_engine.draft import _chat

    models = [m.strip() for m in os.environ.get("VOICE_PASS_MODEL", "").split(",") if m.strip()]
    skipped = []
    if os.environ.get("DRAFT_LLM_PROVIDER", "ollama").lower() == "gemini":
        for model in models:
            try:
                return _gemini_generate(model, system, user), model
            except _Unavailable as exc:
                skipped.append(f"{model}: {exc}")
    return _chat(system, user), "drafting model" + (f" - skipped {'; '.join(skipped)}" if skipped else "")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_CAPITALISED = re.compile(r"\b[A-Z][a-zA-Z'&-]+\b")


def _parse(reply: str) -> str | None:
    cleaned = _FENCE.sub("", reply.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    text = data.get("text") if isinstance(data, dict) else None
    return text.strip() if isinstance(text, str) and text.strip() else None


_NUMBER_WORDS = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|"
    r"forty|fifty|sixty|hundred|thousand|million|billion|dozen|half an hour|an hour)\b",
    re.IGNORECASE,
)


def new_specifics(rewrite: str, source: str, number_words: bool = True) -> list[str]:
    """Numbers (as digits, and as words unless `number_words` is False), and names, in the
    rewrite that aren't anywhere in the draft or its sources - i.e. things it made up ("a
    twenty-minute exercise" from a note that gave no time at all). Number words are worth
    checking on posts about his own life; on news posts they're mostly speculation ("five
    years from now"), so only hard digits count there."""
    source_numbers = {n.replace(",", "") for n in _NUMBER.findall(source)}
    invented = [n for n in _NUMBER.findall(rewrite) if n.replace(",", "") not in source_numbers]
    source_lower = source.lower()
    for match in _NUMBER_WORDS.finditer(rewrite) if number_words else ():
        if match.group(0).lower() not in source_lower and match.group(0).lower() != "one":
            invented.append(match.group(0))
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", rewrite):
        for i, match in enumerate(_CAPITALISED.finditer(sentence)):
            word = match.group(0)
            if word in ("I", "I'm", "I've", "I'd", "I'll") or word.lower() in source_lower:
                continue
            if i == 0 and match.start() == len(sentence) - len(sentence.lstrip()):
                continue  # sentence-initial capital, not a name
            invented.append(word)
    return invented


def _paragraphs(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()])


def voice_pass(
    text: str,
    topic: str,
    research_texts: list[str],
    how_he_writes: str,
    reference: Reference | None = None,
) -> tuple[str, str]:
    """Return (text, note). The text is the rewrite only if it passed every guard and sounds
    clearly more like him; otherwise the draft comes back unchanged with the reason."""
    if os.environ.get("VOICE_PASS", "1") == "0":
        return text, ""
    reference = reference or reference_from_corpus()
    before = score_text(text, reference)
    if before.score >= SKIP_ABOVE:
        return text, ""

    issues = [f"- {line}" for line in _instructions(before.features, reference, before.ai_phrases)]
    system = _PROMPT.format(
        examples=_examples(topic),
        how_he_writes=how_he_writes,
        markers=", ".join(f'"{m}"' for m, _r in his_markers(get_all_sample_texts())),
        issues="\n".join(issues) or "- Nothing specific: just make it sound more like him.",
        ai_phrases=", ".join(f'"{p}"' for p in reference.tells),
        edit_lessons=edit_lessons_block(),
    )
    source = "\n".join([text, topic, *research_texts])
    user = f"SOURCE MATERIAL (only for checking facts - don't add anything from it):\n{topic}\n\nDRAFT TO EDIT:\n{text}"
    try:
        reply, model = _generate(system, user)
    except Exception:  # noqa: BLE001 - a voice pass must never cost the draft
        return text, ("Voice pass skipped - the AI models were busy or out of today's free allowance, "
                      "so this is the draft before its final rewrite into your voice.")
    rewrite = _parse(reply)
    if not rewrite:
        return text, "Voice pass skipped (unreadable reply)."
    rewrite = naturalise(rewrite)

    invented = new_specifics(rewrite, source)
    if invented:
        return text, f"Voice pass not used: it added details that weren't in the draft ({', '.join(invented[:3])})."
    # A personal story the draft didn't tell (grounding.py): the most damaging thing it could add.
    sources = [text, topic, *research_texts]
    if len(unsupported_personal_claims(rewrite, sources)) > len(unsupported_personal_claims(text, sources)):
        return text, "Voice pass not used: it added a personal story that isn't in your note."
    words_before, words_after = len(text.split()), len(rewrite.split())
    if not 0.75 * words_before <= words_after <= 1.3 * words_before:
        return text, "Voice pass not used: it changed the length too much."
    if abs(_paragraphs(rewrite) - _paragraphs(text)) > 1:
        return text, "Voice pass not used: it changed the paragraphs too much."
    after = score_text(rewrite, reference)
    if after.score < before.score + MIN_GAIN:
        return text, f"Voice pass not used: it didn't sound more like you ({before.score} -> {after.score})."

    from linkedin_content_engine.drafting_engine.draft import _run_audit_call

    passes, problem = _run_audit_call(rewrite, topic)
    if not passes:
        return text, f"Voice pass not used: the edit check failed ({problem[:120]})."
    return rewrite, f"Voice pass ({model}): sounds like you {before.score} -> {after.score}."
