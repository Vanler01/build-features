"""Telegram implementation of MessagingPort.

Talks to the Bot API over plain HTTP rather than through a bot framework. The
port already owns the handler model, so a framework's dispatcher would be a
second, competing one -- and LINE's SDK would bring a third. Going direct keeps
both adapters the same shape and makes ``parse_incoming`` a pure function over
the update dict, which is what most of the tests exercise.

Webhook and long polling deliver byte-identical update objects, so nothing here
knows which transport produced one. That is the whole point of the split:
switching transports never touches handler code.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.day import utc_now
from ..core.models import Platform
from .port import (
    Choice,
    IncomingKind,
    IncomingMessage,
    OutgoingMessage,
    chunk_text,
)

_LOG = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"

# Telegram rejects callback payloads over 64 *bytes*. Exceeding it fails
# silently at send time, so choices are truncated to fit rather than trusted.
MAX_CALLBACK_BYTES = 64

# Telegram's own outbound cap. chunk_text splits against it.
MAX_MESSAGE_CHARS = 4096


class TelegramAdapter:
    """Implements ``MessagingPort`` for Telegram."""

    platform = Platform.TELEGRAM

    def __init__(self, token: str, client: httpx.AsyncClient) -> None:
        """Store the bot token and an HTTP client.

        The token is held only for URL construction and must never be logged;
        ``_redact`` exists so a URL can be safely put in a log line.
        """
        if not token:
            raise ValueError("telegram bot token is required")
        self._token = token
        self._client = client

    # -- inbound ------------------------------------------------------------

    def parse_incoming(self, raw: object) -> IncomingMessage | None:
        """Normalize a Telegram update. Returns None for updates we ignore.

        Ignoring rather than raising matters: Telegram sends edited messages,
        channel posts, poll updates and more down the same webhook, and an
        adapter that raises on the unfamiliar ones takes the bot down.
        """
        if not isinstance(raw, dict):
            return None
        message = raw.get("message") or raw.get("edited_message")
        if not isinstance(message, dict):
            return None

        sender = message.get("from")
        if not isinstance(sender, dict) or "id" not in sender:
            return None
        platform_user_id = str(sender["id"])

        received_at = utc_now()

        if isinstance(message.get("location"), dict):
            location = message["location"]
            lat, lon = location.get("latitude"), location.get("longitude")
            if lat is None or lon is None:
                return None
            return IncomingMessage(
                platform=Platform.TELEGRAM,
                platform_user_id=platform_user_id,
                kind=IncomingKind.LOCATION,
                received_at=received_at,
                latitude=float(lat),
                longitude=float(lon),
            )

        photos = message.get("photo")
        if isinstance(photos, list) and photos:
            # photo[] is ascending by size. photo[0] is a thumbnail -- parsing
            # a drink from it would be guesswork, so take the largest.
            largest = photos[-1]
            file_id = largest.get("file_id") if isinstance(largest, dict) else None
            if not file_id:
                return None
            return IncomingMessage(
                platform=Platform.TELEGRAM,
                platform_user_id=platform_user_id,
                kind=IncomingKind.PHOTO,
                received_at=received_at,
                photo_ref=str(file_id),
                text=message.get("caption") or None,
            )

        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        if text.startswith("/"):
            command, args = _split_command(text)
            return IncomingMessage(
                platform=Platform.TELEGRAM,
                platform_user_id=platform_user_id,
                kind=IncomingKind.COMMAND,
                received_at=received_at,
                text=text,
                command=command,
                args=args or None,
            )

        return IncomingMessage(
            platform=Platform.TELEGRAM,
            platform_user_id=platform_user_id,
            kind=IncomingKind.TEXT,
            received_at=received_at,
            text=text,
        )

    # -- outbound -----------------------------------------------------------

    async def send(self, platform_user_id: str, message: OutgoingMessage) -> bool:
        """Deliver a message. Returns whether every part was accepted.

        Never raises on transport failure: a reminder that fails for one user
        must not take down a scheduler serving everyone else.
        """
        chunks = chunk_text(message.text, MAX_MESSAGE_CHARS)
        ok = True
        for index, chunk in enumerate(chunks):
            is_last = index == len(chunks) - 1
            payload: dict[str, Any] = {
                "chat_id": platform_user_id,
                "text": chunk,
                # No parse_mode. Drink names, place names and numeric output
                # routinely contain characters MarkdownV2 treats as syntax, and
                # an unescaped one makes the send fail silently rather than
                # visibly. Plain text cannot fail that way.
                "disable_web_page_preview": True,
            }
            if is_last:
                markup = _reply_markup(message)
                if markup is not None:
                    payload["reply_markup"] = markup
            ok = await self._call("sendMessage", payload) and ok
        return ok

    async def fetch_photo(self, photo_ref: str) -> bytes:
        """Download a photo's bytes.

        Callers must resize before any vision call and must never persist the
        result -- see CLAUDE.md rule 1.
        """
        meta = await self._call_json("getFile", {"file_id": photo_ref})
        if meta is None:
            raise RuntimeError("could not resolve telegram file")
        file_path = meta.get("file_path")
        if not file_path:
            raise RuntimeError("telegram returned no file_path")

        url = f"{API_ROOT}/file/bot{self._token}/{file_path}"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.content

    # -- transport ----------------------------------------------------------

    def _url(self, method: str) -> str:
        return f"{API_ROOT}/bot{self._token}/{method}"

    def _redact(self, text: str) -> str:
        """Remove the bot token from a string before it reaches a log."""
        return text.replace(self._token, "<token>")

    async def _call(self, method: str, payload: dict[str, Any]) -> bool:
        """Call a Bot API method, returning success rather than raising."""
        return await self._call_json(method, payload) is not None

    async def _call_json(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Call a Bot API method and return its ``result``, or None on failure."""
        try:
            response = await self._client.post(self._url(method), json=payload)
        except httpx.HTTPError as exc:
            _LOG.warning("telegram %s failed: %s", method, self._redact(str(exc)))
            return None

        if response.status_code == 429:
            # Telegram puts the backoff hint in the body, not a header.
            retry_after = _retry_after(response)
            _LOG.warning("telegram %s rate limited; retry_after=%ss", method, retry_after)
            return None
        if response.status_code >= 400:
            _LOG.warning("telegram %s returned %s", method, response.status_code)
            return None

        body = response.json()
        if not body.get("ok"):
            _LOG.warning("telegram %s not ok: %s", method, body.get("description"))
            return None
        result = body.get("result")
        return result if isinstance(result, dict) else {}


