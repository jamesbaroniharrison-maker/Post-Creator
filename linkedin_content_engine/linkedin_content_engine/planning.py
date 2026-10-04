"""Prepare a week in one go: plan each day from the weekly template, draft it, and make
its visual. Everything lands in Review - nothing is approved or posted for you.

Used by the dashboard's "Prepare next week" / "Plan this week" buttons and by the
Saturday run in the daily research job (when switched on in the weekly template).

HARD RULE: a personal post is only ever written from real material you gave it - a
saved Personal update (Home), your own note on that day, or an upload. Never from a
stock prompt, never from a holiday alone. A made-up personal story is the most damaging
thing this system could post. With no personal material, the week is capped at
NO_PERSONAL_WEEKLY_CAP posts, filled from the best research topics available.
"""

import json
import pathlib
from datetime import date, datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.drafting_engine.pipeline import generate_and_save_draft, generate_draft_with_research
from linkedin_content_engine.drafting_engine.research import ResearchFinding, ResearchResult
from linkedin_content_engine.holidays import HOLIDAYS, holiday_for_date
from linkedin_content_engine.models import JobRun, PersonalUpdate, PlannedNote, Post, TopicBank, WeeklyTemplate
from linkedin_content_engine.scheduling import current_week_label, week_dates
from linkedin_content_engine.utils import as_utc

CATEGORY_TO_POST_TYPE = {"ai": "ai_commentary", "market": "market_commentary"}
AUTO_PREPARE_JOB = "auto_prepare_week"
AUTO_PREPARE_WEEKDAY = 5  # Saturday - the week's drafts are waiting for you by Sunday
NO_PERSONAL_WEEKLY_CAP = 3  # request: "if no personal has been done... stick to 3 posts"
MAX_UPDATES_PER_POST = 3  # oldest unused Personal updates folded into one personal post
AUTO_NOTE_PREFIX = "Auto-planned"  # notes this module wrote, as opposed to yours


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


def unused_personal_updates(session) -> list[PersonalUpdate]:
    return list(
        session.exec(
            sqlmodel.select(PersonalUpdate)
            .where(sqlmodel.col(PersonalUpdate.used_at).is_(None))
            .order_by(sqlmodel.col(PersonalUpdate.created_at).asc())
        ).all()
    )


def personal_brief(updates: list[PersonalUpdate]) -> tuple[str, str | None]:
    """The drafting brief for one personal post: your own words from each update, plus
    a factual caption per photo for context. Returns (brief, first usable photo path)."""
    parts: list[str] = []
    photo = None
    for u in updates:
        if u.text.strip():
            parts.append(u.text.strip())
        for ph in json.loads(u.photos or "[]"):
            if ph.get("caption"):
                parts.append(f"(Photo: {ph['caption']})")
            if photo is None and ph.get("path") and pathlib.Path(ph["path"]).exists():
                photo = ph["path"]
    return "\n\n".join(parts), photo


def is_real_personal_note(note: PlannedNote) -> bool:
    """A personal-type note you wrote yourself - not one this module generated (older
    versions wrote "Auto-planned ..." and holiday one-liners as personal notes)."""
    if note.post_type != "personal_reflection":
        return False
    text = (note.note_text or "").strip()
    if not text or text.startswith(AUTO_NOTE_PREFIX):
        return False
    return not any(text.startswith(f"{name}:") for name, _angle in HOLIDAYS.values())


def _best_bank_row(session, category: str, claimed: set[int]) -> TopicBank | None:
    """Best unused finding: high tier before mid, newest first. Calendar-linked rows
    belong to their own occasion date, so they're left alone. Falls back to the other
    category when this one has nothing left, rather than leaving the day empty."""

    def best(cat: str | None) -> TopicBank | None:
        query = sqlmodel.select(TopicBank).where(
            TopicBank.used == False,  # noqa: E712
            TopicBank.tier != "discard",
            sqlmodel.col(TopicBank.calendar_event_id).is_(None),
            sqlmodel.col(TopicBank.id).not_in(claimed or {-1}),
        )
        if cat:
            query = query.where(TopicBank.category == cat)
        return session.exec(
            query.order_by(sqlmodel.col(TopicBank.tier).asc(), sqlmodel.col(TopicBank.date_found).desc())
        ).first()

    return best(category) or best(None)


