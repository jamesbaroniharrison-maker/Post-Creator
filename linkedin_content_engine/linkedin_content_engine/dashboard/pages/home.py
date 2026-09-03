"""Home: stats overview + the weekly-input upload box (the two things worth seeing
first). Everything else lives on its own page (request: "don't want everything to be
on one big page")."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, page_shell, stat_card, type_select
from linkedin_content_engine.dashboard.state import POST_TYPES, DashboardState


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
                placeholder="Write a quick note...",
                width="100%",
                resize="vertical",
            ),
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
                _upload_box(),
                spacing="0",
                gap="2.5rem",
                width="100%",
            ),
            padding="var(--pad-lg)",
            width="100%",
        ),
    )