def _split_command(text: str) -> tuple[str, str]:
    """Split ``/log@MyBot two waters`` into ``('/log', 'two waters')``.

    Group chats append ``@botname`` to commands; leaving it attached would make
    every command unrecognised the moment the bot joins a group.
    """
    head, _, rest = text.partition(" ")
    command = head.split("@", 1)[0].lower()
    return command, rest.strip()


def _callback_data(choice: Choice) -> str:
    """Encode a choice's value within Telegram's 64-byte callback limit."""
    encoded = choice.value.encode()
    if len(encoded) <= MAX_CALLBACK_BYTES:
        return choice.value
    return encoded[:MAX_CALLBACK_BYTES].decode(errors="ignore")


def _reply_markup(message: OutgoingMessage) -> dict[str, Any] | None:
    """Build the keyboard for a message, if it needs one."""
    if message.request_location:
        # A reply keyboard is the only way to ask for a location share, and it
        # is one-time: the user opts in per message, never once and forever.
        return {
            "keyboard": [[{"text": "Share my location", "request_location": True}]],
            "one_time_keyboard": True,
            "resize_keyboard": True,
        }
    if message.choices:
        return {
            "inline_keyboard": [
                [
                    {"text": c.label, "url": c.url}
                    if c.url
                    else {"text": c.label, "callback_data": _callback_data(c)}
                ]
                for c in message.choices
            ]
        }
    return None


def _retry_after(response: httpx.Response) -> int:
    """Extract Telegram's retry_after hint, defaulting to a sane backoff."""
    try:
        return int(response.json().get("parameters", {}).get("retry_after", 1))
    except (ValueError, AttributeError, TypeError):
        return 1
