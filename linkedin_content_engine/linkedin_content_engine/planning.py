"""Prepare a week in one go: plan each day from the weekly template and draft it. The
visual is made later, when you accept the post. Everything lands in Review - nothing is
approved or posted for you.

Used by the dashboard's "Prepare next week" / "Plan this week" buttons and by the
Saturday run in the daily research job (when switched on in the weekly template).

HARD RULE: a personal post is only ever written from real material you gave it - a
saved Personal update (Home), your own note on that day, or an upload. Never from a
stock prompt, never from a holiday alone. A made-up personal story is the most damaging
thing this system could post. With no personal material, the week is capped at
NO_PERSONAL_WEEKLY_CAP posts, filled from the best research topics available.
"""

import json
import os
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.drafting_engine.pipeline import generate_and_save_draft, generate_draft_with_research
from linkedin_content_engine.drafting_engine.research import ResearchFinding, ResearchResult
from linkedin_content_engine.drafting_engine.rotation import assign_rotation
from linkedin_content_engine.holidays import HOLIDAYS, holiday_for_date
from linkedin_content_engine.models import CalendarEvent, JobRun, PersonalUpdate, PlannedNote, Post, TopicBank, WeeklyTemplate
from linkedin_content_engine.scheduling import current_week_label, week_dates
from linkedin_content_engine.utils import as_utc

CATEGORY_TO_POST_TYPE = {"ai": "ai_commentary", "market": "market_commentary"}
AUTO_PREPARE_JOB = "auto_prepare_week"
AUTO_PREPARE_WEEKDAY = 5  # Saturday - the week's drafts are waiting for you by Sunday
NO_PERSONAL_WEEKLY_CAP = 3  # request: "if no personal has been done... stick to 3 posts"
MAX_UPDATES_PER_POST = 3  # oldest unused Personal updates folded into one personal post
AUTO_NOTE_PREFIX = "Auto-planned"  # notes this module wrote, as opposed to yours
# Days of a week drafted at the same time. Each draft already runs its best-of-N
# candidates in parallel (DRAFT_PARALLEL_CANDIDATES), so 2 here is ~6 model calls at once.
WEEK_PARALLEL_DRAFTS = int(os.environ.get("WEEK_PARALLEL_DRAFTS", 2))


def _brief_for(bank_id: int, summary: str) -> str:
    with rx.session(url=config.db_url) as session:
        row = session.get(TopicBank, bank_id)
        event = session.get(CalendarEvent, row.calendar_event_id) if row and row.calendar_event_id else None
        take = (row.user_take or "").strip() if row else ""
        link_note = (row.calendar_link_note or "").strip() if row else ""
    brief = summary
    if event:
        brief += (
            f"\n\nThis post goes out for {event.name} ({as_utc(event.date).strftime('%d %B')}). "
            f"Tie the story to it naturally{': ' + link_note if link_note else '.'}"
        )
    if take:
        brief += f"\n\nThe author's own take - build the post around this angle: {take}"
    return brief


