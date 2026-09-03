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
    category: str  # ai / market
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
    # THBM anti-fatigue rotation variables (CPIO/THBM framework, repurposing pivot).
    # Assigned deterministically by drafting_engine/rotation.py before drafting - never
    # left to the model to remember, since the one thing that reliably breaks on this
    # codebase's local model is bundling too many rules into a single instruction.
    funnel_stage: str | None = None  # TOF / MOF / BOF
    hook_posture: str | None = None  # empirical / aspirational_contrast / cost_arbitrage / authority_listicle / in_medias_res
    length_bucket: str | None = None  # micro / standard / deep
    structural_format: str | None = None  # narrative / skimmable_index / binary_contrast
    media_pairing: str | None = None  # candid_photo / carousel / infographic / screenshot / chart / text_only
    media_note: str | None = None  # what the paired visual should actually show, from the drafting call


class VoiceSample(rx.Model, table=True):
    """Raw corpus input feeding the voice-profile pipeline (spec Â§3c).

    `question` is context only (e.g. the question Gemini asked, for gemini_qa
    samples) - it's Gemini's writing, not James's, so it's never fed into the
    keyness/structural/close-read analysis, only `raw_text` (his answer) is.
    """

    source_type: str  # linkedin_post / audio_transcript / gemini_qa
    raw_text: str
    date_added: datetime
    question: str | None = None


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
    category: str  # ai / market
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


class PlannedNote(rx.Model, table=True):
    """A forward-looking brief attached to a specific future date (request: "let me
    put a note... I want this to be about that" / a Halloween-themed post pencilled in
    for 31 Oct) - lets you tell the drafting engine what to focus on for a day before
    any research/topic exists yet, browsable across the 4-week look-ahead on the
    Accepted page.
    """

    target_date: str  # "YYYY-MM-DD"
    note_text: str
    post_type: str = "personal_reflection"
    created_at: datetime
    # Set when this note came from clicking "Link to this day" on a Topic Bank row
    # (request: "if I have topics that I like I want to be able to click on them...
    # select a day that I want them to be linked to for a post") rather than typed by
    # hand - lets the drafting call cite the real source instead of treating the
    # summary as a from-scratch personal note.
    source_bank_id: int | None = sqlmodel.Field(foreign_key="topicbank.id", default=None)


class WeeklyTemplate(rx.Model, table=True):
    """Single-row settings: what kind of post (or none) each day of the week defaults
    to (request: "choose which days the certain types of post... it also needs an
    option for no post as well"). Purely a planning default - "Plan this week" reads
    it to auto-fill a week's worth of days, but never overrides a day that already has
    a note or a generated post, and nothing here forces a post to actually go out
    without the usual review/accept step.
    """

    monday: str = "personal_reflection"
    tuesday: str = "ai_commentary"
    wednesday: str = "no_post"
    thursday: str = "ai_commentary"
    friday: str = "market_commentary"
    saturday: str = "no_post"
    sunday: str = "no_post"
    # Whether "Plan this week" should swap a day's post for a holiday-themed one when
    # that date lands on a recognised holiday (request: "sync with like holidays and
    # recommend if it was a specific day... Christmas post or Halloween post").
    recommend_holidays: bool = True


class EmailSettings(rx.Model, table=True):
    """Single-row settings for the two scheduled email jobs (weekly personal-story
    reminder, weekly post digest). Both day AND time are independently configurable
    per job (request: "fully customizable"). Sending is inert until SMTP credentials
    exist in .env.
    """

    recipient_email: str
    reminder_day: str = "Friday"  # weekday you're most likely to actually send a story
    reminder_time: str = "09:00"  # 24h "HH:MM"
    reminder_enabled: bool = True
    digest_day: str = "Sunday"
    digest_time: str = "12:00"
    digest_enabled: bool = True
    # JSON-encoded list of the prompt suggestions shown in the *last* reminder email -
    # excluded from this week's pick so you never see the same suggestion two weeks
    # running (request: "switch them up each week... don't request that the next week").
    last_reminder_prompts: str = ""
