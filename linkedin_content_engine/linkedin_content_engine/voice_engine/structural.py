"""Structural stats: the shape of your posts, independent of what words you pick."""

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_HASHTAG_RE = re.compile(r"#\w+")
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
_FIRST_PERSON_RE = re.compile(r"\b(i|i'm|i've|i'll|my|me|we|we're|our|us)\b", re.IGNORECASE)
_CTA_PHRASES = (
    "let me know", "thoughts?", "what do you think", "drop a comment",
    "get in touch", "reach out", "comment below", "share your",
)


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s]


def _words(text: str) -> list[str]:
    return text.split()


def compute_structural_stats(texts: list[str]) -> dict:
    """Return averages/rates describing how you structure a post, across the whole corpus."""
    if not texts:
        return {}

    n = len(texts)
    sentence_counts, word_counts, sentence_lengths = [], [], []
    hashtag_counts, emoji_counts, exclaim_counts, question_counts = [], [], [], []
    paragraph_break_counts, first_person_hits = [], []
    opens_with_question = 0
    uses_cta = 0

    for text in texts:
        sents = _sentences(text)
        words = _words(text)
        sentence_counts.append(len(sents))
        word_counts.append(len(words))
        sentence_lengths.extend(len(_words(s)) for s in sents)

        hashtag_counts.append(len(_HASHTAG_RE.findall(text)))
        emoji_counts.append(len(_EMOJI_RE.findall(text)))
        exclaim_counts.append(text.count("!"))
        question_counts.append(text.count("?"))
        paragraph_break_counts.append(text.count("\n\n"))
        first_person_hits.append(len(_FIRST_PERSON_RE.findall(text)))

        if sents and sents[0].strip().endswith("?"):
            opens_with_question += 1
        if any(phrase in text.lower() for phrase in _CTA_PHRASES):
            uses_cta += 1

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    return {
        "sample_count": n,
        "avg_words_per_post": avg(word_counts),
        "avg_sentences_per_post": avg(sentence_counts),
        "avg_words_per_sentence": avg(sentence_lengths),
        "avg_hashtags_per_post": avg(hashtag_counts),
        "avg_emoji_per_post": avg(emoji_counts),
        "avg_exclamation_marks_per_post": avg(exclaim_counts),
        "avg_question_marks_per_post": avg(question_counts),
        "avg_paragraph_breaks_per_post": avg(paragraph_break_counts),
        "avg_first_person_words_per_post": avg(first_person_hits),
        "pct_posts_opening_with_question": round(100 * opens_with_question / n, 1),
        "pct_posts_with_call_to_action": round(100 * uses_cta / n, 1),
    }
