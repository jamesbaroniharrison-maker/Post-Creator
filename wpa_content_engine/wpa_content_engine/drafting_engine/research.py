"""Research call: finds current, source-traceable facts for a topic via Tavily.

Restricted to the trusted-source allow list from spec Â§3a, so nothing from generic
SEO/comparison content or unmoderated forums can end up cited in a compliance-sensitive
health-insurance post.
"""

import os

import dotenv
import httpx
import pydantic

# Reading os.environ directly (rather than via `from rxconfig import config`) means
# this module can't rely on rxconfig's side-effecting load_dotenv() having already run -
# call it here too so this works standalone regardless of import order.
dotenv.load_dotenv()

# Spec Â§3a allow list, expanded well beyond the original starting set (request:
# "drastically expand the reliable sources"). Grouped by why each one is trustworthy
# enough to cite in a compliance-sensitive health-insurance post - still no generic
# SEO/comparison content or unmoderated forums, per the original mandate.
TRUSTED_DOMAINS = [
    # WPA itself
    "wpa.org.uk",
    # NHS / UK government / official health bodies
    "nhs.uk",
    "england.nhs.uk",
    "gov.uk",
    "ons.gov.uk",
    "parliament.uk",
    "nhsconfed.org",
    "nice.org.uk",
    # UK health policy think tanks / research bodies
    "kingsfund.org.uk",
    "nuffieldtrust.org.uk",
    "health.org.uk",
    "laingbuisson.com",
    # Insurance industry bodies + trade press
    "abi.org.uk",
    "biba.org.uk",
    "healthandprotection.co.uk",
    "covermagazine.co.uk",
    "insuranceage.co.uk",
    "insurancebusinessmag.com",
    "insurancetimes.co.uk",
    "postonline.co.uk",
    "protectionreview.co.uk",
    "theactuary.com",
    # Financial/professional adviser press
    "moneymarketing.co.uk",
    "ftadviser.com",
    "professionaladviser.com",
    "corporate-adviser.com",
    # Employee benefits / workplace wellbeing (EAP content, spec Â§1)
    "employeebenefits.co.uk",
    "reba.global",
    "cipd.org",
    # Consumer/ratings bodies
    "which.co.uk",
    "moneyfactscompare.co.uk",
    # Mainstream UK news, health/business sections only in practice via query wording
    "bbc.co.uk",
    "theguardian.com",
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
