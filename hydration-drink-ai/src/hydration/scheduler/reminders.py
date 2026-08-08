"""Reminder scheduling.

Reminders are the only unsolicited message this product sends, which makes them
the only thing that costs LINE quota: the free Thailand plan allows 300 pushes a
month, and a user on a 2-hour interval across a 14-hour window burns 7 a day --
about 210 a month, for one user. So every send goes through ``push_budget``
first, and running out degrades quietly rather than erroring.

Scheduling is computed per user in their own timezone. A window may wrap past
midnight for night-shift users.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..core import day as day_util
from ..core import logs as logs_mod
from ..core import users as users_mod
from ..core.models import Platform

_LOG = logging.getLogger(__name__)

# LINE free plan (Thailand), verified 2026-08-08. Paid Basic is 15,000.
# Kept conservative on purpose: overshooting costs real money.
PUSH_LIMITS: dict[Platform, int | None] = {
    Platform.LINE: 300,
    Platform.TELEGRAM: None,  # unmetered
    Platform.APP: None,  # APNs/FCM, not metered by us
}


@dataclass(frozen=True, slots=True)
class DueReminder:
    """A reminder that should be sent now."""

    user_id: str
    platform: Platform
    platform_user_id: str
    text: str


def _year_month(moment: datetime) -> str:
    return moment.strftime("%Y-%m")


def push_allowance_remaining(
    conn: sqlite3.Connection,
    user_id: str,
    platform: Platform,
    now: datetime | None = None,
) -> int | None:
    """Return remaining pushes this month, or None when the platform is unmetered."""
    limit = PUSH_LIMITS.get(platform)
    if limit is None:
        return None
    moment = now or day_util.utc_now()
    row = conn.execute(
        "SELECT sent_count FROM push_budget"
        " WHERE user_id = ? AND platform = ? AND year_month = ?",
        (user_id, str(platform), _year_month(moment)),
    ).fetchone()
    used = row["sent_count"] if row else 0
    return max(0, limit - used)


def record_push(
    conn: sqlite3.Connection,
    user_id: str,
    platform: Platform,
    now: datetime | None = None,
) -> None:
    """Count one push against the user's monthly budget."""
    moment = now or day_util.utc_now()
    conn.execute(
        "INSERT INTO push_budget (user_id, platform, year_month, sent_count)"
        " VALUES (?, ?, ?, 1)"
        " ON CONFLICT (user_id, platform, year_month)"
        " DO UPDATE SET sent_count = sent_count + 1",
        (user_id, str(platform), _year_month(moment)),
    )


def may_push(
    conn: sqlite3.Connection,
    user_id: str,
    platform: Platform,
    now: datetime | None = None,
) -> bool:
    """Whether a push is allowed right now under the monthly ceiling."""
    remaining = push_allowance_remaining(conn, user_id, platform, now)
    return remaining is None or remaining > 0


def next_fire_time(
    last_sent: datetime | None,
    interval_min: int,
    window_start: str,
    window_end: str,
    timezone: str,
    now: datetime | None = None,
) -> datetime | None:
    """Compute when this user's next reminder is due.

    Returns None when the user is currently outside their active window -- the
    caller should re-check later rather than queueing a send for a sleeping user.
    """
    moment = now or day_util.utc_now()
    if not day_util.is_within_window(window_start, window_end, timezone, now=moment):
        return None
    if last_sent is None:
        return moment
    return last_sent + timedelta(minutes=interval_min)


def is_due(
    last_sent: datetime | None,
    interval_min: int,
    window_start: str,
    window_end: str,
    timezone: str,
    now: datetime | None = None,
) -> bool:
    """Whether a reminder should fire for this user at ``now``."""
    moment = now or day_util.utc_now()
    due_at = next_fire_time(last_sent, interval_min, window_start, window_end, timezone, moment)
    return due_at is not None and due_at <= moment


def compose_reminder(
    conn: sqlite3.Connection,
    user_id: str,
    timezone: str,
    now: datetime | None = None,
) -> str:
    """Build the reminder text, mentioning today's progress if there is any.

    Deliberately plain. A limiter being exceeded is stated as a number
    elsewhere, not nagged about here -- see CLAUDE.md rule 19.
    """
    totals = logs_mod.category_totals(conn, user_id, timezone, when=now)
    water = totals.get("water", 0)
    if water <= 0:
        return "Time for some water. Reply with what you've had and I'll log it."
    return f"Time for some water — {water:g} so far today."


def due_reminders(
    conn: sqlite3.Connection,
    last_sent_by_user: dict[str, datetime],
    now: datetime | None = None,
) -> list[DueReminder]:
    """Return every reminder that should be sent right now.

    Skips users who have reminders switched off, are outside their window, or
    have exhausted their platform's push budget. Budget exhaustion is logged
    once per user per call rather than raising -- one user hitting the LINE
    ceiling must not stop everyone else's reminders.
    """
    moment = now or day_util.utc_now()
    due: list[DueReminder] = []

    for row in conn.execute(
        "SELECT u.id AS user_id, u.timezone, s.reminders_enabled, s.interval_min,"
        "       s.window_start, s.window_end"
        "  FROM users u JOIN user_settings s ON s.user_id = u.id"
        " WHERE s.reminders_enabled = 1"
    ):
        user_id = row["user_id"]
        if not is_due(
            last_sent_by_user.get(user_id),
            row["interval_min"],
            row["window_start"],
            row["window_end"],
            row["timezone"],
            now=moment,
        ):
            continue

        text = compose_reminder(conn, user_id, row["timezone"], now=moment)
        for platform_name, platform_user_id in users_mod.identities_for(conn, user_id):
            platform = Platform(platform_name)
            if platform is Platform.APP:
                continue  # the app uses its own push channel
            if not may_push(conn, user_id, platform, moment):
                _LOG.warning(
                    "push budget exhausted for user %s on %s; skipping reminder",
                    user_id,
                    platform_name,
                )
                continue
            due.append(
                DueReminder(
                    user_id=user_id,
                    platform=platform,
                    platform_user_id=platform_user_id,
                    text=text,
                )
            )
    return due
