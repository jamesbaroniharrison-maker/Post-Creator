"""LLM close read: qualitative tone/rhetoric notes an LLM picks up that stats can't.

Runs against self-hosted Ollama only - her raw writing is sensitive corpus data and
must never leave the machine (CLAUDE.md hard rule: drafting-adjacent calls stay local).
"""

import json
import os

import httpx

_SYSTEM_PROMPT = """You are a close-reading analyst studying one person's writing voice \
from a sample of their real LinkedIn posts. You are not drafting anything - only \
describing patterns you actually observe in THIS SPECIFIC text, so a separate system \
can later imitate this voice.

Respond with strict JSON only, no markdown fences, no commentary outside the JSON.

Here is an example of a correctly-filled response for a DIFFERENT person's writing, so \
you can see the expected level of specificity. Never copy this example's content -
it is only here to show the shape and the kind of concrete, text-grounded observation
expected in each field:
{
  "tone_descriptors": ["self-deprecating", "matter-of-fact", "quietly proud"],
  "rhetorical_patterns": ["opens with a one-line reaction before context", "asks a direct question mid-post", "signs off with a call to action naming a real person"],
  "things_to_avoid": ["corporate buzzwords", "generic motivational quotes", "long unbroken paragraphs"],
  "summary": "Two sentences, in your own words, describing what makes this specific voice recognizable."
}

Now produce the same JSON shape, but every value must be your own observation drawn \
directly from the text you are given below - not the example above. If a field doesn't \
clearly apply, write your best honest observation rather than leaving placeholder text."""


def llm_close_read(texts: list[str]) -> dict:
    """Send the corpus to Ollama and return its qualitative read, or a pending stub on failure."""
    if not texts:
        return {"status": "skipped", "reason": "no corpus samples yet"}

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2")

    corpus_block = "\n\n---\n\n".join(texts)
    user_prompt = f"Here are her posts, separated by '---':\n\n{corpus_block}"

    # Ollama defaults to a 2048-token context regardless of the model's actual max,
    # which would silently truncate a real corpus - override it explicitly.
    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", 8192))

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
                "options": {"num_ctx": num_ctx},
            },
            timeout=300,
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
