"""UI component builders for the review dashboard (spec Â§3d)."""

import reflex as rx

from wpa_content_engine.dashboard.state import (
    DISPLAY_DAYS,
    HISTORY_WEEKS_LIMIT,
    POST_TYPES,
    REJECTION_REASONS,
    TOPIC_CATEGORIES,
    WEEKDAYS,
    BankView,
    DashboardState,
    ForcedTopicView,
    PostView,
)

PRIMARY_CTA = {"color_scheme": "bronze", "variant": "solid"}
SECONDARY_CTA = {"color_scheme": "bronze", "variant": "outline"}


def status_pill(status: rx.Var) -> rx.Component:
    return rx.box(
        status,
        class_name=rx.match(
            status,
            ("drafted", "hud-pill hud-pill-drafted"),
            ("approved", "hud-pill hud-pill-approved"),
            ("published", "hud-pill hud-pill-published"),
            ("rejected", "hud-pill hud-pill-rejected"),
            "hud-pill hud-pill-drafted",
        ),
    )


def stat_card(label: str, value: rx.Var) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(label, class_name="hud-stat-label"),
            rx.text(value, class_name="hud-stat-value"),
            spacing="1",
        ),
        class_name="hud-surface-2",
        padding="var(--pad)",
    )


def stats_panel() -> rx.Component:
    s = DashboardState.stats
    return rx.card(
        rx.vstack(
            rx.heading("Stats", size="4"),
            rx.grid(
                stat_card("Drafted", s["drafted"]),
                stat_card("Approved", s["approved"]),
                stat_card("Published", s["published"]),
                stat_card("Rejected", s["rejected"]),
                stat_card("Acceptance rate", s["acceptance_rate"]),
                stat_card("Avg time to review", s["avg_time_to_review"]),
                stat_card("Avg time to publish", s["avg_time_to_publish"]),
                columns=rx.breakpoints(initial="2", sm="4"),
                spacing="3",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def chip(text: rx.Var, on_remove) -> rx.Component:
    return rx.badge(
        rx.hstack(
            rx.text(text, size="2"),
            rx.icon("x", size=12, cursor="pointer", on_click=on_remove),
            spacing="1",
            align="center",
        ),
        variant="soft",
        radius="full",
    )


def chip_list(
    items: rx.Var,
    on_remove,
    input_value: rx.Var,
    on_input_change,
    on_add,
    placeholder: str,
) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.foreach(items, lambda tag: chip(tag, on_remove(tag))),
            wrap="wrap",
            spacing="2",
        ),
        rx.hstack(
            rx.input(
                value=input_value,
                on_change=on_input_change,
                placeholder=placeholder,
                size="1",
                on_key_down=lambda k: rx.cond(k == "Enter", on_add, rx.noop()),
            ),
            rx.button("Add", on_click=on_add, size="1", variant="outline", color_scheme="bronze"),
            spacing="2",
        ),
        spacing="2",
        align="start",
        width="100%",
    )


def rejection_menu(post_id: rx.Var) -> rx.Component:
    return rx.menu.root(
        rx.menu.trigger(rx.button("Reject", color_scheme="red", variant="outline", size="2")),
        rx.menu.content(
            *[
                rx.menu.item(reason, on_click=DashboardState.reject(post_id, reason))
                for reason in REJECTION_REASONS
            ]
        ),
    )


def sources_list(sources: rx.Var) -> rx.Component:
    return rx.cond(
        sources.length() > 0,
        rx.vstack(
            rx.text("Sources", size="2", weight="medium", class_name="hud-muted"),
            rx.foreach(
                sources,
                lambda s: rx.link(s["title"], href=s["url"], size="2", is_external=True),
            ),
            spacing="1",
            align="start",
        ),
        rx.fragment(),
    )


def post_card(post: PostView) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(post.post_type, variant="outline"),
                status_pill(post.status),
                rx.spacer(),
                rx.select(
                    WEEKDAYS,
                    value=post.suggested_day,
                    on_change=lambda v: DashboardState.set_suggested_day(post.id, v),
                    size="1",
                ),
                width="100%",
                align="center",
            ),
            rx.text_area(
                value=post.draft_text,
                on_change=lambda v: DashboardState.set_draft_text(post.id, v),
                on_blur=lambda _: DashboardState.save_draft_text(post.id),
                width="100%",
                min_height="140px",
                resize="vertical",
            ),
            rx.text("Hashtags", size="2", weight="medium", class_name="hud-muted"),
            chip_list(
                post.hashtags,
                lambda tag: DashboardState.remove_hashtag(post.id, tag),
                post.new_hashtag_input,
                lambda v: DashboardState.set_new_hashtag_input(post.id, v),
                DashboardState.add_hashtag(post.id),
                "add hashtag",
            ),
            rx.text("Tags", size="2", weight="medium", class_name="hud-muted"),
            chip_list(
                post.tags,
                lambda tag: DashboardState.remove_tag(post.id, tag),
                post.new_tag_input,
                lambda v: DashboardState.set_new_tag_input(post.id, v),
                DashboardState.add_tag(post.id),
                "add tag / @mention",
            ),
            sources_list(post.sources),
            rx.text("Compliance note", size="2", weight="medium", class_name="hud-muted"),
            rx.text_area(
                value=post.compliance_note,
                on_change=lambda v: DashboardState.set_compliance_note(post.id, v),
                on_blur=lambda _: DashboardState.save_compliance_note(post.id),
                width="100%",
                min_height="80px",
                resize="vertical",
            ),
            rx.cond(
                post.status == "rejected",
                rx.box(f"Rejected: {post.rejection_reason}", class_name="hud-pill hud-pill-rejected"),
                rx.fragment(),
            ),
            rx.cond(
                post.status == "published",
                rx.hstack(
                    rx.input(
                        value=post.likes_input,
                        on_change=lambda v: DashboardState.set_likes_input(post.id, v),
                        on_blur=lambda _: DashboardState.save_likes(post.id),
                        placeholder="likes",
                        size="2",
                        width="7rem",
                    ),
                    rx.input(
                        value=post.comments_input,
                        on_change=lambda v: DashboardState.set_comments_input(post.id, v),
                        on_blur=lambda _: DashboardState.save_comments(post.id),
                        placeholder="comments",
                        size="2",
                        width="7rem",
                    ),
                    spacing="2",
                ),
                rx.fragment(),
            ),
            rx.hstack(
                rx.cond(
                    post.status == "drafted",
                    rx.hstack(
                        rx.button("Approve", on_click=DashboardState.approve(post.id), **PRIMARY_CTA),
                        rejection_menu(post.id),
                        spacing="2",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    post.status == "approved",
                    rx.vstack(
                        rx.text(
                            "Copy into LinkedIn's composer, then mark it published once it's live.",
                            size="1",
                            class_name="hud-muted",
                        ),
                        rx.hstack(
                            rx.button(
                                "Copy text",
                                on_click=rx.set_clipboard(post.draft_text),
                                **SECONDARY_CTA,
                            ),
                            rx.button(
                                "Mark published",
                                on_click=DashboardState.mark_published(post.id),
                                **PRIMARY_CTA,
                            ),
                            spacing="2",
                        ),
                        spacing="1",
                        align="start",
                    ),
                    rx.fragment(),
                ),
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def day_section(day: str) -> rx.Component:
    """One day's worth of drafts, full width, stacked vertically underneath its own
    heading - replaces the old side-by-side scrolling day columns (too cramped to
    read, needed horizontal scrolling to see other days)."""
    posts = DashboardState.posts_by_day[day]
    return rx.cond(
        posts.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.heading(day, size="4"),
                rx.badge(posts.length(), variant="soft", color_scheme="bronze"),
                spacing="2",
                align="center",
            ),
            rx.vstack(rx.foreach(posts, post_card), spacing="4", width="100%"),
            spacing="3",
            width="100%",
            padding_bottom="1rem",
        ),
        rx.fragment(),
    )


