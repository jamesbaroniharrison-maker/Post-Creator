"""UI component builders for the review dashboard (spec Â§3d)."""

import reflex as rx

from wpa_content_engine.dashboard.state import (
    DISPLAY_DAYS,
    POST_TYPES,
    REJECTION_REASONS,
    WEEKDAYS,
    BankView,
    DashboardState,
    PostView,
)

STATUS_COLORS = {
    "drafted": "gray",
    "approved": "blue",
    "published": "green",
    "rejected": "red",
}


def stat_card(label: str, value: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(label, size="2", color="gray"),
            rx.text(value, size="6", weight="bold"),
            spacing="1",
        ),
        padding="0.75rem 1rem",
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
            rx.button("Add", on_click=on_add, size="1", variant="soft"),
            spacing="2",
        ),
        spacing="2",
        align="start",
        width="100%",
    )


def rejection_menu(post_id: rx.Var) -> rx.Component:
    return rx.menu.root(
        rx.menu.trigger(rx.button("Reject", color_scheme="red", variant="soft", size="2")),
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
            rx.text("Sources", size="2", weight="bold", color="gray"),
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
                rx.badge(post.status, color_scheme=rx.match(
                    post.status,
                    ("drafted", "gray"),
                    ("approved", "blue"),
                    ("published", "green"),
                    ("rejected", "red"),
                    "gray",
                )),
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
                min_height="120px",
            ),
            rx.text("Hashtags", size="2", weight="bold", color="gray"),
            chip_list(
                post.hashtags,
                lambda tag: DashboardState.remove_hashtag(post.id, tag),
                post.new_hashtag_input,
                lambda v: DashboardState.set_new_hashtag_input(post.id, v),
                DashboardState.add_hashtag(post.id),
                "add hashtag",
            ),
            rx.text("Tags", size="2", weight="bold", color="gray"),
            chip_list(
                post.tags,
                lambda tag: DashboardState.remove_tag(post.id, tag),
                post.new_tag_input,
                lambda v: DashboardState.set_new_tag_input(post.id, v),
                DashboardState.add_tag(post.id),
                "add tag / @mention",
            ),
            sources_list(post.sources),
            rx.text("Compliance note", size="2", weight="bold", color="gray"),
            rx.text_area(
                value=post.compliance_note,
                on_change=lambda v: DashboardState.set_compliance_note(post.id, v),
                on_blur=lambda _: DashboardState.save_compliance_note(post.id),
                width="100%",
                min_height="60px",
            ),
            rx.cond(
                post.status == "rejected",
                rx.badge(f"Rejected: {post.rejection_reason}", color_scheme="red"),
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
                        size="1",
                        width="6rem",
                    ),
                    rx.input(
                        value=post.comments_input,
                        on_change=lambda v: DashboardState.set_comments_input(post.id, v),
                        on_blur=lambda _: DashboardState.save_comments(post.id),
                        placeholder="comments",
                        size="1",
                        width="6rem",
                    ),
                    spacing="2",
                ),
                rx.fragment(),
            ),
            rx.hstack(
                rx.cond(
                    post.status == "drafted",
                    rx.hstack(
                        rx.button("Approve", on_click=DashboardState.approve(post.id), color_scheme="green"),
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
                            color="gray",
                        ),
                        rx.hstack(
                            rx.button(
                                "Copy text",
                                on_click=rx.set_clipboard(post.draft_text),
                                variant="soft",
                            ),
                            rx.button(
                                "Mark published",
                                on_click=DashboardState.mark_published(post.id),
                                color_scheme="green",
                                variant="soft",
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


def day_column(day: str) -> rx.Component:
    return rx.vstack(
        rx.heading(day, size="3"),
        rx.foreach(DashboardState.posts_by_day[day], post_card),
        spacing="3",
        align="start",
        width="100%",
        min_width="320px",
    )


def review_queue_section() -> rx.Component:
    return rx.vstack(
        rx.heading("This week's drafts", size="5"),
        rx.scroll_area(
            rx.hstack(
                *[day_column(day) for day in DISPLAY_DAYS],
                spacing="4",
                align="start",
            ),
            type="auto",
            scrollbars="horizontal",
            width="100%",
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
            rx.button("Generate draft", on_click=DashboardState.generate_from_bank(row.id), size="2"),
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
            color="gray",
        ),
        rx.cond(
            DashboardState.bank_rows.length() > 0,
            rx.vstack(rx.foreach(DashboardState.bank_rows, bank_row_card), spacing="2", width="100%"),
            rx.text("Nothing banked right now.", size="2", color="gray"),
        ),
        spacing="3",
        width="100%",
    )


def upload_box() -> rx.Component:
    return rx.vstack(
        rx.heading("Weekly input", size="5"),
        rx.text(
            "Text, photo, or audio - whatever's easiest. Video isn't supported.",
            size="2",
            color="gray",
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
        ),
        rx.button(
            "Draft from note",
            on_click=DashboardState.submit_text_upload,
            loading=DashboardState.is_busy,
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
            variant="soft",
        ),
        rx.cond(
            DashboardState.status_message != "",
            rx.callout(DashboardState.status_message, size="1"),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
    )
