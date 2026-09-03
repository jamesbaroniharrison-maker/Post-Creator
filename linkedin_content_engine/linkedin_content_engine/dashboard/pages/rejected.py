"""Rejected: the last 5 only (request: "only want to save the last five... after
that, delete them") - older ones are pruned automatically by scheduling.py whenever
a new post is rejected."""

import reflex as rx

from linkedin_content_engine.dashboard.components import empty_state, page_shell, rejected_post_card
from linkedin_content_engine.dashboard.state import DashboardState


def rejected_page() -> rx.Component:
    body = rx.cond(
        DashboardState.rejected_posts.length() > 0,
        rx.vstack(rx.foreach(DashboardState.rejected_posts, rejected_post_card), spacing="4", width="100%"),
        empty_state(
            "trash-2",
            "Clean record",
            "Nothing's been rejected - rejected drafts will land here with a reason attached.",
        ),
    )
    return page_shell(
        "/rejected",
        rx.vstack(
            rx.heading("Rejected", size="5"),
            rx.text(
                "Only the most recent 5 are kept - older ones are deleted automatically.",
                size="2",
                class_name="hud-muted",
            ),
            body,
            spacing="4",
            width="100%",
        ),
    )
