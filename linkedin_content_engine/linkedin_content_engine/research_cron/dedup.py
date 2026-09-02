"""Dedup: is a new finding substantially the same story as something already banked?

Lexical similarity is enough at this scale (spec Â§4 LLM08 note: embeddings only become
relevant if dedup needs them - it doesn't yet).
"""

import difflib

SIMILARITY_THRESHOLD = 0.6


def is_duplicate(candidate_title: str, candidate_url: str, recent: list[tuple[str, str]]) -> bool:
    """Compare a candidate (title, url) against recent (title, url) bank entries."""
    for title, url in recent:
        if url == candidate_url:
            return True
        ratio = difflib.SequenceMatcher(None, candidate_title.lower(), title.lower()).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            return True
    return False
