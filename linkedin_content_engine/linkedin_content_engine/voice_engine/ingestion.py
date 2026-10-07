"""Corpus ingestion: writes raw voice samples to the voice_samples table (spec Â§3c, Â§9)."""

import json
import re
from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import VoiceSample
from linkedin_content_engine.voice_engine.embeddings import embed
from linkedin_content_engine.voice_engine.textnorm import clean_sample_text

VALID_SOURCE_TYPES = ("linkedin_post", "audio_transcript", "gemini_qa")

# Whose words a sample is (VoiceSample.origin), with the label the Voice page shows.
# Request: "Some come from posts that you wrote and I liked" - so not every sample is his
# writing, and one (a private topic) must never reach a post. Only "own" samples are used:
# for the stylometry, the voice profile, the examples shown to the drafting model and the
# voice score. The others stay stored and visible, so a wrong call is one click to undo.
ORIGINS: dict[str, str] = {
    "own": "Your own words",
    "suspected_ai": "Looks AI-written - check",
    "ai_assisted": "AI-written - not used",
    "private": "Private - never used",
}
USABLE_ORIGINS = ("own",)

# Request: "Those [Gemini Q&A answers] are the most authentic versions of how I speak
# and is what I want to emulate." Raw interview answers are unscripted and unedited;
# LinkedIn posts (even the personal ones) go through some amount of polish before
# posting - so they carry real signal but shouldn't count equally. Anything not listed
# here (currently just linkedin_post/audio_transcript) falls back to weight 1.0.
SOURCE_AUTHENTICITY_WEIGHT: dict[str, float] = {"gemini_qa": 2.5}
_DEFAULT_WEIGHT = 1.0


def add_sample(raw_text: str, source_type: str, question: str | None = None) -> VoiceSample:
    """Store one corpus sample (a LinkedIn post, a transcribed recording, or one
    answer from a Gemini Q&A/interview session). `question` is Gemini's own text,
    kept as context only - never fed into the voice analysis itself, which only
    ever reads `raw_text`."""
    if source_type not in VALID_SOURCE_TYPES:
        msg = f"source_type must be one of {VALID_SOURCE_TYPES}, got {source_type!r}"
        raise ValueError(msg)
    raw_text = raw_text.strip()
    if not raw_text:
        msg = "raw_text cannot be empty"
        raise ValueError(msg)

    sample = VoiceSample(
        source_type=source_type,
        raw_text=raw_text,
        date_added=datetime.now(timezone.utc),
        question=(question or "").strip() or None,
    )
    with rx.session(url=config.db_url) as session:
        session.add(sample)
        session.commit()
        session.refresh(sample)
    return sample


def add_own_words(text: str, question: str | None = None, min_words: int = 12) -> VoiceSample | None:
    """Keep something he wrote or said elsewhere in the app (a "Your take" answer) as a voice
    sample too: it's his own words on exactly the topics the posts cover, which the corpus is
    thinnest on. Skips anything too short to show how he talks, and anything already banked."""
    text = (text or "").strip()
    if len(text.split()) < min_words:
        return None
    with rx.session(url=config.db_url) as session:
        exists = session.exec(sqlmodel.select(VoiceSample).where(VoiceSample.raw_text == text)).first()
    if exists:
        return None
    return add_sample(text, "gemini_qa", question=question)


def parse_labeled_conversation(text: str, gemini_label: str, me_label: str) -> list[tuple[str | None, str]]:
    """Split a pasted, speaker-labeled transcript (request: "I will ask gemini to
    label who is speaking") into (question, answer) pairs, one per turn spoken by
    `me_label` - each answer is paired with whatever `gemini_label` said immediately
    before it. A turn can span multiple lines; it ends at the next line that starts
    with either label followed by a colon. Deliberately returns pairs rather than
    saving anything directly, so the caller can show a preview before committing -
    a labeling convention this loose is worth letting the user sanity-check."""
    pattern = re.compile(
        rf"^\s*({re.escape(gemini_label)}|{re.escape(me_label)})\s*:\s*(.*)$",
        re.IGNORECASE,
    )
    turns: list[tuple[str, str]] = []
    current_speaker: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            if current_speaker is not None:
                turns.append((current_speaker, "\n".join(current_lines).strip()))
            current_speaker = m.group(1)
            current_lines = [m.group(2)] if m.group(2) else []
        elif current_speaker is not None:
            current_lines.append(line)
    if current_speaker is not None:
        turns.append((current_speaker, "\n".join(current_lines).strip()))

    pairs: list[tuple[str | None, str]] = []
    pending_question: str | None = None
    for speaker, content in turns:
        if not content:
            continue
        if speaker.lower() == gemini_label.lower():
            pending_question = content
        else:
            pairs.append((pending_question, content))
            pending_question = None
    return pairs


