"""Settings: quick actions (generate now, run research now, forced topics) and fully
customizable email reminder timing."""

import reflex as rx

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, SECONDARY_CTA, page_shell
from linkedin_content_engine.dashboard.state import (
    POST_TYPES,
    TOPIC_CATEGORIES,
    WEEKDAYS,
    DashboardState,
    ForcedTopicView,
)


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


def _quick_actions() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Quick Actions", size="5"),
            rx.grid(
                rx.vstack(
                    rx.text("Generate a post now", size="2", weight="medium", class_name="hud-mono"),
                    rx.select(
                        POST_TYPES,
                        value=DashboardState.quick_post_type,
                        on_change=DashboardState.set_quick_post_type,
                        size="2",
                    ),
                    rx.input(
                        value=DashboardState.quick_topic,
                        on_change=DashboardState.set_quick_topic,
                        placeholder="Topic - e.g. the latest AI model release",
                        size="2",
                        width="100%",
                    ),
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
                ),
                rx.vstack(
                    rx.text("Run research now", size="2", weight="medium", class_name="hud-mono"),
                    rx.text(
                        "Scans trusted sources immediately instead of waiting for the "
                        "daily schedule - includes any queued topics below.",
                        size="1",
                        class_name="hud-muted",
                    ),
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
                ),
                rx.vstack(
                    rx.text("Force next search topics", size="2", weight="medium", class_name="hud-mono"),
                    rx.hstack(
                        rx.select(
                            TOPIC_CATEGORIES,
                            value=DashboardState.new_forced_topic_category,
                            on_change=DashboardState.set_new_forced_topic_category,
                            size="2",
                        ),
                        rx.input(
                            value=DashboardState.new_forced_topic,
                            on_change=DashboardState.set_new_forced_topic,
                            placeholder="Topic to search for",
                            size="2",
                            width="100%",
                        ),
                        width="100%",
                        spacing="2",
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
                ),
                columns=rx.breakpoints(initial="1", md="3"),
                spacing="4",
                width="100%",
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
                ),
                columns=rx.breakpoints(initial="1", sm="2"),
                spacing="4",
                width="100%",
            ),
            rx.button("Save", on_click=DashboardState.save_email_settings_click, **SECONDARY_CTA),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def settings_page() -> rx.Component:
    return page_shell("/settings", _quick_actions(), _email_settings())
