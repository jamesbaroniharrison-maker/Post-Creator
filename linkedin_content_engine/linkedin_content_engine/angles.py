"""Topic angles: what an AI or market post is actually about, one level below the post
type (request: "diversify what AI commentary means and have subsections... so the
statistics show a bit more what's actually happening").

A keyword classifier, deliberately - no model call, so every topic bank row and post
can be tagged instantly and the same text always gets the same angle. Planning uses it
to spread a week across different angles; Review cards and Statistics show it.
"""

import re

ANGLES = [
    "tools_products",
    "business_adoption",
    "policy_regulation",
    "research_technical",
    "jobs_skills",
    "markets_money",
]

ANGLE_LABELS = {
    "tools_products": "Tools & Products",
    "business_adoption": "Business & Adoption",
    "policy_regulation": "Policy & Regulation",
    "research_technical": "Research & Technical",
    "jobs_skills": "Jobs & Skills",
    "markets_money": "Markets & Money",
}

_KEYWORDS = {
    "tools_products": [
        "launch", "launches", "launched", "release", "released", "feature", "features", "app", "update",
        "version", "model", "models", "gpt", "chatgpt", "claude", "gemini", "copilot", "llama", "agent",
        "agents", "assistant", "plugin", "product", "tool", "tools", "api", "open source", "open-source",
    ],
    "business_adoption": [
        "adoption", "adopt", "enterprise", "enterprises", "companies", "company", "business", "businesses",
        "roi", "productivity", "workflow", "workflows", "deploy", "deployment", "customers", "sme", "smes",
        "automation", "automate", "efficiency", "pilot", "pilots", "operations", "cost", "costs", "seats",
    ],
    "policy_regulation": [
        "regulation", "regulator", "regulators", "law", "laws", "legislation", "policy", "government",
        "ai act", "eu", "ico", "cma", "fca", "ofcom", "minister", "parliament", "copyright", "lawsuit",
        "court", "compliance", "ban", "safety institute", "guidance", "consultation", "white paper",
    ],
    "research_technical": [
        "research", "researchers", "paper", "study", "benchmark", "benchmarks", "scientists", "training",
        "compute", "chip", "chips", "gpu", "gpus", "dataset", "architecture", "reasoning", "accuracy",
        "hallucination", "hallucinations", "inference", "parameters", "lab", "breakthrough",
    ],
    "jobs_skills": [
        "jobs", "job", "workers", "worker", "hiring", "layoffs", "redundancies", "skills", "education",
        "students", "graduates", "careers", "career", "workforce", "roles", "employees", "staff",
        "unemployment", "training scheme", "apprenticeships", "talent",
    ],
    "markets_money": [
        "funding", "raises", "raised", "valuation", "investment", "investors", "shares", "stock", "stocks",
        "ipo", "revenue", "earnings", "profit", "acquisition", "acquires", "merger", "market cap",
        "billion", "inflation", "interest rates", "economy", "gdp", "bank of england", "ftse", "nasdaq",
    ],
}
_PATTERNS = {
    angle: [re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in words] for angle, words in _KEYWORDS.items()
}
_DEFAULT_FOR_CATEGORY = {"ai": "business_adoption", "market": "markets_money"}


def classify_angle(text: str, category: str = "ai") -> str:
    """The angle whose keywords show up most in `text`. Ties and no-hits fall back to
    the category's natural default (AI -> Business & Adoption, market -> Markets &
    Money). Market items get a small nudge towards Markets & Money."""
    text = text or ""
    scores = {angle: sum(len(p.findall(text)) for p in pats) for angle, pats in _PATTERNS.items()}
    if category == "market":
        scores["markets_money"] += 1
    best = max(scores.values())
    if best == 0:
        return _DEFAULT_FOR_CATEGORY.get(category, "business_adoption")
    default = _DEFAULT_FOR_CATEGORY.get(category, "business_adoption")
    winners = [a for a in ANGLES if scores[a] == best]
    return default if default in winners else winners[0]


def angle_label(angle: str | None) -> str:
    return ANGLE_LABELS.get(angle or "", "")
