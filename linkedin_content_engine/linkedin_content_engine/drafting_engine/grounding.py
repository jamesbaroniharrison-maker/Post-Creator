"""Grounding: catch personal stories a draft tells that nothing it was given supports.

CLAUDE.md's hard rule: "A made-up personal story is the most damaging thing this system could
post." The more a draft sounds like James (first person, "I think", "for me"), the more room a
model has to slip in an experience he never had ("I tried this last week", "my manager once
told me"). The LLM audit gate catches some of that, but it runs on the same small model that
wrote the draft. This is the deterministic backstop: a sentence that tells a first-person event,
or brings in his people or a time ("my manager", "last week"), must be supported by the note,
the research or his biography - most of its content words have to appear in them. Opinions
("I think it's overhyped") are not events and are left alone.

What happens to a flagged sentence: best-of-N ranks that candidate lower, the voice pass may not
add one, and anything still flagged is listed in the compliance note for him to check.
"""

from __future__ import annotations

import re

# First-person actions in the past: the shape of a story. "was"/"were" are left out on purpose -
# "I was surprised" is a reaction, not an event.
_EVENT = re.compile(
    r"\b(?:I|we)\s+(?:(?:just|once|recently|finally|actually|really)\s+)?"
    r"(?:went|saw|met|had|tried|spent|worked|built|ran|used|asked|told|got|found|noticed|watched|"
    r"read|heard|did|made|took|helped|started|finished|lost|won|bought|sold|visited|moved|left|"
    r"joined|sat|spoke|talked|learned|learnt|decided|tested|launched|hired|interviewed|wrote|"
    r"called|emailed|signed|paid|travelled|drove|walked|stayed|lived|studied|graduated|failed|"
    r"passed|showed|sent|set up|signed up|switched|quit|applied|pitched|watched|cooked|played)\b"
    # Perfect tenses tell a story just as much: "I've seen", "I have worked", "we'd tried".
    r"|\b(?:I|we)(?:['’]ve|['’]d| have| had)\s+(?:(?:just|once|recently|always|never|"
    r"actually|really|personally)\s+)?(?:seen|been|worked|tried|met|had|watched|built|used|done|"
    r"spent|found|noticed|heard|helped|run|started|lost|won|hired|interviewed|travelled|lived|"
    r"studied|learned|learnt|dealt|sat|spoken|talked|made|taken|sold|bought|visited)\b",
    re.IGNORECASE,
)

# Concrete scene details a model adds to make a personal post vivid ("you click submit, close
# your laptop, and you're standing in your room") - harmless if true, invented if his note never
# said them. Only checked on posts written from his own note.
SCENE_WORDS = set(
    """laptop desk room bedroom kitchen table hall office train bus car taxi tube station street
    pub cafe coffee tea beer pint lunch dinner breakfast phone screen inbox email meeting call
    zoom teams slack whiteboard notebook bag window rain sun snow coat sofa couch bed garden
    park gym airport flight plane hotel beach shop supermarket queue tram lecture library campus
    classroom exam paper pen keyboard headphones podcast spreadsheet calendar slides rug carpet
    lounge sofa armchair fridge kettle mug cup glass wine whisky cigarette car-park carpark
    lift stairs corridor reception canteen pitch stadium ferry boat bike cycle umbrella""".split()
)
_PEOPLE = re.compile(
    r"\bmy (?:boss|manager|colleague|colleagues|mate|mates|friend|friends|client|clients|team|"
    r"dad|mum|brother|sister|girlfriend|boyfriend|partner|lecturer|tutor|old boss|flatmate)\b",
    re.IGNORECASE,
)
_WHEN = re.compile(
    r"\b(?:last (?:week|month|year|night|time|summer|winter)|yesterday|the other day|this morning|"
    r"(?:a few|a couple of|two|three) (?:days|weeks|months|years) ago|back when|years ago)\b",
    re.IGNORECASE,
)

_STOP = set(
    """a about after again all also am an and any are as at be because been before being but by can
    could did do does doing down during each few for from further had has have having he her here
    hers him his how i if in into is it its itself just let me more most my myself no nor not now of
    off on once only or other our ours out over own same she should so some still such than that the
    their them then there these they this those through to too under until up very was we were what
    when where which while who whom why will with would you your yours really actually genuinely
    honestly think thing things something anything everything kind sort bit lot lots last week
    month year time day days ago back once told went got had made took saw tried just recently
    finally pretty quite""".split()
)
_WORD = re.compile(r"[a-z][a-z'-]+")


