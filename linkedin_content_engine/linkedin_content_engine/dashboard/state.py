"""Dashboard state: review queue, editable chips, topic bank actions, uploads, stats.

Implements spec Â§3d and the level 7 done-when check: a full weekly cycle (bank
populates, shortlist forms, drafts generate, you review and approve or reject,
stats update) has to run end to end without touching code.
"""

import base64
import json
import pathlib
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone

import pydantic
import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.capture.ingest import UnsupportedMediaError, ingest_file, ingest_text
from linkedin_content_engine.capture.transcribe import transcribe_audio
from linkedin_content_engine.drafting_engine.pipeline import (
    generate_and_save_draft,
    generate_draft_with_research,
)
from linkedin_content_engine.drafting_engine.research import ResearchFinding, ResearchResult
from linkedin_content_engine.drafting_engine.rotation import (
    AUTO_SENTINEL,
    FUNNEL_STAGES,
    HOOK_POSTURES,
    LENGTH_BUCKETS,
    MEDIA_PAIRINGS,
    STRUCTURAL_FORMATS,
)
from linkedin_content_engine.email_engine.settings import get_email_settings, save_email_settings
from linkedin_content_engine.holidays import holiday_for_date
from linkedin_content_engine.calendar_engine.pipeline import try_link_now
from linkedin_content_engine.planning import (
    NO_PERSONAL_WEEKLY_CAP,
    draft_from_bank_row,
    next_week_monday,
    prepare_week,
    unused_personal_updates,
)
from linkedin_content_engine.exports import build_bundle
from linkedin_content_engine.visuals_engine.attach import make_visual_for_post
from linkedin_content_engine.visuals_engine.spec import CATALOG
from linkedin_content_engine.models import (
    CalendarEvent,
    ForcedTopic,
    JobRun,
    PersonalUpdate,
    PlannedNote,
    Post,
    TopicBank,
    VoiceProfile,
    VoiceSample,
    WeeklyTemplate,
)
from linkedin_content_engine.research_cron.pipeline import JOB_NAME as RESEARCH_JOB_NAME
from linkedin_content_engine.research_cron.pipeline import run_daily_research
from linkedin_content_engine.utils import as_utc
from linkedin_content_engine.voice_engine.build_profile import build_and_save_profile
from linkedin_content_engine.voice_engine.ingestion import (
    add_sample,
    get_weighted_samples_by_register,
    parse_labeled_conversation,
)
from linkedin_content_engine.voice_engine.similarity import TARGET_REGISTER, _tokenize, validate_voice_metric
from linkedin_content_engine.scheduling import (
    WEEKLY_CAP,
    allocate_accepted_posts,
    current_week_label,
    prune_rejected_posts,
    upcoming_week_mondays,
    week_dates,
)

