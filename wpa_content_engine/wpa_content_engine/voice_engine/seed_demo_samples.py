"""Placeholder corpus for smoke-testing the voice pipeline before her real posts exist.

These are made-up, generic-sounding posts - NOT her real voice. They only exist to prove
the pipeline runs end-to-end and that its output changes when the input does. Wipe them
with `clear_all_samples()` (ingestion.py) before feeding in her real corpus, so the real
voice profile isn't diluted by this placeholder text.

Usage (from the wpa_content_engine/ app directory, with the venv active):
    python -m wpa_content_engine.voice_engine.seed_demo_samples
"""

from wpa_content_engine.voice_engine.ingestion import add_sample

_DEMO_POSTS = [
    """Ever wonder why private medical cover feels like a maze? You're not alone.

Today I sat with a client who'd been putting off a hospital referral for six months
because she wasn't sure what her policy actually covered. Fifteen minutes later, she
had a clear answer and a date booked.

That's the job, really. Not selling policies - making sure people actually use what
they're paying for.

What's stopping you from checking your own cover today?""",
    """Three years ago I didn't know what an excess was, let alone how to explain one.

This week I ran a workshop for forty advisers on exactly that. Funny how the things
that once felt impossible become the things you teach.

Grateful for every client who asked a "silly" question along the way - they weren't
silly, they were the reason I got better at this job.""",
    """New NHS waiting time data dropped this morning and it's worth a look if you
work in protection or PMI.

The headline number gets the attention, but the regional spread underneath is where
the real story is. Worth five minutes of anyone's time in this industry.

Link in comments.""",
    """Quick one today: if a client asks "do I actually need this," that's not an
objection. That's the best question they could ask.

Answer it honestly and you'll keep them for a decade. Dodge it and you'll lose them
in a year.""",
    """Proud to share that our team hit a milestone this quarter - every single
referral resolved within our target window, no exceptions.

Doesn't sound flashy. It is, though. Behind every one of those numbers is someone
who got seen faster because a process worked the way it was supposed to.

Thanks to everyone who made that boring, unglamorous, essential thing happen.""",
]


def seed_demo_samples() -> int:
    """Insert the placeholder demo corpus. Returns the number of samples added."""
    for post in _DEMO_POSTS:
        add_sample(post, source_type="linkedin_post")
    return len(_DEMO_POSTS)


if __name__ == "__main__":
    count = seed_demo_samples()
    print(f"Seeded {count} placeholder demo samples (NOT her real voice - wipe before going live).")
