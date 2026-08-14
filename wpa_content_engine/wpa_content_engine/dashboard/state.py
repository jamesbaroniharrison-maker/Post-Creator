"""Dashboard state: review queue, editable chips, topic bank actions, uploads, stats.

Implements spec Â§3d and the level 7 done-when check: a full weekly cycle (bank
populates, shortlist forms, drafts generate, she reviews and approves or rejects,
stats update) has to run end to end without touching code.
"""

import json
import pathlib
from datetime import datetime, timezone

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
from wpa_content_engine.models import Post, TopicBank

REJECTION_REASONS = ["not relevant", "wrong tone", "already covered"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DISPLAY_DAYS = [*WEEKDAYS, "Unscheduled"]
POST_TYPES = ["industry_insight", "company_update", "personal_reflection"]
CATEGORY_TO_POST_TYPE = {"industry": "industry_insight", "company": "company_update"}
ACTIVE_STATUSES = ["drafted", "approved", "published"]


class PostView(pydantic.BaseModel):
    id: int
    post_type: str
    status: str
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


class BankView(pydantic.BaseModel):
    id: int
    summary: str
    source_title: str
    source_url: str
    tier: str
    category: str


def _row_to_view(p: Post) -> PostView:
    return PostView(
        id=p.id,
        post_type=p.post_type,
        status=p.status,
        draft_text=p.draft_text,
        hashtags=json.loads(p.hashtags or "[]"),
        tags=json.loads(p.tags or "[]"),
        suggested_day=p.suggested_day or "",
        sources=json.loads(p.sources or "[]"),
        compliance_note=p.compliance_note or "",
        rejection_reason=p.rejection_reason or "",
        likes_input=str(p.likes) if p.likes is not None else "",
        comments_input=str(p.comments) if p.comments is not None else "",
    )


class DashboardState(rx.State):
    posts: list[PostView] = []
    bank_rows: list[BankView] = []
    stats: dict[str, str] = {}

    upload_text: str = ""
    upload_post_type: str = "personal_reflection"
    status_message: str = ""
    is_busy: bool = False

    # ---- loading ----

    @rx.event
    def load_dashboard(self):
        self._reload_posts()
        self._reload_bank()
        self._reload_stats()

    def _reload_posts(self):
        with rx.session(url=config.db_url) as session:
            rows = session.exec(
                sqlmodel.select(Post)
                .where(sqlmodel.col(Post.status).in_(ACTIVE_STATUSES))
                .order_by(sqlmodel.col(Post.created_at).desc())
            ).all()
        self.posts = [_row_to_view(p) for p in rows]

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
                category=r.category,
            )
            for r in rows
        ]

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
        for p in self.posts:
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

    # ---- review actions (spec Â§3d: approve/reject/publish, one-tap rejection chips) ----

    @rx.event
    def approve(self, post_id: int):
        now = datetime.now(timezone.utc)
        self._persist(post_id, status="approved", reviewed_at=now)
        self._reload_posts()
        self._reload_stats()

    @rx.event
    def reject(self, post_id: int, reason: str):
        now = datetime.now(timezone.utc)
        self._persist(post_id, status="rejected", reviewed_at=now, rejection_reason=reason)
        self._reload_posts()
        self._reload_stats()

    @rx.event
    def mark_published(self, post_id: int):
        now = datetime.now(timezone.utc)
        self._persist(post_id, status="published", published_at=now)
        self._reload_posts()
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
