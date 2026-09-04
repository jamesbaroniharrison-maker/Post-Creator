"""Lightweight text-similarity helpers - bag-of-words math, not trained embeddings.

There's no embedding model or fine-tuning pipeline anywhere in this stack (drafting
calls a hosted/local inference API, it doesn't own model weights to adapt) - so
"contrastive style retrieval" and "distribution-matching" ideas are implemented here
in the honest, appropriate-for-this-project form: real, well-understood statistical
techniques (cosine similarity over word-count vectors, Burrows' Delta - a genuine
stylometry/authorship-attribution method) rather than pretending to run something
that needs infrastructure this project doesn't have.
"""

import math
import re
import statistics
from collections import Counter

_WORD_RE = re.compile(r"[a-zA-Z']+")


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


def most_similar_texts(query: str, candidates: list[str], n: int = 2) -> list[str]:
    """Rank `candidates` by bag-of-words cosine similarity to `query`, return the top
    `n`. The honest version of "contrastive style retrieval" for a stack with no
    embedding model: raw word overlap rather than a trained similarity space - fully
    explainable, and reasonable for picking which of a handful of real samples best
    match a topic's actual words."""
    if not candidates:
        return []
    query_vec = Counter(_tokenize(query))
    scored = [(c, _cosine(query_vec, Counter(_tokenize(c)))) for c in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, _ in scored[:n]]


def burrows_delta(candidate_text: str, corpus_texts: list[str], vocab_size: int = 30) -> float | None:
    """A real implementation of Burrows' Delta (Burrows, 2002) - a standard
    authorship-attribution statistic, not something invented for this project - scored
    here as "how far does this draft's function-word usage sit from the corpus's own
    normal range," lower being closer. Uses the `vocab_size` most frequent words
    *across the corpus itself* (deliberately not excluding stopwords/function words
    the way keyness.py does - Delta specifically wants the most frequent words, which
    are usually function words, since topic-bearing content words vary too much
    document to document to be a stable style signal).

    Returns None when there isn't enough corpus data to compute a meaningful
    per-word mean/variance (need at least 2 real samples) - callers should treat that
    as "not enough corpus yet to score this," not "perfect match."
    """
    if len(corpus_texts) < 2:
        return None

    corpus_tokens = [_tokenize(t) for t in corpus_texts]
    all_tokens = [tok for doc in corpus_tokens for tok in doc]
    if not all_tokens:
        return None
    vocab = [w for w, _ in Counter(all_tokens).most_common(vocab_size)]
    if not vocab:
        return None

    def _rel_freq(tokens: list[str]) -> dict[str, float]:
        total = len(tokens) or 1
        counts = Counter(tokens)
        return {w: counts.get(w, 0) / total for w in vocab}

    doc_freqs = [_rel_freq(toks) for toks in corpus_tokens]
    means = {w: statistics.mean(d[w] for d in doc_freqs) for w in vocab}
    stdevs = {w: statistics.pstdev(d[w] for d in doc_freqs) for w in vocab}

    candidate_freqs = _rel_freq(_tokenize(candidate_text))
    z_diffs = [
        abs((candidate_freqs[w] - means[w]) / stdevs[w]) for w in vocab if stdevs[w] > 0
    ]
    if not z_diffs:
        return None
    return round(sum(z_diffs) / len(z_diffs), 3)
