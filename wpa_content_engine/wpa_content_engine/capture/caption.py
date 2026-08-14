"""Photo captioning via Gemini vision (spec Â§3b). Free-tier API, per CLAUDE.md hard
rules - photo content isn't the same sensitivity class as her voice/raw notes text, so
it doesn't need to stay self-hosted. No search tool involved, so this isn't hit by the
billing-gated grounding issue found in level 4.
"""

import base64
import mimetypes
import os

import dotenv
import httpx

dotenv.load_dotenv()

_SYSTEM_INSTRUCTION = """Caption this photo for someone drafting a LinkedIn post that \
may reference it. Describe what's actually visible - setting, people/objects present \
(without guessing names or identities), and any mood or context that's evident. \
2-3 sentences. Do not invent details you can't see."""


def caption_photo(file_path: str) -> str:
    """Return a short factual caption for a photo, for the drafting engine's raw notes."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "(photo captioning unavailable - no GEMINI_API_KEY configured)"

    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}:
        msg = f"Unsupported image type for {file_path}: {mime_type}"
        raise ValueError(msg)

    with open(file_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")

    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/interactions?key={api_key}",
        json={
            "model": "gemini-3.7-flash",
            "system_instruction": _SYSTEM_INSTRUCTION,
            "input": [
                {"type": "text", "text": "Caption this photo."},
                {"type": "image", "data": image_b64, "mime_type": mime_type},
            ],
        },
        timeout=60,
    )
    response.raise_for_status()

    steps = response.json().get("steps", [])
    text = next(
        (
            step["content"][0]["text"]
            for step in steps
            if step.get("type") == "model_output" and step.get("content")
        ),
        None,
    )
    return text or "(captioning returned no result)"
