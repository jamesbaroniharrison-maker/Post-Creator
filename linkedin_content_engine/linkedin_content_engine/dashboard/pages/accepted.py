"""Accepted and Plan ahead sections of the Posts page.

Accepted: everything approved or published, auto-sorted into This Week / Next Week /
later by scheduling.allocate_accepted_posts() (request: "AI automatically chooses
which ones are going into this week's lot... too many, puts them for next week").
Plan ahead: the 4-week calendar, each day following the weekly schedule.
"""

import reflex as rx

from linkedin_content_engine.dashboard.components import (
    accepted_filter_bar,
    accepted_post_card,
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


def accepted_section() -> rx.Component:
    body = rx.cond(
        DashboardState.accepted_by_week.length() > 0,
        rx.vstack(rx.foreach(DashboardState.accepted_by_week, _week_group), spacing="5", width="100%"),
        rx.text("Nothing scheduled for this week yet, at this filter.", size="2", class_name="hud-muted"),
    )
    return rx.vstack(
        rx.text(
            "Sorted into weeks automatically - up to 4 a week, extras roll into the next.",
            size="2",
            class_name="hud-muted",
        ),
        week_selector_bar(),
        accepted_filter_bar(),
        body,
        spacing="4",
        width="100%",
    )


def plan_ahead_section() -> rx.Component:
    return rx.vstack(
        rx.text(
            "The next 4 weeks. Each day follows your weekly schedule (Settings > Weekly Plan "
            "Template), and shows any calendar occasions you've ticked Yes.",
            size="2",
            class_name="hud-muted",
        ),
        planning_calendar(),
        spacing="4",
        width="100%",
    )
