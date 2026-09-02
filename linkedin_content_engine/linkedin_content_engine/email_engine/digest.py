"""Weekly digest: everything currently scheduled for the week ahead.

Same daily-trigger-but-internally-gated pattern as reminder.py - both day and time are
fully configurable from the dashboard's "Email reminders" card.
"""

from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.email_engine.send import send_email
from linkedin_content_engine.email_engine.settings import get_email_settings
from linkedin_content_engine.models import JobRun, Post
from linkedin_content_engine.scheduling import allocate_accepted_posts, current_week_label

JOB_NAME = "weekly_digest"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _already_sent_this_week(now_utc: datetime) -> bool:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
    return row is not None and (now_utc - row.last_run_at) < timedelta(days=6)


def _mark_sent(now_utc: datetime) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
        if row:
            row.last_run_at = now_utc
            session.add(row)
        else:
            session.add(JobRun(job_name=JOB_NAME, last_run_at=now_utc))
        session.commit()


def _build_digest_body() -> str:
    allocate_accepted_posts()
    week = current_week_label()
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(Post)
            .where(sqlmodel.col(Post.scheduled_week) == week)
            .order_by(sqlmodel.col(Post.created_at))
        ).all()

    if not rows:
        return "Nothing lined up for this week yet - the topic bank and Quick Actions in the dashboard are the fastest way to fill it in."

    lines = ["Here's what's lined up for this week:\n"]
    for p in rows:
        excerpt = p.draft_text[:120] + ("..." if len(p.draft_text) > 120 else "")
        lines.append(f"({p.status}) {p.post_type.replace('_', ' ').title()}: {excerpt}")
    lines.append("\nReview and approve them in the dashboard whenever suits you.")
    return "\n".join(lines)


def run_weekly_digest(force: bool = False) -> dict:
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()
    settings = get_email_settings()

    if not settings or not settings.digest_enabled:
        return {"status": "skipped", "reason": "digest disabled or no email settings configured"}

    today_name = WEEKDAYS[now_local.weekday()]
    target_hour = int(settings.digest_time.split(":")[0])
    if not force and today_name != settings.digest_day:
        return {"status": "skipped", "reason": f"today is {today_name}, digest day is {settings.digest_day}"}
    if not force and now_local.hour != target_hour:
        return {"status": "skipped", "reason": f"it's {now_local.hour}:00, digest time is {settings.digest_time}"}
    if not force and _already_sent_this_week(now_utc):
        return {"status": "skipped", "reason": "already sent this week"}

    body = _build_digest_body()
    sent, message = send_email(settings.recipient_email, "This week's posts - Content Engine", body)
    if sent:
        _mark_sent(now_utc)
    return {"status": "ok" if sent else "failed", "reason": message}
