"""Small helpers for the local model (Ollama) - free, private, and fine for short
judgement and summary jobs: does this story fit this occasion, and what's the article
about. Drafting itself stays on DRAFT_LLM_PROVIDER.

LOCAL_LLM_MODEL picks the model (defaults to OLLAMA_MODEL, then llama3). Every call is
best-effort: callers get None back if Ollama isn't running, never an exception.
"""

import json
import os
import re

import dotenv
import httpx

dotenv.load_dotenv()


def _model() -> str:
    return os.environ.get("LOCAL_LLM_MODEL") or os.environ.get("OLLAMA_MODEL", "llama3")


def local_chat(system_prompt: str, user_content: str, as_json: bool = False, timeout: int = 120) -> str | None:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.2},
    }
    if as_json:
        payload["format"] = "json"
    try:
        response = httpx.post(f"{base_url}/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()["message"]["content"].strip() or None
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def local_json(system_prompt: str, user_content: str, timeout: int = 120) -> dict | None:
    text = local_chat(system_prompt, user_content, as_json=True, timeout=timeout)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def fetch_article_text(url: str, limit: int = 6000) -> str:
    """Plain text of a web page, roughly - enough for a summary. Empty on any failure
    (paywalls, blocks, no URL), so callers fall back to the stored summary."""
    if not url:
        return ""
    try:
        response = httpx.get(
            url,
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"},
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return ""
    if "html" not in response.headers.get("content-type", "html"):
        return ""
    html = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", response.text)
    paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)
    text = " ".join(re.sub(r"<[^>]+>", " ", p) for p in paragraphs) or re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]
