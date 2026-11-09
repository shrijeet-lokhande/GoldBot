"""GoldBot clock and time utilities."""

from __future__ import annotations

import datetime as dt
from datetime import datetime

UTC = dt.timezone.utc


def now_utc() -> datetime:
    """Return the current UTC datetime."""
    return dt.datetime.now(UTC)


def strip_tz(dt_obj: datetime) -> datetime:
    """Strip timezone info, returning a naive UTC-equivalent datetime."""
    if dt_obj.tzinfo is not None:
        return dt_obj.astimezone(UTC).replace(tzinfo=None)
    return dt_obj


def to_utc(dt_obj: datetime) -> datetime:
    """Convert a datetime to UTC."""
    if dt_obj.tzinfo is None:
        return dt_obj.replace(tzinfo=UTC)
    return dt_obj.astimezone(UTC)


def format_utc(dt_obj: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string."""
    return to_utc(dt_obj).isoformat()


def parse_utc(text: str) -> datetime:
    """Parse an ISO-8601 UTC string to a timezone-aware datetime."""
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
