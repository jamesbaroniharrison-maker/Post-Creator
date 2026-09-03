"""Topic bank: unused research findings, high tier first."""

import reflex as rx

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, empty_state, page_shell
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
            rx.button(
                "Generate draft",
                on_click=DashboardState.generate_from_bank(row.id),
                loading=DashboardState.is_busy,
                size="2",
                **PRIMARY_CTA,
            ),
            width="100%",
            align="start",
        ),
        width="100%",
    )


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
            body,
            spacing="4",
            width="100%",
        ),
    )
