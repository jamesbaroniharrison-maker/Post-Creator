"""Rejected: the last 5 only (request: "only want to save the last five... after
that, delete them") - older ones are pruned automatically by scheduling.py whenever
a new post is rejected."""

import reflex as rx
import reflex_local_auth

from wpa_content_engine.dashboard.components import page_shell, rejected_post_card
from wpa_content_engine.dashboard.state import DashboardState


@reflex_local_auth.require_login
def rejected_page() -> rx.Component:
    body = rx.cond(
        DashboardState.rejected_posts.length() > 0,
        rx.vstack(rx.foreach(DashboardState.rejected_posts, rejected_post_card), spacing="4", width="100%"),
        rx.text("Nothing rejected right now.", size="2", class_name="hud-muted"),
    )
    return page_shell(
        "/rejected",
        rx.vstack(
            rx.heading("Rejected", size="5"),
            rx.text("Only the most recent 5 are kept - older ones are deleted automatically.", size="2", class_name="hud-muted"),
            body,
            spacing="4",
            width="100%",
        ),
    )
