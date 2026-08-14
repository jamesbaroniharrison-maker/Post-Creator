"""The main dashboard page (spec Â§3d, Â§7 level 7). Protected by reflex_local_auth."""

import reflex as rx
import reflex_local_auth

from wpa_content_engine.dashboard.components import review_queue_section, stats_panel, topic_bank_section, upload_box
from wpa_content_engine.dashboard.state import DashboardState


def _header() -> rx.Component:
    return rx.hstack(
        rx.heading("WPA Content Engine", size="6"),
        rx.spacer(),
        rx.color_mode.button(),
        rx.button(
            "Log out",
            on_click=reflex_local_auth.LoginState.do_logout,
            variant="soft",
            color_scheme="gray",
            size="2",
        ),
        width="100%",
        align="center",
        padding_bottom="1rem",
    )


@reflex_local_auth.require_login
def dashboard_page() -> rx.Component:
    return rx.container(
        _header(),
        rx.vstack(
            stats_panel(),
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
    )
