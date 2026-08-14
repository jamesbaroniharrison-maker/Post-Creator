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
    """A draft's full lifecycle from generation through publish (spec Â§3d)."""

    post_type: str
    status: str  # drafted / approved / rejected / published
    draft_text: str
    source_bank_id: int | None = sqlmodel.Field(foreign_key="topicbank.id", default=None)
    created_at: datetime
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    rejection_reason: str | None = None
    likes: int | None = None
    comments: int | None = None
    engagement_updated_at: datetime | None = None


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
