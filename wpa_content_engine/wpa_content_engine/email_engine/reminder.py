"""Weekly personal-story reminder email.

Runs from an hourly Task Scheduler trigger (see scripts/register_email_tasks.ps1) but
only actually sends when today's weekday AND current local hour match what she's set
in the dashboard's "Email reminders" card, and at most once a week - so both the day
and the time are fully changeable without ever touching Windows Task Scheduler again.
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


def run_weekly_reminder(force: bool = False) -> dict:
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()  # the machine's local time - what "9am" means to her
    settings = get_email_settings()

    if not settings or not settings.reminder_enabled:
        return {"status": "skipped", "reason": "reminder disabled or no email settings configured"}

    today_name = WEEKDAYS[now_local.weekday()]
    target_hour = int(settings.reminder_time.split(":")[0])
    if not force and today_name != settings.reminder_day:
        return {"status": "skipped", "reason": f"today is {today_name}, reminder day is {settings.reminder_day}"}
    if not force and now_local.hour != target_hour:
        return {"status": "skipped", "reason": f"it's {now_local.hour}:00, reminder time is {settings.reminder_time}"}
    if not force and _already_sent_this_week(now_utc):
        return {"status": "skipped", "reason": "already sent this week"}

    sent, message = send_email(settings.recipient_email, SUBJECT, BODY)
    if sent:
        _mark_sent(now_utc)
    return {"status": "ok" if sent else "failed", "reason": message}