def _common(word: str) -> bool:
    """Very common English words ("seen", "close", "people") say nothing about whether a story
    is grounded; only the distinctive ones ("construction", "Berlin", "startups") do."""
    try:
        from wordfreq import zipf_frequency
    except ImportError:  # pragma: no cover - wordfreq is in requirements
        return False
    return zipf_frequency(word, "en") >= 5.0


def _content_words(text: str) -> list[str]:
    return [
        w
        for w in _WORD.findall(text.lower())
        if len(w) >= 4 and w not in _STOP and "'" not in w and not _common(w)
    ]


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s", "er", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


_FIRST_PERSON = re.compile(r"\b(?:I|my|me|we|our)\b", re.IGNORECASE)
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")


def personal_claims(text: str) -> list[str]:
    """Sentences that tell a first-person story or bring in his people or a time. A time on its
    own ("Microsoft said last week") is news, so it only counts alongside I/my/we."""
    return [
        s
        for s in _sentences(text)
        if _EVENT.search(s) or _PEOPLE.search(s) or (_WHEN.search(s) and _FIRST_PERSON.search(s))
    ]


_NOTE_PEOPLE = re.compile(
    r"\bmy (?:dad|mum|mom|father|mother|brother|sister|nan|gran|grandad|grandma|girlfriend|"
    r"boyfriend|partner|wife|husband|mate|friend|boss|manager|colleague|son|daughter|uncle|aunt|cousin)\b",
    re.IGNORECASE,
)


def note_drift(text: str, note: str) -> list[str]:
    """For a post written from his own note: what of the note it lost. A person the note is about
    ("my dad") must still be in the post, and at least ~40% of the note's words should be. Seen in
    testing: a note about helping his dad with his phone came back as a generic essay about
    accounts that never mentions his dad."""
    problems = []
    lowered = text.lower()
    for match in _NOTE_PEOPLE.finditer(note):
        person = match.group(0).split()[-1].lower()
        if not re.search(rf"\b{re.escape(person)}\b", lowered):
            problems.append(f"leaves out {match.group(0).lower()}")
    words = {w for w in _WORD.findall(note.lower()) if len(w) >= 3 and w not in _STOP}
    if words:
        kept = sum(1 for w in words if _stem(w) in {_stem(x) for x in _WORD.findall(lowered)})
        if kept / len(words) < 0.4:
            problems.append(f"uses only {kept} of the {len(words)} words in your note")
    return problems


def new_scene_details(text: str, sources: list[str]) -> list[str]:
    """Scene words (laptop, room, train...) in the post that the note and bio never mention."""
    source_stems = {_stem(w) for w in _WORD.findall(" ".join(sources).lower())}
    found = []
    for word in _WORD.findall(text.lower()):
        stem = _stem(word)
        if (word in SCENE_WORDS or stem in SCENE_WORDS) and stem not in source_stems and word not in found:
            found.append(word)
    return found


def unsupported_personal_claims(text: str, sources: list[str], threshold: float = 0.5) -> list[str]:
    """Personal-story sentences less than `threshold` of whose content words appear anywhere in
    the sources (the note, the research, his biography)."""
    joined = " ".join(sources)
    source_lower = joined.lower()
    source_stems = {_stem(w) for w in _content_words(joined)} | {a.lower() for a in _ACRONYM.findall(joined)}
    flagged = []
    for sentence in personal_claims(text):
        # His people and times are checked as phrases: "my manager" or "last week" must be in
        # what he gave, however ordinary the rest of the sentence is.
        people = [m.group(0).lower() for m in _PEOPLE.finditer(sentence)]
        times = [m.group(0).lower() for m in _WHEN.finditer(sentence)]
        if any(p not in source_lower for p in people) or any(t not in source_lower for t in times):
            flagged.append(sentence)
            continue
        words = _content_words(sentence) + [a.lower() for a in _ACRONYM.findall(sentence)]
        if not words:
            continue
        supported = sum(1 for w in words if _stem(w) in source_stems) / len(words)
        if supported < threshold:
            flagged.append(sentence)
    return flagged
