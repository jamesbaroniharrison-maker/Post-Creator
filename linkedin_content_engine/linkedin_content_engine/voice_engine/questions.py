"""Questions that would most improve the voice, and how well each area is covered.

Why: on 6 Oct 2026 his genuine samples were 15 spoken answers about life (travel, guitar, muay
thai, a breakup, people he can't stand) plus 3 old posts - and not one about AI or business
news, which is most of what this system posts. So on those topics the engine is guessing how he
talks. Answering a few of these (typed or dictated on the Voice page) fixes that faster than
anything else: each answer becomes a sample of him talking about exactly what he posts about.
"""

from __future__ import annotations

import random
import re

# What each area is about, for counting which samples cover it. Rough on purpose: it only
# decides which questions to suggest first.
AREAS: dict[str, tuple[str, ...]] = {
    "AI & tech": (
        "ai", "chatgpt", "gpt", "gemini", "claude", "model", "models", "automation", "automate",
        "software", "code", "coding", "python", "agent", "agents", "tech", "technology", "data",
        "chatbot", "chatbots", "tool", "tools", "app", "apps", "machine learning", "prompt",
    ),
    "Work & business": (
        "client", "clients", "business", "company", "companies", "job", "jobs", "career",
        "recruitment", "hiring", "boss", "manager", "team", "kpi", "kpis", "sales", "money",
        "market", "startup", "founder", "work", "office", "customer", "customers", "pitch",
        "salary", "interview", "industry", "construction", "consultant", "agency",
    ),
    "Reacting to news": (
        "news", "announced", "report", "headline", "headlines", "article", "read that",
        "saw that", "this week", "this month", "government", "policy", "prices", "economy",
    ),
}

QUESTIONS: dict[str, list[str]] = {
    "AI & tech": [
        "What's an AI tool you actually use every week, and what do you honestly think of it?",
        "What's the most overhyped thing in AI right now, and why?",
        "Someone asks you if AI is going to take their job. What do you actually tell them?",
        "What's something AI did recently that genuinely impressed you - or let you down?",
        "What do most businesses get wrong when they try to 'add AI'?",
        "Explain what you actually build for clients, like you're telling a mate down the pub.",
        "Where do you draw the line on using AI for your own writing or work?",
        "A small business owner asks where to start with AI. What do you say?",
        "What's an AI headline from the last few weeks that annoyed you, and why?",
    ],
    "Work & business": [
        "What did recruitment teach you about how companies really hire?",
        "What's a business 'best practice' you think is rubbish?",
        "What does a good client look like - and a bad one?",
        "What's the hardest thing about starting something from zero?",
        "What's your honest take on the job market for people your age right now?",
        "Tell me about something that went wrong at work and what you'd do differently.",
        "What advice would you give someone just starting out in your field?",
        "What's something you changed your mind about this year?",
    ],
    "Reacting to news": [
        "House prices, rent, cost of living: how does it actually feel from where you're standing?",
        "Pick a news story from this week and tell me what you really think about it.",
        "Disagree with a popular LinkedIn opinion. Go.",
        "What's a trend everyone's excited about that you think will fizzle out?",
        "What's a story you read recently that you think people are missing the point on?",
    ],
}


def _mentions(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for k in keywords if re.search(rf"\b{re.escape(k)}\b", lowered))


def coverage(texts: list[str]) -> dict[str, int]:
    """How many of his samples are mostly about each area (2+ keyword hits counts)."""
    return {area: sum(1 for t in texts if _mentions(t, words) >= 2) for area, words in AREAS.items()}


def suggested_questions(texts: list[str], already_asked: list[str], k: int = 3, seed: int | None = None) -> list[str]:
    """k questions he hasn't answered yet, from the thinnest-covered areas first."""
    rng = random.Random(seed)
    asked = {q.strip().lower() for q in already_asked if q}
    counts = coverage(texts)
    picks: list[str] = []
    # Two from the thinnest area, then one from each of the others, until there are k.
    for i, area in enumerate(sorted(QUESTIONS, key=lambda a: counts.get(a, 0))):
        options = [q for q in QUESTIONS[area] if q.lower() not in asked]
        rng.shuffle(options)
        picks.extend(options[: 2 if i == 0 else 1])
    return picks[:k]


def coverage_summary(texts: list[str]) -> str:
    counts = coverage(texts)
    parts = ", ".join(f"{area} {n}" for area, n in counts.items())
    thinnest = min(counts, key=counts.get)
    return (
        f"Samples about: {parts}. {thinnest} is the thinnest, so posts on it lean most on "
        "guesswork - the suggested questions below start there."
    )
