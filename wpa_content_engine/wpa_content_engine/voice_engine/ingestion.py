"""Corpus ingestion: writes raw voice samples to the voice_samples table (spec Â§3c, Â§9)."""

from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.models import VoiceSample

VALID_SOURCE_TYPES = ("linkedin_post", "audio_transcript")


def add_sample(raw_text: str, source_type: str) -> VoiceSample:
    """Store one corpus sample (a LinkedIn post or a transcribed recording)."""
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
    )
    with rx.session(url=config.db_url) as session:
        session.add(sample)
        session.commit()
        session.refresh(sample)
    return sample


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
