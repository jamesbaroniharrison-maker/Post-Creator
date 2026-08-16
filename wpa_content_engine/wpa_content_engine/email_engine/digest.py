"""Sunday-midday weekly digest: everything currently lined up for the week ahead.

Same daily-trigger-but-internally-gated pattern as reminder.py - the Task Scheduler
trigger just needs to fire roughly around Sunday midday; the actual "is it Sunday, and
have we already sent this week" check lives here.
"""

from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.email_engine.send import send_email
from wpa_content_engine.email_engine.settings import get_email_settings
from wpa_content_engine.models import JobRun, Post

JOB_NAME = "weekly_digest"
QUEUE_STATUSES = ["drafted", "approved"]


def _already_sent_this_week(now: datetime) -> bool:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
    return row is not None and (now - row.last_run_at) < timedelta(days=6)


def _mark_sent(now: datetime) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
        if row:
            row.last_run_at = now
            session.add(row)
        else:
            session.add(JobRun(job_name=JOB_NAME, last_run_at=now))
        session.commit()


def _build_digest_body() -> str:
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(Post)
            .where(sqlmodel.col(Post.status).in_(QUEUE_STATUSES))
            .order_by(sqlmodel.col(Post.suggested_day))
        ).all()

    if not rows:
        return "Nothing lined up for this week yet - the topic bank and Quick Actions in the dashboard are the fastest way to fill it in."

    lines = ["Here's what's lined up for this week:\n"]
    for p in rows:
        day = p.suggested_day or "Unscheduled"
        excerpt = p.draft_text[:120] + ("..." if len(p.draft_text) > 120 else "")
        lines.append(f"[{day}] ({p.status}) {p.post_type}: {excerpt}")
    lines.append("\nReview and approve them in the dashboard whenever suits you.")
    return "\n".join(lines)


def run_weekly_digest(force: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    settings = get_email_settings()

    if not settings or not settings.digest_enabled:
        return {"status": "skipped", "reason": "digest disabled or no email settings configured"}

    is_sunday = now.weekday() == 6
    if not force and not is_sunday:
        return {"status": "skipped", "reason": "not Sunday"}
    if not force and _already_sent_this_week(now):
        return {"status": "skipped", "reason": "already sent this week"}

    body = _build_digest_body()
    sent, message = send_email(settings.recipient_email, "This week's posts - WPA Content Engine", body)
    if sent:
        _mark_sent(now)
    return {"status": "ok" if sent else "failed", "reason": message}
