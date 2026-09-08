"""Syntactic profile via spaCy - the one idea from the stylometry roadmap that needed
a new dependency, added only once explicitly asked for ("fix all in order").

structural.py already covers surface-level shape (word/sentence counts, punctuation
rates) with plain regex - no model needed. This module covers what regex genuinely
can't: real part-of-speech ratios and passive-voice frequency, which need an actual
syntactic parse, not just counting characters. Deliberately narrow scope - this
augments structural.py, it doesn't replace it.
"""

import functools

_MODEL_NAME = "en_core_web_sm"


@functools.lru_cache(maxsize=1)
def _get_nlp():
    import spacy

    return spacy.load(_MODEL_NAME)


def compute_syntax_stats(texts: list[str]) -> dict:
    """Real POS-ratio and passive-voice stats across the corpus. Fails open (empty
    dict) if spaCy or its model isn't available, rather than crashing profile
    generation over an optional refinement - same reasoning as llm_close_read's
    "unavailable" status for a missing Ollama connection."""
    if not texts:
        return {}
    try:
        nlp = _get_nlp()
    except OSError:
        return {
            "status": "unavailable",
            "reason": f"spaCy model '{_MODEL_NAME}' not downloaded - run: "
            f"python -m spacy download {_MODEL_NAME}",
        }

    noun_counts, verb_counts, adj_counts, adv_counts = [], [], [], []
    sentence_counts = []
    passive_sentences = 0
    total_sentences = 0

    for text in texts:
        doc = nlp(text)
        pos_counts = {"NOUN": 0, "PROPN": 0, "VERB": 0, "ADJ": 0, "ADV": 0}
        for token in doc:
            if token.pos_ in pos_counts:
                pos_counts[token.pos_] += 1

        noun_counts.append(pos_counts["NOUN"] + pos_counts["PROPN"])
        verb_counts.append(pos_counts["VERB"])
        adj_counts.append(pos_counts["ADJ"])
        adv_counts.append(pos_counts["ADV"])

        sents = list(doc.sents)
        sentence_counts.append(len(sents))
        for sent in sents:
            total_sentences += 1
            if any(tok.dep_ in ("nsubjpass", "auxpass") for tok in sent):
                passive_sentences += 1

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    return {
        "status": "ok",
        "avg_nouns_per_post": avg(noun_counts),
        "avg_verbs_per_post": avg(verb_counts),
        "avg_adjectives_per_post": avg(adj_counts),
        "avg_adverbs_per_post": avg(adv_counts),
        "pct_passive_sentences": round(100 * passive_sentences / total_sentences, 1) if total_sentences else 0.0,
    }
