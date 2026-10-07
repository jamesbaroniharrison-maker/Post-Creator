"""Weekly digest: next week's approved posts (full text, images, carousel PDFs) and your
plan-ahead notes, labelled day by day.

Same daily-trigger-but-internally-gated pattern as reminder.py - both day and time are
fully configurable from the dashboard's "Email reminders" card.
"""

import pathlib
from datetime import date, datetime, timedelta, timezone
from html import escape

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.email_engine.send import send_email
from linkedin_content_engine.email_engine.settings import get_email_settings
from linkedin_content_engine.exports import build_bundle, post_date
from linkedin_content_engine.models import JobRun, PlannedNote, Post
from linkedin_content_engine.scheduling import allocate_accepted_posts, current_week_label, week_dates
from linkedin_content_engine.utils import as_utc

JOB_NAME = "weekly_digest"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Gmail rejects anything over 25MB. Above this, carousels show only their first slide
# inline - the attached PDF still carries every slide.
_INLINE_BUDGET = 18 * 1024 * 1024

_LABEL = "font:12px/1.4 monospace;letter-spacing:.12em;color:#7D5C2A;text-transform:uppercase"
_FOOTNOTE = "Nothing is posted automatically - you post each one yourself."


def _already_sent_this_week(now_utc: datetime) -> bool:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
    return row is not None and (now_utc - as_utc(row.last_run_at)) < timedelta(days=6)


def _mark_sent(now_utc: datetime) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
        if row:
            row.last_run_at = now_utc
            session.add(row)
        else:
            session.add(JobRun(job_name=JOB_NAME, last_run_at=now_utc))
        session.commit()


def next_week_monday() -> str:
    monday = datetime.strptime(current_week_label(), "%Y-%m-%d") + timedelta(days=7)
    return monday.strftime("%Y-%m-%d")


def _day_label(day: date) -> str:
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


