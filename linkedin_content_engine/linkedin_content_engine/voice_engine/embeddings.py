"""Real local text embeddings via Ollama's nomic-embed-text model.

The literal version of "contrastive style embedding retrieval," now that a small
(274MB), free, fully local embedding model is actually available - as opposed to
similarity.py's bag-of-words cosine similarity, which was the honest stand-in used
before this model existed. Falls back to that approximation if Ollama or the
embedding model isn't reachable for any reason, rather than failing a draft over a
missing local model - drafting stays local-first and free either way (CLAUDE.md hard
rule), this is strictly an upgrade to retrieval quality, not a new dependency the
rest of the pipeline relies on.
"""

import os

import dotenv
import httpx

dotenv.load_dotenv()

_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def embed(text: str) -> list[float] | None:
    """Return a real embedding vector for `text`, or None if the embedding model
    isn't reachable. Callers must treat None as "fall back to something else," not
    as an error worth crashing a draft over."""
    try:
        response = httpx.post(
            f"{_BASE_URL}/api/embeddings",
            json={"model": _MODEL, "prompt": text},
            timeout=30,
        )
        response.raise_for_status()
        vector = response.json().get("embedding")
        return vector or None
    except httpx.HTTPError:
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def most_similar_by_embedding(
    query: str, candidates: list[tuple[str, float]], n: int = 2
) -> list[str] | None:
    """Real-embedding version of similarity.py's most_similar_texts - ranks by cosine
    similarity in actual embedding space instead of word-count overlap. Takes the same
    weighted-corpus shape as the bag-of-words version but deliberately does NOT
    multiply similarity by authenticity weight - confirmed live that it should not:
    for a query about an AI model release, the raw embedding correctly ranked the two
    genuinely AI-related posts on top (0.59, 0.48 cosine) - multiplying by the 2.5x
    Gemini-answer weight pushed an unrelated breakup story above both of them instead,
    because real cosine scores here cluster narrowly enough (roughly 0.29-0.62 across
    unrelated topics) for a flat multiplier to override genuine topical relevance
    entirely. The authenticity weighting still matters for Burrows' Delta (there it's
    correctly modelling "which documents anchor your normal voice more"), but for
    "which single real example is actually about this topic," topical relevance
    should win outright, not get bid up by source type. Returns None (distinct from
    an empty list) if embedding failed at any point, so the caller knows to fall back
    rather than silently act on a partially-ranked result."""
    if not candidates:
        return []
    query_vec = embed(query)
    if query_vec is None:
        return None
    scored = []
    for text, _weight in candidates:
        vec = embed(text)
        if vec is None:
            return None
        scored.append((text, cosine(query_vec, vec)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [text for text, _ in scored[:n]]
