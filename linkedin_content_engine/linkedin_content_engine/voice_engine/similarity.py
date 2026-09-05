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

from linkedin_content_engine.voice_engine.keyness import _STOPWORDS

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


def compute_characteristic_bigrams(corpus: WeightedCorpus, top_n: int = 15) -> list[str]:
    """Diagnostic only for now - Voice page display, NOT fed into the drafting
    prompt. Two-word sequences that repeat across the corpus, weighted by
    authenticity. Confirmed live this is real signal but not yet distinctive signal
    at a corpus this size: what actually repeats across only 6 documents is mostly
    generic conversational scaffolding ("i need," "i want," "you can," "look at")
    rather than genuinely characteristic phrasing, unlike Zeta above which gave a
    meaningful result at the same corpus size. Injecting a list this generic into the
    drafting prompt risks making output sound more repetitive, not more authentic -
    revisit once the corpus is large enough that distinctive (not just frequent)
    bigrams start to surface."""
    counts: Counter = Counter()
    for text, weight in corpus:
        tokens = _tokenize(text)
        for a, b in zip(tokens, tokens[1:]):
            if a in _STOPWORDS and b in _STOPWORDS:
                continue
            counts[(a, b)] += weight
    repeated = [(bigram, count) for bigram, count in counts.items() if count >= 2]
    repeated.sort(key=lambda pair: pair[1], reverse=True)
    return [f"{a} {b}" for (a, b), _ in repeated[:top_n]]
