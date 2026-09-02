"""Placeholder corpus for smoke-testing the voice pipeline before your real posts exist.

These are made-up, generic-sounding posts - NOT your real voice. They only exist to
prove the pipeline runs end-to-end and that its output changes when the input does. Wipe
them with `clear_all_samples()` (ingestion.py) before feeding in your real corpus, so the
real voice profile isn't diluted by this placeholder text.

Usage (from the linkedin_content_engine/ app directory, with the venv active):
    python -m linkedin_content_engine.voice_engine.seed_demo_samples
"""

from linkedin_content_engine.voice_engine.ingestion import add_sample

_DEMO_POSTS = [
    """Spent this week pairing with an AI coding assistant on a project I'd normally
have blocked out three days for. Took one.

Not because the AI wrote better code than I would have. It didn't. It just handled
the boilerplate so I could spend my time on the parts that actually needed judgment.

That's the pattern I keep seeing: the tool doesn't replace the thinking, it clears
space for it.""",
    """Three months into my degree and the thing nobody warned me about is how much of
it is unlearning assumptions I didn't know I had.

Today's was a small one - a modelling approach I'd been doing "the long way" for
years, because I'd never been shown the shorter one.

Grateful for the reminder that being new at something is still worth it.""",
    """New research on AI adoption in enterprise teams landed this morning and one
number stood out: the teams seeing the biggest gains aren't the ones automating the
most tasks. They're the ones automating the most annoying ones.

Small distinction. Big difference in outcome.

Worth five minutes if you're thinking about where to start.""",
    """Quick one: if someone on your team asks "why are we even using this tool," don't
treat it as resistance.

Answer it properly and you'll get a better rollout. Wave it off and you'll get quiet
non-adoption for the next six months.""",
    """Shipped a small side project this weekend - nothing that'll change the world,
but it's the first thing I've built end to end using an AI pair-programmer the whole
way through.

The interesting part wasn't the speed. It was how much earlier I could test an idea
before committing to it properly.""",
]


def seed_demo_samples() -> int:
    """Insert the placeholder demo corpus. Returns the number of samples added."""
    for post in _DEMO_POSTS:
        add_sample(post, source_type="linkedin_post")
    return len(_DEMO_POSTS)


if __name__ == "__main__":
    count = seed_demo_samples()
    print(f"Seeded {count} placeholder demo samples (NOT your real voice - wipe before going live).")