def build_digest(week: str | None = None) -> dict:
    """Returns {"subject", "text", "html", "inline", "attachments", "count"} for the
    week starting `week` (default: next week). Every approved post comes with its full
    text, its images inline, and its carousel PDF attached; days with only a plan-ahead
    note show the note, marked as not approved yet."""
    allocate_accepted_posts()
    week = week or next_week_monday()
    dates = week_dates(week)
    with rx.session(url=config.db_url) as session:
        posts = session.exec(
            sqlmodel.select(Post).where(
                sqlmodel.col(Post.scheduled_week) == week,
                sqlmodel.col(Post.status).in_(["approved", "published"]),
            )
        ).all()
        ordered = sorted(posts, key=lambda p: (post_date(p) or date.max, p.id))
        meta = {
            p.id: {
                "type": p.post_type.replace("_", " ").title(),
                "note": p.visual_note or "",
            }
            for p in ordered
        }
        ids = [p.id for p in ordered]
        notes = [
            (n.target_date, n.post_type, n.note_text)
            for n in session.exec(
                sqlmodel.select(PlannedNote).where(sqlmodel.col(PlannedNote.target_date).in_(dates))
            ).all()
        ]
        awaiting = session.exec(
            sqlmodel.select(sqlmodel.func.count()).select_from(Post).where(Post.status == "drafted")
        ).one()

    bundles = []
    for pid in ids:
        b = build_bundle(pid)
        if b:
            bundles.append({**b, **meta[pid]})

    total = sum(pathlib.Path(f).stat().st_size for b in bundles for f in [*b["pngs"], b["pdf"]] if f)
    trim = total > _INLINE_BUDGET

    start = date.fromisoformat(week)
    nice_week = f"{start.day} {start.strftime('%B %Y')}"
    which = "This week's" if week == current_week_label() else "Next week's"
    subject = f"{which} posts (w/c {nice_week}) - {len(bundles)} ready"
    text_lines = [f"Your LinkedIn posts for the week commencing {nice_week}.", ""]
    html_days: list[str] = []
    inline: list[tuple[str, str]] = []
    attachments: list[str] = []

    for d in dates:
        day = date.fromisoformat(d)
        day_posts = [b for b in bundles if b["date"] == day]
        day_notes = [n for n in notes if n[0] == d] if not day_posts else []  # an approved post already covers the plan
        if not day_posts and not day_notes:
            continue
        label = _day_label(day)
        text_lines.append(f"=== {label.upper()} ===")
        blocks: list[str] = []
        for b in day_posts:
            files = b["pngs"][:1] if (trim and b["pdf"]) else b["pngs"]
            imgs = []
            for path in files:
                cid = f"img{len(inline)}"
                inline.append((cid, path))
                imgs.append(
                    f'<img src="cid:{cid}" alt="" width="270" style="width:270px;max-width:48%;height:auto;'
                    'border:1px solid #D8D0BF;margin:0 8px 8px 0;display:inline-block">'
                )
            if b["pdf"]:
                attachments.append(b["pdf"])
                kind = "Carousel: upload the attached PDF as a document post"
            elif b["pngs"]:
                kind = "Image: save it from this email"
            else:
                kind = "Text only"
            text_lines += [f"[{b['type']}] {kind}", b["text"], f"Folder: {b['dir']}", ""]
            blocks.append(
                '<div style="margin:0 0 28px">'
                f'<div style="{_LABEL}">{escape(b["type"])} &middot; {escape(kind)}</div>'
                '<div style="font:16px/1.55 Arial,sans-serif;color:#1B1F1A;white-space:pre-wrap;margin:10px 0 14px">'
                f'{escape(b["text"])}</div>'
                + "".join(imgs)
                + (f'<div style="font:13px Arial;color:#8A4B3A">{escape(b["note"])}</div>' if b["note"] else "")
                + f'<div style="font:12px Arial;color:#6B695F;margin-top:6px">Ready-to-post folder: {escape(b["dir"])}</div>'
                "</div>"
            )
        for _, ptype, note in day_notes:
            kind = ptype.replace("_", " ").title()
            text_lines += [f"[Planned: {kind}] not drafted or approved yet: {note}", ""]
            blocks.append(
                '<div style="margin:0 0 28px;padding:14px 16px;background:#ECE6D8">'
                f'<div style="{_LABEL}">Planned &middot; {escape(kind)} &middot; not approved yet</div>'
                f'<div style="font:15px/1.5 Arial;color:#1B1F1A;margin-top:6px">{escape(note)}</div></div>'
            )
        html_days.append(
            '<h2 style="font:400 26px Georgia,serif;color:#1B1F1A;border-top:2px solid #D8D0BF;'
            f'padding-top:18px;margin:28px 0 16px">{escape(label)}</h2>' + "".join(blocks)
        )

    if not html_days:
        when = which.split("'")[0].lower()
        text_lines.append(f"Nothing approved or planned for {when} yet.")
        html_days.append(f'<p style="font:16px Arial;color:#4D4C43">Nothing approved or planned for {when} yet.</p>')
    footer = f"{awaiting} draft(s) waiting in Review. " if awaiting else ""
    if trim:
        footer += "Carousels show their first slide only here, to stay under the email size limit; every slide is in the PDF. "
    footer += _FOOTNOTE
    text_lines.append(footer)

    html = (
        '<div style="background:#F6F2E9;padding:32px 24px"><div style="max-width:640px;margin:0 auto">'
        f'<div style="{_LABEL}">Content Engine &middot; week ahead</div>'
        '<h1 style="font:400 34px Georgia,serif;color:#1B1F1A;margin:8px 0 4px">Week commencing '
        f'<em style="color:#9A7437">{escape(nice_week)}</em></h1>'
        + "".join(html_days)
        + f'<p style="font:13px Arial;color:#6B695F;border-top:2px solid #D8D0BF;padding-top:14px">{escape(footer)}</p>'
        "</div></div>"
    )
    return {
        "subject": subject,
        "text": "\n".join(text_lines),
        "html": html,
        "inline": inline,
        "attachments": attachments,
        "count": len(bundles),
    }


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

    digest = build_digest()
    sent, message = send_email(
        settings.recipient_email,
        digest["subject"],
        digest["text"],
        html=digest["html"],
        inline_images=digest["inline"],
        attachments=digest["attachments"],
    )
    if sent:
        _mark_sent(now_utc)
    return {"status": "ok" if sent else "failed", "reason": message}
