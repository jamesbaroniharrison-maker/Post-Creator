"""Dashboard state: review queue, editable chips, topic bank actions, uploads, stats.

Implements spec Â§3d and the level 7 done-when check: a full weekly cycle (bank
populates, shortlist forms, drafts generate, you review and approve or reject,
stats update) has to run end to end without touching code.
"""

import json
import pathlib
import random
from datetime import date, datetime, timedelta, timezone

import pydantic
import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.capture.ingest import UnsupportedMediaError, ingest_file, ingest_text
from linkedin_content_engine.drafting_engine.pipeline import (
    generate_and_save_draft,
    generate_draft_with_research,
)
from linkedin_content_engine.drafting_engine.research import ResearchFinding, ResearchResult
from linkedin_content_engine.email_engine.reminder import PROMPT_POOL
from linkedin_content_engine.email_engine.settings import get_email_settings, save_email_settings
from linkedin_content_engine.holidays import holiday_for_date
from linkedin_content_engine.models import (
    ForcedTopic,
    JobRun,
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
from linkedin_content_engine.voice_engine.ingestion import add_sample, parse_labeled_conversation
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


def humanize(value: str) -> str:
    """'personal_reflection' -> 'Personal Reflection' - display only, never touches
    the stored value (request: raw snake_case showing up in the UI looked wrong)."""
    return value.replace("_", " ").title() if value else value


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


class BankView(pydantic.BaseModel):
    id: int
    summary: str
    source_title: str
    source_url: str
    tier: str
    tier_label: str = ""
    category: str
    category_label: str = ""


class ForcedTopicView(pydantic.BaseModel):
    id: int
    topic: str
    category: str
    category_label: str = ""


class VoiceSampleView(pydantic.BaseModel):
    id: int
    preview: str
    source_type_label: str = ""
    date_added_str: str = ""
    question_preview: str = ""


class VoiceConvoPairView(pydantic.BaseModel):
    """One parsed (question, answer) turn from a pasted Gemini conversation, shown
    for review before any of it is actually saved as a VoiceSample."""

    index: int
    question: str
    answer: str


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
    )


def _draft_from_bank_row(bank_id: int, summary: str, source_title: str, source_url: str, category: str) -> None:
    """Shared by generate_from_bank and fill_week - drafts from one topic bank row and
    marks it used. Raises on failure so callers can decide how to report it, rather
    than swallowing the error here."""
    research = ResearchResult(
        topic=summary,
        status="ok",
        findings=[ResearchFinding(title=source_title, url=source_url, content=summary)],
    )
    post_type = CATEGORY_TO_POST_TYPE.get(category, "ai_commentary")
    generate_draft_with_research(summary, post_type, research, source_bank_id=bank_id)
    with rx.session(url=config.db_url) as session:
        row = session.get(TopicBank, bank_id)
        row.used = True
        row.date_used = datetime.now(timezone.utc)
        session.add(row)
        session.commit()


