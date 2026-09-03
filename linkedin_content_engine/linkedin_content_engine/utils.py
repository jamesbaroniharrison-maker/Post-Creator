"""Small shared helpers with no home in a more specific module."""

from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    """SQLite drops timezone info on read even though every write in this codebase
    uses datetime.now(timezone.utc) - confirmed live: a real dashboard load crashed
    with "can't compare offset-naive and offset-aware datetimes" the moment
    _reload_full_stats compared a DB-read Post.created_at against a freshly-made
    aware cutoff. Every value read back from the database was written as UTC, so
    treating a naive one as UTC on the way back out is correct, not a guess."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
