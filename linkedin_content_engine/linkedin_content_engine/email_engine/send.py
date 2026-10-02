"""Sends email via SMTP (Gmail app password by default, but any SMTP host works).

Not in the original spec - requested later (weekly personal-story reminder + Sunday
post digest). Sending is inert (returns False, logs why) until EMAIL_ADDRESS/
EMAIL_APP_PASSWORD are set in .env - the two scheduled jobs that use this degrade
gracefully rather than crash if email isn't configured yet.
"""

import mimetypes
import os
import pathlib
import smtplib
from email.message import EmailMessage

import dotenv

dotenv.load_dotenv()


def send_email(
    to_address: str,
    subject: str,
    body: str,
    html: str | None = None,
    inline_images: list[tuple[str, str]] | None = None,
    attachments: list[str] | None = None,
) -> tuple[bool, str]:
    """Returns (sent, message) - message explains failures in plain English.

    `body` is the plain-text version, always sent. `html` adds a rich version;
    `inline_images` are (content_id, path) pairs the html shows via src="cid:<id>";
    `attachments` are file paths attached as downloads (PNGs, carousel PDFs)."""
    from_address = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    if not from_address or not app_password:
        return False, "Email isn't configured yet (EMAIL_ADDRESS/EMAIL_APP_PASSWORD missing in .env)."
    if not to_address:
        return False, "No recipient email set - add one in the dashboard's email settings."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
        html_part = msg.get_payload()[-1]
        for cid, path in inline_images or []:
            maintype, subtype = (mimetypes.guess_type(path)[0] or "image/png").split("/")
            html_part.add_related(
                pathlib.Path(path).read_bytes(), maintype=maintype, subtype=subtype,
                cid=f"<{cid}>", filename=pathlib.Path(path).name,
            )
    for path in attachments or []:
        maintype, subtype = (mimetypes.guess_type(path)[0] or "application/octet-stream").split("/")
        msg.add_attachment(
            pathlib.Path(path).read_bytes(), maintype=maintype, subtype=subtype, filename=pathlib.Path(path).name
        )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(from_address, app_password)
            server.send_message(msg)
        return True, "Sent."
    except Exception as exc:  # noqa: BLE001 - surface any SMTP failure clearly, don't crash the job
        return False, f"Email send failed: {exc}"
