"""The main dashboard page (spec Â§3d, Â§7 level 7). Protected by reflex_local_auth."""

import reflex as rx
import reflex_local_auth

from wpa_content_engine.dashboard.components import (
    quick_actions_section,
    review_queue_section,
    stats_panel,
    topic_bank_section,
    upload_box,
)
from wpa_content_engine.dashboard.state import DashboardState


def _header() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading("WPA Content Engine", size="6"),
            rx.text("Review queue, research, and voice-matched drafting", size="2", class_name="hud-muted"),
            spacing="0",
        ),
        rx.spacer(),
        rx.button(
            "Log out",
            on_click=reflex_local_auth.LoginState.do_logout,
            variant="soft",
            color_scheme="gray",
            size="2",
        ),
        width="100%",
        align="center",
        padding_bottom="1.5rem",
        border_bottom="1px solid var(--border)",
        margin_bottom="1.5rem",
    )


@reflex_local_auth.require_login
def dashboard_page() -> rx.Component:
    return rx.box(
        rx.container(
            _header(),
            rx.vstack(
                stats_panel(),
                quick_actions_section(),
                upload_box(),
                review_queue_section(),
                topic_bank_section(),
                spacing="6",
                width="100%",
                padding_bottom="3rem",
            ),
            on_mount=DashboardState.load_dashboard,
            size="4",
            padding="1.5rem",
        ),
        min_height="100vh",
        background="var(--bg)",
    )
