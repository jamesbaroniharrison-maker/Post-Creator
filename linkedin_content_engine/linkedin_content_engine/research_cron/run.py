"""CLI entrypoint for the daily research cron. Invoked by Task Scheduler (spec Â§5).

Usage (from the linkedin_content_engine/ app directory, with the venv active):
    python -m linkedin_content_engine.research_cron.run
    python -m linkedin_content_engine.research_cron.run --force   # bypass the once-per-day guard
"""

import argparse

from linkedin_content_engine.research_cron.pipeline import run_daily_research

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run even if already run today.")
    args = parser.parse_args()

    result = run_daily_research(force=args.force)
    print(result)
