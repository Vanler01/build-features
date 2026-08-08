"""Webhook delivery deduplication.

Telegram and LINE both redeliver an update if the webhook does not answer 2xx
promptly — a slow Claude call is enough. Handling the same message twice parses
it twice, and each parse mints a fresh entry UUID, so the user's drink is
logged twice with no way for the sync model to tell.

``logs.upsert_entry`` is idempotent per *entry id*, which protects a client
replaying the same entry. It cannot help here, because the server genuinely
produced two different entries from one message. The platform's own event id is
the only stable identity, so it is claimed here before the message is handled.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from . import day as day_util
from .models import Platform

# Long enough to cover any redelivery window either platform uses, short enough
# that the table stays small.
RETENTION = timedelta(days=2)


def claim(conn: sqlite3.Connection, platform: Platform, event_id: str) -> bool:
    """Claim an event id. Returns True if this caller may handle it.

    Relies on the primary key rather than a read-then-write, so two concurrent
    deliveries of the same update cannot both win: one insert succeeds, the
    other raises and returns False.

    An empty event id is treated as unclaimable-but-allowed. Some payload
    shapes carry no usable id, and refusing to serve those users would be a
    worse failure than the duplicate this guards against.
    """
    if not event_id:
        return True
    try:
        conn.execute(
            "INSERT INTO processed_events (platform, event_id, processed_at)"
            " VALUES (?, ?, ?)",
            (str(platform), event_id, day_util.to_iso(day_util.utc_now())),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def release(conn: sqlite3.Connection, platform: Platform, event_id: str) -> None:
    """Give a claim back so a genuine retry can be handled.

    Called when handling failed for a reason a retry might fix. Without this a
    transient database or network error would permanently swallow the message:
    the claim would stand, and the platform's redelivery would be treated as a
    duplicate and silently dropped.
    """
    if not event_id:
        return
    conn.execute(
        "DELETE FROM processed_events WHERE platform = ? AND event_id = ?",
        (str(platform), event_id),
    )


def prune(conn: sqlite3.Connection, older_than: timedelta = RETENTION) -> int:
    """Delete claims older than the redelivery window. Returns how many went."""
    cutoff = day_util.to_iso(day_util.utc_now() - older_than)
    return conn.execute(
        "DELETE FROM processed_events WHERE processed_at < ?", (cutoff,)
    ).rowcount
