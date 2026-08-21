"""Single-row settings for the two scheduled email jobs. Day AND time are independently
configurable per job (request: "fully customizable... ability to change the day and
time of each one").

Each job is a real Windows Scheduled Task that fires once a day at exactly its
configured time (request: hourly polling was "way too much" - max once a day). So a
time change here has to also move the actual OS-level trigger, or the two would drift
apart silently. _sync_scheduled_task_time does that via schtasks - best-effort, since
the task may not be registered yet (first-time setup) or this may not be Windows.
"""

import subprocess
import sys

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.models import EmailSettings

_TASK_NAMES = {
    "reminder": "WPA Weekly Reminder Email",
    "digest": "WPA Weekly Digest Email",
}


def get_email_settings() -> EmailSettings | None:
    with rx.session(url=config.db_url) as session:
        return session.exec(sqlmodel.select(EmailSettings)).first()


def _sync_scheduled_task_time(job: str, time_str: str) -> None:
    """Best-effort: move the live Scheduled Task's trigger to match. Silently does
    nothing if we're not on Windows or the task isn't registered yet - the dashboard
    save must never fail just because Task Scheduler sync couldn't happen."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["schtasks", "/Change", "/TN", _TASK_NAMES[job], "/ST", time_str],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception:  # noqa: BLE001 - best-effort only, never break the settings save
        pass


def save_email_settings(
    recipient_email: str,
    reminder_day: str,
    reminder_time: str,
    digest_day: str,
    digest_time: str,
) -> EmailSettings:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(EmailSettings)).first()
        if row is None:
            row = EmailSettings(recipient_email=recipient_email)
        row.recipient_email = recipient_email
        row.reminder_day = reminder_day
        row.reminder_time = reminder_time
        row.digest_day = digest_day
        row.digest_time = digest_time
        session.add(row)
        session.commit()
        session.refresh(row)

    _sync_scheduled_task_time("reminder", reminder_time)
    _sync_scheduled_task_time("digest", digest_time)
    return row
