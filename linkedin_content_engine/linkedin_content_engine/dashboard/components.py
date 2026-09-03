"""Shared low-level UI building blocks, reused across the dashboard's separate pages."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.scheduling import WEEKLY_CAP
from linkedin_content_engine.dashboard.state import (
    POST_TYPES,
    REJECTION_REASONS,
    WEEKDAYS,
    DashboardState,
    DayPlanView,
    PostView,
    StatBreakdownItem,
    WeekPlanView,
    humanize,
)

PRIMARY_CTA = {"color_scheme": "bronze", "variant": "solid"}
SECONDARY_CTA = {"color_scheme": "bronze", "variant": "outline"}


_SELECT_TRIGGER_PROPS = ["id", "placeholder", "variant", "radius", "width", "flex_shrink"]


def type_select(options: list[str], value, on_change, **props) -> rx.Component:
    """A select where the option shown is humanized ("no_post" -> "No Post") but the
    stored/emitted value stays the raw snake_case string - request: "I don't like the
    personal_content no_post... make them plain text so it looks better." Reflex's
    high-level rx.select only supports one string as both label and value, so this
    rebuilds the same trigger/content/root split rx.select itself uses (see
    HighLevelSelect.create) with a separate label."""
    trigger_props = {k: props.pop(k) for k in _SELECT_TRIGGER_PROPS if k in props}
    return rx.select.root(
        rx.select.trigger(**trigger_props),
        rx.select.content(
            rx.select.group(*[rx.select.item(humanize(opt), value=opt) for opt in options]),
        ),
        value=value,
        on_change=on_change,
        **props,
    )

NAV_ITEMS = [
    ("Home", "/"),
    ("Review", "/review"),
    ("Accepted", "/accepted"),
    ("Rejected", "/rejected"),
    ("Topic Bank", "/topic-bank"),
    ("Past Weeks", "/history"),
    ("Statistics", "/statistics"),
    ("Voice", "/voice"),
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


def stat_card(label: str, value: rx.Var, ghost: bool = False) -> rx.Component:
    """ghost=True is the "derived from the numbers above" style (Home's Acceptance
    Rate/Avg Time row) - dashed outline, transparent fill, smaller number - so it
    doesn't read as a fifth-through-seventh stat of equal weight to the pipeline
    counts above it."""
    return rx.box(
        rx.vstack(
            rx.text(label, class_name="hud-stat-label"),
            rx.text(value, class_name="hud-stat-value-small" if ghost else "hud-stat-value"),
            spacing="1",
        ),
        class_name="hud-stat-ghost" if ghost else "hud-surface-2",
        padding="var(--pad)",
    )


def empty_state(icon: str, heading: str, body: str) -> rx.Component:
    """Shared empty state for Review/Rejected/Topic Bank/Past Weeks, replacing bare
    muted text (design-reference.html §2: "EmptyState component")."""
    return rx.box(
        rx.icon(icon, size=32),
        rx.heading(heading, size="4", margin_top="0.875rem", margin_bottom="0.375rem"),
        rx.text(body, size="2", class_name="hud-muted"),
        class_name="hud-empty-state",
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
                size="2",
                flex="1",
                min_width="0",
                on_key_down=lambda k: rx.cond(k == "Enter", on_add, rx.noop()),
            ),
            rx.button("Add", on_click=on_add, size="2", flex_shrink="0", **SECONDARY_CTA),
            spacing="2",
            width="100%",
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
            rx.cond(
                post.funnel_stage != "",
                rx.hstack(
                    rx.badge(post.funnel_stage, variant="surface", color_scheme="amber"),
                    rx.badge(post.hook_posture_label, variant="surface"),
                    rx.badge(post.length_bucket_label, variant="surface"),
                    rx.badge(post.structural_format_label, variant="surface"),
                    rx.badge(post.media_pairing_label, variant="surface"),
                    spacing="2",
                    wrap="wrap",
                ),
            ),
            rx.cond(
                post.media_note != "",
                rx.text(f"Media: {post.media_note}", size="1", class_name="hud-muted"),
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
                    rx.vstack(
                        rx.text("Likes", size="2", weight="medium", class_name="hud-muted"),
                        rx.input(
                            value=post.likes_input,
                            on_change=lambda v: DashboardState.set_likes_input(post.id, v),
                            on_blur=lambda _: DashboardState.save_likes(post.id),
                            placeholder="0",
                            size="2",
                            width="9rem",
                        ),
                        spacing="1",
                    ),
                    rx.vstack(
                        rx.text("Comments", size="2", weight="medium", class_name="hud-muted"),
                        rx.input(
                            value=post.comments_input,
                            on_change=lambda v: DashboardState.set_comments_input(post.id, v),
                            on_blur=lambda _: DashboardState.save_comments(post.id),
                            placeholder="0",
                            size="2",
                            width="9rem",
                        ),
                        spacing="1",
                    ),
                    spacing="3",
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


def accepted_filter_bar() -> rx.Component:
    """All / Approved (not yet published) / Published toggle - request: 'a filter for
    looking at accepted and looking at published ones... don't want to sift through
    ones that haven't been published yet' when logging likes/comments.

    A single bordered segmented control, not a second row of pill buttons - the week
    selector above it is a different kind of filter (which week) and needs to read as
    visually distinct from this one (which status), per design-reference.html §5."""
    options = [("all", "All"), ("approved", "Accepted, not published"), ("published", "Published")]
    return rx.hstack(
        *[
            rx.box(
                rx.text(label, size="1", weight="medium"),
                on_click=DashboardState.set_accepted_status_filter(value),
                padding="0.4rem 0.75rem",
                cursor="pointer",
                background=rx.cond(
                    DashboardState.accepted_status_filter == value, "var(--accent-terracotta)", "transparent"
                ),
                color=rx.cond(DashboardState.accepted_status_filter == value, "white", "var(--text-muted)"),
                border_right=rx.cond(value != "published", "1px solid var(--border-strong)", "none"),
            )
            for value, label in options
        ],
        display="inline-flex",
        border="1px solid var(--border-strong)",
        border_radius="var(--radius)",
        overflow="hidden",
        spacing="0",
        width="fit-content",
    )


def week_selector_bar() -> rx.Component:
    """This week / next week / +2 / +3 - request: 'select through the weeks almost
    like a calendar... four weeks you can look at and plan ahead for'.

    Unrolled as 4 static buttons (always exactly 4 weeks) rather than rx.foreach over
    DashboardState.week_options - visual review showed the active week never rendered
    solid the way the (plain Python loop, no foreach) filter bar below it does. The
    foreach version compared a dict-indexed loop-var string cast via .to(int) against
    the state int; this compares the state int directly against a known Python int per
    button, the same reliable pattern the filter bar already uses."""
    return rx.hstack(
        *[
            rx.button(
                DashboardState.week_options[i]["label"],
                size="2",
                on_click=DashboardState.set_selected_week_offset(i),
                variant=rx.cond(DashboardState.selected_week_offset == i, "solid", "outline"),
                color_scheme="bronze",
            )
            for i in range(4)
        ],
        spacing="2",
        wrap="wrap",
    )


def day_plan_cell(day: DayPlanView) -> rx.Component:
    """One day in the 4-week planning calendar: shows any note already pencilled in
    for that date, or lets you add one - request: 'tell the bot beforehand what you
    want to go into those so it knows what to focus on' (e.g. a Halloween post for
    31 Oct, or 'focus on the new statement release' for a known announcement date).

    Today gets a 2px terracotta border instead of the default, so it's identifiable at
    a glance across the 7-card grid without reading every "Today" label
    (design-reference.html §5)."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(day.day_label, size="2", weight="medium"),
                rx.cond(day.is_today, rx.badge("Today", color_scheme="bronze", variant="soft"), rx.fragment()),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.cond(
                day.holiday_name != "",
                rx.badge(f"🎉 {day.holiday_name}", variant="soft", size="1", color_scheme="amber"),
                rx.fragment(),
            ),
            rx.cond(
                day.note != None,  # noqa: E711 - rx.Var equality, not a Python None-check
                rx.vstack(
                    rx.text("Notes", size="1", weight="medium", class_name="hud-muted"),
                    rx.text(day.note.note_text, size="2", class_name="hud-muted", white_space="pre-wrap"),
                    rx.hstack(
                        rx.badge(day.note.post_type_label, variant="soft", size="1"),
                        rx.spacer(),
                        rx.button(
                            "Generate draft",
                            size="1",
                            on_click=DashboardState.generate_from_planned_note(day.note.id),
                            loading=DashboardState.is_busy,
                            **SECONDARY_CTA,
                        ),
                        rx.icon(
                            "x",
                            size=14,
                            cursor="pointer",
                            on_click=DashboardState.delete_planned_note(day.note.id),
                        ),
                        width="100%",
                        align="center",
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.vstack(
                    rx.text("Notes", size="1", weight="medium", class_name="hud-muted"),
                    rx.text_area(
                        value=DashboardState.note_drafts[day.date],
                        on_change=lambda v: DashboardState.set_note_draft(day.date, v),
                        placeholder="Pencil in what this day should be about...",
                        size="1",
                        min_height="60px",
                        width="100%",
                    ),
                    rx.hstack(
                        type_select(
                            POST_TYPES,
                            value=DashboardState.note_draft_post_types[day.date],
                            on_change=lambda v: DashboardState.set_note_draft_post_type(day.date, v),
                            size="1",
                            flex="1",
                        ),
                        rx.button(
                            "Save note",
                            size="1",
                            on_click=DashboardState.save_planned_note(day.date),
                            flex_shrink="0",
                            **SECONDARY_CTA,
                        ),
                        width="100%",
                        spacing="2",
                        align="center",
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        class_name=rx.cond(day.is_today, "hud-card-today", ""),
        width="100%",
    )


def week_plan_section(week: WeekPlanView) -> rx.Component:
    """One week's section of the month planning calendar: a heading with how many
    posts are already committed, two catch-up buttons, and its 7 day cells.

    "Plan this week" (request: "a button to actually draft the post for the next
    week... it automatically just selects post for the week") reads the weekday
    template + holiday awareness day by day. "Fill this week" (older, simpler) just
    tops the raw count up from the topic bank regardless of day-of-week - both stay,
    since they answer slightly different questions."""
    return rx.vstack(
        rx.hstack(
            rx.heading(week.week_label, size="3"),
            rx.text(
                f"{week.already_scheduled}/{WEEKLY_CAP} committed",
                size="1",
                class_name="hud-muted",
            ),
            rx.spacer(),
            rx.button(
                "Plan this week",
                size="1",
                on_click=DashboardState.plan_week(week.monday),
                loading=DashboardState.is_busy,
                **PRIMARY_CTA,
            ),
            rx.button(
                "Fill this week",
                size="1",
                on_click=DashboardState.fill_week(week.monday),
                loading=DashboardState.is_busy,
                **SECONDARY_CTA,
            ),
            width="100%",
            align="center",
            wrap="wrap",
        ),
        rx.grid(
            rx.foreach(week.days, day_plan_cell),
            columns=rx.breakpoints(initial="1", sm="2", lg="4"),
            spacing="3",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def planning_calendar() -> rx.Component:
    """The full month (4-week) planning horizon (request: "plan a month of posts out,
    not just a week"), one section per week - not tied to the Accepted-posts week
    filter above it, so the whole month is always visible without extra clicks."""
    return rx.vstack(
        rx.text(
            "Plan ahead - pencil in what a day should be about before it's time to "
            "draft it, or use \"Fill this week\" to catch a thin week up automatically.",
            size="2",
            class_name="hud-muted",
        ),
        rx.foreach(DashboardState.month_plan, week_plan_section),
        spacing="5",
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
    """No background box on the active tab - text-muted for inactive tabs, text colour
    plus a 2px terracotta underline for the active one, full-width border under the
    whole row (design-reference.html §2: "Top nav")."""
    return rx.hstack(
        *[
            rx.link(
                rx.text(label, size="2", weight="medium" if href == active else "regular"),
                href=href,
                class_name="hud-muted" if href != active else "",
                style={"color": "var(--text)"} if href == active else {},
                text_decoration="none",
                padding_bottom="0.875rem",
                border_bottom=f"2px solid {'var(--accent-terracotta)' if href == active else 'transparent'}",
            )
            for label, href in NAV_ITEMS
        ],
        spacing="6",
        wrap="wrap",
        width="100%",
        border_bottom="1px solid var(--border)",
        margin_bottom="1.5rem",
    )


def page_shell(active: str, *children) -> rx.Component:
    """Wraps every page's content: header, nav, status banner, consistent padding."""
    return rx.box(
        rx.container(
            rx.hstack(
                rx.vstack(
                    rx.heading("Content Engine", size="6"),
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


def stat_bar_row(item: StatBreakdownItem) -> rx.Component:
    """One labelled bar in a Statistics-page breakdown card - gold fill, since these
    are data, not an action (design-reference.html's gold/terracotta split)."""
    return rx.vstack(
        rx.hstack(
            rx.text(item.label, size="2"),
            rx.spacer(),
            rx.text(item.count, size="2", class_name="hud-mono hud-muted"),
            width="100%",
        ),
        rx.box(
            rx.box(
                width=f"{item.pct}%",
                height="100%",
                background="var(--accent-gold)",
                border_radius="var(--radius)",
            ),
            width="100%",
            height="8px",
            background="var(--bg-surface-2)",
            border_radius="var(--radius)",
            overflow="hidden",
        ),
        spacing="1",
        width="100%",
    )


def stat_breakdown_card(title: str, items: rx.Var) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading(title, size="3"),
            rx.cond(
                items.length() > 0,
                rx.vstack(rx.foreach(items, stat_bar_row), spacing="3", width="100%"),
                rx.text("No data yet.", size="2", class_name="hud-muted"),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )
