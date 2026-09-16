"""Generates the human-readable voice profile report (context/voice_profile_report.md).

Request (dictated): "I need something that has a... master corpus... that relates to
the samples and that they all link together... certain similarities between word
usage, phrase usage, tonality, phrasings... where I use quotations, where I use
filler words, where I use connector words... continually updated every time a new
corpus voice is created."

This is deliberately a *report*, not a new scoring mechanism - everything numeric in
it either already exists elsewhere in voice_engine/ (Zeta, PMI bigrams, syntax stats,
register-aware Delta) or is a small, well-understood addition (lexical diversity,
filler/connector-word rate, quotation rate, a heuristic British/American spelling
check). It's regenerated every time build_and_save_profile() runs (i.e. whenever
"Regenerate voice profile" is clicked on the dashboard), not on every sample add -
matching the existing app behaviour where adding a sample doesn't itself trigger
profile work.

Gitignored (linkedin_content_engine/.gitignore) like context/about_me.md - it quotes
real fragments of James's private writing, not just aggregate numbers, so it isn't
repo content.
"""

import pathlib
import re
from datetime import datetime, timezone

from linkedin_content_engine.voice_engine.similarity import RegisterCorpus, TARGET_REGISTER, _tokenize

REPORT_PATH = pathlib.Path(__file__).parent.parent / "context" / "voice_profile_report.md"

# Single-word fillers (counted via tokenization) and multi-word fillers (counted via
# substring search on lowercased text, since _tokenize would split "sort of" into two
# separate tokens and lose the phrase).
_SINGLE_FILLERS = {
    "like", "actually", "honestly", "basically", "just", "really", "literally",
    "obviously", "essentially", "totally", "definitely", "probably",
}
_PHRASE_FILLERS = ["sort of", "kind of", "you know", "i mean", "at the end of the day"]

_CONNECTORS = {
    "and", "but", "so", "because", "however", "therefore", "then", "also",
    "although", "meanwhile", "otherwise", "besides", "moreover", "yet", "since",
    "though", "thus", "still",
}

# A simple heuristic, not a real dialect-classification model - just a fixed list of
# spelling variants that reliably differ between British and American English.
# Reported as a raw count with that caveat, not as a confident conclusion.
_BRITISH_MARKERS = {
    "colour", "favourite", "realise", "realising", "organise", "organising",
    "whilst", "amongst", "practise", "centre", "travelling", "learnt", "labour",
    "behaviour", "analyse", "programme",
}
_AMERICAN_MARKERS = {
    "color", "favorite", "realize", "realizing", "organize", "organizing",
    "while", "among", "practice", "center", "traveling", "learned", "labor",
    "behavior", "analyze", "program",
}

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+(?:\s|$)")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def compute_word_usage_stats(texts: list[str]) -> dict:
    """Everything below is computed straightforwardly (token/substring counts, no
    trained model) and normalised per 1,000 words so documents of very different
    lengths (a 90-word LinkedIn post vs. a 500-word interview answer) are comparable -
    the same register-heterogeneity concern already documented for Delta/syntax stats
    elsewhere in this codebase applies here too, so raw counts alone would mislead."""
    if not texts:
        return {"status": "no samples"}

    all_tokens: list[str] = []
    ttrs: list[float] = []
    sentence_lengths: list[float] = []
    word_lengths: list[float] = []
    filler_hits = 0
    connector_hits = 0
    quote_chars = 0
    british_hits = 0
    american_hits = 0
    total_words = 0

    for text in texts:
        tokens = _tokenize(text)
        if not tokens:
            continue
        all_tokens.extend(tokens)
        total_words += len(tokens)
        ttrs.append(len(set(tokens)) / len(tokens))
        word_lengths.extend(len(t) for t in tokens)

        sents = _sentences(text)
        if sents:
            sentence_lengths.extend(len(_tokenize(s)) for s in sents if _tokenize(s))

        lower_text = text.lower()
        filler_hits += sum(1 for t in tokens if t in _SINGLE_FILLERS)
        filler_hits += sum(lower_text.count(p) for p in _PHRASE_FILLERS)
        connector_hits += sum(1 for t in tokens if t in _CONNECTORS)
        quote_chars += text.count('"') + text.count("“") + text.count("”")
        british_hits += sum(1 for t in tokens if t in _BRITISH_MARKERS)
        american_hits += sum(1 for t in tokens if t in _AMERICAN_MARKERS)

    if total_words == 0:
        return {"status": "no samples"}

    per_1000 = 1000.0 / total_words
    return {
        "status": "ok",
        "document_count": len(texts),
        "total_words": total_words,
        "avg_lexical_diversity": round(sum(ttrs) / len(ttrs), 3) if ttrs else None,
        "avg_sentence_length_words": round(sum(sentence_lengths) / len(sentence_lengths), 1)
        if sentence_lengths
        else None,
        "avg_word_length_chars": round(sum(word_lengths) / len(word_lengths), 2) if word_lengths else None,
        "filler_words_per_1000": round(filler_hits * per_1000, 1),
        "connector_words_per_1000": round(connector_hits * per_1000, 1),
        "quotation_marks_per_1000": round(quote_chars * per_1000, 1),
        "british_spelling_hits": british_hits,
        "american_spelling_hits": american_hits,
    }


