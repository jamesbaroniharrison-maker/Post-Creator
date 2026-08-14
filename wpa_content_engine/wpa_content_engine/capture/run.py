"""CLI entrypoint: turn one uploaded file (or inline text) into raw notes.

Usage (from the wpa_content_engine/ app directory, with the venv active):
    python -m wpa_content_engine.capture.run --file "path/to/voice_note.wav"
    python -m wpa_content_engine.capture.run --file "path/to/photo.jpg"
    python -m wpa_content_engine.capture.run --text "Quick note about today"
"""

import argparse

from wpa_content_engine.capture.ingest import ingest_file, ingest_text

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="Path to an audio or photo file.")
    group.add_argument("--text", help="A text note, used directly.")
    args = parser.parse_args()

    if args.text:
        print("--- RAW NOTES (text) ---")
        print(ingest_text(args.text))
    else:
        result = ingest_file(args.file)
        print(f"--- RAW NOTES ({result['kind']}) ---")
        print(result["notes"])
        if result["stored_path"]:
            print(f"--- STORED AT --- {result['stored_path']}")
