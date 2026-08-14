"""Self-hosted Whisper transcription for audio notes (spec Â§3b, Â§5).

Uses faster-whisper (CTranslate2) rather than the reference openai-whisper package -
it decodes audio via bundled PyAV wheels, so no system ffmpeg install is required.
Genuinely free and local: nothing about her voice note leaves this machine.
"""

import functools
import os

DEFAULT_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base")


@functools.lru_cache(maxsize=1)
def _get_model(model_size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe_audio(file_path: str, model_size: str = DEFAULT_MODEL_SIZE) -> str:
    """Transcribe an audio file to plain text."""
    model = _get_model(model_size)
    segments, _info = model.transcribe(file_path)
    return " ".join(segment.text.strip() for segment in segments).strip()
