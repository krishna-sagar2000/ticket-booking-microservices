"""One place to read the current time, so tests can move the clock forward.

All times in booking_db are naive UTC datetimes. The booking service both writes
and compares them, so it always uses the same clock.
"""
from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(dt: datetime | None) -> str | None:
    """Format a naive UTC datetime as ISO-8601 with a Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None
