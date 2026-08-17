"""Review: drafts waiting for a decision. Accept / Redraft / Reject."""

import reflex as rx
import reflex_local_auth

from wpa_content_engine.dashboard.components import page_shell, review_post_card
from wpa_content_engine.dashboard.state import DISPLAY_DAYS, DashboardState


def _day_section(day: str) -> rx.Component:
    posts = DashboardState.posts_by_day[day]
    return rx.cond(
        posts.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.heading(day, size="4"),
                rx.badge(posts.length(), variant="soft", color_scheme="bronze"),
                spacing="2",
                align="center",
            ),
            rx.vstack(rx.foreach(posts, review_post_card), spacing="4", width="100%"),
            spacing="3",
            width="100%",
            padding_bottom="1rem",
        ),
        rx.fragment(),
    )


@reflex_local_auth.require_login
def review_page() -> rx.Component:
    body = rx.cond(
        DashboardState.posts.length() > 0,
        rx.vstack(*[_day_section(day) for day in DISPLAY_DAYS], spacing="5", width="100%"),
        rx.text("Nothing waiting for review right now.", size="2", class_name="hud-muted"),
    )
    return page_shell(
        "/review",
        rx.vstack(rx.heading("Review", size="5"), body, spacing="4", width="100%"),
    )
