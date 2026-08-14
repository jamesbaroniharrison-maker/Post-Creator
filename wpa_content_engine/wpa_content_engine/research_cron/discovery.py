"""Daily discovery search: Tavily's news mode, restricted to the trusted-domain allow
list (reused from the level 4 drafting engine's research module, spec Â§3a).
"""

import os

import dotenv
import httpx
import pydantic

from wpa_content_engine.drafting_engine.research import TRUSTED_DOMAINS

dotenv.load_dotenv()


class DiscoveredItem(pydantic.BaseModel):
    title: str
    url: str
    content: str
    published_date: str | None = None


def discover(query: str, days: int = 1, max_results: int = 5) -> list[DiscoveredItem]:
    """Search trusted sources for items published in the last `days` days."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
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
