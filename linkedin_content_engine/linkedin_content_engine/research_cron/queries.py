"""Standing daily search queries. Runs once a day, builds a continuous topic-bank
backlog.

Each query is tagged with the topic_bank category it's aimed at (the two research-backed
lanes: AI/tech news vs. broader market/business news), though the scorer can still
override the category if a result doesn't match what its query intended.
"""

AI_QUERIES = [
    "AI agents enterprise adoption news",
    "generative AI product launch news",
    "AI regulation policy UK EU news",
    "open source AI model release news",
    "AI and the future of work news",
    "human in the loop AI augmentation news",
    "AI job displacement automation news",
    "AI startup funding news",
    "AI safety alignment research news",
    "AI coding assistant developer tools news",
]

MARKET_QUERIES = [
    "UK tech sector market news",
    "startup funding market report",
    "future of work workplace trends news",
    "UK graduate job market news",
]

# (query, default_category)
DAILY_QUERIES: list[tuple[str, str]] = [
    *[(q, "ai") for q in AI_QUERIES],
    *[(q, "market") for q in MARKET_QUERIES],
]
