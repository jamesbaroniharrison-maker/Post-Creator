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
import re
from collections import Counter

_WORD_RE = re.compile(r"[a-zA-Z']+")

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
