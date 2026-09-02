"""Research call: finds current, source-traceable facts for a topic via Tavily.

Open web search (request: "open up where you can get info from"), not restricted to a
narrow allow list - but specific low-reputation/non-primary source categories are
explicitly excluded (request: "remove certain websites like wikipedia and other
non-reputable websites"). The scorer (research_cron/scorer.py) is the other half of
this - it does the substantive quality judgment on whatever comes back, so opening the
search up shifts more of that weight onto scoring, not less scrutiny overall.
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

# Deny list, not an allow list - excluded because they're tertiary/aggregated,
# unmoderated user-generated content, or generic SEO/comparison content rather than a
# primary source, not because the topic is wrong. Grouped by why.
EXCLUDED_DOMAINS = [
    # Tertiary/aggregated reference content - useful as a starting point for a human,
    # not as a citable source for a post
    "wikipedia.org",
    "wikihow.com",
    "britannica.com",
    # Unmoderated user-generated content / forums - anyone can post anything
    "reddit.com",
    "quora.com",
    "answers.com",
    "ask.com",
    "pinterest.com",
    # Open self-publishing platforms - quality varies wildly, no editorial process
    "medium.com",
    "substack.com",
    # Generic SEO/listicle/comparison content, not primary reporting or research
    "buzzfeed.com",
    "wordstream.com",
    "hubspot.com",
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
    """Search the open web (minus EXCLUDED_DOMAINS) for current, citable facts."""
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
                "exclude_domains": EXCLUDED_DOMAINS,
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
