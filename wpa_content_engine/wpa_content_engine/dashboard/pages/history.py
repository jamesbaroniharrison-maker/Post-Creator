"""Past weeks: everything from the last 6 weeks, any status - browse back and reuse
something as a fresh draft for a thin week."""

import reflex as rx
import reflex_local_auth

from wpa_content_engine.dashboard.components import SECONDARY_CTA, page_shell, status_pill
from wpa_content_engine.dashboard.state import HISTORY_WEEKS_LIMIT, DashboardState, PostView


def _history_row(post: PostView) -> rx.Component:
    return rx.hstack(
        status_pill(post.status, post.status_label),
        rx.badge(post.post_type_label, variant="outline", size="1"),
        rx.text(post.created_at_str, size="1", class_name="hud-muted", min_width="3.5rem"),
        rx.text(
            post.draft_text,
            size="2",
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            flex="1",
        ),
        rx.button(
            "Reuse as new post",
            size="1",
            on_click=DashboardState.reuse_as_new_topic(post.id),
            **SECONDARY_CTA,
        ),
        width="100%",
        align="center",
        spacing="3",
        padding="0.6rem 0",
        border_bottom="1px solid var(--border)",
    )


def _week_group(entry: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.text(entry[0], size="2", weight="medium", class_name="hud-mono hud-muted"),
        rx.vstack(rx.foreach(entry[1], _history_row), spacing="0", width="100%"),
        spacing="2",
        width="100%",
    )


@reflex_local_auth.require_login
def history_page() -> rx.Component:
    body = rx.cond(
        DashboardState.history_by_week.length() > 0,
        rx.vstack(rx.foreach(DashboardState.history_by_week, _week_group), spacing="5", width="100%"),
        rx.text("No history yet.", size="2", class_name="hud-muted"),
    )
    return page_shell(
        "/history",
        rx.vstack(
            rx.heading("Past Weeks", size="5"),
            rx.text(
                f"Everything from the last {HISTORY_WEEKS_LIMIT} weeks, whatever happened to it. "
                'Spot a thin week? Click "Reuse as new post" to line up a catch-up draft.',
                size="2",
                class_name="hud-muted",
            ),
            body,
            spacing="4",
            width="100%",
        ),
    )
