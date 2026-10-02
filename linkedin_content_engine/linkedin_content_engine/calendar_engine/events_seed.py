"""Code-computed yearly occasions for an AI-focused LinkedIn calendar.

Ported from the Ben Holmes content engine (healthcare/insurance occasions), re-pointed
at AI, tech, data and careers. Same rule as the original: only dates that are fixed on
the calendar or follow a simple documented rule are seeded, computed exactly. The rules
below were checked against real past dates (e.g. Ada Lovelace Day: 8 Oct 2024 and
14 Oct 2025, both the second Tuesday). Anything whose date moves unpredictably -
conferences, London Tech Week, Safer Internet Day - is left to discovery.py's
grounded research pass rather than guessed here.
"""

import calendar
from datetime import datetime, timedelta, timezone


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
    """The n-th occurrence (1-indexed) of `weekday` (Monday=0) in a month."""
    first_weekday, _ = calendar.monthrange(year, month)
    offset = (weekday - first_weekday) % 7
    return datetime(year, month, 1 + offset + 7 * (n - 1), tzinfo=timezone.utc)


def _fixed(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


# (month, day, name, category, angle_notes)
_FIXED_SINGLE_DAY: list[tuple[int, int, str, str, str]] = [
    (1, 1, "New Year's Day", "general", "A fresh-start post: what you're building or learning in AI this year."),
    (
        1,
        28,
        "Data Protection Day",
        "data",
        "How AI systems should handle personal data: privacy by design, keeping PII out, consent.",
    ),
    (
        3,
        8,
        "International Women's Day",
        "careers",
        "Women building AI, and who gets left out when training data and teams aren't diverse.",
    ),
    (3, 14, "Pi Day", "tech", "A light angle on the maths underneath the models - optional, keep it fun."),
    (
        4,
        21,
        "World Creativity and Innovation Day",
        "ai",
        "AI and human creativity: tools that extend creative work rather than replace it.",
    ),
    (
        5,
        17,
        "World Telecommunication and Information Society Day",
        "tech",
        "Digital access: who actually benefits from AI, and who's still locked out.",
    ),
    (
        6,
        23,
        "Alan Turing's birthday",
        "ai",
        "Turing's question 'can machines think?' and how far the field has really come since.",
    ),
    (
        7,
        15,
        "World Youth Skills Day",
        "careers",
        "The skills people need now that AI handles the routine work - and your own learning path.",
    ),
    (
        7,
        16,
        "AI Appreciation Day",
        "ai",
        "What AI genuinely does well in practice - a concrete human-in-the-loop win, not hype.",
    ),
    (
        10,
        10,
        "World Mental Health Day",
        "general",
        "Tech and wellbeing: always-on tools, burnout, and building systems that give time back.",
    ),
    (
        11,
        30,
        "Computer Security Day",
        "data",
        "AI security: guardrails, prompt injection, and why a human approval step still matters.",
    ),
    (
        12,
        9,
        "Grace Hopper's birthday",
        "tech",
        "Making technology usable by non-specialists - Hopper's legacy and today's no-code AI tools.",
    ),
    (12, 25, "Christmas Day", "general", "A light seasonal post, not a pitch."),
    (12, 31, "New Year's Eve", "general", "Year in review: what actually changed in AI this year, and what didn't."),
]

# (name, category, angle_notes, start_month, start_day, end_month, end_day)
_FIXED_RANGE: list[tuple[str, str, str, int, int, int, int]] = [
    (
        "Cybersecurity Awareness Month",
        "data",
        "Security of AI systems and data: practical guardrails for small businesses adopting AI.",
        10,
        1,
        10,
        31,
    ),
]


def _rule_based(year: int) -> list[tuple[datetime, str, str, str]]:
    """(date, name, category, angle_notes) for occasions defined by a rule."""
    leap = calendar.isleap(year)
    return [
        (
            _nth_weekday(year, 4, 3, 4),  # fourth Thursday of April
            "International Girls in ICT Day",
            "careers",
            "Getting more girls into tech and AI careers - who's building the future.",
        ),
        (
            _nth_weekday(year, 5, 3, 3),  # third Thursday of May
            "Global Accessibility Awareness Day",
            "tech",
            "AI as an accessibility tool, and designing tools non-technical people can actually use.",
        ),
        (
            _fixed(year, 1, 1) + timedelta(days=255),  # 256th day: 13 Sep, 12 Sep in leap years
            "Day of the Programmer",
            "tech",
            "The people behind the systems - what building with AI is really like day to day."
            + (" (12 Sep this year - a leap year.)" if leap else ""),
        ),
        (
            _nth_weekday(year, 10, 1, 2),  # second Tuesday of October
            "Ada Lovelace Day",
            "careers",
            "Women in STEM, and Lovelace's early insight that machines could do more than calculate.",
        ),
    ]


def seed_events_for_year(year: int) -> list[dict]:
    """Every seeded occasion for a calendar year, as dicts ready to become rows."""
    events = []
    for month, day, name, category, notes in _FIXED_SINGLE_DAY:
        events.append(_row(year, _fixed(year, month, day), None, name, category, notes))
    for name, category, notes, sm, sd, em, ed in _FIXED_RANGE:
        events.append(_row(year, _fixed(year, sm, sd), _fixed(year, em, ed), name, category, notes))
    for when, name, category, notes in _rule_based(year):
        events.append(_row(year, when, None, name, category, notes))
    return sorted(events, key=lambda e: e["date"])


def _row(year, start, end, name, category, notes) -> dict:
    return {
        "date": start,
        "end_date": end,
        "name": name,
        "category": category,
        "angle_notes": notes,
        "year": year,
        "source": "seed",
    }
