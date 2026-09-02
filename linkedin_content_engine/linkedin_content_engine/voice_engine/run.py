"""CLI entrypoint: rebuild the voice profile from whatever's in voice_samples right now.

Usage (from the linkedin_content_engine/ app directory, with the venv active):
    python -m linkedin_content_engine.voice_engine.run
"""

import json

from linkedin_content_engine.voice_engine.build_profile import build_and_save_profile

if __name__ == "__main__":
    row = build_and_save_profile()
    print(f"Voice profile regenerated (id={row.id}, generated_at={row.generated_at})")
    print(json.dumps(json.loads(row.profile_json), indent=2))
