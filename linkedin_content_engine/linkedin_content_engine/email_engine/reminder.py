"""Weekly personal-story reminder email.

Fires from a daily Task Scheduler trigger (see scripts/register_email_tasks.ps1) but
only actually sends when today's weekday AND current local hour match what's set in
the dashboard's "Email reminders" card, and at most once a week - so both the day and
the time are fully changeable without ever touching Windows Task Scheduler again.
"""

import json
import random
from datetime import datetime, timedelta, timezone

import reflex as rx
import sqlmodel

from rxconfig import config
from linkedin_content_engine.email_engine.send import send_email
from linkedin_content_engine.email_engine.settings import get_email_settings
from linkedin_content_engine.models import EmailSettings, JobRun, Post
from linkedin_content_engine.scheduling import current_week_start

JOB_NAME = "weekly_reminder"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SUBJECT = "Your weekly personal story - Content Engine"

# request: "if something is already added into the personal section, I don't want
# that personal nudge to go out... rather than it being a nudge to do it, I want it
# to be a nudge to go [check it] quickly" - so a personal_reflection already sitting
# in the system this week changes the email instead of just suppressing it outright.
NUDGE_SUBJECT = "Your personal post is already in - Content Engine"
NUDGE_DRAFTED_BODY = """Hi,

Quick one - you've already sent something in for this week's personal post, it's just
sitting in Review waiting for a look. No need to send anything new.

When you get a moment, pop into the dashboard and check it over: {excerpt}

- The Content Engine
"""
NUDGE_APPROVED_BODY = """Hi,

Quick one - this week's personal post is already accepted and ready to go, just
waiting to be copied across to LinkedIn whenever suits you:

{excerpt}

- The Content Engine
"""

# Pool of prompt ideas offered as a nudge, not a requirement (request: "give a few
# recommendations of some things it could be about... switch them up each week").
# You're never told which one to use - these are just there to make "nothing comes to
# mind" less likely to be the reason a week goes by without a personal post.
PROMPT_POOL = [
    "An AI tool that changed how you did something this week",
    "Something that didn't go to plan, and what you took from it",
    "A small win worth a mention, even a quiet one",
    "Something from your degree that reframed how you think about a problem",
    "What you're actually building right now, and why",
    "Something outside work/study that's been on your mind",
    "A lesson someone passed on to you recently",
    "Something you're looking forward to",
    "A moment you were proud of a project or a team you're part of",
    "Something you've changed your mind about recently",
]
PROMPTS_PER_EMAIL = 3

BODY_TEMPLATE = """Hi,

Quick nudge - it's time for this week's personal post. Doesn't need to be big: a
quick thought, something that happened this week (or last week is fine too), a photo,
a voice note - whatever's easiest.

Stuck for an angle? A few ideas, if any of them land:
{prompts}
No pressure to use one of these - they're just there in case nothing else comes to
mind.

Open the dashboard and use the "Weekly input" box to send it in, however's quickest
for you. It'll turn into a draft automatically, ready for you to review.

- The Content Engine
"""


def _already_sent_this_week(now_utc: datetime) -> bool:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
    return row is not None and (now_utc - row.last_run_at) < timedelta(days=6)


def _mark_sent(now_utc: datetime) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(JobRun).where(JobRun.job_name == JOB_NAME)).first()
        if row:
            row.last_run_at = now_utc
            session.add(row)
        else:
            session.add(JobRun(job_name=JOB_NAME, last_run_at=now_utc))
        session.commit()


def _pick_prompts(last_shown: list[str]) -> list[str]:
    """Pick this week's prompt suggestions, excluding whatever was shown last time so
    nothing repeats two weeks running. Falls back to the full pool if too much of it
    got excluded (not reachable at the current pool size/PROMPTS_PER_EMAIL, but safe
    if the pool is ever trimmed later)."""
    available = [p for p in PROMPT_POOL if p not in last_shown]
    if len(available) < PROMPTS_PER_EMAIL:
        available = PROMPT_POOL
    return random.sample(available, min(PROMPTS_PER_EMAIL, len(available)))


def _save_shown_prompts(prompts: list[str]) -> None:
    with rx.session(url=config.db_url) as session:
        row = session.exec(sqlmodel.select(EmailSettings)).first()
        if row:
            row.last_reminder_prompts = json.dumps(prompts)
            session.add(row)
            session.commit()


def _existing_personal_post_this_week() -> Post | None:
    """A personal_reflection post already created this week, not counting rejected
    ones (a rejection means it didn't work out, so a fresh nudge is still wanted)."""
    with rx.session(url=config.db_url) as session:
        return session.exec(
            sqlmodel.select(Post)
            .where(
                Post.post_type == "personal_reflection",
                sqlmodel.col(Post.created_at) >= current_week_start(),
                Post.status != "rejected",
            )
            .order_by(sqlmodel.col(Post.created_at).desc())
        ).first()


def run_weekly_reminder(force: bool = False) -> dict:
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()  # the machine's local time - what "9am" means to you
    settings = get_email_settings()

    if not settings or not settings.reminder_enabled:
        return {"status": "skipped", "reason": "reminder disabled or no email settings configured"}

    today_name = WEEKDAYS[now_local.weekday()]
    target_hour = int(settings.reminder_time.split(":")[0])
    if not force and today_name != settings.reminder_day:
        return {"status": "skipped", "reason": f"today is {today_name}, reminder day is {settings.reminder_day}"}
    if not force and now_local.hour != target_hour:
        return {"status": "skipped", "reason": f"it's {now_local.hour}:00, reminder time is {settings.reminder_time}"}
    if not force and _already_sent_this_week(now_utc):
        return {"status": "skipped", "reason": "already sent this week"}

    existing = _existing_personal_post_this_week()
    if existing is not None:
        if existing.status == "published":
            # Already posted - genuinely nothing left to nudge about this week.
            _mark_sent(now_utc)
            return {"status": "skipped", "reason": "personal post already published this week"}
        excerpt = existing.draft_text[:150] + ("..." if len(existing.draft_text) > 150 else "")
        subject = NUDGE_SUBJECT
        body = (NUDGE_DRAFTED_BODY if existing.status == "drafted" else NUDGE_APPROVED_BODY).format(
            excerpt=excerpt
        )
    else:
        last_shown = json.loads(settings.last_reminder_prompts or "[]")
        prompts = _pick_prompts(last_shown)
        subject = SUBJECT
        body = BODY_TEMPLATE.format(prompts="\n".join(f"- {p}" for p in prompts))

    sent, message = send_email(settings.recipient_email, subject, body)
    if sent:
        _mark_sent(now_utc)
        if existing is None:
            _save_shown_prompts(prompts)
    return {"status": "ok" if sent else "failed", "reason": message}
