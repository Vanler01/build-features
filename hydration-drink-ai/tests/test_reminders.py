"""Reminder scheduling and the LINE push budget.

The budget matters commercially: LINE's Thailand free plan is 300 pushes a
month, and a user on a 2-hour interval across a 14-hour window burns about 210
of them. Getting this wrong costs real money.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from hydration.core import users as users_mod
from hydration.core.models import Platform
from hydration.scheduler import reminders

BANGKOK = "Asia/Bangkok"
NOON_BKK = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)
THREE_AM_BKK = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)


# --- due computation -------------------------------------------------------


def test_first_reminder_is_due_immediately_inside_the_window() -> None:
    assert reminders.is_due(None, 120, "08:00", "22:00", BANGKOK, now=NOON_BKK)


def test_nothing_is_due_outside_the_active_window() -> None:
    """3am local — the user is asleep, whatever the server clock says."""
    assert not reminders.is_due(None, 120, "08:00", "22:00", BANGKOK, now=THREE_AM_BKK)
    assert reminders.next_fire_time(None, 120, "08:00", "22:00", BANGKOK, now=THREE_AM_BKK) is None


def test_interval_is_respected() -> None:
    just_sent = NOON_BKK - timedelta(minutes=30)
    assert not reminders.is_due(just_sent, 120, "08:00", "22:00", BANGKOK, now=NOON_BKK)

    long_ago = NOON_BKK - timedelta(minutes=121)
    assert reminders.is_due(long_ago, 120, "08:00", "22:00", BANGKOK, now=NOON_BKK)


def test_night_shift_window_works() -> None:
    """A 22:00-06:00 window must not read as permanently closed."""
    assert reminders.is_due(None, 120, "22:00", "06:00", BANGKOK, now=THREE_AM_BKK)
    assert not reminders.is_due(None, 120, "22:00", "06:00", BANGKOK, now=NOON_BKK)


# --- push budget -----------------------------------------------------------


def test_telegram_is_unmetered(conn: sqlite3.Connection, user: str) -> None:
    assert reminders.push_allowance_remaining(conn, user, Platform.TELEGRAM) is None
    assert reminders.may_push(conn, user, Platform.TELEGRAM)


def test_line_budget_counts_down_and_stops(conn: sqlite3.Connection, user: str) -> None:
    limit = reminders.PUSH_LIMITS[Platform.LINE]
    assert reminders.push_allowance_remaining(conn, user, Platform.LINE) == limit

    for _ in range(limit):
        reminders.record_push(conn, user, Platform.LINE)

    assert reminders.push_allowance_remaining(conn, user, Platform.LINE) == 0
    assert not reminders.may_push(conn, user, Platform.LINE)


def test_budget_resets_each_calendar_month(conn: sqlite3.Connection, user: str) -> None:
    august = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    september = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    for _ in range(reminders.PUSH_LIMITS[Platform.LINE]):
        reminders.record_push(conn, user, Platform.LINE, now=august)

    assert not reminders.may_push(conn, user, Platform.LINE, now=august)
    assert reminders.may_push(conn, user, Platform.LINE, now=september)


def test_budgets_are_per_user(conn: sqlite3.Connection, user: str) -> None:
    other, _ = users_mod.get_or_create_user(conn, Platform.LINE, "line-other")
    for _ in range(reminders.PUSH_LIMITS[Platform.LINE]):
        reminders.record_push(conn, user, Platform.LINE)

    assert not reminders.may_push(conn, user, Platform.LINE)
    assert reminders.may_push(conn, other, Platform.LINE)


# --- the due-reminder sweep ------------------------------------------------


def test_due_sweep_yields_one_entry_per_bot_identity(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1", BANGKOK)
    users_mod.attach_identity(conn, user_id, Platform.LINE, "line-1")

    due = reminders.due_reminders(conn, {}, now=NOON_BKK)
    assert {d.platform for d in due} == {Platform.TELEGRAM, Platform.LINE}


def test_app_identity_is_skipped(conn: sqlite3.Connection) -> None:
    """The app uses its own push channel, not the bot adapters."""
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1", BANGKOK)
    users_mod.attach_identity(conn, user_id, Platform.APP, "app-1")

    due = reminders.due_reminders(conn, {}, now=NOON_BKK)
    assert all(d.platform is not Platform.APP for d in due)


def test_reminders_disabled_means_nothing_is_sent(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1", BANGKOK)
    settings = users_mod.get_settings(conn, user_id)
    users_mod.update_settings(conn, replace(settings, reminders_enabled=False))

    assert reminders.due_reminders(conn, {}, now=NOON_BKK) == []


def test_one_user_hitting_the_line_ceiling_does_not_stop_everyone_else(
    conn: sqlite3.Connection,
) -> None:
    """A shared scheduler must not fail closed for the whole fleet."""
    exhausted, _ = users_mod.get_or_create_user(conn, Platform.LINE, "line-1", BANGKOK)
    healthy, _ = users_mod.get_or_create_user(conn, Platform.LINE, "line-2", BANGKOK)
    for _ in range(reminders.PUSH_LIMITS[Platform.LINE]):
        reminders.record_push(conn, exhausted, Platform.LINE)

    due = reminders.due_reminders(conn, {}, now=NOON_BKK)
    assert [d.user_id for d in due] == [healthy]


def test_sleeping_users_are_not_woken(conn: sqlite3.Connection) -> None:
    users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1", BANGKOK)
    assert reminders.due_reminders(conn, {}, now=THREE_AM_BKK) == []


def test_reminder_text_mentions_progress_without_lecturing(
    conn: sqlite3.Connection, user: str, catalog: None
) -> None:
    from hydration.core import logs as logs_mod
    from hydration.core.models import LogEntry, LogSource

    logs_mod.upsert_entry(
        conn,
        LogEntry(
            user_id=user, logged_at=NOON_BKK, source=LogSource.WIDGET, drink_id="water_250"
        ),
    )
    text = reminders.compose_reminder(conn, user, BANGKOK, now=NOON_BKK)

    assert "1" in text
    for scold in ("should", "must", "failed", "behind", "only"):
        assert scold not in text.lower(), f"reminder reads as a lecture: {text!r}"
