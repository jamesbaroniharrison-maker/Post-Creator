"""Shared low-level UI building blocks, reused across the dashboard's separate pages."""

import reflex as rx
import reflex_local_auth

from wpa_content_engine.dashboard.state import REJECTION_REASONS, WEEKDAYS, DashboardState, PostView

PRIMARY_CTA = {"color_scheme": "bronze", "variant": "solid"}
SECONDARY_CTA = {"color_scheme": "bronze", "variant": "outline"}

NAV_ITEMS = [
    ("Home", "/"),
    ("Review", "/review"),
    ("Accepted", "/accepted"),
    ("Rejected", "/rejected"),
    ("Topic Bank", "/topic-bank"),
    ("Past Weeks", "/history"),
    ("Settings", "/settings"),
]


def status_pill(status: rx.Var, label: rx.Var) -> rx.Component:
    return rx.box(
        label,
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
            rx.button("Add", on_click=on_add, size="1", **SECONDARY_CTA),
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


def post_editable_body(post: PostView, editable: bool = True) -> rx.Component:
    """The shared middle of a post card: text, chips, sources, compliance note.
    Read-only (no text areas/chip editing) when editable=False (Rejected/history views)."""
    if not editable:
        return rx.vstack(
            rx.text(post.draft_text, size="3", white_space="pre-wrap"),
            rx.cond(
                post.hashtags.length() > 0,
                rx.hstack(rx.foreach(post.hashtags, lambda t: rx.badge(t, variant="soft")), wrap="wrap", spacing="2"),
                rx.fragment(),
            ),
            sources_list(post.sources),
            spacing="3",
            width="100%",
        )
    return rx.vstack(
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
        spacing="3",
        width="100%",
    )


def review_post_card(post: PostView) -> rx.Component:
    """Review page: Accept / Redraft / Reject."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(post.post_type_label, variant="outline"),
                status_pill(post.status, post.status_label),
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
            post_editable_body(post),
            rx.hstack(
                rx.button("Accept", on_click=DashboardState.accept(post.id), **PRIMARY_CTA),
                rx.button(
                    "Redraft",
                    on_click=DashboardState.redraft(post.id),
                    loading=DashboardState.is_busy,
                    **SECONDARY_CTA,
                ),
                rejection_menu(post.id),
                spacing="2",
                wrap="wrap",
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def accepted_post_card(post: PostView) -> rx.Component:
    """Accepted page: copy/mark-published, or likes+comments once published."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(post.post_type_label, variant="outline"),
                status_pill(post.status, post.status_label),
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
            post_editable_body(post),
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
                rx.hstack(
                    rx.button("Copy text", on_click=rx.set_clipboard(post.draft_text), **SECONDARY_CTA),
                    rx.button("Mark published", on_click=DashboardState.mark_published(post.id), **PRIMARY_CTA),
                    spacing="2",
                ),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def rejected_post_card(post: PostView) -> rx.Component:
    """Rejected page: read-only, only the last 5 ever shown (scheduling.py prunes the rest)."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(post.post_type_label, variant="outline"),
                status_pill(post.status, post.status_label),
                rx.spacer(),
                rx.text(post.created_at_str, size="1", class_name="hud-muted"),
                width="100%",
                align="center",
            ),
            post_editable_body(post, editable=False),
            rx.box(f"Reason: {post.rejection_reason}", class_name="hud-pill hud-pill-rejected"),
            rx.button(
                "Reuse as new post",
                size="2",
                on_click=DashboardState.reuse_as_new_topic(post.id),
                **SECONDARY_CTA,
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def nav_bar(active: str) -> rx.Component:
    return rx.hstack(
        *[
            rx.link(
                rx.text(label, size="2", weight="medium" if href == active else "regular"),
                href=href,
                class_name="hud-muted" if href != active else "",
                style={"color": "var(--accent-bronze)"} if href == active else {},
                text_decoration="none",
                padding="0.4rem 0.75rem",
                border_radius="var(--radius)",
                background="var(--bg-surface-2)" if href == active else "transparent",
            )
            for label, href in NAV_ITEMS
        ],
        spacing="2",
        wrap="wrap",
        width="100%",
        padding_bottom="1rem",
    )


def page_shell(active: str, *children) -> rx.Component:
    """Wraps every page's content: header, nav, status banner, consistent padding."""
    return rx.box(
        rx.container(
            rx.hstack(
                rx.vstack(
                    rx.heading("WPA Content Engine", size="6"),
                    rx.text("Review queue, research, and voice-matched drafting", size="2", class_name="hud-muted"),
                    spacing="0",
                ),
                rx.spacer(),
                rx.button(
                    "Log out",
                    on_click=reflex_local_auth.LoginState.do_logout,
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                ),
                width="100%",
                align="center",
                padding_bottom="1rem",
            ),
            nav_bar(active),
            rx.cond(
                DashboardState.status_message != "",
                rx.callout(
                    DashboardState.status_message,
                    icon="info",
                    width="100%",
                    margin_bottom="1rem",
                    on_click=DashboardState.clear_status_message,
                    cursor="pointer",
                ),
                rx.fragment(),
            ),
            rx.vstack(*children, spacing="6", width="100%", padding_bottom="3rem"),
            on_mount=DashboardState.load_dashboard,
            size="4",
            padding="1.5rem",
        ),
        min_height="100vh",
        background="var(--bg)",
    )
