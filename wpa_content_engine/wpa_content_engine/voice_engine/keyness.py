"""Keyness stats: which words she uses far more than general English does.

Compares her corpus's word frequencies against `wordfreq`'s general-English baseline
(Zipf scale) rather than needing a separate reference corpus of our own.
"""

import math
import re
from collections import Counter

from wordfreq import zipf_frequency

_WORD_RE = re.compile(r"[a-zA-Z']+")

# Purely mechanical stopwords - excluded so keyness surfaces content-bearing words,
# not just "the"/"and" which are common everywhere and carry no voice signal.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "on", "at", "for", "with", "as", "by", "it", "this", "that",
    "i", "we", "you", "they", "he", "she", "it's", "im", "its",
}


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def compute_keyness(texts: list[str], top_n: int = 25) -> list[dict]:
    """Rank words by how much more often she uses them than general English does.

    Returns a list of {word, her_zipf, general_zipf, keyness} sorted by keyness desc.
    her_zipf/general_zipf are both on the Zipf log scale so they're directly comparable.
    """
    tokens = [w for text in texts for w in _tokenize(text) if w not in _STOPWORDS and len(w) > 2]
    if not tokens:
        return []

    counts = Counter(tokens)
    total = sum(counts.values())

    results = []
    for word, count in counts.items():
        # Convert her raw frequency to the same Zipf log scale wordfreq uses,
        # so it's comparable to the general-English baseline.
        her_freq_per_million = (count / total) * 1_000_000
        her_zipf = 0.0 if her_freq_per_million <= 0 else math.log10(her_freq_per_million) + 3
        general_zipf = zipf_frequency(word, "en")
        keyness = her_zipf - general_zipf
        results.append(
            {
                "word": word,
                "count": count,
                "her_zipf": round(her_zipf, 2),
                "general_zipf": round(general_zipf, 2),
                "keyness": round(keyness, 2),
            }
        )

    results.sort(key=lambda r: r["keyness"], reverse=True)
    return results[:top_n]
