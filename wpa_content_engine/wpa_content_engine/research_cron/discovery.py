"""Daily discovery search: Tavily's news mode, restricted to the trusted-domain allow
list (reused from the level 4 drafting engine's research module, spec Â§3a).
"""

import os

import dotenv
import httpx
import pydantic

from wpa_content_engine.drafting_engine.research import TRUSTED_DOMAINS
from wpa_content_engine.usage_tracking import record_tavily_call, tavily_quota_available

dotenv.load_dotenv()


class DiscoveredItem(pydantic.BaseModel):
    title: str
    url: str
    content: str
    published_date: str | None = None


def discover(query: str, days: int = 3, max_results: int = 5) -> list[DiscoveredItem]:
    """Search trusted sources for items from the last `days` days.

    3 days (not 1) so genuinely recent-but-not-literally-today items aren't missed -
    the scorer (see scorer.py) is what actually judges "is this still worth posting
    about", using the real published_date, not this window alone.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key or not tavily_quota_available():
        return []

    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "topic": "news",
                "days": days,
                "max_results": max_results,
                "include_domains": TRUSTED_DOMAINS,
            },
            timeout=30,
        )
        response.raise_for_status()
        record_tavily_call()
    except httpx.HTTPError:
        return []

    results = response.json().get("results", [])
    return [
        DiscoveredItem(
            title=r["title"],
            url=r["url"],
            content=r["content"],
            published_date=r.get("published_date"),
        )
        for r in results
    ]
