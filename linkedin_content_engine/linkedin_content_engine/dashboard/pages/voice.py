"""Voice: real writing samples feeding the voice-matching profile every draft is
generated against. There was no dashboard flow for this at all before - the only way
in was a CLI script (voice_engine/run.py), so the profile had been running on 5
placeholder samples since the corpus was seeded, with no way to swap in real writing
short of editing the database directly (found while looking for the highest-leverage
next improvement, not a specific request).

Two more ways to add samples, added later (request: "I'm having conversations with
Gemini... it's asking me a question, and I'm putting a text answer... I want to be
able to do [that] because I'll give the full conversation, just a straight script"):
a single Q&A pair, and a whole speaker-labeled transcript parsed into many samples at
once, previewed before anything's actually saved.
"""

import reflex as rx
import reflex_local_auth

from linkedin_content_engine.dashboard.components import PRIMARY_CTA, SECONDARY_CTA, empty_state, page_shell
from linkedin_content_engine.dashboard.state import DashboardState, VoiceConvoPairView, VoiceSampleView


def _field_label(text: str) -> rx.Component:
    return rx.text(text, size="1", weight="medium", class_name="hud-muted")


def _sample_row(item: VoiceSampleView) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.badge(item.source_type_label, variant="outline", size="1"),
                rx.text(item.date_added_str, size="1", class_name="hud-muted"),
                spacing="2",
                align="center",
            ),
            rx.cond(
                item.question_preview != "",
                rx.text(f"Q: {item.question_preview}", size="1", class_name="hud-muted"),
                rx.fragment(),
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
                "Paste in real posts you've written before, or answer a few questions "
                "below - the more of your actual writing and words, the more the voice "
                "profile sounds like you and not a generic placeholder.",
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
            rx.heading("Add a past post", size="4"),
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


def _add_qa_card() -> rx.Component:
    """One Gemini question + your answer -> one sample (request: "two boxes, one for
    gemini and the other for my response")."""
    return rx.card(
        rx.vstack(
            rx.heading("Add a Gemini Q&A", size="4"),
            rx.text(
                "One question Gemini asked you, and the answer you gave - the question "
                "is kept for context but only your answer feeds the voice profile.",
                size="2",
                class_name="hud-muted",
            ),
            _field_label("Question Gemini asked"),
            rx.text_area(
                value=DashboardState.voice_qa_question,
                on_change=DashboardState.set_voice_qa_question,
                placeholder="e.g. What's a project you're proud of recently?",
                width="100%",
                min_height="70px",
                resize="vertical",
            ),
            _field_label("Your answer"),
            rx.text_area(
                value=DashboardState.voice_qa_answer,
                on_change=DashboardState.set_voice_qa_answer,
                placeholder="What you actually said back...",
                width="100%",
                min_height="110px",
                resize="vertical",
            ),
            rx.button(
                "Add sample",
                on_click=DashboardState.add_voice_qa_sample,
                width="100%",
                **SECONDARY_CTA,
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def _convo_pair_preview(item: VoiceConvoPairView) -> rx.Component:
    return rx.vstack(
        rx.text(f"Q: {item.question}", size="1", class_name="hud-muted"),
        rx.text(item.answer, size="2"),
        spacing="1",
        align="start",
        width="100%",
        padding="0.6rem 0.75rem",
        class_name="hud-surface-2",
    )


def _add_conversation_card() -> rx.Component:
    """A whole labeled transcript, parsed into several samples at once (request:
    "I'll give the full conversation, just a straight script... I will ask gemini to
    label who is speaking"). Parsing only builds a preview - nothing is saved until
    "Add these samples" is clicked, since a labeling convention this loose is worth
    letting the user sanity-check before it lands in the corpus."""
    return rx.card(
        rx.vstack(
            rx.heading("Add a whole conversation", size="4"),
            rx.text(
                "Paste a full Gemini conversation where each turn is labeled with who's "
                "speaking - ask Gemini to label the speakers when you copy it out. Every "
                "answer you gave becomes its own sample.",
                size="2",
                class_name="hud-muted",
            ),
            rx.hstack(
                rx.vstack(
                    _field_label("Gemini's label in the transcript"),
                    rx.input(
                        value=DashboardState.voice_convo_gemini_label,
                        on_change=DashboardState.set_voice_convo_gemini_label,
                        width="100%",
                    ),
                    spacing="1",
                    align="start",
                    width="100%",
                ),
                rx.vstack(
                    _field_label("Your label in the transcript"),
                    rx.input(
                        value=DashboardState.voice_convo_me_label,
                        on_change=DashboardState.set_voice_convo_me_label,
                        width="100%",
                    ),
                    spacing="1",
                    align="start",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            _field_label("Full conversation"),
            rx.text_area(
                value=DashboardState.voice_convo_text,
                on_change=DashboardState.set_voice_convo_text,
                placeholder="Gemini: What's a project you're proud of?\nMe: Last month I built...",
                width="100%",
                min_height="160px",
                resize="vertical",
            ),
            rx.cond(
                DashboardState.voice_convo_preview.length() > 0,
                rx.vstack(
                    rx.text(
                        f"{DashboardState.voice_convo_preview.length()} answer(s) found - "
                        "check these before adding them.",
                        size="1",
                        class_name="hud-muted",
                    ),
                    rx.vstack(
                        rx.foreach(DashboardState.voice_convo_preview, _convo_pair_preview),
                        spacing="2",
                        width="100%",
                    ),
                    rx.hstack(
                        rx.button(
                            "Add these samples",
                            on_click=DashboardState.confirm_voice_convo_samples,
                            **PRIMARY_CTA,
                        ),
                        rx.button(
                            "Discard",
                            on_click=DashboardState.discard_voice_convo_preview,
                            variant="soft",
                            color_scheme="gray",
                        ),
                        spacing="2",
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.button(
                    "Preview parsed samples",
                    on_click=DashboardState.preview_voice_conversation,
                    width="100%",
                    **SECONDARY_CTA,
                ),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def _word_chip(word: rx.Var) -> rx.Component:
    return rx.badge(word, variant="soft", size="1")


def _stats_card() -> rx.Component:
    """Real, corpus-derived stats (voice_engine/similarity.py), surfaced so James
    can see what the profile is actually picking up on rather than trust it blindly.
    Both Zeta words and bigrams now feed the drafting prompt directly - bigrams were
    diagnostic-only until PMI-based ranking (vs. the original raw-frequency version)
    started producing genuinely distinctive phrases instead of generic scaffolding."""
    return rx.card(
        rx.vstack(
            rx.heading("What the profile has picked up on", size="4"),
            rx.text(
                "Words you reach for across most of what you've written, regardless of "
                "topic - these feed directly into how new posts get drafted.",
                size="2",
                class_name="hud-muted",
            ),
            rx.cond(
                DashboardState.voice_zeta_words.length() > 0,
                rx.hstack(
                    rx.foreach(DashboardState.voice_zeta_words, _word_chip),
                    spacing="2",
                    wrap="wrap",
                ),
                rx.text("Not enough corpus yet to say.", size="2", class_name="hud-muted"),
            ),
            rx.text(
                "Real two-word phrases from your own writing, ranked by how distinctive "
                "they are (not just how common) - these feed into drafting too.",
                size="2",
                class_name="hud-muted",
                margin_top="0.5rem",
            ),
            rx.cond(
                DashboardState.voice_characteristic_bigrams.length() > 0,
                rx.hstack(
                    rx.foreach(DashboardState.voice_characteristic_bigrams, _word_chip),
                    spacing="2",
                    wrap="wrap",
                ),
                rx.text("Not enough corpus yet to say.", size="2", class_name="hud-muted"),
            ),
            rx.cond(
                DashboardState.voice_syntax_summary != "",
                rx.text(
                    DashboardState.voice_syntax_summary,
                    size="2",
                    class_name="hud-muted",
                    margin_top="0.5rem",
                ),
                rx.fragment(),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


@reflex_local_auth.require_login
def voice_page() -> rx.Component:
    return page_shell(
        "/voice",
        _samples_card(),
        _stats_card(),
        _add_sample_card(),
        _add_qa_card(),
        _add_conversation_card(),
    )
