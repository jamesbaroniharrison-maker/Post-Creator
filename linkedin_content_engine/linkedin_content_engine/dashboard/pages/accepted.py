"""Accepted: everything approved or published, auto-sorted into This Week / Next Week
/ later by scheduling.allocate_accepted_posts() (request: "AI automatically chooses
which ones are going into this week's lot... too many, puts them for next week")."""

import reflex as rx

from linkedin_content_engine.dashboard.components import (
    accepted_filter_bar,
    accepted_post_card,
    page_shell,
    planning_calendar,
    week_selector_bar,
)
from linkedin_content_engine.dashboard.state import DashboardState


def _week_group(entry: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.heading(entry[0], size="4"),
        rx.vstack(rx.foreach(entry[1], accepted_post_card), spacing="4", width="100%"),
        spacing="3",
        width="100%",
        padding_bottom="1rem",
    )


def accepted_page() -> rx.Component:
    body = rx.cond(
        DashboardState.accepted_by_week.length() > 0,
        rx.vstack(rx.foreach(DashboardState.accepted_by_week, _week_group), spacing="5", width="100%"),
        rx.text("Nothing scheduled for this week yet, at this filter.", size="2", class_name="hud-muted"),
    )
    return page_shell(
        "/accepted",
        rx.vstack(
            rx.heading("Accepted", size="5"),
            rx.text(
                "Sorted into weeks automatically - up to 4 a week, extras roll into the next.",
                size="2",
                class_name="hud-muted",
            ),
            week_selector_bar(),
            accepted_filter_bar(),
            body,
            rx.divider(),
            rx.heading("Plan ahead", size="4"),
            planning_calendar(),
            spacing="4",
            width="100%",
        ),
    )
