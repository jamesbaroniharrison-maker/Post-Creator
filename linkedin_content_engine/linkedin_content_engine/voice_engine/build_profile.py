"""Merges keyness + structural + LLM close-read into the single voice_profile row (spec Â§3c, Â§9)."""

import json
from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import Post, VoiceProfile
from linkedin_content_engine.voice_engine.close_read import llm_close_read
from linkedin_content_engine.voice_engine.ingestion import (
    get_all_samples,
    get_all_sample_texts,
    get_weighted_samples,
    get_weighted_samples_by_register,
)
from linkedin_content_engine.voice_engine.keyness import compute_keyness
from linkedin_content_engine.voice_engine.report import write_voice_report
from linkedin_content_engine.voice_engine.similarity import (
    compute_characteristic_bigrams,
    compute_zeta_words,
    validate_voice_metric,
)
from linkedin_content_engine.voice_engine.structural import compute_structural_stats
from linkedin_content_engine.voice_engine.syntax_profile import compute_syntax_stats

# Picking the shortest posts would mostly surface one-line reactions ("Very proud of
# this girl!") which don't show the drafting engine what a full post looks like. Posts
# closest to the corpus's own median length are more representative of an actual post.
_FEW_SHOT_COUNT = 3


def _pick_few_shot_examples(texts: list[str]) -> list[str]:
    if not texts:
        return []
    lengths = sorted(len(t) for t in texts)
    median_len = lengths[len(lengths) // 2]
    return sorted(texts, key=lambda t: abs(len(t) - median_len))[:_FEW_SHOT_COUNT]


def build_profile() -> dict:
    """Run the full voice-profile pipeline against every banked sample. Does not save."""
    texts = get_all_sample_texts()
    weighted = get_weighted_samples()

    profile = {
        "sample_count": len(texts),
        "keyness": compute_keyness(texts),
        "structural": compute_structural_stats(texts),
        "llm_close_read": llm_close_read(texts),
        "few_shot_examples": _pick_few_shot_examples(texts),
        # Zeta and characteristic bigrams (voice_engine/similarity.py) - real,
        # corpus-derived vocabulary and phrasing, both fed into the drafting prompt
        # alongside the hand-authored persona vocabulary. Bigrams are PMI-ranked
        # against general English (like keyness.py's single-word version), not raw
        # frequency - that's what makes them distinctive enough to safely inject into
        # generation rather than just being generic scaffolding.
        "zeta_words": compute_zeta_words(weighted),
        "characteristic_bigrams": compute_characteristic_bigrams(weighted),
        # Real POS-ratio/passive-voice stats (voice_engine/syntax_profile.py, spaCy) -
        # diagnostic only for now (Voice page display), same "test before forcing it
        # into generation" treatment bigrams got before PMI-ranking proved out - not
        # yet translated into a drafting-prompt directive.
        "syntax": compute_syntax_stats(texts),
    }
    return profile


def save_profile(profile: dict) -> VoiceProfile:
    """Regenerate the single voice_profile row (spec Â§9: one row, replaced as the corpus grows)."""
    row = VoiceProfile(
        generated_at=datetime.now(timezone.utc),
        profile_json=json.dumps(profile, ensure_ascii=False),
    )
    with rx.session(url=config.db_url) as session:
        session.exec(sqlmodel.delete(VoiceProfile))
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _sample_counts_by_type() -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in get_all_samples():
        counts[sample.source_type] = counts.get(sample.source_type, 0) + 1
    return counts


def _recent_voice_deltas(limit: int = 15) -> list[float]:
    """The most recent drafts' actual voice_delta scores - the real, direct test of
    "does what's being produced resemble the samples," not a proxy for it."""
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(Post.voice_delta)
            .where(sqlmodel.col(Post.voice_delta).is_not(None))
            .order_by(sqlmodel.col(Post.created_at).desc())
            .limit(limit)
        ).all()
    return [d for d in rows if d is not None]


def build_and_save_profile() -> VoiceProfile:
    """Convenience entrypoint: build the profile from whatever's currently banked,
    save it, and (re)write the human-readable voice_profile_report.md alongside it -
    request: "this needs to be continually updated every time a new corpus voice is
    created," i.e. every time this function runs (dashboard's "Regenerate voice
    profile" button, or the CLI equivalent), not on every individual sample add."""
    profile = build_profile()
    row = save_profile(profile)
    corpus = get_weighted_samples_by_register()
    write_voice_report(
        profile=profile,
        sample_counts=_sample_counts_by_type(),
        corpus=corpus,
        validation=validate_voice_metric(corpus),
        recent_deltas=_recent_voice_deltas(),
    )
    return row
