"""Statistics: breakdowns across every post ever drafted - post type, status, and how
the CPIO/THBM content-framework variables have actually been used, plus a recent
weekly-volume view. Separate from Home's small stat cards, which are meant as a
glanceable overview, not a full analytics page (request: "add a statistics page")."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import page_shell, stat_breakdown_card
from linkedin_content_engine.dashboard.state import HISTORY_WEEKS_LIMIT, DashboardState


@reflex_local_auth.require_login
def statistics_page() -> rx.Component:
    return page_shell(
        "/statistics",
        rx.vstack(
            rx.heading("Statistics", size="5"),
            rx.text(
                "Breakdown across every post you've ever drafted, not just what's currently in play.",
                size="2",
                class_name="hud-muted",
            ),
            rx.grid(
                stat_breakdown_card("Post type", DashboardState.stats_by_post_type),
                stat_breakdown_card("Status", DashboardState.stats_by_status),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="4",
                width="100%",
            ),
            rx.heading("Content framework mix", size="4"),
            rx.text(
                "How the CPIO/THBM rotation variables have actually been used across every draft.",
                size="2",
                class_name="hud-muted",
            ),
            rx.grid(
                stat_breakdown_card("Funnel stage", DashboardState.stats_by_funnel_stage),
                stat_breakdown_card("Hook posture", DashboardState.stats_by_hook_posture),
                stat_breakdown_card("Length", DashboardState.stats_by_length_bucket),
                stat_breakdown_card("Structural format", DashboardState.stats_by_structural_format),
                stat_breakdown_card("Media pairing", DashboardState.stats_by_media_pairing),
                columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                spacing="4",
                width="100%",
            ),
            stat_breakdown_card(f"Posts per week (last {HISTORY_WEEKS_LIMIT} weeks)", DashboardState.stats_by_week),
            spacing="5",
            width="100%",
        ),
    )
