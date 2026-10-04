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

from linkedin_content_engine.calendar_engine.pipeline import run_calendar_engine
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

    # Calendar runs after research so today's findings can be linked to occasions,
    # and separately caught so a calendar problem never fails the research job.
    try:
        calendar_result = run_calendar_engine()
        logging.info("CALENDAR: %s", calendar_result)
    except Exception:
        logging.exception("CALENDAR FAILED")

    # Saturday only (and only if switched on in Settings > Weekly Plan Template):
    # draft next week from the weekly plan, after today's research has landed, so the
    # drafts use the freshest findings. Caught separately like the calendar step.
    try:
        from linkedin_content_engine.planning import maybe_auto_prepare

        prepare_result = maybe_auto_prepare()
        logging.info("AUTO-PREPARE: %s", prepare_result)
    except Exception:
        logging.exception("AUTO-PREPARE FAILED")

    # Every few days: put 2-3 strong fresh findings on Home > Your take for James's own
    # opinion (opinions.py decides whether a new round is due). Caught separately.
    try:
        from linkedin_content_engine.opinions import offer_new_prompts

        logging.info("YOUR TAKE: %s new prompt(s)", offer_new_prompts())
    except Exception:
        logging.exception("YOUR TAKE FAILED")
