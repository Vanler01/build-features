"""User identity, settings, and goals.

One human, many identities. Somebody can be on Telegram, on LINE, and in the app
at once, and all three must resolve to the same ``users.id`` so their drinks land
in one day. Resolution always goes through ``platform_identities`` -- never
assume a platform id *is* a user id.
"""

from __future__ import annotations

import sqlite3
import uuid

from . import day as day_util
from .models import Goal, GoalKind, Platform, UserSettings

DEFAULT_TIMEZONE = "UTC"


def resolve_user(
    conn: sqlite3.Connection,
    platform: Platform,
    platform_user_id: str,
) -> str | None:
    """Return the internal user id for a platform identity, if it is linked."""
    row = conn.execute(
        "SELECT user_id FROM platform_identities WHERE platform = ? AND platform_user_id = ?",
        (str(platform), platform_user_id),
    ).fetchone()
    return row["user_id"] if row else None


def get_or_create_user(
    conn: sqlite3.Connection,
    platform: Platform,
    platform_user_id: str,
    timezone: str = DEFAULT_TIMEZONE,
) -> tuple[str, bool]:
    """Resolve a platform identity to a user, creating one if it is new.

    Returns ``(user_id, created)``. Creating a user also creates their default
    settings row, so no caller has to remember to.
    """
    existing = resolve_user(conn, platform, platform_user_id)
    if existing is not None:
        return existing, False

    user_id = str(uuid.uuid4())
    now = day_util.to_iso(day_util.utc_now())
    conn.execute(
        "INSERT INTO users (id, timezone, created_at) VALUES (?, ?, ?)",
        (user_id, timezone, now),
    )
    conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
    attach_identity(conn, user_id, platform, platform_user_id)
    return user_id, True


def attach_identity(
    conn: sqlite3.Connection,
    user_id: str,
    platform: Platform,
    platform_user_id: str,
) -> None:
    """Link a platform identity to an existing user.

    Raises if that identity already belongs to a *different* user -- silently
    re-pointing it would move somebody's drink history onto another account.
    Re-attaching to the same user is a no-op so redemption stays idempotent.
    """
    owner = resolve_user(conn, platform, platform_user_id)
    if owner == user_id:
        return
    if owner is not None:
        raise ValueError(
            f"{platform} identity is already linked to a different user"
        )
    conn.execute(
        "INSERT INTO platform_identities (user_id, platform, platform_user_id, linked_at)"
        " VALUES (?, ?, ?, ?)",
        (user_id, str(platform), platform_user_id, day_util.to_iso(day_util.utc_now())),
    )


def identities_for(conn: sqlite3.Connection, user_id: str) -> list[tuple[str, str]]:
    """Return every ``(platform, platform_user_id)`` linked to a user."""
    return [
        (row["platform"], row["platform_user_id"])
        for row in conn.execute(
            "SELECT platform, platform_user_id FROM platform_identities WHERE user_id = ?",
            (user_id,),
        )
    ]


def get_timezone(conn: sqlite3.Connection, user_id: str) -> str:
    """Return the user's IANA timezone."""
    row = conn.execute("SELECT timezone FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such user: {user_id}")
    return row["timezone"]


def set_timezone(conn: sqlite3.Connection, user_id: str, timezone: str) -> None:
    """Set the user's timezone, validating it is a real IANA zone.

    An unvalidated value here breaks every summary and reminder for that user
    later, far from the code that accepted it.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"not a valid IANA timezone: {timezone!r}") from exc
    conn.execute("UPDATE users SET timezone = ? WHERE id = ?", (timezone, user_id))


def get_settings(conn: sqlite3.Connection, user_id: str) -> UserSettings:
    """Return the user's settings, creating defaults if the row is missing."""
    row = conn.execute(
        "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
        return UserSettings(user_id=user_id)
    return UserSettings(
        user_id=row["user_id"],
        reminders_enabled=bool(row["reminders_enabled"]),
        interval_min=row["interval_min"],
        window_start=row["window_start"],
        window_end=row["window_end"],
        nearby_enabled=bool(row["nearby_enabled"]),
        nutrition_replies_enabled=bool(row["nutrition_replies_enabled"]),
        undo_window_sec=row["undo_window_sec"],
    )


def update_settings(conn: sqlite3.Connection, settings: UserSettings) -> None:
    """Persist a settings object wholesale."""
    conn.execute(
        "UPDATE user_settings SET reminders_enabled = ?, interval_min = ?,"
        " window_start = ?, window_end = ?, nearby_enabled = ?,"
        " nutrition_replies_enabled = ?, undo_window_sec = ? WHERE user_id = ?",
        (
            int(settings.reminders_enabled),
            settings.interval_min,
            settings.window_start,
            settings.window_end,
            int(settings.nearby_enabled),
            int(settings.nutrition_replies_enabled),
            settings.undo_window_sec,
            settings.user_id,
        ),
    )


def set_goal(conn: sqlite3.Connection, goal: Goal) -> None:
    """Create or replace a goal or limit for a drink category."""
    conn.execute(
        "INSERT INTO user_goals (user_id, drink_category, kind, target, period, active)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (user_id, drink_category, kind) DO UPDATE SET"
        "   target = excluded.target, period = excluded.period, active = excluded.active",
        (
            goal.user_id,
            goal.drink_category,
            str(goal.kind),
            goal.target,
            goal.period,
            int(goal.active),
        ),
    )


def get_goals(conn: sqlite3.Connection, user_id: str) -> list[Goal]:
    """Return the user's active goals and limits."""
    return [
        Goal(
            user_id=row["user_id"],
            drink_category=row["drink_category"],
            kind=GoalKind(row["kind"]),
            target=row["target"],
            period=row["period"],
            active=bool(row["active"]),
        )
        for row in conn.execute(
            "SELECT * FROM user_goals WHERE user_id = ? AND active = 1", (user_id,)
        )
    ]


def delete_account(conn: sqlite3.Connection, user_id: str) -> None:
    """Delete a user and everything belonging to them.

    Relies on ``ON DELETE CASCADE``, which only works when ``PRAGMA
    foreign_keys`` is on for the connection -- ``db.connect()`` sets it.
    """
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
