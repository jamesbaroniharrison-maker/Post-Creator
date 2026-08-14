"""CLI entrypoint: draft one post from a topic.

Usage (from the wpa_content_engine/ app directory, with the venv active):
    python -m wpa_content_engine.drafting_engine.run --topic "..." --post-type industry_insight
    python -m wpa_content_engine.drafting_engine.run --topic "..." --post-type personal_reflection --skip-research
"""

import argparse
import json

from wpa_content_engine.drafting_engine.pipeline import generate_and_save_draft

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--post-type", required=True, choices=["industry_insight", "company_update", "personal_reflection"])
    parser.add_argument("--skip-research", action="store_true", help="For posts that don't need external facts (e.g. personal reflections).")
    args = parser.parse_args()

    post = generate_and_save_draft(args.topic, args.post_type, skip_research=args.skip_research)

    print(f"Draft saved (id={post.id}, status={post.status})\n")
    print("--- TEXT ---")
    print(post.draft_text)
    print("\n--- HASHTAGS ---", json.loads(post.hashtags))
    print("--- TAGS ---", json.loads(post.tags))
    print("--- SUGGESTED DAY ---", post.suggested_day)
    print("--- SOURCES ---")
    for s in json.loads(post.sources):
        print(f"  {s['title']} - {s['url']}")
    print("--- COMPLIANCE NOTE ---", post.compliance_note)