def get_all_samples(include_unused: bool = False) -> list[VoiceSample]:
    """The samples the voice engine may use: only his own words (USABLE_ORIGINS).
    `include_unused=True` also returns AI-written, suspected and private samples - for
    showing them on the Voice page, never for analysis or prompts."""
    with rx.session(url=config.db_url) as session:
        samples = list(session.exec(sqlmodel.select(VoiceSample)).all())
    if include_unused:
        return samples
    return [s for s in samples if (s.origin or "own") in USABLE_ORIGINS]


def sample_text(sample: VoiceSample) -> str:
    """A sample's text as the voice engine reads it (links, copy-paste debris and
    transcription dashes removed, British spelling). The stored text is left alone."""
    return clean_sample_text(sample.raw_text)


def get_all_sample_texts() -> list[str]:
    """Return just the text of every usable corpus sample, for stats/LLM steps."""
    return [sample_text(s) for s in get_all_samples()]


def get_weighted_samples() -> list[tuple[str, float]]:
    """Same as get_all_sample_texts, but paired with each sample's authenticity
    weight (SOURCE_AUTHENTICITY_WEIGHT) - for the stylometry/retrieval math that
    should count your raw Gemini answers more heavily than more polished posts."""
    return [
        (sample_text(s), SOURCE_AUTHENTICITY_WEIGHT.get(s.source_type, _DEFAULT_WEIGHT))
        for s in get_all_samples()
    ]


def get_weighted_samples_by_register() -> list[tuple[str, float, str]]:
    """Same corpus, also tagged with source_type - for register-aware scoring
    (voice_engine/similarity.py::burrows_delta_by_register), which needs to know
    which samples belong to which "register" (raw speech vs polished post) rather
    than just how authentic each one is."""
    return [
        (sample_text(s), SOURCE_AUTHENTICITY_WEIGHT.get(s.source_type, _DEFAULT_WEIGHT), s.source_type)
        for s in get_all_samples()
    ]


def set_sample_origin(sample_id: int, origin: str, note: str | None = None) -> None:
    """Mark whose words a sample is (ORIGINS). Takes effect for drafting at once (every
    getter above filters on it); the stored voice profile catches up when it's rebuilt."""
    if origin not in ORIGINS:
        msg = f"origin must be one of {tuple(ORIGINS)}, got {origin!r}"
        raise ValueError(msg)
    with rx.session(url=config.db_url) as session:
        row = session.get(VoiceSample, sample_id)
        if row is None:
            return
        row.origin = origin
        row.origin_note = note
        session.add(row)
        session.commit()


def get_embedded_samples() -> list[tuple[str, float, list[float] | None]]:
    """Same weighted corpus, plus each sample's embedding - computed once and cached
    on the row (VoiceSample.embedding) rather than recomputed on every single draft.
    Confirmed live this actually mattered: retrieval used to re-embed all 6 samples
    on every draft (~20-50s just for that); with real samples numbering in the
    dozens-to-hundreds this scales linearly and would make best-of-N drafting take
    many minutes just on retrieval. A sample's embedding is only ever (re)computed
    once, the first time it's needed after being added."""
    samples = get_all_samples()
    result: list[tuple[str, float, list[float] | None]] = []
    to_update: list[tuple[int, list[float]]] = []
    for s in samples:
        weight = SOURCE_AUTHENTICITY_WEIGHT.get(s.source_type, _DEFAULT_WEIGHT)
        if s.embedding:
            vector = json.loads(s.embedding)
        else:
            vector = embed(s.raw_text)
            if vector is not None:
                to_update.append((s.id, vector))
        result.append((sample_text(s), weight, vector))

    if to_update:
        with rx.session(url=config.db_url) as session:
            for sample_id, vector in to_update:
                row = session.get(VoiceSample, sample_id)
                if row is not None:
                    row.embedding = json.dumps(vector)
                    session.add(row)
            session.commit()

    return result


def clear_all_samples() -> int:
    """Delete every voice sample. Used to wipe placeholder/demo data before real posts go in."""
    with rx.session(url=config.db_url) as session:
        samples = session.exec(sqlmodel.select(VoiceSample)).all()
        count = len(samples)
        for sample in samples:
            session.delete(sample)
        session.commit()
    return count
