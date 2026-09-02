"""Home: stats overview + the weekly-input upload box (the two things worth seeing
first). Everything else lives on its own page (request: "don't want everything to be
on one big page")."""

import reflex as rx

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, page_shell, stat_card
from linkedin_content_engine.dashboard.state import POST_TYPES, DashboardState


def _stats_panel() -> rx.Component:
    s = DashboardState.stats
    return rx.card(
        rx.vstack(
            rx.heading("Stats", size="4"),
            rx.grid(
                stat_card("Drafted", s["drafted"]),
                stat_card("Approved", s["approved"]),
                stat_card("Published", s["published"]),
                stat_card("Rejected", s["rejected"]),
                stat_card("Acceptance rate", s["acceptance_rate"]),
                stat_card("Avg time to review", s["avg_time_to_review"]),
                stat_card("Avg time to publish", s["avg_time_to_publish"]),
                columns=rx.breakpoints(initial="2", sm="4"),
                spacing="3",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def _upload_box() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Weekly input", size="5"),
            rx.text(
                "Text, photo, or audio - whatever's easiest. Video isn't supported.",
                size="2",
                class_name="hud-muted",
            ),
            rx.select(
                POST_TYPES,
                value=DashboardState.upload_post_type,
                on_change=DashboardState.set_upload_post_type,
                size="2",
            ),
            rx.text_area(
                value=DashboardState.upload_text,
                on_change=DashboardState.set_upload_text,
                placeholder="Write a quick note...",
                width="100%",
                resize="vertical",
            ),
            rx.button(
                "Draft from note",
                on_click=DashboardState.submit_text_upload,
                loading=DashboardState.is_busy,
                **PRIMARY_CTA,
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
                border="1px dashed var(--gray-8)",
                padding="1.5rem",
                border_radius="8px",
            ),
            rx.button(
                "Upload & draft",
                on_click=DashboardState.handle_upload(rx.upload_files(upload_id="weekly_upload")),
                loading=DashboardState.is_busy,
                **PRIMARY_CTA,
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def home_page() -> rx.Component:
    return page_shell("/", _stats_panel(), _upload_box())
