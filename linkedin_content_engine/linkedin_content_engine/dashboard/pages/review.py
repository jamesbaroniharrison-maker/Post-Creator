"""Review: drafts waiting for a decision. Accept / Redraft / Reject.

Grouped by kind of post (AI commentary, market commentary, personal), not by the
model's suggested day - the suggested day still shows, and can be changed, on each
card (request: "have it as AI commentary posts or market posts", because almost every
draft was landing under Tuesday)."""

import reflex as rx

from linkedin_content_engine.dashboard.components import empty_state, review_post_card
from linkedin_content_engine.dashboard.state import REVIEW_GROUPS, DashboardState, humanize


def _type_section(post_type: str) -> rx.Component:
    posts = DashboardState.posts_by_type[post_type]
    heading = "Other" if post_type == "other" else humanize(post_type)
    return rx.cond(
        posts.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.heading(heading, size="4"),
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


def review_section() -> rx.Component:
    body = rx.cond(
        DashboardState.posts.length() > 0,
        rx.vstack(*[_type_section(t) for t in REVIEW_GROUPS], spacing="5", width="100%"),
        empty_state("inbox", "All caught up", "Nothing's waiting for review right now - new drafts will show up here."),
    )
    return rx.vstack(body, spacing="4", width="100%")
