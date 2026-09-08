"""Lightweight text-similarity helpers - bag-of-words math, not trained embeddings.

There's no embedding model or fine-tuning pipeline anywhere in this stack (drafting
calls a hosted/local inference API, it doesn't own model weights to adapt) - so
"contrastive style retrieval" and "distribution-matching" ideas are implemented here
in the honest, appropriate-for-this-project form: real, well-understood statistical
techniques (cosine similarity over word-count vectors, Burrows' Delta - a genuine
stylometry/authorship-attribution method) rather than pretending to run something
that needs infrastructure this project doesn't have.

Both functions take a *weighted* corpus (list of (text, weight) pairs, see
voice_engine/ingestion.py::get_weighted_samples) - request: "Those [Gemini Q&A
answers] are the most authentic versions of how I speak and is what I want to
emulate," so a more authentic sample should count for more than a weight of 1 in
both "how far is this draft from my real style" and "which real example best
matches this topic," not just be one equal vote among many.
"""

import math
import random
import re
from collections import Counter

from wordfreq import word_frequency

from linkedin_content_engine.voice_engine.keyness import _STOPWORDS

# Requires at least one real letter, not just apostrophes - a bare "'" was showing up
# as its own token (and then its own "bigram") from quote-delimited phrases like
# "...a long-distance runner,'" where the tokenizer split on the comma and the
# trailing apostrophe had no adjacent letters left to attach to. Found live while
# testing PMI bigram ranking below - "runner '" was ranking as a top result.
_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)*")

