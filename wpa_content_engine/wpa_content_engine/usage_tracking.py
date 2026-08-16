"""Tavily monthly usage guard, shared by both call sites (drafting_engine/research.py's
on-demand research, research_cron/discovery.py's daily scan).

Tavily's free tier is 1,000 basic-search credits/month (1 credit per search here - no
"advanced" search_depth is used anywhere in this codebase). This stops the app short of
that ceiling with a safety margin, rather than finding out mid-month via a hard failure.
"""

from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.models import ApiUsageCounter

TAVILY_MONTHLY_SAFETY_CAP = 900  # leaves ~100 credits of headroom under the 1000 cap


def _month_key(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return when.strftime("%Y-%m")


def tavily_quota_available() -> bool:
    """True if this month's tracked Tavily usage is still under the safety cap."""
    key = _month_key()
    with rx.session(url=config.db_url) as session:
        row = session.exec(
            sqlmodel.select(ApiUsageCounter).where(ApiUsageCounter.month_key == key)
        ).first()
    return (row.tavily_calls if row else 0) < TAVILY_MONTHLY_SAFETY_CAP


def record_tavily_call() -> None:
    """Call once per real Tavily search request that actually goes out."""
    key = _month_key()
    with rx.session(url=config.db_url) as session:
        row = session.exec(
            sqlmodel.select(ApiUsageCounter).where(ApiUsageCounter.month_key == key)
        ).first()
        if row:
            row.tavily_calls += 1
            session.add(row)
        else:
            session.add(ApiUsageCounter(month_key=key, tavily_calls=1))
        session.commit()


def tavily_usage_this_month() -> tuple[int, int]:
    """Returns (calls_used, safety_cap) for display in the dashboard."""
    key = _month_key()
    with rx.session(url=config.db_url) as session:
        row = session.exec(
            sqlmodel.select(ApiUsageCounter).where(ApiUsageCounter.month_key == key)
        ).first()
    return (row.tavily_calls if row else 0), TAVILY_MONTHLY_SAFETY_CAP
