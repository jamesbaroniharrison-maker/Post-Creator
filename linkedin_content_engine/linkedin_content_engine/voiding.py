"""Void a post: remove it as if it never existed, keeping only a tally line (request:
"a void post option to get rid of it. I want this to wipe from stats. As if it never
existed. Just keep a tiny sub tally... Any that are tested and then deleted are
counted as void").

Voiding deletes the post row and its files, and undoes what drafting it used up, so
nothing it touched stays marked as spent:
- its topic bank finding goes back to unused (and an auto-made Plan ahead note for it
  is removed),
- Personal updates it was written from go back to waiting,
- a "Your take" it was drafted from is offered again, with your answer kept,
- its visual and ready-to-post folder are deleted (post ids can be reused by SQLite,
  so stale files would otherwise attach themselves to a future post).

Then one VoidedPost row is written - the only trace. kind="test" is for posts made
while testing and then removed, so they count in the same tally.
"""

import shutil
from datetime import datetime, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.models import OpinionPrompt, PersonalUpdate, PlannedNote, Post, TopicBank, VoidedPost


def void_post(post_id: int, kind: str = "voided") -> bool:
    """Returns True if a post was voided, False if it didn't exist."""
    from linkedin_content_engine.exports import EXPORTS_DIR
    from linkedin_content_engine.visuals_engine.attach import visuals_dir

    now = datetime.now(timezone.utc)
    with rx.session(url=config.db_url) as session:
        post = session.get(Post, post_id)
        if post is None:
            return False

        if post.source_bank_id:
            bank = session.get(TopicBank, post.source_bank_id)
            if bank is not None:
                bank.used = False
                bank.date_used = None
                session.add(bank)
            for note in session.exec(
                sqlmodel.select(PlannedNote).where(PlannedNote.source_bank_id == post.source_bank_id)
            ).all():
                session.delete(note)

        for update in session.exec(sqlmodel.select(PersonalUpdate).where(PersonalUpdate.used_post_id == post_id)).all():
            update.used_at = None
            update.used_post_id = None
            session.add(update)

        for prompt in session.exec(sqlmodel.select(OpinionPrompt).where(OpinionPrompt.post_id == post_id)).all():
            prompt.post_id = None
            prompt.answered_at = None
            session.add(prompt)

        session.add(VoidedPost(post_type=post.post_type, kind=kind, drafted_at=post.created_at, voided_at=now))
        session.delete(post)
        session.commit()

    shutil.rmtree(visuals_dir(post_id), ignore_errors=True)
    if EXPORTS_DIR.exists():
        for marker in EXPORTS_DIR.glob(f"*/*/.post-{post_id}"):
            shutil.rmtree(marker.parent, ignore_errors=True)
    return True


def voided_tally() -> dict[str, int]:
    """{"voided": n, "test": n, "total": n} for the Statistics page."""
    with rx.session(url=config.db_url) as session:
        rows = session.exec(sqlmodel.select(VoidedPost.kind)).all()
    voided = sum(1 for k in rows if k != "test")
    test = sum(1 for k in rows if k == "test")
    return {"voided": voided, "test": test, "total": voided + test}
