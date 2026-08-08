"""Day-boundary behaviour for a user who is not in the server's timezone.

CLAUDE.md rule 10: "today" is the user's today. These tests pin the cases where
a server-local implementation would look correct in development and be wrong in
production.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from hydration.core import day, logs
from hydration.core.models import LogEntry, LogSource

BANGKOK = "Asia/Bangkok"  # UTC+7, no DST
SANTIAGO = "America/Santiago"  # southern-hemisphere DST
KATHMANDU = "Asia/Kathmandu"  # UTC+5:45, non-hour offset


def test_late_evening_local_belongs_to_local_day_not_utc_day() -> None:
    """23:30 in Bangkok is 16:30 UTC the same date -- but the reverse case bites.

    00:30 Bangkok on the 9th is 17:30 UTC on the 8th. A UTC-based day would file
    that drink under the previous day and the user's morning summary would be
    missing it.
    """
    moment = datetime(2026, 8, 8, 17, 30, tzinfo=UTC)
    assert day.local_date(moment, BANGKOK).isoformat() == "2026-08-09"


def test_day_bounds_are_half_open_and_contiguous() -> None:
    """Consecutive days must not overlap or leave a gap."""
    first_start, first_end = day.day_bounds(datetime(2026, 8, 8).date(), BANGKOK)
    second_start, _ = day.day_bounds(datetime(2026, 8, 9).date(), BANGKOK)
    assert first_end == second_start
    assert first_start < first_end


def test_non_hour_offset_zone() -> None:
    """Kathmandu is UTC+5:45; hour-granular arithmetic gets this wrong."""
    start, end = day.day_bounds(datetime(2026, 8, 8).date(), KATHMANDU)
    assert (start.hour, start.minute) == (18, 15)
    assert end - start == timedelta(hours=24)


def test_dst_transition_day_is_not_assumed_to_be_24_hours() -> None:
    """A local day spanning a DST change is 23 or 25 hours long.

    Santiago shifts in early September. Code that adds timedelta(days=1) to a
    UTC instant instead of computing local midnight will drop or double-count an
    hour of drinks on this day.
    """
    lengths = set()
    for dom in range(1, 16):
        start, end = day.day_bounds(datetime(2026, 9, dom).date(), SANTIAGO)
        lengths.add(end - start)
    assert timedelta(hours=24) in lengths
    assert lengths != {timedelta(hours=24)}, "expected at least one DST-shifted day"


def test_entry_just_after_local_midnight_counts_toward_the_new_day(
    conn: sqlite3.Connection, user: str
) -> None:
    just_after_midnight_bkk = datetime(2026, 8, 8, 17, 5, tzinfo=UTC)  # 00:05 on the 9th
    logs.upsert_entry(
        conn,
        LogEntry(
            user_id=user,
            logged_at=just_after_midnight_bkk,
            source=LogSource.WIDGET,
            custom_name="water",
        ),
    )

    on_the_9th = datetime(2026, 8, 9, 3, 0, tzinfo=UTC)  # 10:00 local on the 9th
    assert logs.day_totals(conn, user, BANGKOK, when=on_the_9th) == {"water": 1.0}

    on_the_8th = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)  # 10:00 local on the 8th
    assert logs.day_totals(conn, user, BANGKOK, when=on_the_8th) == {}


def test_active_window_wrapping_past_midnight() -> None:
    """A night-shift window (22:00-06:00) must not read as always-closed."""
    at_2330_bkk = datetime(2026, 8, 8, 16, 30, tzinfo=UTC)
    at_0300_bkk = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
    at_1200_bkk = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)

    assert day.is_within_window("22:00", "06:00", BANGKOK, now=at_2330_bkk) is True
    assert day.is_within_window("22:00", "06:00", BANGKOK, now=at_0300_bkk) is True
    assert day.is_within_window("22:00", "06:00", BANGKOK, now=at_1200_bkk) is False


def test_normal_window_does_not_wrap() -> None:
    at_1200_bkk = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)
    at_0300_bkk = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)

    assert day.is_within_window("08:00", "22:00", BANGKOK, now=at_1200_bkk) is True
    assert day.is_within_window("08:00", "22:00", BANGKOK, now=at_0300_bkk) is False


def test_bedtime_resolves_to_the_users_local_evening() -> None:
    now = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)  # noon in Bangkok
    bedtime_utc = day.local_moment_today("23:00", BANGKOK, now=now)
    assert bedtime_utc == datetime(2026, 8, 8, 16, 0, tzinfo=UTC)


def test_category_totals_group_by_catalog_category(
    conn: sqlite3.Connection, user: str, catalog: None
) -> None:
    """Goals and limiters are per category, so this is what drives widget colour."""
    now = day.utc_now()
    for drink_id in ("water_250", "water_250", "coffee_240"):
        logs.upsert_entry(
            conn,
            LogEntry(
                user_id=user, logged_at=now, source=LogSource.WIDGET, drink_id=drink_id
            ),
        )
    logs.upsert_entry(
        conn,
        LogEntry(
            user_id=user, logged_at=now, source=LogSource.APP, custom_name="espresso tonic"
        ),
    )

    totals = logs.category_totals(conn, user, BANGKOK)
    assert totals == {"water": 2.0, "coffee": 1.0, "uncategorised": 1.0}


def test_naive_datetime_is_refused_at_serialisation() -> None:
    import pytest

    with pytest.raises(ValueError, match="naive datetime"):
        day.to_iso(datetime(2026, 8, 8, 12, 0))
