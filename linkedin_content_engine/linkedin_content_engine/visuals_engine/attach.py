"""Makes (or re-makes) the brand visual for a saved post and records it on the row."""

import json
import random
import pathlib

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import Post, TopicBank
from linkedin_content_engine.visuals_engine.fill import make_visual
from linkedin_content_engine.visuals_engine.spec import is_dark


DARK_SHARE = 1 / 3  # request: dark visuals "1 in 3, rough average"


def pick_dark(recent_templates: list[str]) -> bool:
    """About 1 in 3 visuals dark. Random, but never two dark in a row and never more
    than three light in a row, so it stays near the average even over a short run."""
    flags = [is_dark(t) for t in recent_templates]  # newest first
    if flags[:1] == [True]:
        return False
    if len(flags) >= 3 and not any(flags[:3]):
        return True
    return random.random() < DARK_SHARE


def visuals_dir(post_id: int) -> pathlib.Path:
    return (pathlib.Path(rx.get_upload_dir()) / "visuals" / f"post-{post_id}").resolve()


def make_visual_for_post(post_id: int, template_key: str | None = None, force: bool = False) -> Post | None:
    """Fill + render the post's visual and save the result on the row.

    Automatic calls (force=False) skip text-only posts - the rotation decided those
    shouldn't carry an image. The dashboard's "Make a visual" passes force=True. A
    failure is recorded in visual_note, never raised: a visual must never cost you
    the draft it belongs to.
    """
    with rx.session(url=config.db_url) as session:
        post = session.get(Post, post_id)
        if post is None:
            return None
        has_photo = bool(post.source_photo) and pathlib.Path(post.source_photo).exists()
        if not force and not template_key and not has_photo and (post.media_pairing or "text_only") == "text_only":
            return post
        source_text = ""
        if post.source_bank_id:
            bank = session.get(TopicBank, post.source_bank_id)
            if bank:
                source_text = f"{bank.source_title}\n{bank.summary}"
        post_text, media_pairing, photo = post.draft_text, post.media_pairing, post.source_photo or ""
        funnel_stage = post.funnel_stage
        if has_photo:
            media_pairing = "candid_photo"  # your own photo beats whatever the rotation picked
        # Templates on the last 3 posts that had a visual - rotated out so the feed
        # doesn't show the same layout twice in a row.
        recent_list = list(session.exec(
            sqlmodel.select(Post.visual_template)
            .where(Post.id != post_id, Post.visual_template != None)  # noqa: E711
            .order_by(sqlmodel.col(Post.created_at).desc())
            .limit(3)
        ).all())
        recent = set(recent_list)
        dark = pick_dark(recent_list)

    try:
        result = make_visual(post_text, source_text, media_pairing, visuals_dir(post_id), photo=photo,
                             template_key=template_key, recent_templates=recent, dark=dark,
                             funnel_stage=funnel_stage)
        fields = {
            "visual_template": result["template"],
            "visual_slots": json.dumps(result["slots"]),
            "visual_files": json.dumps(result["pngs"]),
            "visual_pdf": result["pdf"] or None,
            "visual_note": result["note"] or None,
        }
    except Exception as exc:  # noqa: BLE001 - recorded, not raised (VisualError or a render failure)
        fields = {"visual_note": f"Couldn't make a visual: {exc}"[:500]}

    with rx.session(url=config.db_url) as session:
        post = session.get(Post, post_id)
        for k, v in fields.items():
            setattr(post, k, v)
        session.add(post)
        session.commit()
        session.refresh(post)
        return post


def rerender_from_slots(post_id: int, slots: dict) -> Post | None:
    """Re-render with hand-edited slide text (no LLM call) - for when you just want to
    change a word on the image."""
    from linkedin_content_engine.visuals_engine.fill import check_slots
    from linkedin_content_engine.visuals_engine.render import render
    from linkedin_content_engine.visuals_engine.spec import CATALOG

    with rx.session(url=config.db_url) as session:
        post = session.get(Post, post_id)
        if post is None or not post.visual_template:
            return None
        key, photo = post.visual_template, post.source_photo or ""
    spec = CATALOG[key]
    problems = [p for p in check_slots(key, slots, "") if "numbers are not in" not in p]  # your own edit - numbers are your call
    out_dir = visuals_dir(post_id)
    if problems:
        fields = {"visual_note": "Not re-made: " + "; ".join(problems)}
    else:
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)
        res = render(key, slots, out_dir, photo=photo if spec.needs_photo else "", height=spec.height)
        fields = {
            "visual_slots": json.dumps(slots),
            "visual_files": json.dumps(res["pngs"]),
            "visual_pdf": res["pdf"] or None,
            "visual_note": "Some text may not fit on the image." if res["overflow"] else None,
        }
    with rx.session(url=config.db_url) as session:
        post = session.get(Post, post_id)
        for k, v in fields.items():
            setattr(post, k, v)
        session.add(post)
        session.commit()
        session.refresh(post)
        return post


def visual_pngs(post: Post) -> list[str]:
    try:
        return [p for p in json.loads(post.visual_files or "[]") if pathlib.Path(p).exists()]
    except json.JSONDecodeError:
        return []


