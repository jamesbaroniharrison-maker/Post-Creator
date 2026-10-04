"""Calendar engine orchestration, ported from the Ben Holmes content engine:
bootstrap (fill the rest of this year) -> your Yes/No ticks (dashboard) -> link ticked
occasions to real news or bank their own angle -> each November, plan the whole of
next year.

Called from the daily research cron, wrapped there so a failure here never blocks
research. Every step is idempotent via the JobRun table, so it's safe daily. Nothing
here drafts anything: a ticked occasion only ever becomes a Topic Bank entry.
"""

from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.calendar_engine.discovery import discover_additional_events
from linkedin_content_engine.calendar_engine.events_seed import seed_events_for_year
from linkedin_content_engine.calendar_engine.matching import find_best_topic_bank_match
from linkedin_content_engine.angles import classify_angle
from linkedin_content_engine.models import CalendarEvent, JobRun, TopicBank
from linkedin_content_engine.utils import as_utc

LINKING_JOB = "calendar_linking_check"
LINKING_INTERVAL_DAYS = 30
LINKING_LOOKAHEAD_DAYS = 45  # enough lead time to draft and schedule before the day


def _get_last_run(job_name: str) -> datetime | None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == job_name)).first()
    return as_utc(row.last_run_at) if row else None


def _set_last_run(job_name: str, when: datetime) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == job_name)).first()
        if row:
            row.last_run_at = when
        else:
            row = JobRun(job_name=job_name, last_run_at=when)
        session.add(row)
        session.commit()


def _year_has_events(year: int) -> bool:
    with rx.session(url=config.db_url) as session:
        return session.exec(sqlmodel.select(CalendarEvent).where(CalendarEvent.year == year)).first() is not None


def _researched_rows(year: int) -> list[dict]:
    rows = []
    for e in discover_additional_events(year):
        try:
            start = datetime.strptime(e.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = datetime.strptime(e.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if e.end_date else None
        except ValueError:
            continue
        rows.append(
            {
                "date": start,
                "end_date": end,
                "name": e.name,
                "category": e.category,
                "angle_notes": e.angle_notes,
                "year": year,
                "source": "researched",
            }
        )
    return rows


def _insert(events: list[dict]) -> int:
    with rx.session(url=config.db_url) as session:
        for e in events:
            session.add(CalendarEvent(**e))
        session.commit()
    return len(events)


def bootstrap_calendar(now: datetime | None = None, research: bool = True) -> dict:
    """If this year has no occasions yet, add everything from today to 31 Dec:
    the seeded list plus (best-effort) researched events."""
    now = now or datetime.now(timezone.utc)
    year = now.year
    if _year_has_events(year):
        return {"status": "skipped", "reason": f"{year} already has events"}
    rows = [*seed_events_for_year(year), *(_researched_rows(year) if research else [])]
    upcoming = [e for e in rows if (e["end_date"] or e["date"]).date() >= now.date()]
    return {"status": "ok", "year": year, "events_added": _insert(upcoming)}


def plan_next_year_if_due(now: datetime | None = None) -> dict:
    """From 1 November, plan all of next year once (seed + research)."""
    now = now or datetime.now(timezone.utc)
    if now.month < 11:
        return {"status": "skipped", "reason": "not yet November"}
    next_year = now.year + 1
    job = f"calendar_annual_plan_{next_year}"
    if _get_last_run(job) is not None or _year_has_events(next_year):
        return {"status": "skipped", "reason": f"{next_year} already planned"}
    count = _insert([*seed_events_for_year(next_year), *_researched_rows(next_year)])
    _set_last_run(job, now)
    return {"status": "ok", "year": next_year, "events_added": count}


def _process_event(event: CalendarEvent, now: datetime) -> str:
    """Link to a real finding if one matches, else bank the occasion's own angle."""
    match = find_best_topic_bank_match(event, now)
    with rx.session(url=config.db_url) as session:
        if match:
            row = session.get(TopicBank, match.id)
            row.calendar_event_id = event.id
            session.add(row)
            outcome = "linked"
        else:
            day = as_utc(event.date).strftime("%d %b")
            session.add(
                TopicBank(
                    date_found=now,
                    summary=f"{event.name} ({day}): {event.angle_notes}",
                    source_title=event.name,
                    source_url="",
                    tier="high",
                    category="ai",
                    calendar_event_id=event.id,
                    topic_angle=classify_angle(f"{event.name} {event.angle_notes}", "ai"),
                )
            )
            outcome = "banked"
        ev = session.get(CalendarEvent, event.id)
        ev.suggestion_made = True
        session.add(ev)
        session.commit()
    return outcome


def try_link_now(event_id: int, now: datetime | None = None) -> dict:
    """Called the moment you tick Yes, so you get a result straight away instead of
    waiting up to 30 days. Only links occasions within the lookahead window; later
    ones are picked up automatically as they get closer."""
    now = now or datetime.now(timezone.utc)
    with rx.session(url=config.db_url) as session:
        event = session.get(CalendarEvent, event_id)
    if event is None or event.included is not True:
        return {"status": "skipped"}
    if event.suggestion_made:
        return {"status": "skipped", "reason": "already linked"}
    if as_utc(event.date) > now + timedelta(days=LINKING_LOOKAHEAD_DAYS):
        return {"status": "too_early"}
    return {"status": "ok", "outcome": _process_event(event, now)}


def run_linking_check_if_due(now: datetime | None = None) -> dict:
    """Every 30 days: any ticked occasion coming up within the lookahead window that
    hasn't been handled yet gets linked or banked. A safety net behind try_link_now."""
    now = now or datetime.now(timezone.utc)
    last = _get_last_run(LINKING_JOB)
    if last is not None and (now - last).days < LINKING_INTERVAL_DAYS:
        return {"status": "skipped", "reason": "not due yet"}
    with rx.session(url=config.db_url) as session:
        pending = list(
            session.exec(
                sqlmodel.select(CalendarEvent).where(
                    CalendarEvent.included == True,  # noqa: E712
                    CalendarEvent.suggestion_made == False,  # noqa: E712
                    sqlmodel.col(CalendarEvent.date) >= now - timedelta(days=1),
                    sqlmodel.col(CalendarEvent.date) <= now + timedelta(days=LINKING_LOOKAHEAD_DAYS),
                )
            )
        )
    outcomes = [_process_event(e, now) for e in pending]
    _set_last_run(LINKING_JOB, now)
    return {"status": "ok", "checked": len(pending), "linked": outcomes.count("linked"), "banked": outcomes.count("banked")}


def run_calendar_engine(now: datetime | None = None) -> dict:
    """Single entry point for the daily cron - each step is a no-op unless due."""
    now = now or datetime.now(timezone.utc)
    return {
        "bootstrap": bootstrap_calendar(now),
        "annual_plan": plan_next_year_if_due(now),
        "linking_check": run_linking_check_if_due(now),
    }
