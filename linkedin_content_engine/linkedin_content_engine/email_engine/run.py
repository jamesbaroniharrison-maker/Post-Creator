"""CLI entrypoint for both scheduled email jobs. Invoked by Task Scheduler.

Usage (from the linkedin_content_engine/ app directory, with the venv active):
    python -m linkedin_content_engine.email_engine.run --job reminder
    python -m linkedin_content_engine.email_engine.run --job digest
    python -m linkedin_content_engine.email_engine.run --job reminder --force
"""

import argparse

from linkedin_content_engine.email_engine.digest import run_weekly_digest
from linkedin_content_engine.email_engine.reminder import run_weekly_reminder

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, choices=["reminder", "digest"])
    parser.add_argument("--force", action="store_true", help="Bypass the day-of-week and once-a-week guards.")
    args = parser.parse_args()

    result = run_weekly_reminder(force=args.force) if args.job == "reminder" else run_weekly_digest(force=args.force)
    print(result)
