"""CLI entrypoint for the daily research cron. Invoked by Task Scheduler (spec Â§5).

Usage (from the linkedin_content_engine/ app directory, with the venv active):
    python -m linkedin_content_engine.research_cron.run
    python -m linkedin_content_engine.research_cron.run --force   # bypass the once-per-day guard

Logs to research_cron.log (in linkedin_content_engine/, next to rxconfig.py) - Task
Scheduler doesn't capture a task's stdout/stderr anywhere by default, so without this
a run that errors or gets killed
(e.g. by the task's execution time limit) leaves no trace at all. Confirmed live: the
7am scheduled run on 3 Sept 2026 was force-killed by Task Scheduler's 30-minute limit
(exit code 0xC000013A) and nothing in the topic bank or anywhere else showed it had
failed - only Get-ScheduledTaskInfo's LastTaskResult revealed it, which nobody's going
to check unprompted. A "started" line separate from the "finished" line means a run
that gets killed mid-way still leaves evidence (a start with no matching finish),
not just silence.
"""

import argparse
import logging
from pathlib import Path

from linkedin_content_engine.research_cron.pipeline import run_daily_research

LOG_FILE = Path(__file__).resolve().parents[2] / "research_cron.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run even if already run today.")
    args = parser.parse_args()

    logging.info("STARTED (force=%s)", args.force)
    try:
        result = run_daily_research(force=args.force)
    except Exception:
        logging.exception("FAILED")
        raise
    logging.info("FINISHED: %s", result)
    print(result)
