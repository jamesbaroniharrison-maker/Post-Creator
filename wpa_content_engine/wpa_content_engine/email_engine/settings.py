"""Single-row settings for the two scheduled email jobs (recipient + which day to
nudge for a personal story)."""

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.models import EmailSettings


def get_email_settings() -> EmailSettings | None:
    with rx.session(url=config.db_url) as session:
        return session.exec(sqlmodel.select(EmailSettings)).first()


def save_email_settings(recipient_email: str, reminder_day: str) -> EmailSettings:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(EmailSettings)).first()
        if row:
            row.recipient_email = recipient_email
            row.reminder_day = reminder_day
        else:
            row = EmailSettings(recipient_email=recipient_email, reminder_day=reminder_day)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