def review_queue_section() -> rx.Component:
    return rx.vstack(
        rx.heading("This week's drafts", size="5"),
        rx.cond(
            DashboardState.posts.length() > 0,
            rx.vstack(
                *[day_section(day) for day in DISPLAY_DAYS],
                spacing="5",
                width="100%",
            ),
            rx.text("Nothing waiting for review right now.", size="2", class_name="hud-muted"),
        ),
        spacing="3",
        width="100%",
    )


def bank_row_card(row: BankView) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.badge(row.tier, color_scheme=rx.match(row.tier, ("high", "green"), ("mid", "amber"), "gray")),
                    rx.badge(row.category, variant="outline"),
                    spacing="2",
                ),
                rx.text(row.summary, size="2"),
                rx.link(row.source_title, href=row.source_url, size="1", is_external=True),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.button("Generate draft", on_click=DashboardState.generate_from_bank(row.id), size="2", **PRIMARY_CTA),
            width="100%",
            align="start",
        ),
        width="100%",
    )


def topic_bank_section() -> rx.Component:
    return rx.vstack(
        rx.heading("Topic bank", size="5"),
        rx.text(
            "Unused findings, high tier first - generate a draft directly, or leave it banked.",
            size="2",
            class_name="hud-muted",
        ),
        rx.cond(
            DashboardState.bank_rows.length() > 0,
            rx.vstack(rx.foreach(DashboardState.bank_rows, bank_row_card), spacing="2", width="100%"),
            rx.text("Nothing banked right now.", size="2", class_name="hud-muted"),
        ),
        spacing="3",
        width="100%",
    )


