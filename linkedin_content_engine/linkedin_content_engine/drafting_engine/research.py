"""Research call: finds current, source-traceable facts for a topic via Tavily.

Restricted to the trusted-source allow list below, so nothing from generic SEO/
comparison content or unmoderated forums can end up cited in a post.
"""

import os

import dotenv
import httpx
import pydantic

from linkedin_content_engine.usage_tracking import record_tavily_call, tavily_quota_available

# Reading os.environ directly (rather than via `from rxconfig import config`) means
# this module can't rely on rxconfig's side-effecting load_dotenv() having already run -
# call it here too so this works standalone regardless of import order.
dotenv.load_dotenv()

# Grouped by why each one is trustworthy enough to cite in a post - no generic SEO/
# comparison content or unmoderated forums.
TRUSTED_DOMAINS = [
    # Tech/AI trade press and analysis
    "techcrunch.com",
    "theverge.com",
    "arstechnica.com",
    "wired.com",
    "technologyreview.com",  # MIT Technology Review
    "stratechery.com",
    "venturebeat.com",
    "semianalysis.com",
    # Primary research / labs' own announcements
    "arxiv.org",
    "openai.com",
    "anthropic.com",
    "deepmind.google",
    "ai.meta.com",
    "blog.google",
    "huggingface.co",
    "nature.com",
    # UK policy / government / research bodies
    "gov.uk",
    "ons.gov.uk",
    "turing.ac.uk",  # the Alan Turing Institute
    # Business/market and future-of-work coverage
    "reuters.com",
    "bloomberg.com",
    "mckinsey.com",
    "weforum.org",
    # Mainstream UK news
    "bbc.co.uk",
    "theguardian.com",
    "ft.com",
]


class ResearchFinding(pydantic.BaseModel):
    title: str
    url: str
    content: str


class ResearchResult(pydantic.BaseModel):
    topic: str
    findings: list[ResearchFinding] = pydantic.Field(default_factory=list)
    status: str  # ok / unavailable / no_results


def research_topic(topic: str, max_results: int = 5) -> ResearchResult:
    """Search only the trusted domains for current, citable facts about a topic."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return ResearchResult(topic=topic, status="unavailable")
    if not tavily_quota_available():
        return ResearchResult(topic=topic, status="quota_exceeded")

    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": topic,
                "max_results": max_results,
                "include_domains": TRUSTED_DOMAINS,
            },
            timeout=30,
        )
        response.raise_for_status()
        record_tavily_call()
    except httpx.HTTPError:
        return ResearchResult(topic=topic, status="unavailable")

    results = response.json().get("results", [])
    findings = [
        ResearchFinding(title=r["title"], url=r["url"], content=r["content"])
        for r in results
    ]
    return ResearchResult(
        topic=topic,
        findings=findings,
        status="ok" if findings else "no_results",
    )
