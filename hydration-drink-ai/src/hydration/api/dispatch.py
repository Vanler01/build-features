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
from ..adapters.port import IncomingMessage, MessagingPort
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

        try:
            replies = handlers.handle(conn, message, self.deps)
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
