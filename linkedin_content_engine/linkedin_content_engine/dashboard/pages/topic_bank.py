"""Topic bank: unused research findings, high tier first."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, SECONDARY_CTA, empty_state, page_shell
from linkedin_content_engine.dashboard.state import (
    QUEUE_FUNNEL_STAGE_OPTIONS,
    QUEUE_HOOK_POSTURE_OPTIONS,
    QUEUE_LENGTH_BUCKET_OPTIONS,
    QUEUE_MEDIA_PAIRING_OPTIONS,
    QUEUE_STRUCTURAL_FORMAT_OPTIONS,
    AUTO_SENTINEL,
    BankView,
    DashboardState,
    QueuedDraftView,
    humanize,
)


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
    otherwise. Moves the checked rows into the draft queue below rather than
    drafting immediately - request: "don't start generating them yet"."""
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
                    "Queue selected",
                    on_click=DashboardState.queue_selected_bank_rows,
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


def _style_select(options: list[str], value, on_change, *, raw_labels: bool = False) -> rx.Component:
    """Like components.py's type_select, but special-cases AUTO_SENTINEL to always
    show as "Standard" regardless of `raw_labels` - state.py's own humanize() would
    turn it into "Auto" instead, and funnel stage's real values (TOF/MOF/BOF) need
    `raw_labels=True` so humanize() doesn't mangle them into "Tof"/"Mof"/"Bof"."""

    def _label(opt: str) -> str:
        if opt == AUTO_SENTINEL:
            return "Standard"
        return opt if raw_labels else humanize(opt)

    return rx.select.root(
        rx.select.trigger(),
        rx.select.content(rx.select.group(*[rx.select.item(_label(opt), value=opt) for opt in options])),
        value=value,
        on_change=on_change,
        size="1",
    )


def _queue_item_card(item: QueuedDraftView) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.hstack(
                        rx.badge(item.tier_label, variant="outline", size="1"),
                        rx.badge(item.category_label, variant="outline", size="1"),
                        spacing="2",
                    ),
                    rx.text(item.summary, size="2"),
                    spacing="1",
                    align="start",
                ),
                rx.spacer(),
                rx.icon(
                    "x",
                    size=16,
                    cursor="pointer",
                    on_click=DashboardState.remove_from_queue(item.bank_id),
                    class_name="hud-muted",
                    flex_shrink="0",
                ),
                width="100%",
                align="start",
            ),
            rx.text(
                "Leave any of these on Standard to let it decide automatically, same as usual.",
                size="1",
                class_name="hud-muted",
            ),
            rx.grid(
                rx.vstack(
                    _field_label("Funnel stage"),
                    _style_select(
                        QUEUE_FUNNEL_STAGE_OPTIONS,
                        item.funnel_stage,
                        lambda v: DashboardState.set_queue_option(item.bank_id, "funnel_stage", v),
                        raw_labels=True,
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.vstack(
                    _field_label("Hook posture"),
                    _style_select(
                        QUEUE_HOOK_POSTURE_OPTIONS,
                        item.hook_posture,
                        lambda v: DashboardState.set_queue_option(item.bank_id, "hook_posture", v),
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.vstack(
                    _field_label("Length"),
                    _style_select(
                        QUEUE_LENGTH_BUCKET_OPTIONS,
                        item.length_bucket,
                        lambda v: DashboardState.set_queue_option(item.bank_id, "length_bucket", v),
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.vstack(
                    _field_label("Structural format"),
                    _style_select(
                        QUEUE_STRUCTURAL_FORMAT_OPTIONS,
                        item.structural_format,
                        lambda v: DashboardState.set_queue_option(item.bank_id, "structural_format", v),
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.vstack(
                    _field_label("Media pairing"),
                    _style_select(
                        QUEUE_MEDIA_PAIRING_OPTIONS,
                        item.media_pairing,
                        lambda v: DashboardState.set_queue_option(item.bank_id, "media_pairing", v),
                    ),
                    spacing="1",
                    align="start",
                ),
                columns=rx.breakpoints(initial="1", sm="3", lg="5"),
                spacing="3",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
        class_name="hud-surface-2",
    )


def _field_label(text: str) -> rx.Component:
    return rx.text(text, size="1", weight="medium", class_name="hud-muted")


def _draft_queue_card() -> rx.Component:
    """Request: "add like a selection of dropdowns for each one... put it as
    standard... or actually choose how I want them to come out then I just have a
    button which just generates all the ones inside the box." Only shows once
    something's actually queued."""
    return rx.cond(
        DashboardState.draft_queue.length() > 0,
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.heading("Draft queue", size="4"),
                    rx.spacer(),
                    rx.button(
                        "Clear queue",
                        on_click=DashboardState.clear_draft_queue,
                        size="2",
                        **SECONDARY_CTA,
                    ),
                    rx.button(
                        "Generate all queued",
                        on_click=DashboardState.generate_queued_drafts,
                        loading=DashboardState.is_busy,
                        size="2",
                        **PRIMARY_CTA,
                    ),
                    width="100%",
                    align="center",
                    wrap="wrap",
                ),
                rx.vstack(
                    rx.foreach(DashboardState.draft_queue, _queue_item_card),
                    spacing="3",
                    width="100%",
                ),
                spacing="3",
                width="100%",
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
            _draft_queue_card(),
            body,
            spacing="4",
            width="100%",
        ),
    )
