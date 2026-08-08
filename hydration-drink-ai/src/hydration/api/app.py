"""Webhook endpoints for Telegram and LINE.

Both platforms POST to a public URL, so both routes authenticate before doing
any work. An unauthenticated webhook lets anyone who learns the URL fabricate
drink logs against a guessed user id.

  * Telegram sends a shared secret in ``X-Telegram-Bot-Api-Secret-Token``,
    fixed at ``setWebhook`` time.
  * LINE signs the body with the channel secret; the signature is checked
    against the **raw** bytes, because re-serialising the JSON changes them and
    breaks the MAC.

Both routes answer 2xx as long as the delivery was genuine, including for
redeliveries and unparseable payloads. A non-2xx makes the platform retry, and
retrying will not fix a message we could not read — it just multiplies it.
"""

from __future__ import annotations

import hmac
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI, Header, Request, Response

from ..adapters.line import LineAdapter, verify_signature
from ..core import db
from ..core.models import Platform
from .dispatch import Dispatcher

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    """Secrets the routes need to authenticate callers."""

    db_path: str
    telegram_secret: str = ""
    line_channel_secret: str = ""


def create_app(dispatcher: Dispatcher, config: WebhookConfig) -> FastAPI:
    """Build the ASGI app.

    Takes its dependencies as arguments rather than reading the environment, so
    tests construct it directly with fakes and no secrets.
    """
    app = FastAPI(title="hydration-drink-ai", docs_url=None, redoc_url=None)
    app.include_router(_router(dispatcher, config))
    return app


@contextmanager
def _connection(db_path: str) -> Iterator[sqlite3.Connection]:
    """Open a connection for one request.

    A connection per request rather than a shared one: sqlite3 objects are not
    safe to share across threads, and FastAPI runs sync work in a threadpool.
    """
    conn = db.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _router(dispatcher: Dispatcher, config: WebhookConfig) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    @router.post("/webhook/telegram")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str = Header(default=""),
    ) -> Response:
        """Receive a Telegram update."""
        if not config.telegram_secret or not hmac.compare_digest(
            x_telegram_bot_api_secret_token, config.telegram_secret
        ):
            _LOG.warning("rejected telegram webhook with a bad secret token")
            return Response(status_code=403)

        adapter = dispatcher.adapters.get(Platform.TELEGRAM)
        if adapter is None:
            return Response(status_code=503)

        try:
            payload = await request.json()
        except ValueError:
            # Malformed body. Answer 200: a retry would deliver the same bytes.
            _LOG.warning("telegram webhook body was not json")
            return Response(status_code=200)

        message = adapter.parse_incoming(payload)
        if message is None:
            # An update type we don't handle — channel post, poll, edit.
            return Response(status_code=200)

        with _connection(config.db_path) as conn:
            await dispatcher.dispatch(conn, message)
        return Response(status_code=200)

    @router.post("/webhook/line")
    async def line_webhook(
        request: Request,
        x_line_signature: str = Header(default=""),
    ) -> Response:
        """Receive a batch of LINE events."""
        # Raw bytes: FastAPI's parsed body would not reproduce them, and the
        # signature is over exactly what was sent.
        raw = await request.body()
        if not verify_signature(config.line_channel_secret, raw, x_line_signature):
            _LOG.warning("rejected line webhook with a bad signature")
            return Response(status_code=403)

        adapter = dispatcher.adapters.get(Platform.LINE)
        if not isinstance(adapter, LineAdapter):
            return Response(status_code=503)

        try:
            payload = await request.json()
        except ValueError:
            _LOG.warning("line webhook body was not json")
            return Response(status_code=200)

        # LINE posts an empty batch when the webhook URL is saved in the
        # console; iter_events returns [] and this answers 200, which is what
        # the console's verification button is looking for.
        messages = adapter.iter_events(payload)
        if messages:
            with _connection(config.db_path) as conn:
                for message in messages:
                    await dispatcher.dispatch(conn, message)
        return Response(status_code=200)

    return router
