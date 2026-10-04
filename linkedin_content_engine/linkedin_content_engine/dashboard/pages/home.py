"""Home: stats overview + the weekly-input upload box (the two things worth seeing
first). Everything else lives on its own page (request: "don't want everything to be
on one big page")."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import (
    PRIMARY_CTA,
    SECONDARY_CTA,
    page_shell,
    stat_card,
    type_select,
)
from linkedin_content_engine.dashboard.recorder import record_button
from linkedin_content_engine.dashboard.state import POST_TYPES, DashboardState, PersonalUpdateView, OpinionPromptView


def _stats_panel() -> rx.Component:
    """Split into two visually distinct groups (design-reference.html §3), not one
    7-card row: pipeline counts as solid cards, the three derived metrics as a
    dashed/ghost row underneath so they read as "derived from the numbers above"
    rather than a fifth-through-seventh stat of equal weight."""
    s = DashboardState.stats
    return rx.vstack(
        rx.heading("Stats", size="4"),
        rx.text("This week's activity", size="1", class_name="hud-muted", margin_top="-0.5rem"),
        rx.grid(
            stat_card("Drafted", s["drafted"]),
            stat_card("Approved", s["approved"]),
            stat_card("Published", s["published"]),
            stat_card("Rejected", s["rejected"]),
            columns=rx.breakpoints(initial="2", sm="4"),
            spacing="3",
            width="100%",
        ),
        rx.grid(
            stat_card("Acceptance rate", s["acceptance_rate"], ghost=True),
            stat_card("Avg time to review", s["avg_time_to_review"], ghost=True),
            stat_card("Avg time to publish", s["avg_time_to_publish"], ghost=True),
            columns=rx.breakpoints(initial="1", sm="3"),
            spacing="3",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _upload_box() -> rx.Component:
    """One merged flow (design-reference.html §3): a single "Note or upload" section
    (labeled textarea, dropzone directly below it) and one "Draft this post" button
    that works whichever has content - DashboardState.submit_weekly_input branches on
    the backend rather than needing two separate buttons for two separate inputs."""
    return rx.vstack(
        rx.heading("Weekly input", size="5"),
        rx.text(
            "Text, photo, or audio - whatever's easiest. Video isn't supported.",
            size="2",
            class_name="hud-muted",
        ),
        rx.vstack(
            rx.text("Post type", size="1", weight="medium", class_name="hud-muted"),
            type_select(
                POST_TYPES,
                value=DashboardState.upload_post_type,
                on_change=DashboardState.set_upload_post_type,
                size="2",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        rx.vstack(
            rx.text("Note or upload", size="1", weight="medium", class_name="hud-muted"),
            rx.text_area(
                value=DashboardState.upload_text,
                on_change=DashboardState.set_upload_text,
                placeholder="Write a quick note, or press Record and say it...",
                width="100%",
                resize="vertical",
            ),
            record_button("weekly"),
            rx.upload(
                rx.vstack(
                    rx.icon("upload", size=24),
                    rx.text("Drop a photo or audio file, or click to browse"),
                ),
                id="weekly_upload",
                accept={
                    "image/png": [".png"],
                    "image/jpeg": [".jpg", ".jpeg"],
                    "image/webp": [".webp"],
                    "audio/wav": [".wav"],
                    "audio/mpeg": [".mp3"],
                    "audio/x-m4a": [".m4a"],
                },
                max_files=1,
                border="1px dashed var(--border-strong)",
                border_radius="var(--radius)",
                padding="1.5rem",
                width="100%",
            ),
            spacing="2",
            align="start",
            width="100%",
        ),
        rx.button(
            "Draft this post",
            on_click=DashboardState.submit_weekly_input(rx.upload_files(upload_id="weekly_upload")),
            loading=DashboardState.is_busy,
            **PRIMARY_CTA,
        ),
        spacing="3",
        width="100%",
    )


def _opinion_card(item: OpinionPromptView) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(item.angle_label != "", rx.badge(item.angle_label, variant="soft", color_scheme="bronze", size="1")),
                rx.spacer(),
                rx.button(
                    "Skip",
                    size="1",
                    variant="ghost",
                    color_scheme="gray",
                    on_click=DashboardState.skip_opinion(item.id),
                ),
                width="100%",
                align="center",
            ),
            rx.cond(
                item.url != "",
                rx.link(item.title, href=item.url, is_external=True, size="2", weight="medium"),
                rx.text(item.title, size="2", weight="medium"),
            ),
            rx.text(item.summary, size="2", class_name="hud-muted"),
            rx.text_area(
                value=DashboardState.opinion_answers[item.key],
                on_change=lambda v: DashboardState.set_opinion_answer(item.id, v),
                placeholder="What do you actually think? Agree, disagree, what it means for small businesses, what people are missing...",
                width="100%",
                min_height="90px",
                resize="vertical",
            ),
            rx.hstack(
                record_button("opinion", item.id),
                rx.button(
                    "Turn my take into a post",
                    on_click=DashboardState.submit_opinion(item.id),
                    loading=DashboardState.opinion_busy_id == item.id,
                    **PRIMARY_CTA,
                ),
                spacing="2",
                wrap="wrap",
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
    )


def _your_take_box() -> rx.Component:
    """A few research findings for your own opinion, refreshed every few days by the
    daily job (opinions.py). Each answer becomes an Opinion post in Review."""
    return rx.vstack(
        rx.hstack(
            rx.heading("Your take", size="5"),
            rx.spacer(),
            rx.button("Give me new topics", size="1", on_click=DashboardState.new_opinion_topics, **SECONDARY_CTA),
            width="100%",
            align="center",
        ),
        rx.text(
            "Every few days, a few of the strongest new stories land here. Say what you think - typed or "
            "recorded, as rough as you like - and it's written up as an Opinion post in your voice.",
            size="2",
            class_name="hud-muted",
        ),
        rx.cond(
            DashboardState.opinion_prompts.length() > 0,
            rx.vstack(rx.foreach(DashboardState.opinion_prompts, _opinion_card), spacing="2", width="100%"),
            rx.text("Nothing waiting - new topics arrive every few days, or press Give me new topics.", size="2", class_name="hud-muted"),
        ),
        spacing="3",
        width="100%",
    )


def _personal_update_card(item: PersonalUpdateView) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(item.added_label, size="1", class_name="hud-muted"),
                rx.cond(
                    item.used_label != "",
                    rx.badge(item.used_label, variant="soft", color_scheme="green", size="1"),
                    rx.badge("Waiting for the next personal post", variant="soft", color_scheme="bronze", size="1"),
                ),
                rx.spacer(),
                rx.cond(
                    item.used_label == "",
                    rx.icon(
                        "x",
                        size=14,
                        cursor="pointer",
                        on_click=DashboardState.delete_personal_update(item.id),
                    ),
                    rx.fragment(),
                ),
                width="100%",
                align="center",
                wrap="wrap",
            ),
            rx.cond(item.text != "", rx.text(item.text, size="2", white_space="pre-wrap"), rx.fragment()),
            rx.cond(
                item.photo_names.length() > 0,
                rx.hstack(
                    rx.foreach(
                        item.photo_names,
                        lambda n: rx.image(
                            src=rx.get_upload_url(n),
                            width="96px",
                            height="96px",
                            object_fit="cover",
                            border="1px solid var(--border)",
                            loading="lazy",
                        ),
                    ),
                    spacing="2",
                    wrap="wrap",
                ),
                rx.fragment(),
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
    )


def _personal_updates_box() -> rx.Component:
    """Milestones and news, with photos, saved for the next planned personal post -
    the only thing a planned personal post is ever written from (planning.py)."""
    return rx.vstack(
        rx.heading("Personal updates", size="5"),
        rx.text(
            "Milestones, wins, news, things that happened - in your own words, as much detail as you like. "
            "Next time the week is planned, one personal post is written from what's here (with a photo, "
            "if you add one), and these are marked used.",
            size="2",
            class_name="hud-muted",
        ),
        rx.text_area(
            value=DashboardState.personal_text,
            on_change=DashboardState.set_personal_text,
            placeholder="e.g. Finished my first module of the MSc - 72%, and the project I built for it...",
            width="100%",
            resize="vertical",
        ),
        record_button("personal"),
        rx.upload(
            rx.vstack(
                rx.icon("image", size=24),
                rx.text("Add photos (up to 5) - drop them here or click to browse"),
                rx.foreach(rx.selected_files("personal_upload"), lambda f: rx.text(f, size="1", class_name="hud-muted")),
            ),
            id="personal_upload",
            accept={
                "image/png": [".png"],
                "image/jpeg": [".jpg", ".jpeg"],
                "image/webp": [".webp"],
            },
            max_files=5,
            multiple=True,
            border="1px dashed var(--border-strong)",
            border_radius="var(--radius)",
            padding="1.5rem",
            width="100%",
        ),
        rx.button(
            "Save update",
            on_click=DashboardState.save_personal_update(rx.upload_files(upload_id="personal_upload")),
            **PRIMARY_CTA,
        ),
        rx.cond(
            DashboardState.personal_updates.length() > 0,
            rx.vstack(rx.foreach(DashboardState.personal_updates, _personal_update_card), spacing="2", width="100%"),
            rx.text(
                "Nothing saved yet - until there is, planning won't write a personal post.",
                size="2",
                class_name="hud-muted",
            ),
        ),
        rx.cond(
            DashboardState.personal_updates_used.length() > 0,
            rx.vstack(
                rx.text("Recently used", size="1", weight="medium", class_name="hud-muted"),
                rx.foreach(DashboardState.personal_updates_used, _personal_update_card),
                spacing="2",
                width="100%",
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
    )


def _prepare_week_box() -> rx.Component:
    """One click from nothing to a reviewable week: drafts every day the weekly plan
    asks for, with visuals, straight into Review."""
    return rx.vstack(
        rx.heading("Next week", size="5"),
        rx.text(
            "Drafts next week from your weekly plan, ready in Posts > Review, using the "
            "best research topics available - designs are made once you accept. The personal post is "
            "written from your Personal updates "
            "below - with none saved, no personal post is made up and the week is kept to 3 posts. "
            "Nothing goes out until you accept it and post it yourself.",
            size="2",
            class_name="hud-muted",
        ),
        rx.hstack(
            rx.button(
                "Prepare next week",
                on_click=DashboardState.prepare_next_week,
                loading=DashboardState.is_busy,
                **PRIMARY_CTA,
            ),
            rx.button(
                "Email me next week's posts",
                on_click=DashboardState.send_digest_now,
                loading=DashboardState.is_busy,
                **SECONDARY_CTA,
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="3",
        width="100%",
    )


@reflex_local_auth.require_login
def home_page() -> rx.Component:
    """The reference's Home mockup wraps everything - stats, weekly input - in one
    40px-padded "main content card" (design-reference.html, UI-OVERHAUL.md §1's
    `--pad-lg` token), not two separately-padded cards - request (audit finding, not
    a fresh ask): "--pad-lg... never actually applied anywhere.\""""
    return page_shell(
        "/",
        rx.card(
            rx.vstack(
                _stats_panel(),
                _prepare_week_box(),
                _your_take_box(),
                _personal_updates_box(),
                _upload_box(),
                spacing="0",
                gap="2.5rem",
                width="100%",
            ),
            padding="var(--pad-lg)",
            width="100%",
        ),
    )