WeightedCorpus = list[tuple[str, float]]


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _cosine(a: Counter, b: Counter) -> float:
    shared = set(a) & set(b)
    dot = sum(a[w] * b[w] for w in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def most_similar_texts(query: str, candidates: WeightedCorpus, n: int = 2) -> list[str]:
    """Rank `candidates` by bag-of-words cosine similarity to `query`, scaled by each
    candidate's authenticity weight, and return the top `n` texts. The honest version
    of "contrastive style retrieval" for a stack with no embedding model: raw word
    overlap rather than a trained similarity space - fully explainable, and reasonable
    for picking which of a handful of real samples best match a topic's actual words.
    The weight means a highly authentic sample can outrank a slightly-more-topically-
    similar but less authentic one, not just break exact ties."""
    if not candidates:
        return []
    query_vec = Counter(_tokenize(query))
    scored = [
        (text, _cosine(query_vec, Counter(_tokenize(text))) * weight) for text, weight in candidates
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [text for text, _ in scored[:n]]


def burrows_delta(candidate_text: str, corpus: WeightedCorpus, vocab_size: int = 30) -> float | None:
    """A real implementation of Burrows' Delta (Burrows, 2002) - a standard
    authorship-attribution statistic, not something invented for this project - scored
    here as "how far does this draft's function-word usage sit from the corpus's own
    normal range," lower being closer. Uses the `vocab_size` most frequent words
    *across the corpus itself* (deliberately not excluding stopwords/function words
    the way keyness.py does - Delta specifically wants the most frequent words, which
    are usually function words, since topic-bearing content words vary too much
    document to document to be a stable style signal).

    The per-word mean/variance that everything else is measured against is a
    weighted mean/variance across corpus documents (standard weighted-statistics
    formulas), not a plain average - a document with authenticity weight 2.5 pulls
    the "normal range" toward itself 2.5x as hard as a weight-1 document.

    Returns None when there isn't enough corpus data to compute a meaningful
    per-word mean/variance (need at least 2 real samples) - callers should treat that
    as "not enough corpus yet to score this," not "perfect match."
    """
    if len(corpus) < 2:
        return None

    texts = [t for t, _ in corpus]
    weights = [w for _, w in corpus]
    total_weight = sum(weights)
    if total_weight <= 0:
        return None

    corpus_tokens = [_tokenize(t) for t in texts]

    # Vocab selection is also weight-aware - a word common in your most authentic
    # samples should be more likely to end up in the "frequent words" set than one
    # that's only common in a less authentic sample.
    weighted_counts: Counter = Counter()
    for tokens, weight in zip(corpus_tokens, weights):
        for tok, count in Counter(tokens).items():
            weighted_counts[tok] += count * weight
    vocab = [w for w, _ in weighted_counts.most_common(vocab_size)]
    if not vocab:
        return None

    def _rel_freq(tokens: list[str]) -> dict[str, float]:
        total = len(tokens) or 1
        counts = Counter(tokens)
        return {w: counts.get(w, 0) / total for w in vocab}

    doc_freqs = [_rel_freq(toks) for toks in corpus_tokens]

    means = {
        w: sum(weight * freqs[w] for weight, freqs in zip(weights, doc_freqs)) / total_weight
        for w in vocab
    }
    variances = {
        w: sum(weight * (freqs[w] - means[w]) ** 2 for weight, freqs in zip(weights, doc_freqs))
        / total_weight
        for w in vocab
    }
    stdevs = {w: math.sqrt(variances[w]) for w in vocab}

    candidate_freqs = _rel_freq(_tokenize(candidate_text))
    z_diffs = [
        abs((candidate_freqs[w] - means[w]) / stdevs[w]) for w in vocab if stdevs[w] > 0
    ]
    if not z_diffs:
        return None
    return round(sum(z_diffs) / len(z_diffs), 3)


RegisterCorpus = list[tuple[str, float, str]]

# What a generated post's register actually is - used to pick which register's
# baseline is the primary score. Not every source_type in VALID_SOURCE_TYPES is
# necessarily a target register (audio_transcript could go either way depending on
# what was said), but this is the one we know for certain: a LinkedIn post should be
# judged primarily against other LinkedIn posts, not against raw spoken interview
# answers, even though the interview answers are weighted more heavily for *what
# vocabulary/values* to draw on via retrieval and Zeta.
TARGET_REGISTER = "linkedin_post"


def burrows_delta_by_register(candidate_text: str, corpus: RegisterCorpus, vocab_size: int = 30) -> dict[str, float | None]:
    """Splits the corpus by source_type/register and scores the candidate against
    each register's own baseline separately, instead of one pooled baseline across
    every register at once. Confirmed live why this matters: pooling a handful of
    short, formatted LinkedIn posts with several long, raw spoken transcripts made
    Delta noisy - a real draft and a deliberately corporate paragraph scored within
    0.01 of each other, because the pooled "normal range" was really an unstable mix
    of two different registers' statistics, not a coherent single baseline.

    Each register's score only exists once that register itself has enough documents
    (burrows_delta's own len<2 guard) - with only 2 LinkedIn posts today, the
    "linkedin_post" register can't yet produce a stable score on its own, so this
    degrades safely to `None` for that key until there are at least 2, same as the
    pooled version already does for the whole corpus. Nothing here breaks at small
    scale; it just isn't fully active yet."""
    by_register: dict[str, WeightedCorpus] = {}
    for text, weight, source_type in corpus:
        by_register.setdefault(source_type, []).append((text, weight))
    return {register: burrows_delta(candidate_text, docs, vocab_size) for register, docs in by_register.items()}


def primary_voice_delta(candidate_text: str, corpus: RegisterCorpus, vocab_size: int = 30) -> float | None:
    """The single score best_of_n_draft_post actually selects on: the TARGET_REGISTER
    (linkedin_post) score if that register has enough of its own samples to produce
    one, otherwise the old pooled-corpus score across every register as a fallback -
    so this is always at least as good as the pre-register-split behaviour, never
    worse, and automatically switches to the more precise per-register score the
    moment enough LinkedIn posts exist to support it."""
    by_register = burrows_delta_by_register(candidate_text, corpus, vocab_size)
    target_score = by_register.get(TARGET_REGISTER)
    if target_score is not None:
        return target_score
    pooled = [(text, weight) for text, weight, _source_type in corpus]
    return burrows_delta(candidate_text, pooled, vocab_size)


def validate_voice_metric(
    corpus: RegisterCorpus, holdout_fraction: float = 0.15, min_baseline: int = 6
) -> dict:
    """A real train/validation check on Delta itself, not something that changes how
    a live draft gets scored - holds back a slice of real samples per register, builds
    that register's baseline from everything else, then scores the held-out samples
    (genuine examples of your writing the baseline never saw) against it. If the
    metric is doing its job, held-out real writing should reliably come back "close" -
    if it doesn't, that's a sign the metric or its thresholds need revisiting, not
    just a data problem.

    Deliberately NOT wired into best_of_n_draft_post's live scoring - holding samples
    back to validate the metric would mean building an already-fragile-at-small-scale
    baseline from even fewer documents, which would make live scoring worse, not
    better, until the corpus is large enough to spare the holdout without hurting the
    baseline. Only activates per register once that register has at least
    `min_baseline` documents left over after holding out `holdout_fraction` of it -
    below that, reports "not enough data" for that register rather than forcing a
    split that would starve the baseline. Call this on demand to check calibration,
    not on every draft."""
    by_register: dict[str, WeightedCorpus] = {}
    for text, weight, source_type in corpus:
        by_register.setdefault(source_type, []).append((text, weight))

    results: dict[str, dict] = {}
    for register, docs in by_register.items():
        n_holdout = int(len(docs) * holdout_fraction)
        if n_holdout < 1 or len(docs) - n_holdout < min_baseline:
            results[register] = {
                "status": "not enough data",
                "total_documents": len(docs),
                "needed": min_baseline + max(1, int(min_baseline * holdout_fraction)),
            }
            continue

        shuffled = docs[:]
        random.shuffle(shuffled)
        held_out, baseline = shuffled[:n_holdout], shuffled[n_holdout:]
        deltas = [burrows_delta(text, baseline) for text, _weight in held_out]
        valid_deltas = [d for d in deltas if d is not None]
        results[register] = {
            "status": "ok",
            "baseline_size": len(baseline),
            "held_out_size": len(held_out),
            "held_out_deltas": valid_deltas,
            "mean_held_out_delta": round(sum(valid_deltas) / len(valid_deltas), 3) if valid_deltas else None,
        }
    return results


def compute_zeta_words(corpus: WeightedCorpus, min_doc_frequency: float = 0.5, top_n: int = 20) -> list[str]:
    """Burrows'/Craig's Zeta - a different question from Delta's "how far off is the
    usual mix of words": which words show up in most of your documents *regardless
    of topic*, i.e. words you reliably reach for rather than words that just happen
    to be common. Uses document presence (a word either appears in a document or it
    doesn't, once per document no matter how many times it's repeated), weighted by
    each document's authenticity weight - so a word you use in every one of your
    Gemini answers counts more toward "signature" than one that only shows up in a
    single LinkedIn post. Excludes the same stopword list keyness.py does - Zeta,
    unlike Delta, wants distinctive vocabulary, not function words.

    Confirmed live on the real corpus before trusting this: "have" showed up in
    100% of documents, "just"/"really"/"proud"/"know" in the majority - a genuinely
    informative signature list even at only 6 real samples, unlike the bigram
    extraction below which needed a much bigger corpus to say anything useful."""
    if not corpus:
        return []
    total_weight = sum(weight for _, weight in corpus)
    if total_weight <= 0:
        return []

    doc_weight_for_word: dict[str, float] = {}
    for text, weight in corpus:
        seen = {w for w in _tokenize(text) if len(w) > 2 and w not in _STOPWORDS}
        for w in seen:
            doc_weight_for_word[w] = doc_weight_for_word.get(w, 0.0) + weight

    signature = [
        (w, freq / total_weight) for w, freq in doc_weight_for_word.items() if freq / total_weight >= min_doc_frequency
    ]
    signature.sort(key=lambda pair: pair[1], reverse=True)
    return [w for w, _ in signature[:top_n]]


def compute_characteristic_bigrams(corpus: WeightedCorpus, top_n: int = 15, min_count: float = 2.0) -> list[str]:
    """Ranks repeated two-word sequences by Pointwise Mutual Information (PMI)
    against general English, not raw frequency - the same idea as keyness.py's
    single-word comparison against `wordfreq`, extended to bigrams. `wordfreq` has no
    bigram frequencies to compare against directly, so this uses the standard
    collocation-detection approach instead: PMI(w1,w2) = log2(P(w1,w2) /
    (P(w1)*P(w2))) - how much more often this exact pair occurs together in your
    corpus than you'd expect from each word's general-English frequency alone, if
    they were unrelated. A high PMI bigram is one that's a real pairing, not just two
    common words that happen to sit next to each other sometimes.

    Confirmed live why this matters: raw-frequency ranking on this same corpus
    surfaced mostly generic scaffolding ("i need," "i want," "you can," "look at") -
    each individually common, so also common as a pair by pure chance, but not
    actually a distinctive collocation. PMI is exactly the fix for that failure mode.
    Still requires `min_count` weighted occurrences (default 2) to avoid a single
    coincidental pairing looking artificially distinctive at low sample size."""
    counts: Counter = Counter()
    for text, weight in corpus:
        tokens = _tokenize(text)
        for a, b in zip(tokens, tokens[1:]):
            if a in _STOPWORDS and b in _STOPWORDS:
                continue
            counts[(a, b)] += weight
    total = sum(counts.values())
    if total <= 0:
        return []

    scored = []
    for (a, b), count in counts.items():
        if count < min_count:
            continue
        p_ab = count / total
        p_a = word_frequency(a, "en") or 1e-9
        p_b = word_frequency(b, "en") or 1e-9
        pmi = math.log2(p_ab / (p_a * p_b))
        scored.append(((a, b), pmi))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [f"{a} {b}" for (a, b), _ in scored[:top_n]]