def draft_from_bank_row(
    bank_id: int,
    summary: str,
    source_title: str,
    source_url: str,
    category: str,
    rotation_overrides: dict[str, str] | None = None,
) -> None:
    """Drafts from one topic bank row and marks it used. Raises on failure so callers
    can decide how to report it. Your own take on the row, and the occasion it's tied
    to (with why it fits), go into the brief so the post actually uses them."""
    research = ResearchResult(
        topic=summary,
        status="ok",
        findings=[ResearchFinding(title=source_title, url=source_url, content=summary)],
    )
    post_type = CATEGORY_TO_POST_TYPE.get(category, "ai_commentary")
    generate_draft_with_research(
        _brief_for(bank_id, summary), post_type, research, source_bank_id=bank_id, rotation_overrides=rotation_overrides
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


def _best_bank_row(session, category: str, claimed: set[int], used_angles: set[str] | None = None) -> TopicBank | None:
    """Best unused finding: high tier before mid, newest first. Calendar-linked rows
    belong to their own occasion date, so they're left alone. Prefers an angle the week
    hasn't had yet (angles.py), so a week isn't three takes on the same kind of story.
    Falls back to the other category when this one has nothing left."""
    used_angles = used_angles or set()

    def best(cat: str | None, fresh_angle: bool) -> TopicBank | None:
        query = sqlmodel.select(TopicBank).where(
            TopicBank.used == False,  # noqa: E712
            TopicBank.tier != "discard",
            sqlmodel.col(TopicBank.calendar_event_id).is_(None),
            sqlmodel.col(TopicBank.id).not_in(claimed or {-1}),
        )
        if cat:
            query = query.where(TopicBank.category == cat)
        if fresh_angle and used_angles:
            query = query.where(
                sqlmodel.or_(
                    sqlmodel.col(TopicBank.topic_angle).is_(None),
                    sqlmodel.col(TopicBank.topic_angle).not_in(used_angles),
                )
            )
        return session.exec(
            query.order_by(sqlmodel.col(TopicBank.tier).asc(), sqlmodel.col(TopicBank.date_found).desc())
        ).first()

    return best(category, True) or best(category, False) or best(None, True) or best(None, False)


def prepare_week(monday: str, on_progress=None) -> dict:
    """Plans and drafts the week from the weekly template. A day that already has a note
    stays yours, and days already gone are left alone.

    - Personal days: written from your unused Personal updates (one post, with a photo
      if you added one). No updates and no note of your own -> the day is skipped.
      Never a stock prompt (hard rule, see module docstring).
    - Commentary days: the best unused research finding for that category (or the
      other category if that one has run dry).
    - No personal material at all this week -> at most NO_PERSONAL_WEEKLY_CAP posts.

    Two phases (request: "make things faster"): first every day is decided one at a
    time - topic, note, rotation - so two days never claim the same finding or style;
    then the slow drafting runs for several days at once (WEEK_PARALLEL_DRAFTS).

    `on_progress(steps)`, if given, is called (from worker threads) with a fresh list of
    {"label", "status"} dicts whenever a day changes - status is queued / drafting /
    done / failed - so the dashboard can show each day as it goes.

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
    used_angles: set[str] = set()
    rotations: list[dict] = []
    jobs: list[dict] = []

    # ---- phase 1: decide every day (quick, one at a time) ----
    for d in dates:
        if d < today or d in already_noted:
            continue
        post_type = getattr(template, date.fromisoformat(d).strftime("%A").lower())
        if post_type == "no_post":
            counts["skipped_no_post"] += 1
            continue
        day_label = date.fromisoformat(d).strftime("%a %d %b")

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
            rotation = assign_rotation(post_type=post_type, has_photo=bool(photo), also_exclude=rotations)
            rotations.append(rotation)
            personal_done = True
            jobs.append({
                "kind": "personal",
                "label": f"{day_label} - Personal post from your updates",
                "topic": topic,
                "note_id": note_id,
                "rotation": rotation,
            })
            continue

        if cap is not None and existing + len(jobs) >= cap:
            counts["skipped_cap"] += 1
            continue

        category = "ai" if post_type == "ai_commentary" else "market"
        with rx.session(url=config.db_url) as session:
            bank_row = _best_bank_row(session, category, claimed, used_angles)
            if bank_row and bank_row.topic_angle:
                used_angles.add(bank_row.topic_angle)
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
        draft_type = CATEGORY_TO_POST_TYPE.get(bank_data[4], post_type) if bank_data else post_type
        rotation = assign_rotation(post_type=draft_type, also_exclude=rotations)
        rotations.append(rotation)
        kind_label = "AI commentary" if draft_type == "ai_commentary" else "Market commentary"
        title = (bank_data[2] or bank_data[1]) if bank_data else "researching a fresh topic"
        jobs.append({
            "kind": "bank" if bank_data else "fresh",
            "label": f"{day_label} - {kind_label}: {_short(title)}",
            "bank_data": bank_data,
            "post_type": post_type,
            "category": category,
            "rotation": rotation,
        })

    # ---- phase 2: draft them (slow, several at once) ----
    lock = threading.Lock()
    steps = [{"label": job["label"], "status": "queued"} for job in jobs]

    def report(i: int, status: str) -> None:
        with lock:
            steps[i]["status"] = status
            snapshot = [dict(s) for s in steps]
        if on_progress:
            on_progress(snapshot)

    def run(i: int) -> str:
        job = jobs[i]
        report(i, "drafting")
        try:
            if job["kind"] == "personal":
                post = generate_and_save_draft(
                    job["topic"],
                    "personal_reflection",
                    skip_research=True,
                    source_photo=photo,
                    rotation_overrides=job["rotation"],
                )
                with rx.session(url=config.db_url) as session:
                    for uid in update_ids:
                        row = session.get(PersonalUpdate, uid)
                        if row:
                            row.used_at = datetime.now(timezone.utc)
                            row.used_post_id = post.id
                            session.add(row)
                    session.commit()
            elif job["kind"] == "bank":
                draft_from_bank_row(*job["bank_data"], rotation_overrides=job["rotation"])
            else:
                generate_and_save_draft(
                    f"Something notable in {job['category']} recently",
                    job["post_type"],
                    skip_research=False,
                    rotation_overrides=job["rotation"],
                )
        except Exception:  # noqa: BLE001 - keep going through the rest of the week
            if job["kind"] == "personal":  # keep the updates for next time
                with rx.session(url=config.db_url) as session:
                    row = session.get(PlannedNote, job["note_id"])
                    if row:
                        session.delete(row)
                        session.commit()
            report(i, "failed")
            return "failed"
        report(i, "done")
        return job["kind"]

    if on_progress:
        on_progress([dict(s) for s in steps])
    if jobs:
        with ThreadPoolExecutor(max_workers=max(1, min(WEEK_PARALLEL_DRAFTS, len(jobs)))) as pool:
            outcomes = list(pool.map(run, range(len(jobs))))
        for outcome in outcomes:
            if outcome == "failed":
                counts["failed"] += 1
            else:
                counts["planned"] += 1
                if outcome == "personal":
                    counts["personal"] += 1

    return {**counts, "cap": cap}


def _short(text: str, limit: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


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
