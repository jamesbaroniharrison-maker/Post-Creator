"""Topic bank: unused research findings, high tier first."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, SECONDARY_CTA, empty_state, page_shell
from linkedin_content_engine.dashboard.state import BankView, DashboardState


def _bank_row_card(row: BankView) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.checkbox(
                checked=row.is_selected,
                on_change=lambda _: DashboardState.toggle_bank_selection(row.id),
                size="2",
                margin_top="0.25rem",
            ),
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
        class_name=rx.cond(row.is_selected, "hud-card-selected", ""),
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


def _batch_draft_bar() -> rx.Component:
    """Request: "add the ability to select multiple topics to queue to draft at the
    same time." Only shows once at least one row is checked - stays out of the way
    otherwise. Queues drafts one after another via generate_from_selected_bank_rows,
    reusing the exact same _draft_from_bank_row path "Generate draft" already uses
    per row, just looped."""
    return rx.cond(
        DashboardState.selected_bank_count > 0,
        rx.card(
            rx.hstack(
                rx.text(
                    DashboardState.selected_bank_count.to_string() + " topic(s) selected",
                    size="2",
                    weight="medium",
                ),
                rx.spacer(),
                rx.button(
                    "Clear selection",
                    on_click=DashboardState.clear_bank_selection,
                    size="2",
                    **SECONDARY_CTA,
                ),
                rx.button(
                    "Draft selected",
                    on_click=DashboardState.generate_from_selected_bank_rows,
                    loading=DashboardState.is_busy,
                    size="2",
                    **PRIMARY_CTA,
                ),
                width="100%",
                align="center",
                wrap="wrap",
            ),
            width="100%",
        ),
        rx.fragment(),
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
                "Unused findings, high tier first - generate a draft directly, or leave it banked. "
                "Check several rows to draft them all as a queue.",
                size="2",
                class_name="hud-muted",
            ),
            _link_date_picker(),
            _batch_draft_bar(),
            body,
            spacing="4",
            width="100%",
        ),
    )
