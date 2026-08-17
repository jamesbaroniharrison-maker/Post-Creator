"""Single-row settings for the two scheduled email jobs. Day AND time are independently
configurable per job (request: "fully customizable... ability to change the day and
time of each one")."""

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.models import EmailSettings


def get_email_settings() -> EmailSettings | None:
    with rx.session(url=config.db_url) as session:
        return session.exec(sqlmodel.select(EmailSettings)).first()


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
        return row
