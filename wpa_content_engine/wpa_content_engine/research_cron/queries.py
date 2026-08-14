"""Standing daily search queries (spec Â§3a: runs once a day, builds a continuous backlog).

Each query is tagged with the topic_bank category it's aimed at (spec Â§1's two
research-backed post types: industry insight vs. company update), though the scorer
can still override the category if a result doesn't match what its query intended.
"""

INDUSTRY_QUERIES = [
    "UK private medical insurance industry news",
    "NHS health policy news",
    "UK health insurance regulation ABI",
    "UK private healthcare screening cancer news",
]

COMPANY_QUERIES = [
    "WPA health insurance news",
]

# (query, default_category)
DAILY_QUERIES: list[tuple[str, str]] = [
    *[(q, "industry") for q in INDUSTRY_QUERIES],
    *[(q, "company") for q in COMPANY_QUERIES],
]