def history_row(post: PostView) -> rx.Component:
    return rx.hstack(
        status_pill(post.status),
        rx.badge(post.post_type, variant="outline", size="1"),
        rx.text(post.created_at_str, size="1", class_name="hud-muted", min_width="3.5rem"),
        rx.text(
            post.draft_text,
            size="2",
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            flex="1",
        ),
        rx.button(
            "Reuse as new post",
            size="1",
            on_click=DashboardState.reuse_as_new_topic(post.id),
            **SECONDARY_CTA,
        ),
        width="100%",
        align="center",
        spacing="3",
        padding="0.6rem 0",
        border_bottom="1px solid var(--border)",
    )


def history_week_group(week_entry: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.text(week_entry[0], size="2", weight="medium", class_name="hud-mono hud-muted"),
        rx.vstack(rx.foreach(week_entry[1], history_row), spacing="0", width="100%"),
        spacing="2",
        width="100%",
    )


def history_section() -> rx.Component:
    return rx.vstack(
        rx.heading("Past weeks", size="5"),
        rx.text(
            f"Everything from the last {HISTORY_WEEKS_LIMIT} weeks, whatever happened to "
            "it. Spot a thin week? Click \"Reuse as new post\" to line up a catch-up draft.",
            size="2",
            class_name="hud-muted",
        ),
        rx.cond(
            DashboardState.history_by_week.length() > 0,
            rx.vstack(
                rx.foreach(DashboardState.history_by_week, history_week_group),
                spacing="5",
                width="100%",
            ),
            rx.text("No history yet.", size="2", class_name="hud-muted"),
        ),
        spacing="3",
        width="100%",
    )


def forced_topic_chip(item: ForcedTopicView) -> rx.Component:
    return rx.hstack(
        rx.badge(item.category, variant="outline", size="1"),
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


def quick_actions_section() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Quick actions", size="5"),
            rx.text(
                "Skip the wait - draft something now, run the research scan on demand, "
                "or queue a topic to be searched next time it runs.",
                size="2",
                class_name="hud-muted",
            ),
            rx.grid(
                # Generate a post right now
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
                        placeholder="Topic - e.g. WPA's latest Which? award",
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
                # Run research now
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
                # Force next search topics
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
                            rx.foreach(DashboardState.forced_topics, forced_topic_chip),
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


def email_settings_section() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Email reminders", size="5"),
            rx.text(
                "A weekly nudge to send in a personal story, and a digest of the "
                "week's posts every Sunday around midday. Both go to the same address.",
                size="2",
                class_name="hud-muted",
            ),
            rx.hstack(
                rx.input(
                    value=DashboardState.email_recipient,
                    on_change=DashboardState.set_email_recipient,
                    placeholder="her email address",
                    size="2",
                    width="100%",
                ),
                rx.select(
                    WEEKDAYS,
                    value=DashboardState.email_reminder_day,
                    on_change=DashboardState.set_email_reminder_day,
                    size="2",
                ),
                rx.button("Save", on_click=DashboardState.save_email_settings_click, size="2", **SECONDARY_CTA),
                spacing="2",
                width="100%",
                align="center",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def upload_box() -> rx.Component:
    return rx.vstack(
        rx.heading("Weekly input", size="5"),
        rx.text(
            "Text, photo, or audio - whatever's easiest. Video isn't supported.",
            size="2",
            class_name="hud-muted",
        ),
        rx.select(
            POST_TYPES,
            value=DashboardState.upload_post_type,
            on_change=DashboardState.set_upload_post_type,
            size="2",
        ),
        rx.text_area(
            value=DashboardState.upload_text,
            on_change=DashboardState.set_upload_text,
            placeholder="Write a quick note...",
            width="100%",
            resize="vertical",
        ),
        rx.button(
            "Draft from note",
            on_click=DashboardState.submit_text_upload,
            loading=DashboardState.is_busy,
            **PRIMARY_CTA,
        ),
        rx.upload(
            rx.vstack(
                rx.icon("upload", size=24),
                rx.text("Drop a photo or audio file, or click to browse"),
            ),
            id="weekly_upload",
            accept={
                "image/png": [".png"],
                "image/jpeg": [".jpg", ".jpeg"],
                "image/webp": [".webp"],
                "audio/wav": [".wav"],
                "audio/mpeg": [".mp3"],
                "audio/x-m4a": [".m4a"],
            },
            max_files=1,
            border="1px dashed var(--gray-8)",
            padding="1.5rem",
            border_radius="8px",
        ),
        rx.button(
            "Upload & draft",
            on_click=DashboardState.handle_upload(rx.upload_files(upload_id="weekly_upload")),
            loading=DashboardState.is_busy,
            **PRIMARY_CTA,
        ),
        spacing="3",
        width="100%",
    )
