"""Auto-allocates accepted posts into weeks (request: "AI automatically chooses which
ones are going into this week's lot... if too many, automatically puts them for next
week"), and prunes rejected posts down to the last 5 (request: "only want to save the
last five... after that, I wanted to delete them").
"""

from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import Post

WEEKLY_CAP = 4  # spec Â§1: 3-4 posts/week
REJECTED_KEEP = 5


def _week_monday(dt: datetime) -> str:
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def _next_week(week: str) -> str:
    monday = datetime.strptime(week, "%Y-%m-%d") + timedelta(days=7)
    return monday.strftime("%Y-%m-%d")


def current_week_label() -> str:
    return _week_monday(datetime.now(timezone.utc))


def current_week_start() -> datetime:
    """Monday 00:00 UTC of the current week, as a tz-aware datetime - for filtering
    `Post.created_at` (also tz-aware UTC) against "this week", e.g. checking whether
    you've already sent in a personal reflection before nudging for one."""
    monday_str = current_week_label()
    return datetime.strptime(monday_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def upcoming_week_mondays(count: int = 4) -> list[str]:
    """This week's Monday plus the next `count - 1` - the 4-week look-ahead horizon
    used by the Accepted page's week selector and forward-planning notes."""
    start = datetime.strptime(current_week_label(), "%Y-%m-%d")
    return [(start + timedelta(days=7 * i)).strftime("%Y-%m-%d") for i in range(count)]


def week_dates(monday: str) -> list[str]:
    """The 7 calendar dates (YYYY-MM-DD) in the week starting on `monday`."""
    start = datetime.strptime(monday, "%Y-%m-%d")
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def allocate_accepted_posts() -> int:
    """Give every unscheduled approved/published post a scheduled_week, filling the
    current week up to WEEKLY_CAP before spilling into the next, and so on. Safe to
    call repeatedly (a no-op once everything's allocated). Returns count newly assigned.
    """
    with rx.session(url=config.db_url) as session:
        scheduled_rows = session.exec(
            sqlmodel.select(Post).where(sqlmodel.col(Post.scheduled_week).is_not(None))
        ).all()
        week_counts: dict[str, int] = {}
        for r in scheduled_rows:
            week_counts[r.scheduled_week] = week_counts.get(r.scheduled_week, 0) + 1

        unscheduled = session.exec(
            sqlmodel.select(Post)
            .where(
                sqlmodel.col(Post.status).in_(["approved", "published"]),
                sqlmodel.col(Post.scheduled_week).is_(None),
            )
            .order_by(sqlmodel.col(Post.reviewed_at).asc())
        ).all()

        week = current_week_label()
        assigned = 0
        for post in unscheduled:
            while week_counts.get(week, 0) >= WEEKLY_CAP:
                week = _next_week(week)
            post.scheduled_week = week
            week_counts[week] = week_counts.get(week, 0) + 1
            session.add(post)
            assigned += 1
        session.commit()
    return assigned


def prune_rejected_posts(keep: int = REJECTED_KEEP) -> int:
    """Delete rejected posts beyond the most recent `keep`. Returns count deleted."""
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(Post)
            .where(Post.status == "rejected")
            .order_by(sqlmodel.col(Post.reviewed_at).desc())
        ).all()
        stale = rows[keep:]
        for row in stale:
            session.delete(row)
        session.commit()
    return len(stale)
