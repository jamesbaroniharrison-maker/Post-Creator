"""Database schema (spec Â§9). Every table here maps 1:1 to the consolidated data model."""

from datetime import datetime

import reflex as rx
import sqlmodel


class TopicBank(rx.Model, table=True):
    """Daily research findings, scored and banked (spec Â§3a)."""

    date_found: datetime
    summary: str
    source_title: str
    source_url: str
    tier: str  # high / mid / discard
    category: str  # industry / company
    used: bool = False
    date_used: datetime | None = None


class Post(rx.Model, table=True):
    """A draft's full lifecycle from generation through publish (spec Â§3d).

    Beyond the original Â§9 columns: the dashboard (Â§3d) needs hashtags and tags as
    editable chips, a suggested posting day, and a compliance note shown separately
    from the post body - so those need their own columns, not folded into draft_text.
    Added at level 4, while the table was still empty, rather than after real drafts
    exist (CLAUDE.md: schema mistakes are expensive to unwind once there's real data).
    """

    post_type: str
    status: str  # drafted / approved / rejected / published
    draft_text: str
    hashtags: str = ""  # JSON-encoded list[str]
    tags: str = ""  # JSON-encoded list[str] - people/orgs to @mention
    suggested_day: str | None = None  # e.g. "Tuesday"
    sources: str = ""  # JSON-encoded list[{"title": str, "url": str}]
    compliance_note: str | None = None
    source_bank_id: int | None = sqlmodel.Field(foreign_key="topicbank.id", default=None)
    created_at: datetime
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    rejection_reason: str | None = None
    likes: int | None = None
    comments: int | None = None
    engagement_updated_at: datetime | None = None
    # Monday-of-week date string (e.g. "2026-08-17"), auto-assigned to approved posts
    # by scheduling.py so a thin week doesn't get overloaded and an over-full one
    # spills into the following week automatically. None until allocated.
    scheduled_week: str | None = None


class VoiceSample(rx.Model, table=True):
    """Raw corpus input feeding the voice-profile pipeline (spec Â§3c)."""

    source_type: str  # linkedin_post / audio_transcript
    raw_text: str
    date_added: datetime


class VoiceProfile(rx.Model, table=True):
    """Single regenerated row holding the merged voice profile (spec Â§3c)."""

    generated_at: datetime
    profile_json: str


class JobRun(rx.Model, table=True):
    """Scheduler state, checked by the daily research job before it runs (spec Â§5)."""

    job_name: str
    last_run_at: datetime


class ForcedTopic(rx.Model, table=True):
    """A topic queued from the dashboard to be searched on the next research cron run,
    on top of the standing daily queries (HUD quick action, not in the original spec).
    Consumed (searched at least once) rather than recurring - a one-shot nudge, not a
    permanent addition to the standing query list.
    """

    topic: str
    category: str  # industry / company
    created_at: datetime
    consumed: bool = False
    consumed_at: datetime | None = None


class ApiUsageCounter(rx.Model, table=True):
    """Tracks Tavily search calls per calendar month, so the research pipeline can stop
    itself before exceeding the free tier's 1000/month cap, rather than finding out the
    hard way mid-month (request: "check it won't overuse usage").
    """

    month_key: str  # "2026-08"
    tavily_calls: int = 0


class EmailSettings(rx.Model, table=True):
    """Single-row settings for the two scheduled email jobs (weekly personal-story
    reminder, weekly post digest) - requested after the original spec, not in Â§9.
    Both day AND time are independently configurable per job (request: "fully
    customizable"). Sending is inert until SMTP credentials exist in .env.
    """

    recipient_email: str
    reminder_day: str = "Friday"  # weekday she's most likely to actually send a story
    reminder_time: str = "09:00"  # 24h "HH:MM"
    reminder_enabled: bool = True
    digest_day: str = "Sunday"
    digest_time: str = "12:00"
    digest_enabled: bool = True
