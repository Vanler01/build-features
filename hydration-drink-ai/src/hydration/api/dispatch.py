"""Turning one normalized message into sent replies.

Shared by every transport — Telegram webhook, LINE webhook, and the local
poller all funnel through ``dispatch``. That is what keeps the promise made in
``AI_PROJECTS.md``: switching between webhook and polling never touches handler
code, because neither transport contains any.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from .. import handlers
from ..adapters.port import IncomingKind, IncomingMessage, MessagingPort
from ..core import events
from ..core.models import Platform

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Dispatcher:
    """Holds the adapters and handler dependencies a transport needs."""

    adapters: dict[Platform, MessagingPort]
    deps: handlers.HandlerDeps

    async def dispatch(self, conn: sqlite3.Connection, message: IncomingMessage) -> bool:
        """Handle one message and send its replies. Returns whether it was handled.

        Returns False for a redelivery, which the caller should still answer
        2xx to — the platform is asking "did you get this?", and the honest
        answer is yes.
        """
        adapter = self.adapters.get(message.platform)
        if adapter is None:
            _LOG.warning("no adapter configured for %s", message.platform)
            return False

        if not events.claim(conn, message.platform, message.event_id or ""):
            _LOG.info(
                "ignoring redelivery of %s event %s", message.platform, message.event_id
            )
            return False

        photo_bytes = await self._download_photo(adapter, message)

        try:
            replies = handlers.handle(conn, message, self.deps, photo_bytes)
        except Exception:
            # handlers.handle catches its own failures, so reaching here means
            # something below it broke badly. Release the claim so the
            # platform's retry is not swallowed as a duplicate.
            events.release(conn, message.platform, message.event_id or "")
            raise

        for reply in replies:
            # The reply token is single-use and expires in about a minute, so
            # only the first reply can use it. On LINE the rest would be
            # metered pushes, which is why replies are kept to one message.
            await adapter.send(
                message.platform_user_id, reply, reply_token=message.reply_token
            )
        return True

    async def _download_photo(
        self, adapter: MessagingPort, message: IncomingMessage
    ) -> bytes | None:
        """Fetch a photo's bytes, if this is a photo and vision is switched on.

        Downloading here rather than in the handler is what lets the handler
        stay synchronous: ``fetch_photo`` is async and per-platform, and this
        is the only layer that is both async and holds the right adapter.

        Skipped entirely when vision is off, so a text-only deployment never
        pays for a download it would immediately discard.
        """
        if message.kind is not IncomingKind.PHOTO or self.deps.parse_photo is None:
            return None
        if not message.photo_ref:
            return None

        try:
            return await adapter.fetch_photo(message.photo_ref)
        except Exception:  # noqa: BLE001 — a failed download is a retry, not a crash
            _LOG.warning(
                "photo download failed for %s; replying with a retry", message.platform
            )
            return None
