"""User-local day boundaries.

Everything user-facing in this app is scoped to a *day*: the daily summary, goal
and limiter progress, and every widget colour state. The day that matters is the
user's, never the server's -- a summary that is only correct in the server's
timezone is wrong for most users and the bug is invisible to whoever wrote it.

Timestamps are stored UTC and resolved through ``users.timezone`` here.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Always use this rather than ``datetime.now()``, which returns a naive
    local-time value that compares incorrectly against stored timestamps.
    """
    return datetime.now(ZoneInfo("UTC"))


def to_iso(moment: datetime) -> str:
    """Serialise an aware datetime to an ISO-8601 UTC string for storage."""
    if moment.tzinfo is None:
        raise ValueError("refusing to store a naive datetime; attach a timezone")
    return moment.astimezone(ZoneInfo("UTC")).isoformat()


def from_iso(value: str) -> datetime:
    """Parse a stored ISO-8601 timestamp back into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(ZoneInfo("UTC"))


def local_date(moment: datetime, timezone: str) -> date:
    """Return the calendar date ``moment`` falls on for a user in ``timezone``."""
    return moment.astimezone(ZoneInfo(timezone)).date()


def day_bounds(day: date, timezone: str) -> tuple[datetime, datetime]:
    """Return the UTC half-open interval ``[start, end)`` covering a local day.

    The interval is half-open so that consecutive days neither overlap nor leave
    a gap -- an entry logged at exactly local midnight belongs to the day
    starting then, and to exactly one day.

    DST is handled by constructing local midnight and converting, rather than by
    assuming a day is 24 hours long. On a DST transition a local day may be 23
    or 25 hours, and arithmetic that assumes otherwise drops or double-counts an
    hour of drinks.
    """
    zone = ZoneInfo(timezone)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    utc = ZoneInfo("UTC")
    return start_local.astimezone(utc), end_local.astimezone(utc)


def current_day_bounds(timezone: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """UTC bounds of the user's *current* local day."""
    moment = now or utc_now()
    return day_bounds(local_date(moment, timezone), timezone)


def parse_hhmm(value: str) -> time:
    """Parse a stored ``'HH:MM'`` setting into a ``time``."""
    hour, _, minute = value.partition(":")
    return time(hour=int(hour), minute=int(minute))


def local_moment_today(
    clock: str,
    timezone: str,
    now: datetime | None = None,
) -> datetime:
    """Return the UTC instant at which local ``clock`` occurs on the user's today.

    Used for bedtime-derived widget states and for reminder windows.
    """
    moment = now or utc_now()
    zone = ZoneInfo(timezone)
    today = local_date(moment, timezone)
    local = datetime.combine(today, parse_hhmm(clock), tzinfo=zone)
    return local.astimezone(ZoneInfo("UTC"))


def is_within_window(
    window_start: str,
    window_end: str,
    timezone: str,
    now: datetime | None = None,
) -> bool:
    """Whether the user's local wall-clock time is inside their active window.

    Windows that wrap past midnight (``'22:00'``--``'06:00'``) are supported;
    a naive ``start <= t <= end`` comparison returns False for the entire
    wrapped window, which would silently disable reminders for night-shift users.
    """
    moment = now or utc_now()
    local_time = moment.astimezone(ZoneInfo(timezone)).time()
    start = parse_hhmm(window_start)
    end = parse_hhmm(window_end)
    if start <= end:
        return start <= local_time <= end
    return local_time >= start or local_time <= end
