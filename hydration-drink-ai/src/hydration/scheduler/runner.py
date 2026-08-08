"""The reminder loop.

Finds users whose next nudge is due and sends it through their platform's
adapter. Two rules shape everything here:

**One user's failure must not stop the others.** A send that fails is logged
and skipped; the loop continues. A scheduler that dies on the first bad chat id
silently stops serving everyone.

**Quota is only spent when a message actually lands.** The push budget is
recorded after a successful send, and ``last_sent_at`` is only advanced then
too — so a failed reminder is retried on the next tick rather than being
counted as delivered and skipped for two hours.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime

from ..adapters.port import MessagingPort, OutgoingMessage
from ..core import day as day_util
from ..core.models import Platform
from . import reminders

_LOG = logging.getLogger(__name__)

# How often to look for due reminders. Well below the shortest sensible
# interval, so a reminder is never late by more than this.
TICK_SECONDS = 60


def load_last_sent(conn: sqlite3.Connection) -> dict[str, datetime]:
    """Read every user's last reminder time.

    Persisted rather than held in memory: on a restart, an in-memory map looks
    like "nobody has ever been reminded", so every user in their active window
    gets an immediate nudge. On LINE that is real money.
    """
    return {
        row["user_id"]: day_util.from_iso(row["last_sent_at"])
        for row in conn.execute(
            "SELECT user_id, last_sent_at FROM reminder_state WHERE last_sent_at IS NOT NULL"
        )
    }


def record_sent(
    conn: sqlite3.Connection, user_id: str, when: datetime | None = None
) -> None:
    """Mark a reminder as delivered."""
    moment = day_util.to_iso(when or day_util.utc_now())
    conn.execute(
        "INSERT INTO reminder_state (user_id, last_sent_at) VALUES (?, ?)"
        " ON CONFLICT (user_id) DO UPDATE SET last_sent_at = excluded.last_sent_at",
        (user_id, moment),
    )


async def send_due(
    conn: sqlite3.Connection,
    adapters: dict[Platform, MessagingPort],
    now: datetime | None = None,
) -> int:
    """Send every reminder that is due. Returns how many were delivered.

    Safe to call repeatedly; it is the body of the loop and the unit the tests
    drive directly.
    """
    moment = now or day_util.utc_now()
    due = reminders.due_reminders(conn, load_last_sent(conn), now=moment)
    delivered = 0

    for item in due:
        adapter = adapters.get(item.platform)
        if adapter is None:
            # Configured for a platform this process doesn't serve.
            continue

        try:
            ok = await adapter.send(
                item.platform_user_id,
                # is_push marks this as unsolicited, which is what makes LINE
                # bill it. A reminder genuinely is, so it is honest as well as
                # necessary — see LineAdapter.send.
                OutgoingMessage(text=item.text, is_push=True),
            )
        except Exception:  # noqa: BLE001 — one user must not stop the rest
            _LOG.exception(
                "reminder failed for user=%s platform=%s", item.user_id, item.platform
            )
            continue

        if not ok:
            _LOG.warning(
                "reminder not accepted for user=%s platform=%s; will retry next tick",
                item.user_id,
                item.platform,
            )
            continue

        # Only now: the message landed, so it costs quota and counts as sent.
        reminders.record_push(conn, item.user_id, item.platform, now=moment)
        record_sent(conn, item.user_id, moment)
        delivered += 1

    return delivered


async def run_forever(
    conn: sqlite3.Connection,
    adapters: dict[Platform, MessagingPort],
    tick_seconds: int = TICK_SECONDS,
) -> None:
    """Run the reminder loop until cancelled.

    Exceptions from a single tick are logged and swallowed; the loop is
    supposed to outlive a transient database or network problem.
    """
    _LOG.info("reminder loop started, tick=%ss", tick_seconds)
    while True:
        try:
            delivered = await send_due(conn, adapters)
            if delivered:
                _LOG.info("sent %d reminder(s)", delivered)
        except asyncio.CancelledError:
            _LOG.info("reminder loop stopping")
            raise
        except Exception:  # noqa: BLE001 — the loop must survive a bad tick
            _LOG.exception("reminder tick failed")
        await asyncio.sleep(tick_seconds)
