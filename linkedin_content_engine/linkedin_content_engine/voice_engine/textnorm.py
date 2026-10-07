"""Plain-text tidying shared by the voice engine (samples) and the drafting engine (drafts).

Why: James writes British English, but transcription (Gemini) and drafting models default to
American spelling and add em dashes he doesn't type. Left in the samples, those habits get
learned back as "his" style; left in drafts, they read as machine-written. Nothing here
changes what a sentence says, only how it's spelled and punctuated.
"""

from __future__ import annotations

import re

# -ize/-yze words that are -ise/-yse in British English. Listed by stem rather than a blanket
# -ize rule, which would wreck "size", "prize", "seize" and "capsize".
_ISE_STEMS = (
    "apolog", "author", "capital", "categor", "central", "character", "civil", "commercial",
    "critic", "custom", "democrat", "digit", "emphas", "familiar", "final", "general", "global",
    "industrial", "internal", "jeopard", "legal", "local", "maxim", "memor", "minim", "mobil",
    "modern", "monet", "normal", "optim", "organ", "personal", "priorit", "real", "recogn",
    "revolution", "special", "stabil", "standard", "subsid", "summar", "symbol", "synthes",
    "util", "visual", "western", "energ", "equal", "fertil", "harmon", "hospital", "human",
    "ideal", "immun", "item", "legitim", "marginal", "neutral", "polar", "public", "rational",
    "scrutin", "sensit", "social", "sterl", "theor", "trivial", "vandal", "victim",
)
_ISE = re.compile(
    r"\b(" + "|".join(_ISE_STEMS) + r")iz(e|es|ed|ing|ation|ations|er|ers)\b", re.IGNORECASE
)
_YSE = re.compile(r"\b(anal|paral|catal)yz(e|es|ed|ing|er|ers)\b", re.IGNORECASE)

