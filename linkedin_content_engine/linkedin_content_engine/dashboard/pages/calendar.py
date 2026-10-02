"""Calendar section of the Posts page: yearly AI, tech, data and careers occasions,
ported from the Ben Holmes content engine. Recommended, never forced - tick Yes and
the occasion is linked to a real Topic Bank story, or its angle is banked."""

import reflex as rx

from linkedin_content_engine.dashboard.components import empty_state
from linkedin_content_engine.dashboard.state import CalendarEventView, DashboardState


def _month_bar() -> rx.Component:
    return rx.hstack(
        rx.foreach(
            DashboardState.calendar_month_options,
            lambda m, i: rx.button(
                m["label"],
                size="2",
                on_click=DashboardState.set_calendar_month_offset(i),
                variant=rx.cond(DashboardState.selected_calendar_month == m["key"], "solid", "outline"),
                color_scheme="bronze",
            ),
        ),
        spacing="2",
        wrap="wrap",
    )


def _event_card(event: CalendarEventView) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(event.date_label, size="2", weight="medium"),
                rx.badge(event.category_label, variant="outline", size="1"),
                rx.cond(
                    event.source == "researched",
                    rx.badge("Found by research", variant="soft", size="1", color_scheme="gray"),
                    rx.fragment(),
                ),
                rx.cond(
                    event.suggestion_made,
                    rx.badge("In the Topic Bank", variant="soft", size="1", color_scheme="green"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.text(event.name, size="3", weight="medium"),
            rx.cond(event.angle_notes != "", rx.text(event.angle_notes, size="2", class_name="hud-muted"), rx.fragment()),
            rx.hstack(
                rx.button(
                    "Use this",
                    size="2",
                    on_click=DashboardState.set_calendar_event_included(event.id, True),
                    variant=rx.cond(event.decision == "yes", "solid", "outline"),
                    color_scheme="bronze",
                ),
                rx.button(
                    "Skip",
                    size="2",
                    on_click=DashboardState.set_calendar_event_included(event.id, False),
                    variant=rx.cond(event.decision == "no", "solid", "outline"),
                    color_scheme="gray",
                ),
                rx.cond(
                    event.decision == "",
                    rx.text("Not decided yet", size="1", class_name="hud-muted"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            spacing="2",
            width="100%",
            align="start",
        ),
        width="100%",
    )


def calendar_section() -> rx.Component:
    return rx.vstack(
        rx.text(
            "AI, tech, data and careers occasions for the year. Tick Use this and the occasion "
            "is linked to a real story in the Topic Bank, or its angle is banked there for you to "
            "draft from. Nothing drafts itself. Next year is planned automatically each November.",
            size="2",
            class_name="hud-muted",
        ),
        rx.cond(
            DashboardState.calendar_month_options.length() > 0,
            rx.vstack(
                _month_bar(),
                rx.vstack(rx.foreach(DashboardState.calendar_events_for_month, _event_card), spacing="3", width="100%"),
                spacing="4",
                width="100%",
            ),
            empty_state("calendar", "No occasions yet", "They load with the next 7am research run."),
        ),
        spacing="4",
        width="100%",
    )
