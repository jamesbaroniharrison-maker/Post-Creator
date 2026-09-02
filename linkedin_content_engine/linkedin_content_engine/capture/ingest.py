"""Unified ingestion: turns whatever you send into the same 'raw notes' text the
drafting engine already expects (spec Â§3b) - text passes through, audio gets
transcribed, photos get captioned (and kept, for attaching to the finished post).

No video processing anywhere (CLAUDE.md hard rule) - a video upload is rejected
outright rather than silently processed or ignored.
"""

import pathlib
import shutil
import uuid

from linkedin_content_engine.capture.caption import caption_photo
from linkedin_content_engine.capture.transcribe import transcribe_audio

TEXT_EXTENSIONS = {".txt", ".md"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".wma"}
PHOTO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

UPLOADS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "assets" / "uploads"


class UnsupportedMediaError(ValueError):
    """Raised for video (explicitly out of scope) or any other unrecognized file type."""


def ingest_text(text: str) -> str:
    """Text note: used directly."""
    return text.strip()


def ingest_file(file_path: str) -> dict:
    """Turn an uploaded file into raw notes text, dispatching by extension.

    Returns {"notes": str, "kind": "audio"|"photo", "stored_path": str | None}.
    stored_path is only set for photos (spec Â§3b: kept to attach to the finished post).
    """
    path = pathlib.Path(file_path)
    suffix = path.suffix.lower()

    if suffix in VIDEO_EXTENSIONS:
        msg = (
            f"Video files are not supported ({path.name}). Per CLAUDE.md hard rules, "
            "this system only handles text, audio, and photos - please send the audio "
            "track separately, or a photo instead."
        )
        raise UnsupportedMediaError(msg)

    if suffix in AUDIO_EXTENSIONS:
        notes = transcribe_audio(str(path))
        return {"notes": notes, "kind": "audio", "stored_path": None}

    if suffix in PHOTO_EXTENSIONS:
        caption = caption_photo(str(path))
        stored_path = _store_photo(path)
        return {"notes": caption, "kind": "photo", "stored_path": str(stored_path)}

    msg = f"Unrecognized file type: {path.name} ({suffix})"
    raise UnsupportedMediaError(msg)


def _store_photo(source: pathlib.Path) -> pathlib.Path:
    """Copy a photo into the persistent uploads dir under a unique name, for later
    attachment to the finished post (spec Â§3b)."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS_DIR / f"{uuid.uuid4().hex}{source.suffix.lower()}"
    shutil.copy2(source, dest)
    return dest