# Whole-word swaps. Deliberately conservative: only words where the British form is the
# only one he'd use (no "program", "math" or "check", which are ambiguous).
_WORDS = {
    "center": "centre", "centers": "centres", "centered": "centred",
    "labor": "labour", "labors": "labours", "color": "colour", "colors": "colours",
    "colored": "coloured", "favor": "favour", "favors": "favours", "favorite": "favourite",
    "favorites": "favourites", "favorable": "favourable", "behavior": "behaviour",
    "behaviors": "behaviours", "honor": "honour", "honors": "honours", "honored": "honoured",
    "neighbor": "neighbour", "neighbors": "neighbours", "humor": "humour", "flavor": "flavour",
    "rumor": "rumour", "endeavor": "endeavour", "harbor": "harbour", "savor": "savour",
    "traveled": "travelled", "traveling": "travelling", "traveler": "traveller",
    "travelers": "travellers", "canceled": "cancelled", "canceling": "cancelling",
    "modeling": "modelling", "labeled": "labelled", "labeling": "labelling",
    "fueled": "fuelled", "fueling": "fuelling", "signaled": "signalled", "leveled": "levelled",
    "defense": "defence", "offense": "offence", "catalog": "catalogue",
    "gray": "grey", "mom": "mum", "moms": "mums", "aluminum": "aluminium",
    "jewelry": "jewellery", "enrollment": "enrolment", "fulfill": "fulfil", "skeptical": "sceptical",
    "skeptic": "sceptic", "pajamas": "pyjamas", "cozy": "cosy", "practicing": "practising",
}
_WORD = re.compile(r"\b(" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def _keep_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


# "program" is British only for software; everything else (an employee assistance programme, a
# TV or training programme) is "programme". So it's changed unless its sentence is about software.
_PROGRAM = re.compile(r"\bprogram(s)?\b", re.IGNORECASE)
_SOFTWARE = re.compile(
    r"\b(?:computer|software|code|coding|coded|app|apps|script|python|install|installed|download|"
    r"run|runs|ran|running|compile|developer|laptop|pc)\b",
    re.IGNORECASE,
)


def _programme(match: re.Match[str]) -> str:
    text = match.string
    start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
    ends = [i for i in (text.find(".", match.end()), text.find("\n", match.end())) if i != -1]
    if _SOFTWARE.search(text[start : min(ends) if ends else len(text)]):
        return match.group(0)
    return _keep_case(match.group(0), "programme" + (match.group(1) or "").lower())


def to_british(text: str) -> str:
    """American spellings to British, keeping capitalisation."""
    text = _ISE.sub(lambda m: _keep_case(m.group(0), f"{m.group(1)}is{m.group(2)}"), text)
    text = _YSE.sub(lambda m: _keep_case(m.group(0), f"{m.group(1)}ys{m.group(2)}"), text)
    text = _WORD.sub(lambda m: _keep_case(m.group(0), _WORDS[m.group(0).lower()]), text)
    return _PROGRAM.sub(_programme, text)


_DASH = re.compile(r"[ \t]*[—–][ \t]*")  # em dash, en dash


def strip_dashes(text: str) -> str:
    """Em/en dashes to commas (or nothing at the start of a line), then tidy the punctuation
    that leaves behind. A number range like "5–10" becomes "5-10"."""
    text = re.sub(r"(\d)\s*[–—]\s*(\d)", r"\1-\2", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*[—–]\s*", "", line)
        line = re.sub(r"\s*[—–]\s*$", ".", line)
        line = _DASH.sub(", ", line)
        line = re.sub(r",\s*([,.!?;:])", r"\1", line)  # ", ." -> "."
        lines.append(line)
    return "\n".join(lines)


# Spelled-out forms to their contractions. Drafting models write "it is" and "do not" where
# James says "it's" and "don't": his own samples run ~5 contractions per 100 words, drafts ran 0.
# Pronoun + "be/have/will" forms only contract when another word follows in the same clause
# ("I am going" -> "I'm going", but never "that's what it is." -> "that's what it's.").
_ALWAYS = {
    "do not": "don't", "does not": "doesn't", "did not": "didn't", "is not": "isn't",
    "are not": "aren't", "was not": "wasn't", "were not": "weren't", "cannot": "can't",
    "can not": "can't", "will not": "won't", "would not": "wouldn't", "could not": "couldn't",
    "should not": "shouldn't", "has not": "hasn't", "have not": "haven't", "had not": "hadn't",
    "must not": "mustn't", "need not": "needn't", "let us": "let's",
}
_BEFORE_WORD = {
    "it is": "it's", "that is": "that's", "there is": "there's", "here is": "here's",
    "what is": "what's", "who is": "who's", "you are": "you're", "we are": "we're",
    "they are": "they're", "i am": "I'm", "i will": "I'll", "you will": "you'll",
    "we will": "we'll", "they will": "they'll", "it will": "it'll", "that will": "that'll",
    "i would": "I'd", "you would": "you'd", "we would": "we'd", "they would": "they'd",
}
# "I have"/"you have" etc. only as an auxiliary ("I have seen" -> "I've seen"); "I have a
# dog" stays as it is.
_HAVE = re.compile(
    r"\b(I|you|we|they) have (been|seen|done|had|got|made|found|said|tried|used|worked|built|"
    r"spent|learned|learnt|noticed|heard|met|lost|gone|come|taken|given|started|finished|always|"
    r"never|just|already|also|only|ever)\b",
    re.IGNORECASE,
)


def _contract_match(match: re.Match[str], table: dict[str, str]) -> str:
    original = match.group(0)
    replacement = table[" ".join(original.lower().split())]
    if replacement.startswith("I"):
        return replacement
    return _keep_case(original, replacement)


_ALWAYS_RE = re.compile(r"\b(" + "|".join(k.replace(" ", r"\s+") for k in _ALWAYS) + r")\b", re.IGNORECASE)
# Followed by a space and then a letter: there is more clause to come ("it is a"), as opposed
# to "...what it is." or "...where they are," where the contraction would be wrong.
_BEFORE_WORD_RE = re.compile(
    r"\b(" + "|".join(k.replace(" ", r"\s+") for k in _BEFORE_WORD) + r")\b(?=\s+[A-Za-z])", re.IGNORECASE
)


def contractable_count(text: str) -> int:
    """How many spelled-out forms in `text` could have been contractions (same rules as
    contract(), so "that's where they are." doesn't count against it)."""
    return len(_ALWAYS_RE.findall(text)) + len(_BEFORE_WORD_RE.findall(text)) + len(_HAVE.findall(text))


def contract(text: str) -> str:
    """Use contractions the way he talks. Leaves emphasis alone where a stressed word is
    written in capitals ("it IS")."""
    text = _ALWAYS_RE.sub(lambda m: m.group(0) if m.group(0).isupper() else _contract_match(m, _ALWAYS), text)
    text = _BEFORE_WORD_RE.sub(
        lambda m: m.group(0) if m.group(0).split()[-1].isupper() else _contract_match(m, _BEFORE_WORD), text
    )
    return _HAVE.sub(lambda m: f"{m.group(1)}'ve {m.group(2)}", text)


def naturalise(text: str) -> str:
    """The deterministic finish every draft gets: contractions, no em dashes, British spelling."""
    return to_british(strip_dashes(contract(text)))


_URL = re.compile(r"(?:https?://|www\.)\S+")
_HASHTAG_COPY = re.compile(r"\bhashtag#(\w+)")


def clean_sample_text(text: str) -> str:
    """A voice sample as it should be read for analysis and examples: no links, no LinkedIn
    copy-paste debris, no transcription dashes, British spelling. The stored text is never
    changed; this runs on read."""
    text = _URL.sub("", text)
    text = _HASHTAG_COPY.sub(r"#\1", text)
    text = strip_dashes(text)
    text = to_british(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
