"""Topic bank: unused research findings, high tier first."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, SECONDARY_CTA, empty_state, page_shell
from linkedin_content_engine.dashboard.state import BankView, DashboardState


def _bank_row_card(row: BankView) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.badge(
                        row.tier_label,
                        color_scheme=rx.match(row.tier, ("high", "green"), ("mid", "amber"), "gray"),
                    ),
                    rx.badge(row.category_label, variant="outline"),
                    spacing="2",
                ),
                rx.text(row.summary, size="2"),
                rx.link(row.source_title, href=row.source_url, size="1", is_external=True),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.vstack(
                rx.button(
                    "Generate draft",
                    on_click=DashboardState.generate_from_bank(row.id),
                    loading=DashboardState.is_busy,
                    size="2",
                    width="100%",
                    **PRIMARY_CTA,
                ),
                rx.button(
                    "Link to day",
                    on_click=DashboardState.link_topic_to_day(row.id),
                    size="2",
                    width="100%",
                    **SECONDARY_CTA,
                ),
                spacing="2",
                align="stretch",
                flex_shrink="0",
            ),
            width="100%",
            align="start",
        ),
        width="100%",
    )


def _link_date_picker() -> rx.Component:
    """The shared target date for "Link to day" (request: "if I have topics that I
    like I want to be able to click on them... select a day that I want them to be
    linked to for a post"). Real cross-page drag-and-drop isn't practical to build
    reliably in Reflex - pick the date once here, then click "Link to day" on
    whichever topic should land there; it shows up on the Accepted page's Plan
    ahead calendar."""
    return rx.card(
        rx.hstack(
            rx.vstack(
                rx.text("Link topics to this date", size="2", weight="medium"),
                rx.text(
                    "Pick a date, then click \"Link to day\" on any topic below - it'll show up "
                    "on the Accepted page's Plan ahead calendar for that date.",
                    size="1",
                    class_name="hud-muted",
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.input(
                type="date",
                value=DashboardState.link_target_date,
                on_change=DashboardState.set_link_target_date,
                size="2",
                width="10rem",
            ),
            width="100%",
            align="center",
            wrap="wrap",
        ),
        width="100%",
    )


@reflex_local_auth.require_login
def topic_bank_page() -> rx.Component:
    body = rx.cond(
        DashboardState.bank_rows.length() > 0,
        rx.vstack(rx.foreach(DashboardState.bank_rows, _bank_row_card), spacing="3", width="100%"),
        empty_state(
            "archive",
            "Bank's empty",
            "Research findings that don't get used straight away will collect here.",
        ),
    )
    return page_shell(
        "/topic-bank",
        rx.vstack(
            rx.heading("Topic Bank", size="5"),
            rx.text(
                "Unused findings, high tier first - generate a draft directly, or leave it banked.",
                size="2",
                class_name="hud-muted",
            ),
            _link_date_picker(),
            body,
            spacing="4",
            width="100%",
        ),
    )
