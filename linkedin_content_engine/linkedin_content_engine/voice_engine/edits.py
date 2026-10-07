"""Learning from James's own edits.

Every draft keeps the text exactly as the engine wrote it (Post.original_text); edits in Review
only change draft_text. So for every post he accepts, the difference between the two is the most
direct evidence there is of what still doesn't sound like him - and it costs him nothing extra.

Two uses:
- recent_edit_lessons(): his actual changes ("It is a bit" -> "It's a bit", "cut: operational
  discipline is what keeps things moving") go back into the drafting prompt and the voice pass,
  newest first, so the next draft makes the same changes before he has to.
- edit_stats(): how much he's had to change accepted drafts, on average. That's the real,
  human measure of "does this sound like me": it should fall over time.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import Post

ACCEPTED = ("approved", "published")
_PUNCT_ONLY = re.compile(r"^[\W_]*$")


def _words(text: str) -> list[str]:
    return text.split()


def edit_ratio(before: str, after: str) -> float:
    """Share of the words that changed between the draft and what he kept, 0..1."""
    return 1.0 - difflib.SequenceMatcher(a=_words(before), b=_words(after), autojunk=False).ratio()


def word_hunks(before: str, after: str) -> list[tuple[str, str]]:
    """(what the draft said, what he changed it to) for every changed stretch of words."""
    a, b = _words(before), _words(after)
    hunks = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        old, new = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if _PUNCT_ONLY.match(old) and _PUNCT_ONLY.match(new):
            continue  # a moved comma tells the next draft nothing
        hunks.append((old, new))
    return hunks


def _accepted_with_edits(limit: int) -> list[Post]:
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(Post)
            .where(sqlmodel.col(Post.status).in_(ACCEPTED))
            .where(sqlmodel.col(Post.original_text).is_not(None))
            .order_by(sqlmodel.col(Post.reviewed_at).desc())
            .limit(limit)
        ).all()
    return [p for p in rows if p.original_text and p.original_text.strip() != (p.draft_text or "").strip()]


def recent_edit_lessons(limit_posts: int = 8, max_lessons: int = 10) -> list[str]:
    """His recent changes to drafts as short "before -> after" lines, newest posts first. Very
    long rewrites are summarised rather than quoted whole, so one big edit can't crowd out the rest."""
    lessons: list[str] = []
    for post in _accepted_with_edits(limit_posts):
        before, after = post.original_text or "", post.draft_text or ""
        if edit_ratio(before, after) > 0.5:
            # Rewritten almost entirely: word-level pieces of that diff read as nonsense, so show
            # how the draft started and how his version started instead.
            lessons.append(
                f'rewrote most of a draft - it began "{" ".join(before.split()[:30])}..." and he made it '
                f'"{" ".join(after.split()[:30])}..."'
            )
            if len(lessons) >= max_lessons:
                return lessons
            continue
        for old, new in word_hunks(before, after):
            old_short, new_short = " ".join(old.split()[:25]), " ".join(new.split()[:25])
            if old and new:
                lessons.append(f'"{old_short}" -> "{new_short}"')
            elif old:
                lessons.append(f'cut: "{old_short}"')
            else:
                lessons.append(f'added: "{new_short}"')
            if len(lessons) >= max_lessons:
                return lessons
    return lessons


def edit_lessons_block() -> str:
    """The prompt block, or "" when there's nothing to learn from yet."""
    try:
        lessons = recent_edit_lessons()
    except Exception:  # noqa: BLE001 - learning from edits must never stop a draft
        return ""
    if not lessons:
        return ""
    lines = "\n".join(f"- {line}" for line in lessons)
    return (
        "HOW HE'S CORRECTED RECENT DRAFTS (his own edits before posting, newest first). Make "
        "the same kind of changes yourself, so he doesn't have to:\n" + lines
    )


@dataclass
class EditStats:
    accepted_with_original: int  # accepted posts that kept their original draft
    edited: int  # how many of those he changed at all
    average_changed: float  # mean share of words changed, 0..1, over all of them
    score_up: int = 0  # edited posts his edit made score higher on "sounds like you"
    score_down: int = 0  # ...and lower. Mostly "up" = the score agrees with his taste.


def edit_stats(limit: int = 30) -> EditStats:
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(Post)
            .where(sqlmodel.col(Post.status).in_(ACCEPTED))
            .where(sqlmodel.col(Post.original_text).is_not(None))
            .order_by(sqlmodel.col(Post.reviewed_at).desc())
            .limit(limit)
        ).all()
    ratios = [edit_ratio(p.original_text or "", p.draft_text or "") for p in rows]
    # Does the "sounds like you" score agree with him? His edits are the ground truth: if they
    # usually raise the score, it's measuring what he cares about; if not, it needs recalibrating.
    from linkedin_content_engine.voice_engine.fingerprint import reference_from_corpus, score_text

    up = down = 0
    edited_rows = [p for p, r in zip(rows, ratios) if r > 0.005]
    if edited_rows:
        reference = reference_from_corpus()
        for p in edited_rows:
            before = score_text(p.original_text or "", reference).score
            after = score_text(p.draft_text or "", reference).score
            up += after > before
            down += after < before
    return EditStats(
        accepted_with_original=len(ratios),
        edited=sum(1 for r in ratios if r > 0.005),
        average_changed=(sum(ratios) / len(ratios)) if ratios else 0.0,
        score_up=up,
        score_down=down,
    )
