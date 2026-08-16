"""Weekly personal-story reminder email.

Runs from a daily Task Scheduler trigger (like the research cron) but only actually
sends on the day she's chosen (EmailSettings.reminder_day) and at most once a week -
so the day preference is fully changeable from the dashboard without ever touching
Windows Task Scheduler again.
"""

from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.email_engine.send import send_email
from wpa_content_engine.email_engine.settings import get_email_settings
from wpa_content_engine.models import JobRun

JOB_NAME = "weekly_reminder"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SUBJECT = "Your weekly personal story - WPA Content Engine"
BODY = """Hi Ben,

Quick nudge - it's time for this week's personal post. Doesn't need to be big: a
quick thought, something that happened this week (or last week is fine too), a photo,
a voice note - whatever's easiest.

Open the dashboard and use the "Weekly input" box to send it in, however's quickest
for you. It'll turn into a draft automatically, ready for you to review.

- The WPA Content Engine
"""


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


def run_weekly_reminder(force: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    settings = get_email_settings()

    if not settings or not settings.reminder_enabled:
        return {"status": "skipped", "reason": "reminder disabled or no email settings configured"}

    today_name = WEEKDAYS[now.weekday()]
    if not force and today_name != settings.reminder_day:
        return {"status": "skipped", "reason": f"today is {today_name}, reminder day is {settings.reminder_day}"}
    if not force and _already_sent_this_week(now):
        return {"status": "skipped", "reason": "already sent this week"}

    sent, message = send_email(settings.recipient_email, SUBJECT, BODY)
    if sent:
        _mark_sent(now)
    return {"status": "ok" if sent else "failed", "reason": message}