REJECTION_REASONS = ["not relevant", "wrong tone", "already covered"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DISPLAY_DAYS = [*WEEKDAYS, "Unscheduled"]
POST_TYPES = ["ai_commentary", "market_commentary", "personal_reflection"]
DAY_TEMPLATE_OPTIONS = [*POST_TYPES, "no_post"]
_WEEKDAY_FIELDS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TOPIC_CATEGORIES = ["ai", "market"]
CATEGORY_TO_POST_TYPE = {"ai": "ai_commentary", "market": "market_commentary"}
HISTORY_WEEKS_LIMIT = 6

# Per-queued-topic style dropdowns (request: "add a selection of dropdowns for each
# one either put it as standard where it decides as normal... or actually choose how
# I want them to come out"). AUTO_SENTINEL ("auto", not "standard" - see rotation.py
# for the real collision that would cause) means "let rotation.py pick this field
# exactly as it always has" - see rotation.py::assign_rotation's `overrides` param.
QUEUE_FUNNEL_STAGE_OPTIONS = [AUTO_SENTINEL, *FUNNEL_STAGES]
QUEUE_HOOK_POSTURE_OPTIONS = [AUTO_SENTINEL, *HOOK_POSTURES]
QUEUE_LENGTH_BUCKET_OPTIONS = [AUTO_SENTINEL, *LENGTH_BUCKETS]
QUEUE_STRUCTURAL_FORMAT_OPTIONS = [AUTO_SENTINEL, *STRUCTURAL_FORMATS]
QUEUE_MEDIA_PAIRING_OPTIONS = [AUTO_SENTINEL, *MEDIA_PAIRINGS]


# Browsers only give microphone access on a secure page: https, or localhost on this PC.
# Plain http over Tailscale (the phone) counts as insecure, so recording is blocked there.
_RECORDING_ERRORS = {
    "insecure": (
        "Recording only works on a secure page - open the dashboard at http://localhost:3000 "
        "on this PC. Over plain http from another device (e.g. your phone via Tailscale) the "
        "browser blocks the microphone; upload a voice memo there instead."
    ),
    "unsupported": "This browser can't record audio - try Chrome or Edge.",
    "denied": "Microphone access was blocked - allow it in the browser's address bar and try again.",
}


def humanize(value: str) -> str:
    """'personal_reflection' -> 'Personal Reflection' - display only, never touches
    the stored value (request: raw snake_case showing up in the UI looked wrong)."""
    return value.replace("_", " ").title() if value else value


def _words_present_in(text: str, words: list[str]) -> list[str]:
    """Real attribution for a sample's expanded view (request: "what information it
    pulled from each one... like phrasings") - which of the profile's Zeta words
    actually appear in *this* sample's own text, not a guess or an even split."""
    if not words:
        return []
    tokens = set(_tokenize(text))
    return [w for w in words if w in tokens]


def _bigrams_present_in(text: str, bigrams: list[str]) -> list[str]:
    """Same idea as _words_present_in, for two-word phrases - checked as a token
    pair so it matches how compute_characteristic_bigrams itself extracts them,
    not a raw substring search (which would miss/over-match on punctuation)."""
    if not bigrams:
        return []
    tokens = _tokenize(text)
    pairs = {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}
    return [bg for bg in bigrams if bg in pairs]


class PostView(pydantic.BaseModel):
    id: int
    post_type: str
    post_type_label: str = ""
    status: str
    status_label: str = ""
    draft_text: str
    hashtags: list[str] = []
    tags: list[str] = []
    suggested_day: str = ""
    sources: list[dict] = []
    compliance_note: str = ""
    rejection_reason: str = ""
    new_hashtag_input: str = ""
    new_tag_input: str = ""
    likes_input: str = ""
    comments_input: str = ""
    week_label: str = ""
    created_at_str: str = ""
    scheduled_week: str = ""
    funnel_stage: str = ""
    hook_posture_label: str = ""
    length_bucket_label: str = ""
    structural_format_label: str = ""
    media_pairing_label: str = ""
    media_note: str = ""
    voice_delta_label: str = ""
    redraft_note: str = ""  # what to change on Redraft - typed or dictated, kept across reloads
    # Brand visual (visuals_engine/): paths relative to the upload dir, for rx.get_upload_url
    visual_files: list[str] = []
    visual_pdf: str = ""
    visual_template: str = ""
    visual_template_label: str = ""
    visual_note: str = ""
    visual_choice: str = ""  # the template picked in the switcher, before "Re-make visual"
    bundle_dir: str = ""


class BankView(pydantic.BaseModel):
    id: int
    summary: str
    source_title: str
    source_url: str
    tier: str
    tier_label: str = ""
    category: str
    category_label: str = ""
    # Multi-select for queued drafting (request: "select multiple topics to queue to
    # draft at the same time") - tracked on the row itself rather than a separate
    # id list, since Reflex 0.9.8's Var API has no list .contains() to check
    # membership from inside a rx.foreach render function.
    is_selected: bool = False
    occasion_label: str = ""  # set when tied to a calendar occasion, e.g. "AI Appreciation Day, 16 Jul"


class QueuedDraftView(pydantic.BaseModel):
    """One topic staged in the batch-draft queue (request: "add it to a box, don't
    start generating them yet... add a selection of dropdowns for each one either
    put it as standard... or actually choose how I want them to come out"). Carries
    its own copy of the bank row's data (captured at queue time, not re-fetched at
    draft time) plus one dropdown selection per THBM rotation variable - each
    defaults to AUTO_SENTINEL, meaning rotation.py picks it exactly as it always
    has; only a non-AUTO_SENTINEL value overrides that field for this one queued
    item."""

    bank_id: int
    summary: str
    source_title: str
    source_url: str
    category: str
    tier_label: str = ""
    category_label: str = ""
    funnel_stage: str = AUTO_SENTINEL
    hook_posture: str = AUTO_SENTINEL
    length_bucket: str = AUTO_SENTINEL
    structural_format: str = AUTO_SENTINEL
    media_pairing: str = AUTO_SENTINEL


class CalendarEventView(pydantic.BaseModel):
    """One occasion on the Posts > Calendar tab. `included` mirrors the database
    (None = not reviewed yet); nothing acts on an occasion until it's ticked Yes."""

    id: int
    name: str
    category_label: str = ""
    date_label: str = ""  # "16 Jul", or "1 Oct - 31 Oct" for a range
    start: str = ""  # "YYYY-MM-DD", for matching plan-ahead days
    end: str = ""
    angle_notes: str = ""
    source: str = "seed"
    included: bool | None = None
    # "yes" / "no" / "" - what the buttons compare against. A None-vs-False check on
    # `included` misfired in the browser (undecided rows showed Skip as chosen).
    decision: str = ""
    suggestion_made: bool = False
    month_key: str = ""  # "2026-10"
    month_label: str = ""  # "October 2026"


def _calendar_row_to_view(e: CalendarEvent) -> CalendarEventView:
    start, end = as_utc(e.date), as_utc(e.end_date or e.date)
    label = start.strftime("%d %b") if start.date() == end.date() else f"{start:%d %b} - {end:%d %b}"
    return CalendarEventView(
        id=e.id,
        name=e.name,
        category_label=humanize(e.category),
        date_label=label,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        angle_notes=e.angle_notes,
        source=e.source,
        included=e.included,
        decision="" if e.included is None else ("yes" if e.included else "no"),
        suggestion_made=e.suggestion_made,
        month_key=start.strftime("%Y-%m"),
        month_label=start.strftime("%B %Y"),
    )


class ForcedTopicView(pydantic.BaseModel):
    id: int
    topic: str
    category: str
    category_label: str = ""


class SampleCountView(pydantic.BaseModel):
    """Per-source-type sample count (request: "add a count to show how many of each
    type of sample I've got, like the Q&A or the LinkedIn post ones")."""

    source_type_label: str
    count: int


class VoiceSampleView(pydantic.BaseModel):
    id: int
    preview: str
    full_text: str = ""
    source_type_label: str = ""
    date_added_str: str = ""
    question_preview: str = ""
    # What this specific sample contributes to the profile (request: "click on each
    # one of the samples and it expands out... what information it pulled from
    # each one... like phrasings and such") - which of the profile's Zeta words and
    # characteristic bigrams actually appear in this sample's own text. Real
    # attribution (a substring/token check against this sample only), not a guess.
    contributing_zeta_words: list[str] = []
    contributing_bigrams: list[str] = []
    is_expanded: bool = False


class VoiceConvoPairView(pydantic.BaseModel):
    """One parsed (question, answer) turn from a pasted Gemini conversation, shown
    for review before any of it is actually saved as a VoiceSample."""

    index: int
    question: str
    answer: str


class VoiceRegisterHealthView(pydantic.BaseModel):
    """One register's (source_type's) readiness row on the Voice page's corpus-health
    check - request: surface `validate_voice_metric`/register-aware Delta's readiness
    on demand instead of it only being checkable by running a script."""

    register_label: str
    sample_count: int
    is_primary_register: bool = False
    status_text: str = ""


class PersonalUpdateView(pydantic.BaseModel):
    """One saved Personal update on Home."""

    id: int
    text: str
    photo_names: list[str] = []  # upload-dir file names; the page builds the URLs
    photo_count: int = 0
    added_label: str = ""  # "Added 4 Oct"
    used_label: str = ""  # "Used in a draft on 6 Oct" - empty while still waiting


class PlannedNoteView(pydantic.BaseModel):
    id: int
    target_date: str
    note_text: str
    post_type: str = "personal_reflection"
    post_type_label: str = ""


class DayPlanView(pydantic.BaseModel):
    """One day cell in the month planning calendar: the date, a friendly label,
    whether it's today, and the note attached to it (if any)."""

    date: str
    day_label: str  # "Mon 31 Aug"
    is_today: bool
    note: PlannedNoteView | None = None
    holiday_name: str = ""  # e.g. "Halloween" - request: "sync with like holidays"
    scheduled_label: str = ""  # the weekly schedule's type for this weekday, e.g. "Ai Commentary"
    is_no_post_day: bool = False
    occasion_names: list[str] = []  # Yes-ticked calendar occasions covering this date


class WeekPlanView(pydantic.BaseModel):
    """One week's section in the month planning calendar (request: "plan a month of
    posts out, not just a week") - a label, its Monday date (for the per-week fill
    button), and its 7 day cells."""

    week_label: str
    monday: str
    already_scheduled: int  # accepted/published posts already locked into this week
    days: list[DayPlanView] = []


class StatBreakdownItem(pydantic.BaseModel):
    """One bar in a Statistics-page breakdown."""

    label: str
    count: int
    pct: int = 0  # 0-100, bar width


def _breakdown(counts: dict[str, int], sort_by_count: bool = True) -> list[StatBreakdownItem]:
    total = sum(counts.values()) or 1
    items = [
        StatBreakdownItem(label=humanize(k) or "(none)", count=v, pct=round(v / total * 100))
        for k, v in counts.items()
        if v > 0
    ]
    if sort_by_count:
        return sorted(items, key=lambda i: i.count, reverse=True)
    return sorted(items, key=lambda i: i.label)


def _week_label(dt: datetime) -> str:
    monday = dt - timedelta(days=dt.weekday())
    return f"Week of {monday.strftime('%d %b %Y')}"


def _voice_delta_label(delta: float | None) -> str:
    """Human label for Burrows' Delta (voice_engine/similarity.py) - lower is closer
    to the real corpus. Thresholds are explicitly provisional, not settled science:
    calibrated against a tiny, heterogeneous real sample (2 short polished LinkedIn
    posts + 4 long raw interview transcripts, weighted 2.5x for authenticity), and
    confirmed live that the score is genuinely noisy at this sample size - a real
    draft and a deliberately corporate paragraph scored within 0.01 of each other in
    one test. This isn't a bug in the math, it's a real consequence of estimating
    per-word variance from ~6 documents of very different shapes - it should get
    meaningfully more stable as more samples (especially more Gemini Q&A answers,
    the same register as the 4 that already carry the most weight) get added."""
    if delta is None:
        return ""
    if delta < 1.2:
        return f"Voice match: close ({delta})"
    if delta < 1.6:
        return f"Voice match: typical ({delta})"
    return f"Voice match: distant ({delta})"


def _json_list(value: str | None) -> list:
    try:
        return json.loads(value or "[]")
    except json.JSONDecodeError:
        return []


def _upload_rel(path: str) -> str:
    """A file under the upload dir as the relative path rx.get_upload_url expects."""
    try:
        return pathlib.Path(path).resolve().relative_to(pathlib.Path(rx.get_upload_dir()).resolve()).as_posix()
    except ValueError:
        return ""


# Template switcher options: "" keeps the model's own pick.
VISUAL_TEMPLATE_OPTIONS = list(CATALOG)


def _row_to_view(p: Post) -> PostView:
    return PostView(
        id=p.id,
        post_type=p.post_type,
        post_type_label=humanize(p.post_type),
        status=p.status,
        status_label=humanize(p.status),
        draft_text=p.draft_text,
        hashtags=json.loads(p.hashtags or "[]"),
        tags=json.loads(p.tags or "[]"),
        suggested_day=p.suggested_day or "",
        sources=json.loads(p.sources or "[]"),
        compliance_note=p.compliance_note or "",
        rejection_reason=p.rejection_reason or "",
        likes_input=str(p.likes) if p.likes is not None else "",
        comments_input=str(p.comments) if p.comments is not None else "",
        week_label=_week_label(p.created_at),
        created_at_str=p.created_at.strftime("%d %b"),
        scheduled_week=p.scheduled_week or "",
        funnel_stage=p.funnel_stage or "",
        hook_posture_label=humanize(p.hook_posture or ""),
        length_bucket_label=humanize(p.length_bucket or ""),
        structural_format_label=humanize(p.structural_format or ""),
        media_pairing_label=humanize(p.media_pairing or ""),
        media_note=p.media_note or "",
        voice_delta_label=_voice_delta_label(p.voice_delta),
        visual_files=[_upload_rel(f) for f in _json_list(p.visual_files) if pathlib.Path(f).exists()],
        visual_pdf=_upload_rel(p.visual_pdf) if p.visual_pdf and pathlib.Path(p.visual_pdf).exists() else "",
        visual_template=p.visual_template or "",
        visual_template_label=CATALOG[p.visual_template].name if p.visual_template in CATALOG else "",
        visual_note=p.visual_note or "",
        visual_choice=p.visual_template or "",
    )


_draft_from_bank_row = draft_from_bank_row  # shared with planning.py's prepare_week


class DashboardState(rx.State):
    posts: list[PostView] = []  # review queue: status == "drafted" only
    accepted_posts: list[PostView] = []  # approved + published
    rejected_posts: list[PostView] = []  # last 5 only, per scheduling.REJECTED_KEEP
    bank_rows: list[BankView] = []
    draft_queue: list[QueuedDraftView] = []
    forced_topics: list[ForcedTopicView] = []
    history_posts: list[PostView] = []
    stats: dict[str, str] = {}

    # Last successful daily research run (request: after a real scheduled run got
    # silently force-killed by Task Scheduler's execution time limit with nothing
    # anywhere showing it had failed, surface this instead of leaving it something
    # only discoverable via Get-ScheduledTaskInfo).
    last_research_run_display: str = "no successful run yet"
    last_research_run_stale: bool = False

    # Statistics page - breakdowns across every post ever drafted, not just what's
    # currently loaded for the other pages above.
    stats_by_post_type: list[StatBreakdownItem] = []
    stats_by_status: list[StatBreakdownItem] = []
    stats_by_funnel_stage: list[StatBreakdownItem] = []
    stats_by_hook_posture: list[StatBreakdownItem] = []
    stats_by_length_bucket: list[StatBreakdownItem] = []
    stats_by_structural_format: list[StatBreakdownItem] = []
    stats_by_media_pairing: list[StatBreakdownItem] = []
    stats_by_week: list[StatBreakdownItem] = []

    # Accepted page: status filter + 4-week look-ahead selector (request: "a filter for
    # looking at accepted and looking at published ones" / "select through the weeks
    # almost like a calendar... four weeks you can look at and plan ahead for")
    accepted_status_filter: str = "all"  # all / approved / published
    selected_week_offset: int = 0  # 0-3, index into upcoming_week_mondays()
    planned_notes: list[PlannedNoteView] = []
    note_drafts: dict[str, str] = {}  # date -> in-progress note text, before Save
    note_draft_post_types: dict[str, str] = {}  # date -> post type for that in-progress note

    # Quick actions
    quick_topic: str = ""
    quick_post_type: str = "ai_commentary"
    new_forced_topic: str = ""
    new_forced_topic_category: str = "ai"

    upload_text: str = ""
    # Home > Personal updates: milestones/news (+ photos) saved for the next planned
    # personal post. The only thing a planned personal post may be written from.
    personal_text: str = ""
    personal_updates: list[PersonalUpdateView] = []  # waiting to be used
    personal_updates_used: list[PersonalUpdateView] = []  # recently used, for reference

    # Dictation (request: "a button that can be pressed to allow for voice to be recorded
    # and transcribed directly in"). target is "weekly" (Home's note box) or "redraft"
    # (a Review card's redraft note, identified by post_id). Recording happens in the
    # browser; transcription runs locally with the same faster-whisper capture uses.
    recording_target: str = ""
    recording_post_id: int = 0
    transcribing_target: str = ""
    transcribing_post_id: int = 0
    upload_post_type: str = "personal_reflection"
    status_message: str = ""
    is_busy: bool = False

    # Voice page - the only way real writing samples get into voice_samples was a
    # CLI script; there was no dashboard flow for it at all, so the profile driving
    # every single draft has been running on 5 placeholder samples since 2 Sept 2026
    # with no way for James to replace them short of editing the database directly.
    voice_samples: list[VoiceSampleView] = []
    voice_sample_counts: list[SampleCountView] = []
    voice_new_sample_text: str = ""
    voice_profile_status: str = "no profile generated yet"
    # Zeta words (real, corpus-derived - voice_engine/similarity.py::compute_zeta_
    # words) and repeated bigrams, surfaced so James can see what the profile is
    # actually picking up on, not just trust it blindly.
    voice_zeta_words: list[str] = []
    voice_characteristic_bigrams: list[str] = []
    # Real POS-ratio/passive-voice stats (voice_engine/syntax_profile.py, spaCy) -
    # diagnostic display only, not yet a drafting-prompt directive.
    voice_syntax_summary: str = ""
    # Corpus health check (on demand, not on every load - request: surface
    # `validate_voice_metric`/register-aware Delta readiness on the dashboard instead
    # of needing to ask for a script run). Empty until "Check corpus health" is clicked.
    voice_health_rows: list[VoiceRegisterHealthView] = []
    voice_health_checked: bool = False

    # Gemini Q&A samples (request: "I'm having conversations with Gemini... it's
    # asking me a question, and I'm putting a text answer" - the answers are real,
    # unscripted James-in-his-own-words material, a second source alongside pasted
    # LinkedIn posts). One pair at a time:
    voice_qa_question: str = ""
    voice_qa_answer: str = ""
    # Or a whole labeled transcript at once ("I'll give the full conversation, just a
    # straight script... I will ask gemini to label who is speaking") - parsed into a
    # preview the user confirms before anything is actually saved.
    voice_convo_text: str = ""
    voice_convo_gemini_label: str = "Gemini"
    voice_convo_me_label: str = "Me"
    voice_convo_preview: list[VoiceConvoPairView] = []

    # Email settings - both jobs fully independent on day AND time
    email_recipient: str = ""
    email_reminder_day: str = "Friday"
    email_reminder_time: str = "09:00"
    email_digest_day: str = "Sunday"
    email_digest_time: str = "12:00"

    # Weekly post-type template (request: "choose which days the certain types of
    # post to go to... option for no post as well") - "Plan this week" reads this to
    # auto-fill empty days; it's a default, never forced onto a day you've already
    # put your own note on.
    wt_monday: str = "personal_reflection"
    wt_tuesday: str = "ai_commentary"
    wt_wednesday: str = "no_post"
    wt_thursday: str = "ai_commentary"
    wt_friday: str = "market_commentary"
    wt_saturday: str = "no_post"
    wt_sunday: str = "no_post"
    wt_recommend_holidays: bool = True
    wt_auto_prepare: bool = True

    # Topic Bank -> day linking (request: "click on them and even drag them or select
    # a day that I want them to be linked to" - literal cross-page drag-and-drop isn't
    # practical to build reliably in Reflex, so this is a pick-a-date-then-click flow
    # instead: one shared target date, a "Link to day" button per bank row).
    link_target_date: str = ""

    # Calendar of yearly occasions (calendar_engine/) and the Posts page's sub-tabs.
    calendar_events: list[CalendarEventView] = []
    calendar_month_offset: int = 0
    posts_tab: str = "review"

    # ---- loading ----

    @rx.event
    def load_dashboard(self):
        """Runs on every page load. Never let a single bad reload blank the whole
        page for someone with no way to debug it - fail into a visible message."""
        try:
            allocate_accepted_posts()
            self._reload_posts()
            self._reload_accepted()
            self._reload_rejected()
            self._reload_bank()
            self._reload_forced_topics()
            self._reload_history()
            self._reload_email_settings()
            self._reload_weekly_template()
            self._reload_planned_notes()
            self._reload_calendar()
            self._reload_stats()
            self._reload_job_status()
            self._reload_voice()
            self._reload_personal_updates()
            if not self.link_target_date:
                self.link_target_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception as exc:  # noqa: BLE001
            self.status_message = (
                f"Couldn't load the dashboard ({exc}). Try refreshing the page - "
                "if it keeps happening, get in touch."
            )

    @rx.event
    def clear_status_message(self):
        self.status_message = ""

    def _reload_posts(self):
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(Post)
                .where(Post.status == "drafted")
                .order_by(sqlmodel.col(Post.created_at).desc())
            ).all()
        notes = {p.id: p.redraft_note for p in self.posts if p.redraft_note}
        self.posts = [
            _row_to_view(p).model_copy(update={"redraft_note": notes.get(p.id, "")}) for p in rows
        ]

    def _reload_accepted(self):
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(Post)
                .where(sqlmodel.col(Post.status).in_(["approved", "published"]))
                .order_by(sqlmodel.col(Post.scheduled_week).asc(), sqlmodel.col(Post.created_at).asc())
            ).all()
        self.accepted_posts = [_row_to_view(p) for p in rows]
        self._refresh_bundles()

    def _reload_rejected(self):
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(Post)
                .where(Post.status == "rejected")
                .order_by(sqlmodel.col(Post.reviewed_at).desc())
            ).all()
        self.rejected_posts = [_row_to_view(p) for p in rows]

    @rx.event
    def set_accepted_status_filter(self, value: str):
        self.accepted_status_filter = value

    @rx.event
    def set_selected_week_offset(self, offset: int):
        """Controls the Accepted-posts week filter only - the planning calendar below
        shows the whole month regardless (request: "plan a month of posts out, not
        just a week"), so this no longer needs to reload planned notes."""
        self.selected_week_offset = offset

    @rx.var
    def week_options(self) -> list[dict[str, str]]:
        """The 4-week look-ahead: this week, next week, and two more - request: 'four
        weeks you can look at and plan ahead for'."""
        mondays = upcoming_week_mondays(4)
        names = ["This week", "Next week", "In 2 weeks", "In 3 weeks"]
        return [
            {"offset": str(i), "monday": monday, "label": f"{names[i]} ({monday})"}
            for i, monday in enumerate(mondays)
        ]

    @rx.var
    def selected_week_monday(self) -> str:
        mondays = upcoming_week_mondays(4)
        idx = min(max(self.selected_week_offset, 0), len(mondays) - 1)
        return mondays[idx]

    @rx.var
    def accepted_by_week(self) -> list[tuple[str, list[PostView]]]:
        current = current_week_label()
        selected = self.selected_week_monday
        filtered = [
            p
            for p in self.accepted_posts
            if p.scheduled_week == selected
            and (self.accepted_status_filter == "all" or p.status == self.accepted_status_filter)
        ]
        if not filtered:
            return []
        label = "This week" if selected == current else f"Week starting {selected}"
        return [(f"{label} ({selected})", filtered)]

    # ---- forward-planning notes: pencil in what a future date should be about,
    # before any topic/research exists (request: "put a note... I want this to be
    # about that new statement" / a Halloween-themed post pencilled in ahead of time) ----

    def _reload_planned_notes(self):
        """Loads notes across the whole month horizon (all 4 upcoming weeks), not just
        one selected week - the planning calendar always shows the full month."""
        dates = [d for monday in upcoming_week_mondays(4) for d in week_dates(monday)]
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(PlannedNote).where(sqlmodel.col(PlannedNote.target_date).in_(dates))
            ).all()
        self.planned_notes = [
            PlannedNoteView(
                id=r.id,
                target_date=r.target_date,
                note_text=r.note_text,
                post_type=r.post_type,
                post_type_label=humanize(r.post_type),
            )
            for r in rows
        ]
        # Pre-seed the draft-input dicts for every date across the month, so the
        # frontend never indexes a missing dict key for a day with no note yet.
        self.note_drafts = {**{d: "" for d in dates}, **self.note_drafts}
        # Each day's post type defaults to the weekly schedule (Settings > Weekly Plan
        # Template), not a blanket personal_reflection.
        self.note_draft_post_types = {
            **{d: self._template_default_type(d) for d in dates},
            **self.note_draft_post_types,
        }

    def _template_type_for(self, date_str: str) -> str:
        """The weekly schedule's post type (or "no_post") for this date's weekday."""
        weekday = date.fromisoformat(date_str).weekday()
        return getattr(self, f"wt_{_WEEKDAY_FIELDS[weekday]}")

    def _template_default_type(self, date_str: str) -> str:
        planned = self._template_type_for(date_str)
        return planned if planned in POST_TYPES else "personal_reflection"

    @rx.var
    def month_plan(self) -> list[WeekPlanView]:
        """The full 4-week planning horizon, grouped by week, each with a "Fill this
        week" entry point (request: "have a button per week")."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        by_date = {n.target_date: n for n in self.planned_notes}
        scheduled_counts: dict[str, int] = {}
        for p in self.accepted_posts:
            if p.scheduled_week:
                scheduled_counts[p.scheduled_week] = scheduled_counts.get(p.scheduled_week, 0) + 1

        weeks = []
        for monday in upcoming_week_mondays(4):
            days = []
            for d in week_dates(monday):
                dt = datetime.strptime(d, "%Y-%m-%d")
                holiday = holiday_for_date(d)
                planned = self._template_type_for(d)
                days.append(
                    DayPlanView(
                        date=d,
                        day_label=dt.strftime("%a %d %b"),
                        is_today=d == today,
                        note=by_date.get(d),
                        holiday_name=holiday[0] if holiday else "",
                        scheduled_label="No post" if planned == "no_post" else humanize(planned),
                        is_no_post_day=planned == "no_post",
                        occasion_names=[
                            e.name for e in self.calendar_events if e.included is True and e.start <= d <= e.end
                        ],
                    )
                )
            label = "This week" if monday == current_week_label() else f"Week of {monday}"
            weeks.append(
                WeekPlanView(
                    week_label=label,
                    monday=monday,
                    already_scheduled=scheduled_counts.get(monday, 0),
                    days=days,
                )
            )
        return weeks

    @rx.event
    def set_note_draft(self, date: str, value: str):
        self.note_drafts = {**self.note_drafts, date: value}

    @rx.event
    def set_note_draft_post_type(self, date: str, value: str):
        self.note_draft_post_types = {**self.note_draft_post_types, date: value}

    @rx.event
    def save_planned_note(self, date: str):
        note_text = self.note_drafts.get(date, "").strip()
        if not note_text:
            return
        post_type = self.note_draft_post_types.get(date, "personal_reflection")
        with rx.session(url=config.db_url) as session:
            existing = session.exec(
                sqlmodel.select(PlannedNote).where(PlannedNote.target_date == date)
            ).first()
            if existing:
                existing.note_text = note_text
                existing.post_type = post_type
                session.add(existing)
            else:
                session.add(
                    PlannedNote(
                        target_date=date,
                        note_text=note_text,
                        post_type=post_type,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()
        self.note_drafts = {k: v for k, v in self.note_drafts.items() if k != date}
        self._reload_planned_notes()
        self.status_message = f"Note saved for {date}."

    @rx.event
    def delete_planned_note(self, note_id: int):
        with rx.session(url=config.db_url) as session:
            row = session.get(PlannedNote, note_id)
            if row:
                session.delete(row)
                session.commit()
        self._reload_planned_notes()

    @rx.event(background=True)
    async def generate_from_planned_note(self, note_id: int):
        async with self:
            note = next((n for n in self.planned_notes if n.id == note_id), None)
            if note is None:
                return
            self.is_busy = True
            self.status_message = f"Drafting from your note for {note.target_date}..."
            note_text, post_type, target_date = note.note_text, note.post_type, note.target_date

        try:
            skip_research = post_type == "personal_reflection"
            post = generate_and_save_draft(note_text, post_type, skip_research=skip_research)
            with rx.session(url=config.db_url) as session:
                row = session.get(Post, post.id)
                dt = datetime.strptime(target_date, "%Y-%m-%d")
                row.suggested_day = dt.strftime("%A")
                session.add(row)
                session.commit()
            message = f"Draft generated for {target_date} - check Review."
        except Exception as exc:  # noqa: BLE001
            message = f"Draft generation failed: {exc}"

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_posts()
            self._reload_stats()

    def _reload_bank(self):
        with rx.session(url=config.db_url) as session:
            # Calendar-linked findings first (soonest occasion first), so a ticked
            # occasion's story is always visible even if it's older than the top 20.
            linked = session.exec(
                sqlmodel.select(TopicBank, CalendarEvent)
                .join(CalendarEvent, TopicBank.calendar_event_id == CalendarEvent.id)
                .where(TopicBank.used == False)  # noqa: E712
                .order_by(sqlmodel.col(CalendarEvent.date).asc())
            ).all()
            rows = session.exec(
                sqlmodel.select(TopicBank)
                .where(
                    TopicBank.used == False,  # noqa: E712
                    TopicBank.tier != "discard",
                    TopicBank.calendar_event_id == None,  # noqa: E711
                )
                .order_by(sqlmodel.col(TopicBank.tier).asc(), sqlmodel.col(TopicBank.date_found).desc())
                .limit(20)
            ).all()
        pairs = [(r, f"{e.name}, {as_utc(e.date).strftime('%d %b')}") for r, e in linked] + [(r, "") for r in rows]
        self.bank_rows = [
            BankView(
                id=r.id,
                summary=r.summary,
                source_title=r.source_title,
                source_url=r.source_url,
                tier=r.tier,
                tier_label=humanize(r.tier),
                category=r.category,
                category_label=humanize(r.category),
                occasion_label=occasion,
            )
            for r, occasion in pairs
        ]

    def _reload_calendar(self):
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(CalendarEvent).order_by(sqlmodel.col(CalendarEvent.date).asc())
            ).all()
        self.calendar_events = [_calendar_row_to_view(r) for r in rows]

    @rx.var
    def calendar_month_options(self) -> list[dict[str, str]]:
        """Every month that has occasions, in order - from today to year end at first,
        then a full year ahead once the November plan has run."""
        seen: dict[str, str] = {}
        for e in self.calendar_events:
            seen.setdefault(e.month_key, e.month_label)
        return [{"key": k, "label": v} for k, v in seen.items()]

    @rx.var
    def selected_calendar_month(self) -> str:
        options = self.calendar_month_options
        if not options:
            return ""
        return options[min(max(self.calendar_month_offset, 0), len(options) - 1)]["key"]

    @rx.var
    def calendar_events_for_month(self) -> list[CalendarEventView]:
        return [e for e in self.calendar_events if e.month_key == self.selected_calendar_month]

    @rx.event
    def set_calendar_month_offset(self, offset: int):
        self.calendar_month_offset = offset

    @rx.event
    def set_posts_tab(self, value: str):
        self.posts_tab = value

    @rx.event(background=True)
    async def set_calendar_event_included(self, event_id: int, value: bool):
        """Your Yes/No tick. A Yes links the occasion to a real Topic Bank story (or
        banks its own angle) straight away if it's within 45 days - background,
        because matching may embed recent stories the first time."""
        with rx.session(url=config.db_url) as session:
            row = session.get(CalendarEvent, event_id)
            if row:
                row.included = value
                session.add(row)
                session.commit()
        async with self:
            self._reload_calendar()
            if value:
                self.status_message = "Checking the Topic Bank for a story that fits this occasion..."
        if not value:
            return

        try:
            result = try_link_now(event_id)
        except Exception as exc:  # noqa: BLE001
            result = {"status": "error", "reason": str(exc)}

        async with self:
            self._reload_calendar()
            self._reload_bank()
            if result.get("status") == "ok" and result.get("outcome") == "linked":
                self.status_message = "Linked to a real story - it's at the top of the Topic Bank."
            elif result.get("status") == "ok":
                self.status_message = "No matching story yet, so its angle is banked at the top of the Topic Bank."
            elif result.get("status") == "too_early":
                self.status_message = "Saved. It's more than 45 days away, so it'll link automatically closer to the date."
            elif result.get("status") == "error":
                self.status_message = f"Saved, but linking failed: {result['reason']}"
            else:
                self.status_message = "Saved."

    def _reload_forced_topics(self):
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(ForcedTopic)
                .where(ForcedTopic.consumed == False)  # noqa: E712
                .order_by(sqlmodel.col(ForcedTopic.created_at).asc())
            ).all()
        self.forced_topics = [
            ForcedTopicView(id=r.id, topic=r.topic, category=r.category, category_label=humanize(r.category))
            for r in rows
        ]

    def _reload_history(self):
        """Everything from the last few weeks, regardless of status - lets you look
        back and decide to line up a catch-up post for a thin week (request: "ability
        to look over the last few weeks... get them lined up")."""
        cutoff = datetime.now(timezone.utc) - timedelta(weeks=HISTORY_WEEKS_LIMIT)
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(Post)
                .where(sqlmodel.col(Post.created_at) >= cutoff)
                .order_by(sqlmodel.col(Post.created_at).desc())
            ).all()
        self.history_posts = [_row_to_view(p) for p in rows]

    @rx.var
    def history_by_week(self) -> list[tuple[str, list[PostView]]]:
        weeks: dict[str, list[PostView]] = {}
        for p in self.history_posts:
            weeks.setdefault(p.week_label, []).append(p)
        return list(weeks.items())

    def _reload_email_settings(self):
        settings = get_email_settings()
        if settings:
            self.email_recipient = settings.recipient_email
            self.email_reminder_day = settings.reminder_day
            self.email_reminder_time = settings.reminder_time
            self.email_digest_day = settings.digest_day
            self.email_digest_time = settings.digest_time

    @rx.event
    def set_email_recipient(self, value: str):
        self.email_recipient = value

    @rx.event
    def set_email_reminder_day(self, value: str):
        self.email_reminder_day = value

    @rx.event
    def set_email_reminder_time(self, value: str):
        self.email_reminder_time = value

    @rx.event
    def set_email_digest_day(self, value: str):
        self.email_digest_day = value

    @rx.event
    def set_email_digest_time(self, value: str):
        self.email_digest_time = value

    @rx.event
    def save_email_settings_click(self):
        save_email_settings(
            self.email_recipient,
            self.email_reminder_day,
            self.email_reminder_time,
            self.email_digest_day,
            self.email_digest_time,
        )
        self.status_message = "Email settings saved."

    def _reload_job_status(self):
        """job_runs.last_run_at is only ever written after run_daily_research
        finishes successfully (pipeline.py's _set_last_run, called at the very end) -
        so it's a genuine "last successful completion" signal, not "last attempt."
        Flagged stale past ~36h to give the 7am daily cadence a day-plus-a-bit of
        slack before nagging (avoids a false alarm just from checking a few hours
        after a normal delay, e.g. the machine being off overnight)."""
        with rx.session(url=config.db_url) as session:
            row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == RESEARCH_JOB_NAME)).first()
        if row is None:
            self.last_research_run_display = "no successful run yet"
            self.last_research_run_stale = False
            return
        last_run = as_utc(row.last_run_at)
        age = datetime.now(timezone.utc) - last_run
        self.last_research_run_display = last_run.strftime("%a %d %b, %H:%M UTC")
        self.last_research_run_stale = age > timedelta(hours=36)

    # ---- weekly post-type template (request: "choose which days the certain types
    # of post to go to... option for no post as well") ----

    def _reload_weekly_template(self):
        with rx.session(url=config.db_url) as session:
            row = session.exec(sqlmodel.select(WeeklyTemplate)).first()
        if row:
            for day in _WEEKDAY_FIELDS:
                setattr(self, f"wt_{day}", getattr(row, day))
            self.wt_recommend_holidays = row.recommend_holidays
            self.wt_auto_prepare = row.auto_prepare

    @rx.event
    def set_wt_monday(self, value: str):
        self.wt_monday = value

    @rx.event
    def set_wt_tuesday(self, value: str):
        self.wt_tuesday = value

    @rx.event
    def set_wt_wednesday(self, value: str):
        self.wt_wednesday = value

    @rx.event
    def set_wt_thursday(self, value: str):
        self.wt_thursday = value

    @rx.event
    def set_wt_friday(self, value: str):
        self.wt_friday = value

    @rx.event
    def set_wt_saturday(self, value: str):
        self.wt_saturday = value

    @rx.event
    def set_wt_sunday(self, value: str):
        self.wt_sunday = value

    @rx.event
    def set_wt_recommend_holidays(self, value: bool):
        self.wt_recommend_holidays = value

    @rx.event
    def set_wt_auto_prepare(self, value: bool):
        self.wt_auto_prepare = value

    @rx.event
    def save_weekly_template(self):
        with rx.session(url=config.db_url) as session:
            row = session.exec(sqlmodel.select(WeeklyTemplate)).first()
            if row is None:
                row = WeeklyTemplate()
            for day in _WEEKDAY_FIELDS:
                setattr(row, day, getattr(self, f"wt_{day}"))
            row.recommend_holidays = self.wt_recommend_holidays
            row.auto_prepare = self.wt_auto_prepare
            session.add(row)
            session.commit()
        # Plan ahead's per-day dropdowns follow the schedule, so re-seed them from it.
        self.note_draft_post_types = {d: self._template_default_type(d) for d in self.note_draft_post_types}
        self.status_message = "Weekly plan saved."

    @rx.event
    def reuse_as_new_topic(self, post_id: int):
        post = next((p for p in self.history_posts if p.id == post_id), None)
        if not post:
            return
        self.quick_topic = post.draft_text[:200]
        self.status_message = (
            "Copied into 'Generate a post now' below - adjust the topic and post type, "
            "then click Research + draft."
        )

    def _reload_stats(self):
        with rx.session(url=config.db_url) as session:
            all_posts = session.exec(sqlmodel.select(Post)).all()

        counts: dict[str, int] = {}
        for p in all_posts:
            counts[p.status] = counts.get(p.status, 0) + 1

        decided = counts.get("approved", 0) + counts.get("published", 0) + counts.get("rejected", 0)
        accepted = counts.get("approved", 0) + counts.get("published", 0)
        acceptance_rate = f"{100 * accepted / decided:.0f}%" if decided else "n/a"

        review_times = [
            (as_utc(p.reviewed_at) - as_utc(p.created_at)).total_seconds() / 3600
            for p in all_posts
            if p.reviewed_at is not None
        ]
        publish_times = [
            (as_utc(p.published_at) - as_utc(p.reviewed_at)).total_seconds() / 3600
            for p in all_posts
            if p.published_at is not None and p.reviewed_at is not None
        ]
        avg_review = f"{sum(review_times) / len(review_times):.1f}h" if review_times else "n/a"
        avg_publish = f"{sum(publish_times) / len(publish_times):.1f}h" if publish_times else "n/a"

        self.stats = {
            "drafted": str(counts.get("drafted", 0)),
            "approved": str(counts.get("approved", 0)),
            "published": str(counts.get("published", 0)),
            "rejected": str(counts.get("rejected", 0)),
            "acceptance_rate": acceptance_rate,
            "avg_time_to_review": avg_review,
            "avg_time_to_publish": avg_publish,
        }

        self._reload_full_stats(all_posts)

    def _reload_full_stats(self, all_posts: list[Post]) -> None:
        """Statistics page breakdowns - reuses the same all-posts query _reload_stats
        already ran rather than hitting the database a second time."""

        def _count_by(attr: str) -> dict[str, int]:
            counts: dict[str, int] = {}
            for p in all_posts:
                value = getattr(p, attr) or ""
                if value:
                    counts[value] = counts.get(value, 0) + 1
            return counts

        self.stats_by_post_type = _breakdown(_count_by("post_type"))
        self.stats_by_status = _breakdown(_count_by("status"))
        self.stats_by_funnel_stage = _breakdown(_count_by("funnel_stage"))
        self.stats_by_hook_posture = _breakdown(_count_by("hook_posture"))
        self.stats_by_length_bucket = _breakdown(_count_by("length_bucket"))
        self.stats_by_structural_format = _breakdown(_count_by("structural_format"))
        self.stats_by_media_pairing = _breakdown(_count_by("media_pairing"))

        cutoff = datetime.now(timezone.utc) - timedelta(weeks=HISTORY_WEEKS_LIMIT)
        week_counts: dict[str, int] = {}
        for p in all_posts:
            if as_utc(p.created_at) >= cutoff:
                wk = _week_label(p.created_at)
                week_counts[wk] = week_counts.get(wk, 0) + 1
        self.stats_by_week = _breakdown(week_counts, sort_by_count=False)

    @rx.var
    def posts_by_day(self) -> dict[str, list[PostView]]:
        buckets: dict[str, list[PostView]] = {day: [] for day in DISPLAY_DAYS}
        for p in self.posts:
            key = p.suggested_day if p.suggested_day in WEEKDAYS else "Unscheduled"
            buckets[key].append(p)
        return buckets

    def _find_post(self, post_id: int) -> PostView | None:
        for collection in (self.posts, self.accepted_posts, self.rejected_posts, self.history_posts):
            for p in collection:
                if p.id == post_id:
                    return p
        return None

    def _persist(self, post_id: int, **fields) -> None:
        with rx.session(url=config.db_url) as session:
            row = session.get(Post, post_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            session.add(row)
            session.commit()

    def _rebuild_bundles(self) -> None:
        """Ready-to-post folders (exports/<week>/<NN Day - type>/) for every approved
        post - rebuilt after anything that can change a post's day or files."""
        with rx.session(url=config.db_url) as session:
            ids = session.exec(
                sqlmodel.select(Post.id).where(sqlmodel.col(Post.status).in_(["approved", "published"]))
            ).all()
        for pid in ids:
            try:
                build_bundle(pid)
            except Exception:  # noqa: BLE001 - a folder copy must never block a review click
                pass
        self._refresh_bundles()

    def _refresh_bundles(self) -> None:
        from linkedin_content_engine.exports import EXPORTS_DIR

        folders = {}
        if EXPORTS_DIR.exists():
            for marker in EXPORTS_DIR.glob("*/*/.post-*"):
                folders[int(marker.name.split("-")[1])] = str(marker.parent)
        for p in self.accepted_posts:
            p.bundle_dir = folders.get(p.id, "")

    @rx.event
    def set_visual_choice(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.visual_choice = value

    @rx.event(background=True)
    async def remake_visual(self, post_id: int):
        """Makes (or re-makes) a post's visual - in the template picked in the
        switcher, or the model's own pick when nothing's chosen. Works on text-only
        posts too: asking by hand overrides the rotation's "no image"."""
        async with self:
            view = self._find_post(post_id)
            choice = view.visual_choice if view else ""
            self.is_busy = True
            self.status_message = "Making the visual..."
        make_visual_for_post(post_id, template_key=choice or None, force=True)
        with rx.session(url=config.db_url) as session:
            post = session.get(Post, post_id)
            approved = post is not None and post.status in ("approved", "published")
        if approved:
            build_bundle(post_id)
        async with self:
            self.is_busy = False
            self.status_message = "Visual ready." if self._visual_ok(post_id) else "Visual didn't work - see the note on the post."
            self._reload_posts()
            self._reload_accepted()
            self._refresh_bundles()

    def _visual_ok(self, post_id: int) -> bool:
        with rx.session(url=config.db_url) as session:
            post = session.get(Post, post_id)
        return bool(post and _json_list(post.visual_files)) and not (post.visual_note or "").startswith("Couldn't")

    @rx.event
    def open_bundle(self, post_id: int):
        """Opens the post's ready-to-post folder in Explorer (this PC only)."""
        import os

        post = self._find_post(post_id)
        if post and post.bundle_dir and pathlib.Path(post.bundle_dir).exists():
            os.startfile(post.bundle_dir)  # noqa: S606 - local folder we wrote ourselves
        else:
            self.status_message = "No ready-to-post folder yet - it's made when the post is accepted."

    @rx.event
    def prepare_next_week(self):
        return DashboardState.plan_week(next_week_monday())

    @rx.event(background=True)
    async def send_digest_now(self):
        """Sends next week's digest now, regardless of the scheduled day."""
        from linkedin_content_engine.email_engine.digest import build_digest
        from linkedin_content_engine.email_engine.send import send_email

        async with self:
            self.is_busy = True
            self.status_message = "Building next week's email..."
        settings = get_email_settings()
        if not settings or not settings.recipient_email:
            message = "Set a recipient in Email reminders first."
        else:
            d = build_digest()
            sent, why = send_email(
                settings.recipient_email, d["subject"], d["text"],
                html=d["html"], inline_images=d["inline"], attachments=d["attachments"],
            )
            message = f"Sent next week's email ({d['count']} post(s))." if sent else why
        async with self:
            self.is_busy = False
            self.status_message = message

    # ---- editing ----

    @rx.event
    def set_draft_text(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.draft_text = value

    @rx.event
    def save_draft_text(self, post_id: int):
        post = self._find_post(post_id)
        if post:
            self._persist(post_id, draft_text=post.draft_text)

    @rx.event
    def set_compliance_note(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.compliance_note = value

    @rx.event
    def save_compliance_note(self, post_id: int):
        post = self._find_post(post_id)
        if post:
            self._persist(post_id, compliance_note=post.compliance_note)

    @rx.event
    def set_suggested_day(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.suggested_day = value
            self._persist(post_id, suggested_day=value)

    @rx.event
    def set_new_hashtag_input(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.new_hashtag_input = value

    @rx.event
    def add_hashtag(self, post_id: int):
        post = self._find_post(post_id)
        if not post:
            return
        tag = post.new_hashtag_input.strip().lstrip("#")
        if tag and tag not in post.hashtags:
            post.hashtags = [*post.hashtags, tag]
            self._persist(post_id, hashtags=json.dumps(post.hashtags))
        post.new_hashtag_input = ""

    @rx.event
    def remove_hashtag(self, post_id: int, tag: str):
        post = self._find_post(post_id)
        if post:
            post.hashtags = [t for t in post.hashtags if t != tag]
            self._persist(post_id, hashtags=json.dumps(post.hashtags))

    @rx.event
    def set_new_tag_input(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.new_tag_input = value

    @rx.event
    def add_tag(self, post_id: int):
        post = self._find_post(post_id)
        if not post:
            return
        tag = post.new_tag_input.strip()
        if tag and tag not in post.tags:
            post.tags = [*post.tags, tag]
            self._persist(post_id, tags=json.dumps(post.tags))
        post.new_tag_input = ""

    @rx.event
    def remove_tag(self, post_id: int, tag: str):
        post = self._find_post(post_id)
        if post:
            post.tags = [t for t in post.tags if t != tag]
            self._persist(post_id, tags=json.dumps(post.tags))

    # ---- review actions: Accept / Redraft / Reject (request: replace the old
    # approve-or-reject-only flow with a third "Redraft" option) ----

    @rx.event
    def accept(self, post_id: int):
        now = datetime.now(timezone.utc)
        self._persist(post_id, status="approved", reviewed_at=now)
        allocate_accepted_posts()  # request: auto-assign into this/next week
        self._rebuild_bundles()
        self._reload_posts()
        self._reload_accepted()
        self._reload_stats()

    @rx.event
    def reject(self, post_id: int, reason: str):
        now = datetime.now(timezone.utc)
        self._persist(post_id, status="rejected", reviewed_at=now, rejection_reason=reason)
        prune_rejected_posts()  # request: only keep the last 5
        self._reload_posts()
        self._reload_rejected()
        self._reload_stats()

    @rx.event(background=True)
    async def redraft(self, post_id: int):
        """Generates a fresh draft from the same material and retires the old one -
        request: Review needs a third option beyond just accept/reject."""
        async with self:
            self.is_busy = True
            self.status_message = "Redrafting..."
            view = self._find_post(post_id)
            note = view.redraft_note.strip() if view else ""

        with rx.session(url=config.db_url) as session:
            old = session.get(Post, post_id)
            if old is None:
                async with self:
                    self.is_busy = False
                    self.status_message = "That post no longer exists."
                return
            topic, post_type, sources_json = old.draft_text, old.post_type, old.sources
            photo = old.source_photo

        # With a note, the model needs the whole previous draft to know what it's
        # changing; without one, keep the original behaviour (a fresh take on its opening).
        draft_topic = (
            f"Rewrite this previous draft:\n\n{topic}\n\nWhat to change: {note}" if note else topic[:200]
        )
        try:
            findings = [ResearchFinding(**s) for s in json.loads(sources_json or "[]")]
            research = ResearchResult(topic=topic, status="ok" if findings else "no_results", findings=findings)
            generate_draft_with_research(draft_topic, post_type, research, source_photo=photo)
            now = datetime.now(timezone.utc)
            with rx.session(url=config.db_url) as session:
                old = session.get(Post, post_id)
                old.status = "rejected"
                old.rejection_reason = "redrafted"
                old.reviewed_at = now
                session.add(old)
                session.commit()
            prune_rejected_posts()
            message = "New draft generated - the old version moved to Rejected."
        except Exception as exc:  # noqa: BLE001
            message = f"Redraft failed: {exc}"

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_posts()
            self._reload_rejected()
            self._reload_stats()

    @rx.event
    def mark_published(self, post_id: int):
        now = datetime.now(timezone.utc)
        self._persist(post_id, status="published", published_at=now)
        self._reload_accepted()
        self._reload_stats()

    @rx.event
    def set_likes_input(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.likes_input = value

    @rx.event
    def save_likes(self, post_id: int):
        post = self._find_post(post_id)
        if not post:
            return
        try:
            likes = int(post.likes_input)
        except ValueError:
            return
        self._persist(post_id, likes=likes, engagement_updated_at=datetime.now(timezone.utc))

    @rx.event
    def set_comments_input(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.comments_input = value

    @rx.event
    def save_comments(self, post_id: int):
        post = self._find_post(post_id)
        if not post:
            return
        try:
            comments = int(post.comments_input)
        except ValueError:
            return
        self._persist(post_id, comments=comments, engagement_updated_at=datetime.now(timezone.utc))

    # ---- topic bank -> draft (spec Â§3d: "the topic bank underneath it if you want to intervene") ----

    @rx.event(background=True)
    async def generate_from_bank(self, bank_id: int):
        async with self:
            self.is_busy = True
            self.status_message = "Generating draft from topic bank..."

        with rx.session(url=config.db_url) as session:
            bank_row = session.get(TopicBank, bank_id)
            if bank_row is None:
                async with self:
                    self.is_busy = False
                    self.status_message = "That topic bank row no longer exists."
                return
            summary, source_title, source_url, category = (
                bank_row.summary,
                bank_row.source_title,
                bank_row.source_url,
                bank_row.category,
            )

        try:
            _draft_from_bank_row(bank_id, summary, source_title, source_url, category)
            message = "Draft generated from topic bank."
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI, don't crash the app
            message = f"Draft generation failed: {exc}"

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_posts()
            self._reload_bank()
            self._reload_stats()

    @rx.event
    def toggle_bank_selection(self, bank_id: int):
        """Multi-select for queued drafting (request: "select multiple topics to
        queue to draft at the same time"). Flips one row's checkbox - flags live on
        the row itself (BankView.is_selected) rather than a separate id list, since
        there's no list-membership check available from inside a foreach render."""
        self.bank_rows = [
            row.model_copy(update={"is_selected": not row.is_selected}) if row.id == bank_id else row
            for row in self.bank_rows
        ]

    @rx.event
    def clear_bank_selection(self):
        self.bank_rows = [row.model_copy(update={"is_selected": False}) for row in self.bank_rows]

    @rx.var
    def selected_bank_count(self) -> int:
        return sum(1 for row in self.bank_rows if row.is_selected)

    @rx.event
    def queue_selected_bank_rows(self):
        """Moves every currently-checked bank row into the draft queue instead of
        drafting immediately (request: "take each one of the ones I selected to
        queue into a box, don't start generating them yet"). Skips anything already
        queued (checking a row twice shouldn't duplicate it) and clears the bank's
        own checkbox selection afterward, since the row now lives in the queue
        instead."""
        already_queued = {item.bank_id for item in self.draft_queue}
        newly_queued = [
            QueuedDraftView(
                bank_id=row.id,
                summary=row.summary,
                source_title=row.source_title,
                source_url=row.source_url,
                category=row.category,
                tier_label=row.tier_label,
                category_label=row.category_label,
            )
            for row in self.bank_rows
            if row.is_selected and row.id not in already_queued
        ]
        self.draft_queue = self.draft_queue + newly_queued
        self.bank_rows = [row.model_copy(update={"is_selected": False}) for row in self.bank_rows]

    @rx.event
    def remove_from_queue(self, bank_id: int):
        self.draft_queue = [item for item in self.draft_queue if item.bank_id != bank_id]

    @rx.event
    def clear_draft_queue(self):
        self.draft_queue = []

    @rx.event
    def set_queue_option(self, bank_id: int, field: str, value: str):
        """Backs all 5 per-queued-topic style dropdowns - one handler bound with a
        different `field` per dropdown (see topic_bank.py) rather than 5 near-
        identical setters."""
        self.draft_queue = [
            item.model_copy(update={field: value}) if item.bank_id == bank_id else item
            for item in self.draft_queue
        ]

    @rx.event(background=True)
    async def generate_queued_drafts(self):
        """Draft everything currently sitting in the queue, one after another, each
        with its own per-item rotation overrides (any field left on AUTO_SENTINEL is
        picked automatically by rotation.py exactly as before). Reuses the same
        _draft_from_bank_row helper generate_from_bank/fill_week already share.
        Reports progress as it goes (each `async with self:` exit pushes a real UI
        update) since drafting several topics back to back - each one its own
        best-of-N pass - is genuinely slow."""
        async with self:
            queued = list(self.draft_queue)
            if not queued:
                return
            self.is_busy = True

        succeeded = 0
        failed = 0
        for i, item in enumerate(queued, start=1):
            async with self:
                self.status_message = f"Drafting {i} of {len(queued)} queued topics..."

            overrides = {
                "funnel_stage": item.funnel_stage,
                "hook_posture": item.hook_posture,
                "length_bucket": item.length_bucket,
                "structural_format": item.structural_format,
                "media_pairing": item.media_pairing,
            }
            try:
                _draft_from_bank_row(
                    item.bank_id,
                    item.summary,
                    item.source_title,
                    item.source_url,
                    item.category,
                    rotation_overrides=overrides,
                )
                succeeded += 1
            except Exception:  # noqa: BLE001 - one failure shouldn't stop the rest of the queue
                failed += 1

        async with self:
            self.is_busy = False
            failure_note = f" ({failed} failed)" if failed else ""
            self.status_message = f"Drafted {succeeded} of {len(queued)} queued topics{failure_note}."
            self.draft_queue = []
            self._reload_posts()
            self._reload_bank()
            self._reload_stats()

    @rx.event
    def set_link_target_date(self, value: str):
        self.link_target_date = value

    @rx.event
    def link_topic_to_day(self, bank_id: int):
        """request: "if I have topics that I like I want to be able to click on them...
        select a day that I want them to be linked to for a post." Genuine
        cross-page drag-and-drop isn't practical to build reliably in Reflex, so this
        is the click-then-pick-a-date equivalent: pick link_target_date once at the
        top of Topic Bank, then click "Link to day" on whichever topic should land
        there. Creates (or overwrites) that date's planned note, pointed at this bank
        row, so generating the draft later cites the real finding instead of treating
        it as a from-scratch personal note."""
        target_date = self.link_target_date
        with rx.session(url=config.db_url) as session:
            bank_row = session.get(TopicBank, bank_id)
            if bank_row is None:
                self.status_message = "That topic bank row no longer exists."
                return
            post_type = CATEGORY_TO_POST_TYPE.get(bank_row.category, "ai_commentary")
            existing = session.exec(
                sqlmodel.select(PlannedNote).where(PlannedNote.target_date == target_date)
            ).first()
            if existing:
                existing.note_text = bank_row.summary
                existing.post_type = post_type
                existing.source_bank_id = bank_id
                session.add(existing)
            else:
                session.add(
                    PlannedNote(
                        target_date=target_date,
                        note_text=bank_row.summary,
                        post_type=post_type,
                        created_at=datetime.now(timezone.utc),
                        source_bank_id=bank_id,
                    )
                )
            session.commit()
        self.status_message = f"Linked to {target_date} - see Posts > Plan ahead."
        self._reload_planned_notes()

    @rx.event(background=True)
    async def fill_week(self, monday: str):
        """Catch-up button: tops that week's committed (accepted/published) posts up to
        its target from the best unused topic bank rows. The target is WEEKLY_CAP when
        the week already has a personal post, else NO_PERSONAL_WEEKLY_CAP. Never makes
        up a personal post when the bank runs dry (hard rule, see planning.py) - it
        stops and says so instead."""
        async with self:
            self.is_busy = True
            self.status_message = f"Filling the week of {monday}..."

        with rx.session(url=config.db_url) as session:
            committed = session.exec(
                sqlmodel.select(sqlmodel.func.count())
                .select_from(Post)
                .where(Post.scheduled_week == monday)
            ).one()
            has_personal = session.exec(
                sqlmodel.select(sqlmodel.func.count())
                .select_from(Post)
                .where(Post.scheduled_week == monday, Post.post_type == "personal_reflection")
            ).one() > 0
            target = WEEKLY_CAP if has_personal else NO_PERSONAL_WEEKLY_CAP
            bank_rows = session.exec(
                sqlmodel.select(TopicBank)
                .where(
                    TopicBank.used == False,  # noqa: E712
                    TopicBank.tier != "discard",
                    sqlmodel.col(TopicBank.calendar_event_id).is_(None),
                )
                .order_by(sqlmodel.col(TopicBank.tier).asc(), sqlmodel.col(TopicBank.date_found).desc())
                .limit(target)
            ).all()
            bank_data = [(r.id, r.summary, r.source_title, r.source_url, r.category) for r in bank_rows]

        needed = max(0, target - committed)
        generated = 0
        failed = False
        for i in range(min(needed, len(bank_data))):
            try:
                _draft_from_bank_row(*bank_data[i])
                generated += 1
            except Exception:  # noqa: BLE001 - keep going, report what actually landed
                failed = True
                break

        if needed == 0:
            message = f"Week of {monday} already has {committed}/{target} posts committed."
        elif failed:
            message = f"Generated {generated} of {needed} needed for the week of {monday} before a failure - check Review."
        elif generated < needed:
            message = (
                f"Generated {generated} of {needed} for the week of {monday} - the topic bank ran out. "
                "Run research, or add a Personal update on Home for a personal post."
            )
        else:
            message = f"Generated {generated} draft(s) for the week of {monday} - check Review."

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_posts()
            self._reload_bank()
            self._reload_stats()

    @rx.event(background=True)
    async def plan_week(self, monday: str):
        """"Plan this week" (request: "a button to actually draft the post for the
        next week... it automatically just selects post for the week"). Unlike
        fill_week (which just tops up a raw count from the bank), this reads the
        weekly post-type template day by day - including "no post" - and, when
        recommend_holidays is on, swaps in a holiday angle on a day that lands on one
        (request: "sync with like holidays... Christmas post or Halloween post").
        Never touches a day that already has a note - "never overwrites a day you've
        already decided on"."""
        async with self:
            self.is_busy = True
            self.status_message = f"Planning the week of {monday}..."

        result = prepare_week(monday)
        message = f"Planned {result['planned']} post(s) for the week of {monday}"
        if result["personal"]:
            message += " (one personal post from your updates)"
        elif result["skipped_no_personal"]:
            message += (
                f". No personal post - nothing in Personal updates, so the week is kept to "
                f"{NO_PERSONAL_WEEKLY_CAP} posts"
            )
        if result["failed"]:
            message += f". {result['failed']} failed - check Review"
        message += "."

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_posts()
            self._reload_bank()
            self._reload_planned_notes()
            self._reload_stats()

    # ---- Home > Personal updates: milestones / news (+ photos) for personal posts ----

    def _reload_personal_updates(self):
        with rx.session(url=config.db_url) as session:
            waiting = unused_personal_updates(session)
            used = session.exec(
                sqlmodel.select(PersonalUpdate)
                .where(sqlmodel.col(PersonalUpdate.used_at).is_not(None))
                .order_by(sqlmodel.col(PersonalUpdate.used_at).desc())
                .limit(3)
            ).all()

        def view(u: PersonalUpdate) -> PersonalUpdateView:
            photos = json.loads(u.photos or "[]")
            return PersonalUpdateView(
                id=u.id,
                text=u.text,
                photo_names=[ph["name"] for ph in photos if ph.get("name")],
                photo_count=len(photos),
                added_label=f"Added {u.created_at.strftime('%d %b')}",
                used_label=f"Used in a draft on {u.used_at.strftime('%d %b')}" if u.used_at else "",
            )

        self.personal_updates = [view(u) for u in waiting]
        self.personal_updates_used = [view(u) for u in used]

    @rx.event
    def set_personal_text(self, value: str):
        self.personal_text = value

    @rx.event
    async def save_personal_update(self, files: list[rx.UploadFile]):
        """Saves the text and photos straight away; captioning the photos (a slower
        Gemini call) happens in the background afterwards. Upload handlers can't be
        background events themselves."""
        text = self.personal_text.strip()
        if not text and not files:
            self.status_message = "Write something or add a photo first."
            return
        names = []
        for file in files[:5]:
            name = f"personal-{uuid.uuid4().hex[:8]}-{pathlib.Path(file.name).name}"
            dest = rx.get_upload_dir() / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await file.read())
            names.append(name)
        with rx.session(url=config.db_url) as session:
            row = PersonalUpdate(
                text=text,
                photos=json.dumps([{"name": n, "path": "", "caption": ""} for n in names]),
                created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            update_id = row.id
        self.personal_text = ""
        self._reload_personal_updates()
        self.status_message = "Saved - the next planned personal post will be written from it."
        if names:
            return [rx.clear_selected_files("personal_upload"), DashboardState.caption_personal_photos(update_id)]
        return rx.clear_selected_files("personal_upload")

    @rx.event(background=True)
    async def caption_personal_photos(self, update_id: int):
        """Copies each photo to the persistent uploads folder (for the post image) and
        captions it, so the drafting call knows what's in the picture. A failed
        caption just leaves it blank - the photo is still used."""
        with rx.session(url=config.db_url) as session:
            row = session.get(PersonalUpdate, update_id)
            photos = json.loads(row.photos or "[]") if row else []
        for ph in photos:
            try:
                result = ingest_file(str(rx.get_upload_dir() / ph["name"]))
                ph["path"] = result.get("stored_path") or ""
                ph["caption"] = result.get("notes") or ""
            except Exception:  # noqa: BLE001
                ph["path"] = ph.get("path") or str(rx.get_upload_dir() / ph["name"])
        with rx.session(url=config.db_url) as session:
            row = session.get(PersonalUpdate, update_id)
            if row:
                row.photos = json.dumps(photos)
                session.add(row)
                session.commit()
        async with self:
            self._reload_personal_updates()

    @rx.event
    def delete_personal_update(self, update_id: int):
        with rx.session(url=config.db_url) as session:
            row = session.get(PersonalUpdate, update_id)
            if row and row.used_at is None:
                # A waiting update's photos aren't used anywhere else yet, so they go too.
                for ph in json.loads(row.photos or "[]"):
                    for path in (rx.get_upload_dir() / ph.get("name", ""), pathlib.Path(ph.get("path") or "")):
                        if path.name and path.is_file():
                            path.unlink(missing_ok=True)
                session.delete(row)
                session.commit()
        self._reload_personal_updates()

    # ---- quick actions: generate post now, run research now, forced-topic queue ----

    @rx.event
    def set_quick_topic(self, value: str):
        self.quick_topic = value

    @rx.event
    def set_quick_post_type(self, value: str):
        self.quick_post_type = value

    @rx.event(background=True)
    async def generate_post_now(self):
        async with self:
            topic = self.quick_topic.strip()
            if not topic:
                self.status_message = "Give it a topic first."
                return
            post_type = self.quick_post_type
            self.is_busy = True
            self.status_message = f"Researching and drafting: {topic}..."

        try:
            generate_and_save_draft(topic, post_type, skip_research=False)
            message = "Draft generated."
        except Exception as exc:  # noqa: BLE001
            message = f"Draft generation failed: {exc}"

        async with self:
            self.is_busy = False
            self.status_message = message
            self.quick_topic = ""
            self._reload_posts()
            self._reload_stats()

    @rx.event(background=True)
    async def run_research_now(self):
        async with self:
            self.is_busy = True
            self.status_message = "Running research cron now..."

        try:
            result = run_daily_research(force=True)
            tiers = result.get("stored_by_tier", {})
            message = (
                f"Research done - stored {tiers.get('high', 0)} high, "
                f"{tiers.get('mid', 0)} mid, {tiers.get('discard', 0)} discard "
                f"({result.get('duplicates_skipped', 0)} duplicates skipped, "
                f"{result.get('forced_topics_searched', 0)} forced topics searched)."
            )
        except Exception as exc:  # noqa: BLE001
            message = f"Research run failed: {exc}"

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_bank()
            self._reload_forced_topics()
            self._reload_job_status()

    @rx.event
    def set_new_forced_topic(self, value: str):
        self.new_forced_topic = value

    @rx.event
    def set_new_forced_topic_category(self, value: str):
        self.new_forced_topic_category = value

    @rx.event
    def add_forced_topic(self):
        topic = self.new_forced_topic.strip()
        if not topic:
            return
        with rx.session(url=config.db_url) as session:
            session.add(
                ForcedTopic(
                    topic=topic,
                    category=self.new_forced_topic_category,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        self.new_forced_topic = ""
        self._reload_forced_topics()
        self.status_message = f'"{topic}" queued for the next research run.'

    @rx.event
    def remove_forced_topic(self, topic_id: int):
        with rx.session(url=config.db_url) as session:
            row = session.get(ForcedTopic, topic_id)
            if row:
                session.delete(row)
                session.commit()
        self._reload_forced_topics()

    # ---- voice samples/profile (request: no dashboard flow existed for this at all -
    # the only way to add a real writing sample was a CLI script nobody had run since
    # the placeholder corpus was seeded, so every draft has been voice-matched against
    # 5 test samples, not James's actual writing) ----

    def _reload_voice(self):
        with rx.session(url=config.db_url) as session:
            samples = session.exec(
                sqlmodel.select(VoiceSample).order_by(sqlmodel.col(VoiceSample.date_added).desc())
            ).all()
            profile = session.exec(
                sqlmodel.select(VoiceProfile).order_by(sqlmodel.col(VoiceProfile.generated_at).desc())
            ).first()

        if profile is None:
            self.voice_profile_status = "no profile generated yet"
            zeta_words: list[str] = []
            bigrams: list[str] = []
            self.voice_zeta_words = []
            self.voice_characteristic_bigrams = []
            self.voice_syntax_summary = ""
        else:
            self.voice_profile_status = (
                f"generated {profile.generated_at.strftime('%d %b %Y')} from {len(samples)} current sample(s)"
            )
            profile_data = json.loads(profile.profile_json)
            zeta_words = profile_data.get("zeta_words", [])
            bigrams = profile_data.get("characteristic_bigrams", [])
            self.voice_zeta_words = zeta_words
            self.voice_characteristic_bigrams = bigrams
            syntax = profile_data.get("syntax", {})
            if syntax.get("status") == "ok":
                self.voice_syntax_summary = (
                    f"~{syntax['avg_nouns_per_post']:.0f} nouns, {syntax['avg_verbs_per_post']:.0f} verbs, "
                    f"{syntax['avg_adjectives_per_post']:.0f} adjectives per post on average - "
                    f"{syntax['pct_passive_sentences']:.0f}% of sentences are passive voice."
                )
            else:
                self.voice_syntax_summary = ""
        self.voice_health_rows = []
        self.voice_health_checked = False

        previously_expanded = {v.id for v in self.voice_samples if v.is_expanded}
        self.voice_samples = [
            VoiceSampleView(
                id=s.id,
                preview=(s.raw_text[:180] + "...") if len(s.raw_text) > 180 else s.raw_text,
                full_text=s.raw_text,
                source_type_label=humanize(s.source_type),
                date_added_str=s.date_added.strftime("%d %b %Y"),
                question_preview=s.question or "",
                contributing_zeta_words=_words_present_in(s.raw_text, zeta_words),
                contributing_bigrams=_bigrams_present_in(s.raw_text, bigrams),
                is_expanded=s.id in previously_expanded,
            )
            for s in samples
        ]
        counts: dict[str, int] = {}
        for s in samples:
            counts[s.source_type] = counts.get(s.source_type, 0) + 1
        self.voice_sample_counts = [
            SampleCountView(source_type_label=humanize(source_type), count=count)
            for source_type, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ]

    @rx.event
    def toggle_sample_expanded(self, sample_id: int):
        self.voice_samples = [
            v.model_copy(update={"is_expanded": not v.is_expanded}) if v.id == sample_id else v
            for v in self.voice_samples
        ]

    @rx.event
    def check_voice_corpus_health(self):
        """On-demand corpus-health check (request: "next upgrades" -> surface
        `validate_voice_metric`/register-aware Delta readiness on the dashboard
        instead of it only being checkable by running a script). Cheap enough to run
        live at this corpus size - not worth caching or running on every page load."""
        corpus = get_weighted_samples_by_register()
        counts: dict[str, int] = {}
        for _text, _weight, source_type in corpus:
            counts[source_type] = counts.get(source_type, 0) + 1
        validation = validate_voice_metric(corpus)
        rows = []
        for register, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            result = validation.get(register, {"status": "not enough data"})
            if result["status"] == "ok" and result.get("mean_held_out_delta") is not None:
                status_text = (
                    f"register-aware Delta is live and validated - {result['held_out_size']} held-out "
                    f"sample(s) scored {result['mean_held_out_delta']:.2f} avg against a "
                    f"{result['baseline_size']}-document baseline"
                )
            elif count >= 2:
                status_text = "register-aware Delta is live (not yet enough samples to validate against a holdout)"
            else:
                needed = result.get("needed", 7)
                status_text = f"pooled fallback only - needs {needed - count} more sample(s) to validate"
            rows.append(
                VoiceRegisterHealthView(
                    register_label=humanize(register),
                    sample_count=count,
                    is_primary_register=(register == TARGET_REGISTER),
                    status_text=status_text,
                )
            )
        self.voice_health_rows = rows
        self.voice_health_checked = True

    @rx.event
    def set_voice_new_sample_text(self, value: str):
        self.voice_new_sample_text = value

    @rx.event
    def add_voice_sample(self):
        text = self.voice_new_sample_text.strip()
        if not text:
            return
        add_sample(text, "linkedin_post")
        self.voice_new_sample_text = ""
        self._reload_voice()
        self.status_message = "Sample added. Regenerate the voice profile below to have it take effect."

    @rx.event
    def set_voice_qa_question(self, value: str):
        self.voice_qa_question = value

    @rx.event
    def set_voice_qa_answer(self, value: str):
        self.voice_qa_answer = value

    @rx.event
    def add_voice_qa_sample(self):
        answer = self.voice_qa_answer.strip()
        if not answer:
            return
        add_sample(answer, "gemini_qa", question=self.voice_qa_question)
        self.voice_qa_question = ""
        self.voice_qa_answer = ""
        self._reload_voice()
        self.status_message = "Sample added. Regenerate the voice profile below to have it take effect."

    @rx.event
    def set_voice_convo_text(self, value: str):
        self.voice_convo_text = value

    @rx.event
    def set_voice_convo_gemini_label(self, value: str):
        self.voice_convo_gemini_label = value

    @rx.event
    def set_voice_convo_me_label(self, value: str):
        self.voice_convo_me_label = value

    @rx.event
    def preview_voice_conversation(self):
        gemini_label = self.voice_convo_gemini_label.strip() or "Gemini"
        me_label = self.voice_convo_me_label.strip() or "Me"
        pairs = parse_labeled_conversation(self.voice_convo_text, gemini_label, me_label)
        self.voice_convo_preview = [
            VoiceConvoPairView(index=i, question=q or "(no question found before this answer)", answer=a)
            for i, (q, a) in enumerate(pairs)
        ]
        if not pairs:
            self.status_message = (
                "Couldn't find any turns labeled with those speaker names - check the "
                "labels above match what's in the pasted text."
            )

    @rx.event
    def discard_voice_convo_preview(self):
        self.voice_convo_preview = []

    @rx.event
    def confirm_voice_convo_samples(self):
        for pair in self.voice_convo_preview:
            question = "" if pair.question.startswith("(no question") else pair.question
            add_sample(pair.answer, "gemini_qa", question=question)
        count = len(self.voice_convo_preview)
        self.voice_convo_preview = []
        self.voice_convo_text = ""
        self._reload_voice()
        self.status_message = (
            f"Added {count} sample(s) from the conversation. Regenerate the voice "
            "profile below to have them take effect."
        )

    @rx.event
    def delete_voice_sample(self, sample_id: int):
        with rx.session(url=config.db_url) as session:
            row = session.get(VoiceSample, sample_id)
            if row:
                session.delete(row)
                session.commit()
        self._reload_voice()

    @rx.event(background=True)
    async def regenerate_voice_profile(self):
        async with self:
            self.is_busy = True
            self.status_message = "Regenerating voice profile..."
        try:
            build_and_save_profile()
            message = "Voice profile regenerated - new drafts will use it."
        except Exception as exc:  # noqa: BLE001
            message = f"Voice profile regeneration failed: {exc}"
        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_voice()

    # ---- upload box (spec Â§3b/Â§3d) ----

    @rx.event
    def set_upload_text(self, value: str):
        self.upload_text = value

    @rx.event
    def set_redraft_note(self, post_id: int, value: str):
        post = self._find_post(post_id)
        if post:
            post.redraft_note = value

    @rx.event
    def start_recording(self, target: str, post_id: int = 0):
        self.recording_target = target
        self.recording_post_id = post_id

    @rx.event
    def recording_started(self, result: str):
        """Callback from the browser's start(): anything but "ok" means no mic."""
        if result == "ok":
            return
        self.recording_target = ""
        self.status_message = _RECORDING_ERRORS.get(result, f"Couldn't start recording ({result}).")

    @rx.event(background=True)
    async def receive_recording(self, data_url: str):
        """Callback from the browser's stop(): a data URL of the recorded audio.
        Transcribed locally (faster-whisper), then appended to whichever box was
        recording - appended, not replaced, so dictation can add to typed text."""
        async with self:
            target, post_id = self.recording_target, self.recording_post_id
            self.recording_target = ""
            self.transcribing_target, self.transcribing_post_id = target, post_id

        text, error = "", ""
        if not data_url or "," not in data_url:
            error = "Nothing was recorded."
        else:
            header, encoded = data_url.split(",", 1)
            suffix = ".mp4" if "mp4" in header else ".ogg" if "ogg" in header else ".webm"
            path = pathlib.Path(tempfile.gettempdir()) / f"dictation-{uuid.uuid4().hex}{suffix}"
            try:
                path.write_bytes(base64.b64decode(encoded))
                text = transcribe_audio(str(path))
            except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
                error = f"Transcription failed: {exc}"
            finally:
                path.unlink(missing_ok=True)
            if not error and not text:
                error = "No speech was picked up - try again a little closer to the mic."

        async with self:
            self.transcribing_target = ""
            if error:
                self.status_message = error
                return
            if target == "weekly":
                self.upload_text = f"{self.upload_text.rstrip()} {text}".strip()
            elif target == "personal":
                self.personal_text = f"{self.personal_text.rstrip()} {text}".strip()
            elif target == "redraft":
                post = self._find_post(post_id)
                if post:
                    post.redraft_note = f"{post.redraft_note.rstrip()} {text}".strip()

    @rx.event
    def set_upload_post_type(self, value: str):
        self.upload_post_type = value

    @rx.event(background=True)
    async def submit_text_upload(self):
        async with self:
            if not self.upload_text.strip():
                self.status_message = "Nothing to submit - write a note first."
                return
            self.is_busy = True
            self.status_message = "Drafting from your note..."
            notes = ingest_text(self.upload_text)
            post_type = self.upload_post_type

        try:
            generate_and_save_draft(notes, post_type, skip_research=True)
            message = "Draft generated from your note."
        except Exception as exc:  # noqa: BLE001
            message = f"Draft generation failed: {exc}"

        async with self:
            self.is_busy = False
            self.status_message = message
            self.upload_text = ""
            self._reload_posts()
            self._reload_stats()

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """Upload handlers can't be @rx.event(background=True) - save the files here
        (quick), then hand off to a background event for the slow processing."""
        paths = []
        for file in files:
            dest = rx.get_upload_dir() / file.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = await file.read()
            dest.write_bytes(data)
            paths.append(str(dest))

        self.is_busy = True
        self.status_message = "Processing upload..."
        return DashboardState.process_uploaded_files(paths)

    @rx.event
    async def submit_weekly_input(self, files: list[rx.UploadFile]):
        """Single entry point for Home's merged "Draft this post" button (UI overhaul:
        one button that works whichever of the note/upload fields has content, instead
        of two separate flows with their own buttons). Text takes priority if both are
        somehow present - delegates to the existing text/file handlers rather than
        duplicating their logic."""
        if self.upload_text.strip():
            return DashboardState.submit_text_upload
        if files:
            return DashboardState.handle_upload(files)
        self.status_message = "Nothing to submit - write a note or drop a file first."

    @rx.event(background=True)
    async def process_uploaded_files(self, paths: list[str]):
        async with self:
            post_type = self.upload_post_type

        messages = []
        for path in paths:
            name = pathlib.Path(path).name
            try:
                result = ingest_file(path)
                generate_and_save_draft(
                    result["notes"], post_type, skip_research=True, source_photo=result.get("stored_path")
                )
                messages.append(f"{name}: draft generated.")
            except UnsupportedMediaError as exc:
                messages.append(f"{name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                messages.append(f"{name}: failed ({exc}).")

        async with self:
            self.is_busy = False
            self.status_message = " ".join(messages)
            self._reload_posts()
            self._reload_stats()
