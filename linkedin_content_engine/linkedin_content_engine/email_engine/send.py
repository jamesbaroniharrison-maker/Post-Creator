"""Sends email via SMTP (Gmail app password by default, but any SMTP host works).

Not in the original spec - requested later (weekly personal-story reminder + Sunday
post digest). Sending is inert (returns False, logs why) until EMAIL_ADDRESS/
EMAIL_APP_PASSWORD are set in .env - the two scheduled jobs that use this degrade
gracefully rather than crash if email isn't configured yet.
"""

import os
import smtplib
from email.mime.text import MIMEText

import dotenv

dotenv.load_dotenv()


def send_email(to_address: str, subject: str, body: str) -> tuple[bool, str]:
    """Returns (sent, message) - message explains failures in plain English."""
    from_address = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    if not from_address or not app_password:
        return False, "Email isn't configured yet (EMAIL_ADDRESS/EMAIL_APP_PASSWORD missing in .env)."
    if not to_address:
        return False, "No recipient email set - add one in the dashboard's email settings."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(from_address, app_password)
            server.send_message(msg)
        return True, "Sent."
    except Exception as exc:  # noqa: BLE001 - surface any SMTP failure clearly, don't crash the job
        return False, f"Email send failed: {exc}"
