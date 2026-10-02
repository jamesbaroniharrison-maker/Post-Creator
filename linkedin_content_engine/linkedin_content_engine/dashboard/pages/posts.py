"""Posts: one tab for the whole post lifecycle (request: "minimise tabs... review,
accepted and rejected into just a posts tab with those being subheadings, with past
weeks, plan ahead and calendar as subheadings within that")."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import page_shell
from linkedin_content_engine.dashboard.pages.accepted import accepted_section, plan_ahead_section
from linkedin_content_engine.dashboard.pages.calendar import calendar_section
from linkedin_content_engine.dashboard.pages.history import history_section
from linkedin_content_engine.dashboard.pages.rejected import rejected_section
from linkedin_content_engine.dashboard.pages.review import review_section
from linkedin_content_engine.dashboard.state import DashboardState

_SECTIONS = [
    ("review", "Review", review_section),
    ("accepted", "Accepted", accepted_section),
    ("rejected", "Rejected", rejected_section),
    ("history", "Past weeks", history_section),
    ("plan", "Plan ahead", plan_ahead_section),
    ("calendar", "Calendar", calendar_section),
]


@reflex_local_auth.require_login
def posts_page() -> rx.Component:
    return page_shell(
        "/posts",
        rx.vstack(
            rx.heading("Posts", size="5"),
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger(
                        "Review",
                        rx.cond(
                            DashboardState.posts.length() > 0,
                            rx.badge(DashboardState.posts.length(), variant="soft", color_scheme="bronze", margin_left="0.4rem"),
                            rx.fragment(),
                        ),
                        value="review",
                    ),
                    *[rx.tabs.trigger(label, value=key) for key, label, _ in _SECTIONS[1:]],
                    wrap="wrap",
                ),
                *[rx.tabs.content(section(), value=key, padding_top="1.25rem") for key, _, section in _SECTIONS],
                value=DashboardState.posts_tab,
                on_change=DashboardState.set_posts_tab,
                width="100%",
            ),
            spacing="4",
            width="100%",
        ),
    )