def _word_usage_by_register(corpus: RegisterCorpus) -> dict[str, dict]:
    by_register: dict[str, list[str]] = {}
    for text, _weight, source_type in corpus:
        by_register.setdefault(source_type, []).append(text)
    return {register: compute_word_usage_stats(texts) for register, texts in by_register.items()}


def _format_word_usage_block(label: str, stats: dict) -> str:
    if stats.get("status") != "ok":
        return f"**{label}**: not enough text yet.\n"
    return (
        f"**{label}** ({stats['document_count']} document(s), {stats['total_words']} words)\n\n"
        f"- Lexical diversity (unique words / total words, higher = more varied vocabulary): "
        f"{stats['avg_lexical_diversity']}\n"
        f"- Average sentence length: {stats['avg_sentence_length_words']} words\n"
        f"- Average word length: {stats['avg_word_length_chars']} characters\n"
        f"- Filler words (\"like,\" \"actually,\" \"sort of,\"...): "
        f"{stats['filler_words_per_1000']} per 1,000 words\n"
        f"- Connector words (\"and,\" \"but,\" \"because,\" \"however,\"...): "
        f"{stats['connector_words_per_1000']} per 1,000 words\n"
        f"- Quotation marks: {stats['quotation_marks_per_1000']} per 1,000 words\n"
        f"- Spelling markers (heuristic only, not a real dialect model): "
        f"{stats['british_spelling_hits']} British-style, {stats['american_spelling_hits']} American-style\n"
    )


def _format_recent_delta_section(recent_deltas: list[float]) -> str:
    if not recent_deltas:
        return "No drafts with a voice-match score yet.\n"
    close = sum(1 for d in recent_deltas if d < 1.2)
    typical = sum(1 for d in recent_deltas if 1.2 <= d < 1.6)
    distant = sum(1 for d in recent_deltas if d >= 1.6)
    avg = sum(recent_deltas) / len(recent_deltas)
    return (
        f"Last {len(recent_deltas)} drafted post(s) with a voice-match score: "
        f"average Delta {avg:.2f} (lower = closer to the real corpus).\n\n"
        f"- Close (<1.2): {close}\n"
        f"- Typical (1.2-1.6): {typical}\n"
        f"- Distant (>=1.6): {distant}\n\n"
        f"This is the direct test of \"does what's actually being produced resemble the "
        f"samples\" - not a proxy metric, the same Burrows' Delta score every draft is "
        f"selected on before it reaches Review.\n"
    )


def _format_health_section(sample_counts: dict[str, int], validation: dict) -> str:
    lines = []
    for register, count in sorted(sample_counts.items(), key=lambda kv: -kv[1]):
        is_primary = " (this is the register every draft is generated as)" if register == TARGET_REGISTER else ""
        result = validation.get(register, {"status": "not enough data"})
        if result["status"] == "ok" and result.get("mean_held_out_delta") is not None:
            status = (
                f"validated - {result['held_out_size']} held-out sample(s) scored "
                f"{result['mean_held_out_delta']:.2f} avg against a {result['baseline_size']}-document baseline"
            )
        elif count >= 2:
            status = "register-aware scoring is live, not yet validated against a holdout"
        else:
            needed = result.get("needed", 7)
            status = f"pooled fallback only - needs {max(0, needed - count)} more sample(s) to validate"
        lines.append(f"- **{register}**{is_primary}: {count} sample(s) - {status}")
    return "\n".join(lines) + "\n"


