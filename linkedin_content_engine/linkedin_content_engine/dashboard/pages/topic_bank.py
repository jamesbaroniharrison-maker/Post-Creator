"""Topic bank: unused research findings, high tier first."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.drafting_engine.rotation import STYLE_HELP
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
    """Topic + its actions. Side by side on desktop; on a phone the buttons sit under
    the topic (CSS .hud-split) instead of squeezing it into a narrow column."""
    return rx.card(
        rx.box(
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
                        rx.cond(
                            row.occasion_label != "",
                            rx.badge(rx.icon("calendar", size=12), "For " + row.occasion_label, variant="soft", color_scheme="green"),
                            rx.fragment(),
                        ),
                        spacing="2",
                        wrap="wrap",
                    ),
                    rx.text(row.summary, size="2"),
                    rx.cond(
                        row.source_url != "",
                        rx.link(row.source_title, href=row.source_url, size="1", is_external=True),
                        rx.fragment(),
                    ),
                    _occasion_fit(row),
                    _summary_dropdown(row),
                    _take_box(row),
                    spacing="1",
                    align="start",
                    width="100%",
                ),
                align="start",
                width="100%",
                class_name="hud-split-main",
            ),
            rx.box(
                rx.button(
                    "Generate draft",
                    on_click=DashboardState.generate_from_bank(row.id),
                    loading=DashboardState.is_busy,
                    size="2",
                    **PRIMARY_CTA,
                ),
                rx.button(
                    "Link to day",
                    on_click=DashboardState.link_topic_to_day(row.id),
                    size="2",
                    **SECONDARY_CTA,
                ),
                class_name="hud-split-side",
            ),
            class_name="hud-split",
        ),
        width="100%",
        class_name=rx.cond(row.is_selected, "hud-card-selected", ""),
    )


def _bank_toolbar() -> rx.Component:
    """Search + filter + "select all shown" (request: "search and filter... collapse
    long lists, bulk actions")."""
    return rx.vstack(
        rx.input(
            rx.input.slot(rx.icon("search", size=16)),
            value=DashboardState.bank_search,
            on_change=DashboardState.set_bank_search,
            placeholder="Search topics, sources, occasions...",
            width="100%",
            size="2",
        ),
        rx.hstack(
            *[
                rx.button(
                    label,
                    on_click=DashboardState.set_bank_filter(value),
                    size="1",
                    variant=rx.cond(DashboardState.bank_filter == value, "solid", "outline"),
                    color_scheme="bronze",
                )
                for value, label in [
                    ("all", "All"),
                    ("occasion", "For an occasion"),
                    ("high", "High tier"),
                    ("ai", "AI"),
                    ("market", "Market"),
                ]
            ],
            spacing="2",
            wrap="wrap",
        ),
        rx.hstack(
            rx.text(
                "Showing " + DashboardState.visible_bank_rows.length().to_string() + " of "
                + DashboardState.bank_rows.length().to_string(),
                size="1",
                class_name="hud-muted",
            ),
            rx.spacer(),
            rx.button(
                "Select all shown",
                on_click=DashboardState.select_visible_bank_rows,
                size="1",
                variant="ghost",
                color_scheme="gray",
            ),
            width="100%",
            align="center",
        ),
        spacing="2",
        width="100%",
    )


def _occasion_fit(row: BankView) -> rx.Component:
    """Why the story was linked to its occasion, and a way to say it doesn't fit
    (request: "add a way to say hey this topic doesn't match the calendar event")."""
    return rx.cond(
        row.occasion_label != "",
        rx.hstack(
            rx.text(
                rx.cond(row.occasion_link_note != "", "Why it fits: " + row.occasion_link_note, ""),
                size="1",
                class_name="hud-muted",
            ),
            rx.button(
                rx.icon("unlink", size=12),
                "Doesn't fit",
                on_click=DashboardState.reject_occasion_link(row.id),
                loading=DashboardState.is_busy,
                size="1",
                variant="ghost",
                color_scheme="red",
            ),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        rx.fragment(),
    )


def _summary_dropdown(row: BankView) -> rx.Component:
    """Click-to-open summary of the article (and its link to the occasion), written by
    the local model the first time it's opened, then cached."""
    return rx.vstack(
        rx.button(
            rx.icon(rx.cond(row.summary_open, "chevron-down", "chevron-right"), size=14),
            "Summary",
            on_click=DashboardState.toggle_bank_summary(row.id),
            size="1",
            variant="ghost",
            color_scheme="gray",
        ),
        rx.cond(
            row.summary_open,
            rx.box(
                rx.cond(
                    row.summarising,
                    rx.hstack(
                        rx.spinner(size="1"),
                        rx.text("Reading the article with the local model...", size="1", class_name="hud-muted"),
                        spacing="2",
                        align="center",
                    ),
                    rx.text(row.llm_summary, size="2", white_space="pre-wrap"),
                ),
                padding="0.5rem 0.75rem",
                width="100%",
                class_name="hud-surface-2",
            ),
            rx.fragment(),
        ),
        spacing="1",
        align="start",
        width="100%",
    )


def _take_box(row: BankView) -> rx.Component:
    """Optional: your own take or which side to go with - used in the draft."""
    return rx.hstack(
        rx.input(
            value=row.user_take,
            on_change=lambda v: DashboardState.set_bank_take(row.id, v),
            on_blur=lambda _: DashboardState.save_bank_take(row.id),
            placeholder="Your take or side (optional)",
            size="2",
            flex="1",
            min_width="0",
        ),
        rx.button(
            "Save",
            on_click=DashboardState.save_bank_take(row.id),
            size="2",
            variant="soft",
            color_scheme="gray",
            flex_shrink="0",
        ),
        spacing="2",
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
                    "in Posts > Plan ahead on that date.",
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
            position="sticky",
            top="0.5rem",
            z_index="3",
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
                        rx.cond(
                            item.occasion_label != "",
                            rx.badge(rx.icon("calendar", size=12), "For " + item.occasion_label, variant="soft", color_scheme="green", size="1"),
                            rx.fragment(),
                        ),
                        spacing="2",
                        wrap="wrap",
                    ),
                    rx.cond(
                        item.source_url != "",
                        rx.link(item.source_title, href=item.source_url, size="2", weight="medium", is_external=True),
                        rx.text(item.source_title, size="2", weight="medium"),
                    ),
                    rx.text(item.summary, size="2"),
                    rx.cond(
                        item.user_take != "",
                        rx.text("Your take: " + item.user_take, size="1", class_name="hud-muted"),
                        rx.fragment(),
                    ),
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
                "Leave any on Standard to let it decide. The line under each one says what your pick does.",
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
                    _style_help("funnel_stage", item.funnel_stage),
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
                    _style_help("hook_posture", item.hook_posture),
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
                    _style_help("length_bucket", item.length_bucket),
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
                    _style_help("structural_format", item.structural_format),
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
                    _style_help("media_pairing", item.media_pairing),
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


def _style_help(field: str, value) -> rx.Component:
    """What the selected option actually does (request: "impossible to remember what
    all the keys mean")."""
    help_texts = STYLE_HELP[field]
    return rx.text(
        rx.match(value, *[(key, text) for key, text in help_texts.items()], ""),
        size="1",
        class_name="hud-muted",
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
        rx.vstack(
            _bank_toolbar(),
            rx.cond(
                DashboardState.visible_bank_rows.length() > 0,
                rx.vstack(rx.foreach(DashboardState.visible_bank_rows, _bank_row_card), spacing="3", width="100%"),
                rx.text("Nothing matches - try another search or filter.", size="2", class_name="hud-muted"),
            ),
            spacing="3",
            width="100%",
        ),
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
