"""Orchestrates the daily research cron: discover -> dedup -> score -> bank (spec Â§3a).

Idempotent per day: `job_runs` tracks the last successful run so re-invoking on the same
day (e.g. the at-logon catch-up trigger firing after the daily trigger already ran) is a
no-op, per spec Â§5's catch-up-on-next-activation scheduling pattern.
"""

from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import ForcedTopic, JobRun, TopicBank
from linkedin_content_engine.research_cron.dedup import is_duplicate
from linkedin_content_engine.research_cron.discovery import discover
from linkedin_content_engine.research_cron.queries import DAILY_QUERIES
from linkedin_content_engine.research_cron.scorer import score_finding

JOB_NAME = "daily_research"
DEDUP_LOOKBACK_DAYS = 30


def _get_last_run() -> datetime | None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
    return row.last_run_at if row else None


def _set_last_run(when: datetime) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
        if row:
            row.last_run_at = when
            session.add(row)
        else:
            session.add(JobRun(job_name=JOB_NAME, last_run_at=when))
        session.commit()


def _recent_bank_entries(since: datetime) -> list[tuple[str, str]]:
    with rx.session(url=config.db_url) as session:
        rows = session.exec(
            sqlmodel.select(TopicBank).where(TopicBank.date_found >= since)
        ).all()
    return [(r.source_title, r.source_url) for r in rows]


def _get_pending_forced_topics() -> list[ForcedTopic]:
    with rx.session(url=config.db_url) as session:
        return list(
            session.exec(sqlmodel.select(ForcedTopic).where(ForcedTopic.consumed == False))  # noqa: E712
        )


def _mark_forced_topic_consumed(topic_id: int, when: datetime) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.get(ForcedTopic, topic_id)
        if row:
            row.consumed = True
            row.consumed_at = when
            session.add(row)
            session.commit()


def already_ran_today(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    last_run = _get_last_run()
    return last_run is not None and last_run.date() == now.date()


def run_daily_research(force: bool = False) -> dict:
    """Run the daily discover -> dedup -> score -> bank cycle once.

    Skips (returns status="skipped") if already run today, unless force=True - this is
    what makes the dual Task Scheduler trigger (daily + at-logon) safe to both fire.
    """
    now = datetime.now(timezone.utc)
    if not force and already_ran_today(now):
        return {"status": "skipped", "reason": "already ran today"}

    recent = _recent_bank_entries(now - timedelta(days=DEDUP_LOOKBACK_DAYS))
    stored_by_tier = {"high": 0, "mid": 0, "discard": 0}
    duplicates_skipped = 0

    # Forced topics (HUD quick action) run alongside the standing queries and are
    # consumed (searched once) regardless of what tier they end up scored as.
    forced_topics = _get_pending_forced_topics()
    all_queries = [*DAILY_QUERIES, *[(t.topic, t.category) for t in forced_topics]]

    with rx.session(url=config.db_url) as session:
        for query, default_category in all_queries:
            items = discover(query)
            for item in items:
                if is_duplicate(item.title, item.url, recent):
                    duplicates_skipped += 1
                    continue

                result = score_finding(item, default_category)
                row = TopicBank(
                    date_found=now,
                    summary=result.summary,
                    source_title=item.title,
                    source_url=item.url,
                    tier=result.tier,
                    category=result.category,
                    used=False,
                )
                session.add(row)
                stored_by_tier[result.tier] = stored_by_tier.get(result.tier, 0) + 1
                recent.append((item.title, item.url))  # avoid dupes within this same run
        session.commit()

    for topic in forced_topics:
        _mark_forced_topic_consumed(topic.id, now)

    _set_last_run(now)
    return {
        "status": "ok",
        "stored_by_tier": stored_by_tier,
        "duplicates_skipped": duplicates_skipped,
        "forced_topics_searched": len(forced_topics),
    }
