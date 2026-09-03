"""Fixed-date holiday recognition for the planning calendar (request: "sync with like
holidays and recommend if it was a specific day... Christmas post or Halloween post").

Deliberately fixed-date only, not a full holiday-calculation library - variable-date
holidays (Easter, Mother's/Father's Day, bank holiday Mondays) would need real date
arithmetic and aren't worth the complexity for a nudge feature. UK-leaning, since
that's the actual audience. Add more here as they come up; nothing else needs to
change - callers just look up a "MM-DD" key.
"""

from datetime import date

# "MM-DD" -> (name, a short angle to nudge the topic/note field toward)
HOLIDAYS: dict[str, tuple[str, str]] = {
    "01-01": ("New Year's Day", "a fresh-start/new-year reflection post"),
    "02-14": ("Valentine's Day", "a lighthearted post about relationships/connection, kept professional"),
    "03-17": ("St Patrick's Day", "a lighthearted, optional seasonal post"),
    "04-01": ("April Fools' Day", "a playful, clearly-not-serious post if it fits the voice"),
    "05-04": ("Star Wars Day", "a playful tech/pop-culture-adjacent post if it fits"),
    "10-31": ("Halloween", "a Halloween-themed post - a spooky/seasonal framing on the usual content"),
    "11-05": ("Bonfire Night", "a UK seasonal post if it fits"),
    "12-24": ("Christmas Eve", "a warm, reflective end-of-year post"),
    "12-25": ("Christmas Day", "a Christmas-themed post - keep it light, this is a big day to post seriously"),
    "12-26": ("Boxing Day", "a quiet, low-key post if posting at all"),
    "12-31": ("New Year's Eve", "a reflective look-back-on-the-year post"),
}


def holiday_for_date(date_str: str) -> tuple[str, str] | None:
    """date_str is "YYYY-MM-DD". Returns (name, suggested angle) or None."""
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return None
    return HOLIDAYS.get(d.strftime("%m-%d"))
