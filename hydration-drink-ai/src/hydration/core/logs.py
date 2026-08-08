"""The log store: entry events, not counts.

Three surfaces write to the same day -- an offline widget, the app, and a bot
writing server-side. If any of them synced a *count* ("today = 3"), two sources
disagreeing would silently overwrite each other and drinks would appear or
vanish. So the only operations are:

    add(entry)        -> create entry <uuid>
    remove(entry_id)  -> tombstone entry <uuid>

Both are idempotent and commutative: applying the same event twice is identical
to applying it once, and applying a set of events in any order gives the same
result. That is what makes offline widget taps safe to replay later.

The one ordering rule is that a tombstone is *absorbing*: once an entry is
removed it stays removed, even if a delayed "add" for the same id arrives
afterwards. Without that, a slow network could resurrect a drink the user had
already deleted.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime

from . import day as day_util
from .models import LogEntry, LogSource


def upsert_entry(conn: sqlite3.Connection, entry: LogEntry) -> bool:
    """Record an entry. Returns True if this call created it.

    Safe to call repeatedly with the same entry id -- a duplicate delivery is
    ignored rather than double-counted. An entry that has already been
    tombstoned is *not* revived.
    """
    existing = conn.execute(
        "SELECT deleted_at FROM logs WHERE id = ?", (entry.id,)
    ).fetchone()
    if existing is not None:
        return False

    now = day_util.to_iso(day_util.utc_now())
    conn.execute(
        "INSERT INTO logs (id, user_id, drink_id, custom_name, quantity, logged_at,"
        "                  source, place_id, deleted_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entry.id,
            entry.user_id,
            entry.drink_id,
            entry.custom_name,
            entry.quantity,
            day_util.to_iso(entry.logged_at),
            str(entry.source),
            entry.place_id,
            day_util.to_iso(entry.deleted_at) if entry.deleted_at else None,
            now,
        ),
    )
    return True


def remove_entry(
    conn: sqlite3.Connection,
    entry_id: str,
    user_id: str,
    when: datetime | None = None,
) -> bool:
    """Tombstone an entry. Returns True if this call removed a live entry.

    Tombstoning an unknown id writes a tombstone anyway, so that a removal
    arriving before the add it refers to still wins. This is what makes the
    operation order-independent.
    """
    moment = day_util.to_iso(when or day_util.utc_now())
    row = conn.execute(
        "SELECT deleted_at FROM logs WHERE id = ? AND user_id = ?",
        (entry_id, user_id),
    ).fetchone()

    if row is None:
        # Removal arrived before its add. Record a tombstoned placeholder so the
        # later add cannot resurrect the entry.
        conn.execute(
            "INSERT INTO logs (id, user_id, custom_name, quantity, logged_at,"
            "                  source, deleted_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (entry_id, user_id, "", 1.0, moment, str(LogSource.APP), moment, moment),
        )
        return False

    if row["deleted_at"] is not None:
        return False

    conn.execute(
        "UPDATE logs SET deleted_at = ? WHERE id = ? AND user_id = ?",
        (moment, entry_id, user_id),
    )
    return True


def apply_events(conn: sqlite3.Connection, events: list[tuple[str, object]]) -> None:
    """Apply a batch of ``('add', LogEntry)`` / ``('remove', entry_id)`` events.

    This is the outbox drain path: the widget accumulates events offline and the
    app replays them here. Order within the batch does not matter.
    """
    for kind, payload in events:
        if kind == "add":
            assert isinstance(payload, LogEntry)
            upsert_entry(conn, payload)
        elif kind == "remove":
            assert isinstance(payload, tuple)
            entry_id, user_id = payload
            remove_entry(conn, entry_id, user_id)
        else:
            raise ValueError(f"unknown event kind: {kind!r}")


def live_entries(
    conn: sqlite3.Connection,
    user_id: str,
    timezone: str,
    when: datetime | None = None,
) -> list[sqlite3.Row]:
    """Every non-removed entry for the user's current local day."""
    start, end = day_util.current_day_bounds(timezone, when)
    return list(
        conn.execute(
            "SELECT * FROM logs"
            " WHERE user_id = ? AND deleted_at IS NULL"
            "   AND logged_at >= ? AND logged_at < ?"
            " ORDER BY logged_at",
            (user_id, day_util.to_iso(start), day_util.to_iso(end)),
        )
    )


def last_live_entry(
    conn: sqlite3.Connection,
    user_id: str,
    timezone: str,
    when: datetime | None = None,
) -> sqlite3.Row | None:
    """Return the most recent non-removed entry on the user's current local day.

    Backs ``/undo``. Scoped to today so an undo can never silently reach back
    into a previous day the user has stopped thinking about.
    """
    entries = live_entries(conn, user_id, timezone, when)
    return entries[-1] if entries else None


def day_totals(
    conn: sqlite3.Connection,
    user_id: str,
    timezone: str,
    when: datetime | None = None,
) -> dict[str, float]:
    """Quantity per drink for the user's current local day.

    Keyed by ``drink_id`` when the drink is in the catalog, otherwise by
    ``custom_name``. This is what the daily summary and the widget read.
    """
    totals: Counter[str] = Counter()
    for row in live_entries(conn, user_id, timezone, when):
        key = row["drink_id"] or row["custom_name"]
        if not key:
            continue
        totals[key] += row["quantity"]
    return dict(totals)


def category_totals(
    conn: sqlite3.Connection,
    user_id: str,
    timezone: str,
    when: datetime | None = None,
) -> dict[str, float]:
    """Quantity per catalog category for the local day.

    Goals and limiters are set per category, so this is what their progress and
    the widget colour states are computed from. Custom drinks with no catalog
    entry fall under ``'uncategorised'`` rather than being dropped.
    """
    start, end = day_util.current_day_bounds(timezone, when)
    rows = conn.execute(
        "SELECT COALESCE(d.category, 'uncategorised') AS category,"
        "       SUM(l.quantity) AS total"
        "  FROM logs l"
        "  LEFT JOIN drinks_catalog d ON d.id = l.drink_id"
        " WHERE l.user_id = ? AND l.deleted_at IS NULL"
        "   AND l.logged_at >= ? AND l.logged_at < ?"
        " GROUP BY category",
        (user_id, day_util.to_iso(start), day_util.to_iso(end)),
    )
    return {row["category"]: float(row["total"]) for row in rows}
