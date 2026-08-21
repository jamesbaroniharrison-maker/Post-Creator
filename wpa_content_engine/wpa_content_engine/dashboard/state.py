"""Dashboard state: review queue, editable chips, topic bank actions, uploads, stats.

Implements spec Â§3d and the level 7 done-when check: a full weekly cycle (bank
populates, shortlist forms, drafts generate, she reviews and approves or rejects,
stats update) has to run end to end without touching code.
"""

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pydantic
import reflex as rx
import sqlmodel

from rxconfig import config
from wpa_content_engine.capture.ingest import UnsupportedMediaError, ingest_file, ingest_text
from wpa_content_engine.drafting_engine.pipeline import (
    generate_and_save_draft,
    generate_draft_with_research,
)
from wpa_content_engine.drafting_engine.research import ResearchFinding, ResearchResult
from wpa_content_engine.email_engine.settings import get_email_settings, save_email_settings
from wpa_content_engine.models import ForcedTopic, PlannedNote, Post, TopicBank
from wpa_content_engine.research_cron.pipeline import run_daily_research
from wpa_content_engine.scheduling import (
    allocate_accepted_posts,
    current_week_label,
    prune_rejected_posts,
    upcoming_week_mondays,
    week_dates,
)

REJECTION_REASONS = ["not relevant", "wrong tone", "already covered"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DISPLAY_DAYS = [*WEEKDAYS, "Unscheduled"]
POST_TYPES = ["industry_insight", "company_update", "personal_reflection"]
TOPIC_CATEGORIES = ["industry", "company"]
CATEGORY_TO_POST_TYPE = {"industry": "industry_insight", "company": "company_update"}
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


class PlannedNoteView(pydantic.BaseModel):
    id: int
    target_date: str
    note_text: str
    post_type: str = "personal_reflection"
    post_type_label: str = ""


class DayPlanView(pydantic.BaseModel):
    """One day cell in the 4-week planning calendar: the date, a friendly label,
    whether it's today, and the note attached to it (if any)."""

    date: str
    day_label: str  # "Mon 31 Aug"
    is_today: bool
    note: PlannedNoteView | None = None


def _week_label(dt: datetime) -> str:
    monday = dt - timedelta(days=dt.weekday())
    return f"Week of {monday.strftime('%d %b %Y')}"


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
    )


class DashboardState(rx.State):
    posts: list[PostView] = []  # review queue: status == "drafted" only
    accepted_posts: list[PostView] = []  # approved + published
    rejected_posts: list[PostView] = []  # last 5 only, per scheduling.REJECTED_KEEP
    bank_rows: list[BankView] = []
    forced_topics: list[ForcedTopicView] = []
    history_posts: list[PostView] = []
    stats: dict[str, str] = {}

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
    quick_post_type: str = "industry_insight"
    new_forced_topic: str = ""
    new_forced_topic_category: str = "industry"

    upload_text: str = ""
    upload_post_type: str = "personal_reflection"
    status_message: str = ""
    is_busy: bool = False

    # Email settings - both jobs fully independent on day AND time
    email_recipient: str = ""
    email_reminder_day: str = "Friday"
    email_reminder_time: str = "09:00"
    email_digest_day: str = "Sunday"
    email_digest_time: str = "12:00"

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
            self._reload_planned_notes()
            self._reload_stats()
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
        self.selected_week_offset = offset
        self._reload_planned_notes()

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
        dates = week_dates(self.selected_week_monday)
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
        # Pre-seed the draft-input dicts for every date in the visible week, so the
        # frontend never indexes a missing dict key for a day with no note yet.
        self.note_drafts = {**{d: "" for d in dates}, **self.note_drafts}
        self.note_draft_post_types = {
            **{d: "personal_reflection" for d in dates},
            **self.note_draft_post_types,
        }

    @rx.var
    def week_plan(self) -> list[DayPlanView]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        by_date = {n.target_date: n for n in self.planned_notes}
        days = []
        for d in week_dates(self.selected_week_monday):
            dt = datetime.strptime(d, "%Y-%m-%d")
            days.append(
                DayPlanView(
                    date=d,
                    day_label=dt.strftime("%a %d %b"),
                    is_today=d == today,
                    note=by_date.get(d),
                )
            )
        return days

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
        """Everything from the last few weeks, regardless of status - lets her look
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
            (p.reviewed_at - p.created_at).total_seconds() / 3600
            for p in all_posts
            if p.reviewed_at is not None
        ]
        publish_times = [
            (p.published_at - p.reviewed_at).total_seconds() / 3600
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

        research = ResearchResult(
            topic=summary,
            status="ok",
            findings=[ResearchFinding(title=source_title, url=source_url, content=summary)],
        )
        post_type = CATEGORY_TO_POST_TYPE.get(category, "industry_insight")

        try:
            generate_draft_with_research(summary, post_type, research, source_bank_id=bank_id)
            with rx.session(url=config.db_url) as session:
                row = session.get(TopicBank, bank_id)
                row.used = True
                row.date_used = datetime.now(timezone.utc)
                session.add(row)
                session.commit()
            message = "Draft generated from topic bank."
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI, don't crash the app
            message = f"Draft generation failed: {exc}"

        async with self:
            self.is_busy = False
            self.status_message = message
            self._reload_posts()
            self._reload_bank()
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