def prepare_week(monday: str) -> dict:
    """Plans and drafts the week from the weekly template. A day that already has a note
    stays yours, and days already gone are left alone.

    - Personal days: written from your unused Personal updates (one post, with a photo
      if you added one). No updates and no note of your own -> the day is skipped.
      Never a stock prompt (hard rule, see module docstring).
    - Commentary days: the best unused research finding for that category (or the
      other category if that one has run dry).
    - No personal material at all this week -> at most NO_PERSONAL_WEEKLY_CAP posts.

    Returns counts: planned, personal, skipped_no_post, skipped_no_personal,
    skipped_cap, failed, cap (None when uncapped)."""
    dates = week_dates(monday)
    today = date.today().isoformat()
    with rx.session(url=config.db_url) as session:
        template = session.exec(sqlmodel.select(WeeklyTemplate)).first() or WeeklyTemplate()
        notes = session.exec(
            sqlmodel.select(PlannedNote).where(sqlmodel.col(PlannedNote.target_date).in_(dates))
        ).all()
        personal_posts = session.exec(
            sqlmodel.select(sqlmodel.func.count())
            .select_from(Post)
            .where(
                Post.post_type == "personal_reflection",
                Post.scheduled_week == monday,
                Post.status != "rejected",
            )
        ).one()
        updates = unused_personal_updates(session)[:MAX_UPDATES_PER_POST]
        update_ids = [u.id for u in updates]
        brief, photo = personal_brief(updates)

    already_noted = {n.target_date for n in notes}
    personal_done = personal_posts > 0 or any(is_real_personal_note(n) for n in notes)
    has_personal = personal_done or bool(brief)
    cap = None if has_personal else NO_PERSONAL_WEEKLY_CAP
    existing = len(already_noted)

    counts = {k: 0 for k in ("planned", "personal", "skipped_no_post", "skipped_no_personal", "skipped_cap", "failed")}
    claimed: set[int] = set()
    for d in dates:
        if d < today or d in already_noted:
            continue
        post_type = getattr(template, date.fromisoformat(d).strftime("%A").lower())
        if post_type == "no_post":
            counts["skipped_no_post"] += 1
            continue

        if post_type == "personal_reflection":
            if personal_done or not brief:
                counts["skipped_no_personal"] += 1
                continue
            holiday = holiday_for_date(d) if template.recommend_holidays else None
            topic = brief
            if holiday:
                topic += f"\n\n(Posting on {holiday[0]} - only mention it if it fits naturally.)"
            with rx.session(url=config.db_url) as session:
                note = PlannedNote(target_date=d, note_text=brief, post_type=post_type, created_at=datetime.now(timezone.utc))
                session.add(note)
                session.commit()
                session.refresh(note)
                note_id = note.id
            try:
                post = generate_and_save_draft(topic, post_type, skip_research=True, source_photo=photo)
            except Exception:  # noqa: BLE001 - keep the updates for next time, carry on with the week
                with rx.session(url=config.db_url) as session:
                    row = session.get(PlannedNote, note_id)
                    if row:
                        session.delete(row)
                        session.commit()
                counts["failed"] += 1
                continue
            with rx.session(url=config.db_url) as session:
                for uid in update_ids:
                    row = session.get(PersonalUpdate, uid)
                    if row:
                        row.used_at = datetime.now(timezone.utc)
                        row.used_post_id = post.id
                        session.add(row)
                session.commit()
            personal_done = True
            counts["personal"] += 1
            counts["planned"] += 1
            continue

        if cap is not None and existing + counts["planned"] >= cap:
            counts["skipped_cap"] += 1
            continue

        category = "ai" if post_type == "ai_commentary" else "market"
        with rx.session(url=config.db_url) as session:
            bank_row = _best_bank_row(session, category, claimed)
            note = PlannedNote(
                target_date=d,
                note_text=bank_row.summary if bank_row else f"{AUTO_NOTE_PREFIX} {post_type.replace('_', ' ')} post.",
                post_type=CATEGORY_TO_POST_TYPE.get(bank_row.category, post_type) if bank_row else post_type,
                created_at=datetime.now(timezone.utc),
                source_bank_id=bank_row.id if bank_row else None,
            )
            session.add(note)
            session.commit()
            bank_data = (
                (bank_row.id, bank_row.summary, bank_row.source_title, bank_row.source_url, bank_row.category)
                if bank_row
                else None
            )
        if bank_data:
            claimed.add(bank_data[0])
        try:
            if bank_data:
                draft_from_bank_row(*bank_data)
            else:
                generate_and_save_draft(f"Something notable in {category} recently", post_type, skip_research=False)
            counts["planned"] += 1
        except Exception:  # noqa: BLE001 - keep going through the rest of the week
            counts["failed"] += 1

    return {**counts, "cap": cap}


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
