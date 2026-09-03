"""Voice: real writing samples feeding the voice-matching profile every draft is
generated against. There was no dashboard flow for this at all before - the only way
in was a CLI script (voice_engine/run.py), so the profile had been running on 5
placeholder samples since the corpus was seeded, with no way to swap in real writing
short of editing the database directly (found while looking for the highest-leverage
next improvement, not a specific request)."""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, SECONDARY_CTA, empty_state, page_shell
from linkedin_content_engine.dashboard.state import DashboardState, VoiceSampleView


def _sample_row(item: VoiceSampleView) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.badge(item.source_type_label, variant="outline", size="1"),
                rx.text(item.date_added_str, size="1", class_name="hud-muted"),
                spacing="2",
                align="center",
            ),
            rx.text(item.preview, size="2"),
            spacing="1",
            align="start",
            width="100%",
        ),
        rx.icon(
            "x",
            size=14,
            cursor="pointer",
            on_click=DashboardState.delete_voice_sample(item.id),
            class_name="hud-muted",
        ),
        width="100%",
        align="start",
        padding="0.6rem 0.75rem",
        class_name="hud-surface-2",
    )


def _samples_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Your samples", size="4"),
            rx.text(
                "Paste in real posts you've written before - LinkedIn posts you're happy "
                "with are the best source. The more of your actual writing, the more the "
                "voice profile sounds like you and not a generic placeholder.",
                size="2",
                class_name="hud-muted",
            ),
            rx.text(DashboardState.voice_profile_status, size="1", class_name="hud-muted"),
            rx.cond(
                DashboardState.voice_samples.length() > 0,
                rx.vstack(
                    rx.foreach(DashboardState.voice_samples, _sample_row),
                    spacing="2",
                    width="100%",
                ),
                empty_state(
                    "mic",
                    "No samples yet",
                    "Add at least a handful of your own posts below, then regenerate the profile.",
                ),
            ),
            rx.button(
                "Regenerate voice profile",
                on_click=DashboardState.regenerate_voice_profile,
                loading=DashboardState.is_busy,
                **PRIMARY_CTA,
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def _add_sample_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Add a sample", size="4"),
            rx.text_area(
                value=DashboardState.voice_new_sample_text,
                on_change=DashboardState.set_voice_new_sample_text,
                placeholder="Paste one of your past LinkedIn posts here...",
                width="100%",
                min_height="140px",
                resize="vertical",
            ),
            rx.button(
                "Add sample",
                on_click=DashboardState.add_voice_sample,
                width="100%",
                **SECONDARY_CTA,
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


@reflex_local_auth.require_login
def voice_page() -> rx.Component:
    return page_shell("/voice", _samples_card(), _add_sample_card())
