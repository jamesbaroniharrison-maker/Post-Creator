"""Settings: quick actions (generate now, run research now, forced topics) and fully
customizable email reminder timing."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, SECONDARY_CTA, page_shell, type_select
from linkedin_content_engine.dashboard.state import (
    DAY_TEMPLATE_OPTIONS,
    POST_TYPES,
    TOPIC_CATEGORIES,
    WEEKDAYS,
    DashboardState,
    ForcedTopicView,
)


def _field_label(text: str) -> rx.Component:
    return rx.text(text, size="1", weight="medium", class_name="hud-muted")


def _forced_topic_chip(item: ForcedTopicView) -> rx.Component:
    return rx.hstack(
        rx.badge(item.category_label, variant="outline", size="1"),
        rx.text(item.topic, size="2"),
        rx.spacer(),
        rx.icon(
            "x",
            size=14,
            cursor="pointer",
            on_click=DashboardState.remove_forced_topic(item.id),
            class_name="hud-muted",
        ),
        width="100%",
        align="center",
        padding="0.4rem 0.6rem",
        class_name="hud-surface-2",
    )


def _generate_now_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Generate a post now", size="3"),
            _field_label("Post type"),
            type_select(
                POST_TYPES,
                value=DashboardState.quick_post_type,
                on_change=DashboardState.set_quick_post_type,
                size="2",
                width="100%",
            ),
            _field_label("Topic"),
            rx.input(
                value=DashboardState.quick_topic,
                on_change=DashboardState.set_quick_topic,
                placeholder="e.g. the latest AI model release",
                size="2",
                width="100%",
            ),
            rx.spacer(),
            rx.button(
                "Research + draft",
                on_click=DashboardState.generate_post_now,
                loading=DashboardState.is_busy,
                width="100%",
                **PRIMARY_CTA,
            ),
            spacing="2",
            align="start",
            width="100%",
            height="100%",
        ),
        width="100%",
    )


def _run_research_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Run research now", size="3"),
            rx.text(
                "Scans trusted sources immediately instead of waiting for the "
                "daily schedule - includes any queued topics from the card on the right.",
                size="1",
                class_name="hud-muted",
            ),
            rx.hstack(
                rx.text("Last successful run:", size="1", weight="medium", class_name="hud-muted"),
                rx.text(
                    DashboardState.last_research_run_display,
                    size="1",
                    color=rx.cond(DashboardState.last_research_run_stale, "red", "gray"),
                    weight=rx.cond(DashboardState.last_research_run_stale, "bold", "regular"),
                ),
                rx.cond(
                    DashboardState.last_research_run_stale,
                    rx.badge("overdue", color_scheme="red", variant="soft", size="1"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
            ),
            rx.spacer(),
            rx.button(
                "Run research now",
                on_click=DashboardState.run_research_now,
                loading=DashboardState.is_busy,
                width="100%",
                **SECONDARY_CTA,
            ),
            spacing="2",
            align="start",
            width="100%",
            height="100%",
        ),
        width="100%",
    )


def _force_topics_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Force next search topics", size="3"),
            _field_label("Category"),
            rx.select(
                TOPIC_CATEGORIES,
                value=DashboardState.new_forced_topic_category,
                on_change=DashboardState.set_new_forced_topic_category,
                size="2",
                width="100%",
            ),
            _field_label("Topic"),
            rx.input(
                value=DashboardState.new_forced_topic,
                on_change=DashboardState.set_new_forced_topic,
                placeholder="Topic to search for",
                size="2",
                width="100%",
            ),
            rx.button(
                "Queue topic",
                on_click=DashboardState.add_forced_topic,
                width="100%",
                **SECONDARY_CTA,
            ),
            rx.cond(
                DashboardState.forced_topics.length() > 0,
                rx.vstack(
                    rx.foreach(DashboardState.forced_topics, _forced_topic_chip),
                    spacing="1",
                    width="100%",
                ),
                rx.text("Nothing queued.", size="1", class_name="hud-muted"),
            ),
            spacing="2",
            align="start",
            width="100%",
            height="100%",
        ),
        width="100%",
    )


def _quick_actions() -> rx.Component:
    """Three separate cards, not one card with whitespace-only separation between
    unevenly-sized sections (design-reference.html §6)."""
    return rx.vstack(
        rx.heading("Quick Actions", size="5"),
        rx.grid(
            _generate_now_card(),
            _run_research_card(),
            _force_topics_card(),
            columns=rx.breakpoints(initial="1", md="3"),
            spacing="3",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


_WEEKDAY_TEMPLATE_ROWS = [
    ("Monday", DashboardState.wt_monday, DashboardState.set_wt_monday),
    ("Tuesday", DashboardState.wt_tuesday, DashboardState.set_wt_tuesday),
    ("Wednesday", DashboardState.wt_wednesday, DashboardState.set_wt_wednesday),
    ("Thursday", DashboardState.wt_thursday, DashboardState.set_wt_thursday),
    ("Friday", DashboardState.wt_friday, DashboardState.set_wt_friday),
    ("Saturday", DashboardState.wt_saturday, DashboardState.set_wt_saturday),
    ("Sunday", DashboardState.wt_sunday, DashboardState.set_wt_sunday),
]


def _weekly_plan_card() -> rx.Component:
    """Request: "choose which days the certain types of post to go to... option for
    no post as well... sync with like holidays and recommend if it was a specific
    day." This is the default template "Plan this week" (Accepted page) reads - it
    never overrides a day you've already put your own note on."""
    return rx.card(
        rx.vstack(
            rx.heading("Weekly Plan Template", size="5"),
            rx.text(
                "The default post type for each day of the week - used by \"Plan this "
                "week\" on the Accepted page. Never overrides a day you've already "
                "pencilled a note on.",
                size="2",
                class_name="hud-muted",
            ),
            rx.grid(
                *[
                    rx.vstack(
                        _field_label(day_name),
                        type_select(
                            DAY_TEMPLATE_OPTIONS,
                            value=value,
                            on_change=setter,
                            size="2",
                            width="100%",
                        ),
                        spacing="1",
                        align="start",
                        width="100%",
                    )
                    for day_name, value, setter in _WEEKDAY_TEMPLATE_ROWS
                ],
                columns=rx.breakpoints(initial="2", sm="4"),
                spacing="3",
                width="100%",
            ),
            rx.hstack(
                rx.checkbox(
                    "Recommend a holiday-themed post on days like Christmas or Halloween",
                    checked=DashboardState.wt_recommend_holidays,
                    on_change=DashboardState.set_wt_recommend_holidays,
                ),
                width="100%",
            ),
            rx.button(
                "Save weekly plan",
                on_click=DashboardState.save_weekly_template,
                size="3",
                **PRIMARY_CTA,
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


_HOURS = [f"{h:02d}:00" for h in range(24)]


def _email_settings() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Email Reminders", size="5"),
            rx.text(
                "Both emails go to the same address - set the day and time for each independently.",
                size="2",
                class_name="hud-muted",
            ),
            _field_label("Email address"),
            rx.input(
                value=DashboardState.email_recipient,
                on_change=DashboardState.set_email_recipient,
                placeholder="your email address",
                size="2",
                width="100%",
            ),
            rx.grid(
                rx.vstack(
                    rx.text("Personal story reminder", size="2", weight="medium", class_name="hud-mono"),
                    rx.hstack(
                        rx.select(
                            WEEKDAYS,
                            value=DashboardState.email_reminder_day,
                            on_change=DashboardState.set_email_reminder_day,
                            size="2",
                        ),
                        rx.select(
                            _HOURS,
                            value=DashboardState.email_reminder_time,
                            on_change=DashboardState.set_email_reminder_time,
                            size="2",
                        ),
                        spacing="2",
                    ),
                    spacing="2",
                    align="start",
                    padding_right="1.25rem",
                    border_right=rx.breakpoints(initial="none", sm="1px solid var(--border)"),
                ),
                rx.vstack(
                    rx.text("Weekly post digest", size="2", weight="medium", class_name="hud-mono"),
                    rx.hstack(
                        rx.select(
                            WEEKDAYS,
                            value=DashboardState.email_digest_day,
                            on_change=DashboardState.set_email_digest_day,
                            size="2",
                        ),
                        rx.select(
                            _HOURS,
                            value=DashboardState.email_digest_time,
                            on_change=DashboardState.set_email_digest_time,
                            size="2",
                        ),
                        spacing="2",
                    ),
                    spacing="2",
                    align="start",
                    padding_left=rx.breakpoints(initial="0", sm="1.25rem"),
                ),
                columns=rx.breakpoints(initial="1", sm="2"),
                spacing="4",
                width="100%",
            ),
            rx.button(
                "Save",
                on_click=DashboardState.save_email_settings_click,
                size="3",
                **PRIMARY_CTA,
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


@reflex_local_auth.require_login
def settings_page() -> rx.Component:
    return page_shell("/settings", _quick_actions(), _weekly_plan_card(), _email_settings())