class DashboardState(rx.State):
    posts: list[PostView] = []  # review queue: status == "drafted" only
    accepted_posts: list[PostView] = []  # approved + published
    rejected_posts: list[PostView] = []  # last 5 only, per scheduling.REJECTED_KEEP
    bank_rows: list[BankView] = []
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
    upload_post_type: str = "personal_reflection"
    status_message: str = ""
    is_busy: bool = False

    # Voice page - the only way real writing samples get into voice_samples was a
    # CLI script; there was no dashboard flow for it at all, so the profile driving
    # every single draft has been running on 5 placeholder samples since 2 Sept 2026
    # with no way for James to replace them short of editing the database directly.
    voice_samples: list[VoiceSampleView] = []
    voice_new_sample_text: str = ""
    voice_profile_status: str = "no profile generated yet"

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

    # Topic Bank -> day linking (request: "click on them and even drag them or select
    # a day that I want them to be linked to" - literal cross-page drag-and-drop isn't
    # practical to build reliably in Reflex, so this is a pick-a-date-then-click flow
    # instead: one shared target date, a "Link to day" button per bank row).
    link_target_date: str = ""

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
            self._reload_stats()
            self._reload_job_status()
            self._reload_voice()
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
        self.posts = [_row_to_view(p) for p in rows]

    def _reload_accepted(self):
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(Post)
                .where(sqlmodel.col(Post.status).in_(["approved", "published"]))
                .order_by(sqlmodel.col(Post.scheduled_week).asc(), sqlmodel.col(Post.created_at).asc())
            ).all()
        self.accepted_posts = [_row_to_view(p) for p in rows]

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
        self.note_draft_post_types = {
            **{d: "personal_reflection" for d in dates},
            **self.note_draft_post_types,
        }

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
                days.append(
                    DayPlanView(
                        date=d,
                        day_label=dt.strftime("%a %d %b"),
                        is_today=d == today,
                        note=by_date.get(d),
                        holiday_name=holiday[0] if holiday else "",
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
            rows = session.exec(
                sqlmodel.select(TopicBank)
                .where(TopicBank.used == False, TopicBank.tier != "discard")  # noqa: E712
                .order_by(sqlmodel.col(TopicBank.tier).asc(), sqlmodel.col(TopicBank.date_found).desc())
                .limit(20)
            ).all()
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
            )
            for r in rows
        ]

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
    def save_weekly_template(self):
        with rx.session(url=config.db_url) as session:
            row = session.exec(sqlmodel.select(WeeklyTemplate)).first()
            if row is None:
                row = WeeklyTemplate()
            for day in _WEEKDAY_FIELDS:
                setattr(row, day, getattr(self, f"wt_{day}"))
            row.recommend_holidays = self.wt_recommend_holidays
            session.add(row)
            session.commit()
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

        with rx.session(url=config.db_url) as session:
            old = session.get(Post, post_id)
            if old is None:
                async with self:
                    self.is_busy = False
                    self.status_message = "That post no longer exists."
                return
            topic, post_type, sources_json = old.draft_text, old.post_type, old.sources

        try:
            findings = [ResearchFinding(**s) for s in json.loads(sources_json or "[]")]
            research = ResearchResult(topic=topic, status="ok" if findings else "no_results", findings=findings)
            generate_draft_with_research(topic[:200], post_type, research)
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
        self.status_message = f"Linked to {target_date} - see Plan ahead on the Accepted page."
        self._reload_planned_notes()

    @rx.event(background=True)
    async def fill_week(self, monday: str):
        """Catch-up button (request: "a draft this week's post button if for whatever
        time they haven't come up... have a button per week") - tops that week's
        committed (accepted/published) post count up to the weekly cap, pulling from
        the best unused topic bank rows first and falling back to a rotating personal-
        reflection prompt (same pool the email reminder uses) if the bank is empty, so
        the button never just does nothing."""
        async with self:
            self.is_busy = True
            self.status_message = f"Filling the week of {monday}..."

        with rx.session(url=config.db_url) as session:
            committed = session.exec(
                sqlmodel.select(sqlmodel.func.count())
                .select_from(Post)
                .where(Post.scheduled_week == monday)
            ).one()
            bank_rows = session.exec(
                sqlmodel.select(TopicBank)
                .where(TopicBank.used == False, TopicBank.tier != "discard")  # noqa: E712
                .order_by(sqlmodel.col(TopicBank.tier).asc(), sqlmodel.col(TopicBank.date_found).desc())
                .limit(WEEKLY_CAP)
            ).all()
            bank_data = [(r.id, r.summary, r.source_title, r.source_url, r.category) for r in bank_rows]

        needed = max(0, WEEKLY_CAP - committed)
        generated = 0
        failed = False
        for i in range(needed):
            try:
                if i < len(bank_data):
                    _draft_from_bank_row(*bank_data[i])
                else:
                    generate_and_save_draft(
                        random.choice(PROMPT_POOL), "personal_reflection", skip_research=True
                    )
                generated += 1
            except Exception:  # noqa: BLE001 - keep going, report what actually landed
                failed = True
                break

        if needed == 0:
            message = f"Week of {monday} already has {committed}/{WEEKLY_CAP} posts committed."
        elif failed:
            message = f"Generated {generated} of {needed} needed for the week of {monday} before a failure - check Review."
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

        with rx.session(url=config.db_url) as session:
            template = session.exec(sqlmodel.select(WeeklyTemplate)).first()
            if template is None:
                template = WeeklyTemplate()
            already_noted = {
                n.target_date
                for n in session.exec(
                    sqlmodel.select(PlannedNote).where(
                        sqlmodel.col(PlannedNote.target_date).in_(week_dates(monday))
                    )
                ).all()
            }

        planned = 0
        skipped_no_post = 0
        failed = 0
        for d in week_dates(monday):
            if d in already_noted:
                continue
            weekday_field = date.fromisoformat(d).strftime("%A").lower()
            post_type = getattr(template, weekday_field)
            holiday = holiday_for_date(d) if template.recommend_holidays else None
            note_text = ""
            if holiday:
                note_text = f"{holiday[0]}: {holiday[1]}"
                if post_type == "no_post":
                    post_type = "personal_reflection"
            if post_type == "no_post":
                skipped_no_post += 1
                continue

            with rx.session(url=config.db_url) as session:
                note = PlannedNote(
                    target_date=d,
                    note_text=note_text or f"Auto-planned {humanize(post_type)} post.",
                    post_type=post_type,
                    created_at=datetime.now(timezone.utc),
                )
                bank_row = None
                if post_type != "personal_reflection":
                    category = "ai" if post_type == "ai_commentary" else "market"
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
                session.refresh(note)
                bank_data = (
                    (bank_row.id, bank_row.summary, bank_row.source_title, bank_row.source_url, bank_row.category)
                    if bank_row
                    else None
                )

            try:
                if post_type == "personal_reflection":
                    generate_and_save_draft(note_text or random.choice(PROMPT_POOL), post_type, skip_research=True)
                elif bank_data:
                    _draft_from_bank_row(*bank_data)
                else:
                    generate_and_save_draft(
                        note_text or f"Something notable in {category} recently", post_type, skip_research=False
                    )
                planned += 1
            except Exception:  # noqa: BLE001 - keep going through the rest of the week
                failed += 1

        message = f"Planned {planned} day(s) for the week of {monday}"
        if skipped_no_post:
            message += f", {skipped_no_post} left as no-post"
        if failed:
            message += f", {failed} failed - check Review"
        message += "."

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_posts()
            self._reload_bank()
            self._reload_planned_notes()
            self._reload_stats()

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
        self.voice_samples = [
            VoiceSampleView(
                id=s.id,
                preview=(s.raw_text[:180] + "...") if len(s.raw_text) > 180 else s.raw_text,
                source_type_label=humanize(s.source_type),
                date_added_str=s.date_added.strftime("%d %b %Y"),
                question_preview=s.question or "",
            )
            for s in samples
        ]
        if profile is None:
            self.voice_profile_status = "no profile generated yet"
        else:
            self.voice_profile_status = (
                f"generated {profile.generated_at.strftime('%d %b %Y')} from "
                f"{len(self.voice_samples)} current sample(s)"
            )

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
                generate_and_save_draft(result["notes"], post_type, skip_research=True)
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