def generate_voice_report_markdown(
    profile: dict,
    sample_counts: dict[str, int],
    corpus: RegisterCorpus,
    validation: dict,
    recent_deltas: list[float],
) -> str:
    """Assembles everything into one Markdown document. Pulls from data that's
    already computed elsewhere (profile dict, validate_voice_metric's result) rather
    than recomputing it, except for the word-usage stats (filler/connector/quotation/
    lexical-diversity/dialect), which are new and computed here."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_samples = sum(sample_counts.values())
    pooled_texts = [text for text, _weight, _source_type in corpus]
    pooled_usage = compute_word_usage_stats(pooled_texts)
    by_register_usage = _word_usage_by_register(corpus)

    sections = [
        "# Voice Profile Report",
        "",
        "_Auto-generated every time the voice profile is rebuilt - do not hand-edit, "
        "it will be overwritten on the next regeneration. This describes the corpus "
        "as it exists right now, not a fixed target._",
        "",
        f"Generated: {generated_at} | Total samples: {total_samples}",
        "",
        "## 1. Corpus overview",
        "",
    ]
    for source_type, count in sorted(sample_counts.items(), key=lambda kv: -kv[1]):
        sections.append(f"- **{source_type}**: {count} sample(s)")
    sections += ["", "## 2. Corpus health (per register)", "", _format_health_section(sample_counts, validation)]

    sections += [
        "## 3. Does what's being produced actually resemble the samples?",
        "",
        _format_recent_delta_section(recent_deltas),
    ]

    zeta_words = profile.get("zeta_words", [])
    sections += [
        "## 4. Vocabulary signature (words used across most samples, regardless of topic)",
        "",
        (", ".join(zeta_words) if zeta_words else "Not enough corpus yet to say.") + "\n",
    ]

    bigrams = profile.get("characteristic_bigrams", [])
    sections += [
        "## 5. Characteristic phrasing (real two-word sequences, ranked by distinctiveness)",
        "",
        (", ".join(bigrams) if bigrams else "Not enough corpus yet to say.") + "\n",
    ]

    sections += [
        "## 6. Word usage statistics",
        "",
        "### Whole corpus (pooled)",
        "",
        _format_word_usage_block("All samples", pooled_usage),
        "### By register",
        "",
    ]
    for register, stats in sorted(by_register_usage.items(), key=lambda kv: -kv[1].get("document_count", 0)):
        sections.append(_format_word_usage_block(register, stats))

    syntax = profile.get("syntax", {})
    if syntax.get("status") == "ok":
        syntax_block = (
            f"~{syntax['avg_nouns_per_post']:.0f} nouns, {syntax['avg_verbs_per_post']:.0f} verbs, "
            f"{syntax['avg_adjectives_per_post']:.0f} adjectives, {syntax['avg_adverbs_per_post']:.0f} adverbs "
            f"per post on average. {syntax['pct_passive_sentences']:.0f}% of sentences are passive voice "
            f"(lower = more direct/active). Diagnostic only - not yet stable enough across registers to "
            f"feed into drafting directly (see CLAUDE.md, 10 Sept 2026 entry, for why)."
        )
    else:
        syntax_block = "Not enough corpus yet to say."
    sections += ["## 7. Tone / sentence construction", "", syntax_block + "\n"]

    sections += [
        "## 8. Known limitations of this report",
        "",
        "- All per-register and word-usage numbers above are only as reliable as the "
        f"sample count backing them ({total_samples} total right now) - small counts "
        "make averages swing on a single document. Treat single-digit sample counts "
        "as a rough sketch, not a settled conclusion.",
        "- The British/American spelling check is a fixed word list, not a real "
        "dialect-classification model - a zero count either way just means neither "
        "list's words happened to appear, not that a dialect judgement was made.",
        "- Whether phrasing genuinely changes by topic isn't separately tested here - "
        "there isn't enough data yet to split by topic *and* register at the same "
        "time without every slice becoming too small to mean anything. Worth adding "
        "once there are enough LinkedIn-post-register samples to support it.",
        "",
    ]

    return "\n".join(sections)


def write_voice_report(
    profile: dict,
    sample_counts: dict[str, int],
    corpus: RegisterCorpus,
    validation: dict,
    recent_deltas: list[float],
) -> pathlib.Path:
    markdown = generate_voice_report_markdown(profile, sample_counts, corpus, validation, recent_deltas)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(markdown, encoding="utf-8")
    return REPORT_PATH
