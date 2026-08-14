"""LLM close read: qualitative tone/rhetoric notes an LLM picks up that stats can't.

Runs against self-hosted Ollama only - her raw writing is sensitive corpus data and
must never leave the machine (CLAUDE.md hard rule: drafting-adjacent calls stay local).
"""

import json
import os

import httpx

_SYSTEM_PROMPT = """You are a close-reading analyst studying one person's writing voice \
from a sample of their real LinkedIn posts. You are not drafting anything - only \
describing patterns you notice, so a separate system can later imitate this voice.

Respond with strict JSON only, no markdown fences, matching this shape:
{
  "tone_descriptors": ["3-6 short adjectives/phrases"],
  "rhetorical_patterns": ["distinctive habits: e.g. rhetorical questions, direct address, storytelling opens"],
  "things_to_avoid": ["patterns that would sound wrong/off-voice if a draft used them"],
  "summary": "2-3 sentence plain-English description of the voice overall"
}"""


def llm_close_read(texts: list[str]) -> dict:
    """Send the corpus to Ollama and return its qualitative read, or a pending stub on failure."""
    if not texts:
        return {"status": "skipped", "reason": "no corpus samples yet"}

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2")

    corpus_block = "\n\n---\n\n".join(texts)
    user_prompt = f"Here are her posts, separated by '---':\n\n{corpus_block}"

    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {
            "status": "unavailable",
            "reason": f"Could not reach Ollama at {base_url}: {exc}",
        }

    content = response.json().get("message", {}).get("content", "")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"status": "unparsable", "raw_response": content}

    parsed["status"] = "ok"
    return parsed
