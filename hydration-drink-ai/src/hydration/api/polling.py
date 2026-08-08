"""Telegram long polling, for local development.

A webhook needs a public HTTPS URL, which is a tunnel or a deploy. Polling
needs neither, so this is what you run while building.

It goes through the same ``Dispatcher`` as the webhook route, so switching
between them changes nothing below this file — the promise ``MessagingPort``
and ``Dispatcher`` exist to keep.

Not for production: one poller per bot token, and a second one silently steals
half the updates.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

import httpx

from ..adapters.telegram import API_ROOT
from .dispatch import Dispatcher

_LOG = logging.getLogger(__name__)

# Telegram holds the request open until something arrives or this elapses.
LONG_POLL_SECONDS = 25


async def poll_forever(
    conn: sqlite3.Connection,
    dispatcher: Dispatcher,
    token: str,
    client: httpx.AsyncClient,
) -> None:
    """Poll getUpdates and dispatch what arrives, until cancelled."""
    from ..adapters.telegram import TelegramAdapter

    adapter = dispatcher.adapters.get(TelegramAdapter.platform)
    if adapter is None:
        raise RuntimeError("no telegram adapter configured")

    offset: int | None = None
    _LOG.info("long polling started")

    while True:
        try:
            response = await client.get(
                f"{API_ROOT}/bot{token}/getUpdates",
                params={
                    "timeout": LONG_POLL_SECONDS,
                    **({"offset": offset} if offset is not None else {}),
                },
                timeout=LONG_POLL_SECONDS + 10,
            )
            body = response.json()
        except asyncio.CancelledError:
            _LOG.info("long polling stopping")
            raise
        except (httpx.HTTPError, ValueError) as exc:
            _LOG.warning("getUpdates failed: %s", type(exc).__name__)
            await asyncio.sleep(3)
            continue

        if not body.get("ok"):
            _LOG.warning("getUpdates not ok: %s", body.get("description"))
            await asyncio.sleep(3)
            continue

        for update in body.get("result", []):
            # Advance the offset even for updates we ignore, or Telegram
            # redelivers them forever and the poller never moves on.
            offset = update.get("update_id", 0) + 1

            message = adapter.parse_incoming(update)
            if message is None:
                continue
            try:
                await dispatcher.dispatch(conn, message)
            except Exception:  # noqa: BLE001 — one bad update must not stop the poller
                _LOG.exception("dispatch failed for update %s", update.get("update_id"))
