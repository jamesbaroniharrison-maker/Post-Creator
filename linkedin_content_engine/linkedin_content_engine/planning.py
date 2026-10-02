"""Prepare a week in one go: plan each day from the weekly template, draft it, and make
its visual. Everything lands in Review - nothing is approved or posted for you.

Used by the dashboard's "Prepare next week" / "Plan this week" buttons and by the
Saturday run in the daily research job (when switched on in the weekly template).
"""

import random
from datetime import date, datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.drafting_engine.pipeline import generate_and_save_draft, generate_draft_with_research
from linkedin_content_engine.drafting_engine.research import ResearchFinding, ResearchResult
from linkedin_content_engine.email_engine.reminder import PROMPT_POOL
from linkedin_content_engine.holidays import holiday_for_date
from linkedin_content_engine.models import JobRun, PlannedNote, TopicBank, WeeklyTemplate
from linkedin_content_engine.scheduling import current_week_label, week_dates
from linkedin_content_engine.utils import as_utc

CATEGORY_TO_POST_TYPE = {"ai": "ai_commentary", "market": "market_commentary"}
AUTO_PREPARE_JOB = "auto_prepare_week"
AUTO_PREPARE_WEEKDAY = 5  # Saturday - the week's drafts are waiting for you by Sunday


def draft_from_bank_row(
    bank_id: int,
    summary: str,
    source_title: str,
    source_url: str,
    category: str,
    rotation_overrides: dict[str, str] | None = None,
) -> None:
    """Drafts from one topic bank row and marks it used. Raises on failure so callers
    can decide how to report it."""
    research = ResearchResult(
        topic=summary,
        status="ok",
        findings=[ResearchFinding(title=source_title, url=source_url, content=summary)],
    )
    post_type = CATEGORY_TO_POST_TYPE.get(category, "ai_commentary")
    generate_draft_with_research(
        summary, post_type, research, source_bank_id=bank_id, rotation_overrides=rotation_overrides
    )
    with rx.session(url=config.db_url) as session:
        row = session.get(TopicBank, bank_id)
        row.used = True
        row.date_used = datetime.now(timezone.utc)
        session.add(row)
        session.commit()


def next_week_monday() -> str:
    return (datetime.strptime(current_week_label(), "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")


def prepare_week(monday: str) -> dict:
    """Reads the weekly template day by day (including "no post"), swaps in a holiday
    angle where one lands (when switched on), and drafts each planned day. Never
    touches a day that already has a note - a day you've decided on stays yours.

    Returns {"planned", "skipped_no_post", "failed"}."""
    with rx.session(url=config.db_url) as session:
        template = session.exec(sqlmodel.select(WeeklyTemplate)).first() or WeeklyTemplate()
        already_noted = {
            n.target_date
            for n in session.exec(
                sqlmodel.select(PlannedNote).where(sqlmodel.col(PlannedNote.target_date).in_(week_dates(monday)))
            ).all()
        }

    planned = skipped_no_post = failed = 0
    for d in week_dates(monday):
        if d in already_noted:
            continue
        post_type = getattr(template, date.fromisoformat(d).strftime("%A").lower())
        holiday = holiday_for_date(d) if template.recommend_holidays else None
        note_text = ""
        if holiday:
            note_text = f"{holiday[0]}: {holiday[1]}"
            if post_type == "no_post":
                post_type = "personal_reflection"
        if post_type == "no_post":
            skipped_no_post += 1
            continue

        category = "ai" if post_type == "ai_commentary" else "market"
        with rx.session(url=config.db_url) as session:
            note = PlannedNote(
                target_date=d,
                note_text=note_text or f"Auto-planned {post_type.replace('_', ' ')} post.",
                post_type=post_type,
                created_at=datetime.now(timezone.utc),
            )
            bank_row = None
            if post_type != "personal_reflection":
                bank_row = session.exec(
                    sqlmodel.select(TopicBank)
                    .where(
                        TopicBank.used == False,  # noqa: E712
                        TopicBank.tier != "discard",
                        TopicBank.category == category,
                    )
                    .order_by(sqlmodel.col(TopicBank.tier).asc(), sqlmodel.col(TopicBank.date_found).desc())
                ).first()
                if bank_row:
                    note.source_bank_id = bank_row.id
            session.add(note)
            session.commit()
            bank_data = (
                (bank_row.id, bank_row.summary, bank_row.source_title, bank_row.source_url, bank_row.category)
                if bank_row
                else None
            )

        try:
            if post_type == "personal_reflection":
                generate_and_save_draft(note_text or random.choice(PROMPT_POOL), post_type, skip_research=True)
            elif bank_data:
                draft_from_bank_row(*bank_data)
            else:
                generate_and_save_draft(
                    note_text or f"Something notable in {category} recently", post_type, skip_research=False
                )
            planned += 1
        except Exception:  # noqa: BLE001 - keep going through the rest of the week
            failed += 1

    return {"planned": planned, "skipped_no_post": skipped_no_post, "failed": failed}


def maybe_auto_prepare(today: date | None = None) -> dict:
    """Saturday run from the daily research job: prepares next week once, if switched on."""
    today = today or date.today()
    with rx.session(url=config.db_url) as session:
        template = session.exec(sqlmodel.select(WeeklyTemplate)).first() or WeeklyTemplate()
        last = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == AUTO_PREPARE_JOB)).first()
    if not template.auto_prepare:
        return {"status": "skipped", "reason": "auto-prepare is switched off"}
    if today.weekday() != AUTO_PREPARE_WEEKDAY:
        return {"status": "skipped", "reason": "not Saturday"}
    now = datetime.now(timezone.utc)
    if last and now - as_utc(last.last_run_at) < timedelta(days=6):
        return {"status": "skipped", "reason": "already prepared this week"}

    result = prepare_week(next_week_monday())
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == AUTO_PREPARE_JOB)).first()
        if row:
            row.last_run_at = now
            session.add(row)
        else:
            session.add(JobRun(job_name=AUTO_PREPARE_JOB, last_run_at=now))
        session.commit()
    return {"status": "ok", **result}
