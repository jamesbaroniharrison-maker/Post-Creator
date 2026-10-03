"""Ready-to-post bundles: one folder per approved post, holding exactly what you paste
or upload into LinkedIn - the text (with hashtags) and the image(s) or carousel PDF -
named `baroni-[format]-[topic]-[yyyy-mm-dd]` so they sort and search sensibly.

    exports/2026-10-05/01 Monday - AI Commentary/
        post.txt
        baroni-statement-automate-the-task-2026-10-05.png
        baroni-how-it-works-one-task-2026-10-06-1.png ... + .pdf

Built on accept, after a visual is re-made, and fresh for the weekly digest - the
folder is always a copy of what's in the database, never the source of truth.
"""

import json
import pathlib
import re
import shutil
from datetime import date, datetime, timedelta

import reflex as rx

from rxconfig import config
from linkedin_content_engine.models import Post

EXPORTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "exports"
# The slot that best names what a visual is about, in order of preference.
_TOPIC_FIELDS = ["headline", "cover_headline", "project_name", "take", "quote", "question", "myth", "tool_name", "stat_desc"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def post_date(post: Post) -> date | None:
    """The day a scheduled post goes out: its week's Monday plus its suggested day."""
    if not post.scheduled_week:
        return None
    monday = datetime.strptime(post.scheduled_week, "%Y-%m-%d").date()
    day = (post.suggested_day or "").strip().title()
    return monday + timedelta(days=WEEKDAYS.index(day)) if day in WEEKDAYS else monday


def _slug(text: str, words: int = 5) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(tokens[:words]) or "post"


def bundle_name(post: Post) -> str:
    fmt = (post.visual_template or "text").replace("_", "-")
    topic = post.draft_text
    if post.visual_slots:
        try:
            slots = json.loads(post.visual_slots)
            topic = next((slots[k] for k in _TOPIC_FIELDS if isinstance(slots.get(k), str) and slots[k]), topic)
        except json.JSONDecodeError:
            pass
    when = post_date(post) or date.today()
    return f"baroni-{fmt}-{_slug(topic)}-{when.isoformat()}"


def post_text_with_hashtags(post: Post) -> str:
    try:
        tags = json.loads(post.hashtags or "[]")
    except json.JSONDecodeError:
        tags = []
    tag_line = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)
    return post.draft_text.strip() + (f"\n\n{tag_line}" if tag_line else "")


def build_bundle(post_id: int) -> dict | None:
    """Writes the post's folder and returns {"dir", "text", "pngs", "pdf", "date"} with
    the bundle's own (renamed) file paths. None if the post isn't scheduled yet."""
    with rx.session(url=config.db_url) as session:
        post = session.get(Post, post_id)
        if post is None or post.status not in ("approved", "published"):
            return None
        when = post_date(post)
        if when is None:
            return None
        week_dir = EXPORTS_DIR / post.scheduled_week
        folder_name = f"{when.weekday() + 1:02d} {WEEKDAYS[when.weekday()]} - {post.post_type.replace('_', ' ').title()}"
        # A post that moved day/type leaves its old folder behind - clear any folder
        # carrying this post's id marker before writing the new one.
        if EXPORTS_DIR.exists():
            for old in EXPORTS_DIR.glob(f"*/*/.post-{post_id}"):
                shutil.rmtree(old.parent, ignore_errors=True)
        out = week_dir / folder_name
        if out.exists():
            out = week_dir / f"{folder_name} ({post_id})"  # two posts on one day - keep both
        out.mkdir(parents=True, exist_ok=True)
        (out / f".post-{post_id}").write_text("", encoding="utf-8")

        name = bundle_name(post)
        text = post_text_with_hashtags(post)
        (out / "post.txt").write_text(text, encoding="utf-8")

        try:
            src_pngs = [p for p in json.loads(post.visual_files or "[]") if pathlib.Path(p).exists()]
        except json.JSONDecodeError:
            src_pngs = []
        pngs = []
        for i, src in enumerate(src_pngs, start=1):
            dest = out / (f"{name}-{i}.png" if len(src_pngs) > 1 else f"{name}.png")
            shutil.copyfile(src, dest)
            pngs.append(str(dest))
        pdf = ""
        if post.visual_pdf and pathlib.Path(post.visual_pdf).exists():
            pdf = str(out / f"{name}.pdf")
            shutil.copyfile(post.visual_pdf, pdf)
        return {"dir": str(out), "text": text, "pngs": pngs, "pdf": pdf, "date": when}
