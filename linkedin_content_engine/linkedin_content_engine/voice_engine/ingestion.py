"""Corpus ingestion: writes raw voice samples to the voice_samples table (spec Â§3c, Â§9)."""

import re
from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import VoiceSample

VALID_SOURCE_TYPES = ("linkedin_post", "audio_transcript", "gemini_qa")


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


def get_all_samples() -> list[VoiceSample]:
    """Return every corpus sample currently banked."""
    with rx.session(url=config.db_url) as session:
        return list(session.exec(sqlmodel.select(VoiceSample)).all())


def get_all_sample_texts() -> list[str]:
    """Return just the raw text of every corpus sample, for stats/LLM steps."""
    return [s.raw_text for s in get_all_samples()]


def clear_all_samples() -> int:
    """Delete every voice sample. Used to wipe placeholder/demo data before real posts go in."""
    with rx.session(url=config.db_url) as session:
        samples = session.exec(sqlmodel.select(VoiceSample)).all()
        count = len(samples)
        for sample in samples:
            session.delete(sample)
        session.commit()
    return count
