"""LINE implementation of MessagingPort.

Same shape as the Telegram adapter -- HTTP over httpx, ``parse_incoming`` a
pure function over the webhook payload -- but LINE has one property Telegram
does not, and it dominates the design:

**Replying is free; pushing is metered.** A reply answers something the user
just sent and costs nothing. A push is unsolicited and counts against the
Thailand free plan's 300 messages a month, which one user on a two-hour
reminder interval burns about 210 of. So every send takes the reply path when
it can, and the only thing that should ever push is a reminder.

That is why ``send`` takes a ``reply_token``: LINE issues one per incoming
message, it is single-use and expires in about a minute, and using it is the
entire difference between free and paid.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any

import httpx

from ..core.day import utc_now
from ..core.models import Platform
from .port import (
    IncomingKind,
    IncomingMessage,
    OutgoingMessage,
    chunk_text,
)

_LOG = logging.getLogger(__name__)

API_ROOT = "https://api.line.me/v2/bot"
CONTENT_ROOT = "https://api-data.line.me/v2/bot"

# LINE's own limits. Exceeding any of them is a rejected request, not a warning.
MAX_MESSAGE_CHARS = 5000
MAX_MESSAGES_PER_REQUEST = 5
MAX_QUICK_REPLY_ITEMS = 13
MAX_QUICK_REPLY_LABEL = 20
MAX_POSTBACK_DATA = 300

TRUNCATION_NOTICE = "\n\n(…message truncated)"


def verify_signature(channel_secret: str, body: bytes, signature: str) -> bool:
    """Whether a webhook body genuinely came from LINE.

    Anyone who learns the webhook URL can POST to it, so an unverified endpoint
    lets a stranger fabricate drink logs for any user id they guess. Compared
    with ``compare_digest`` to avoid leaking the expected value by timing.
    """
    if not channel_secret or not signature:
        return False
    expected = base64.b64encode(
        hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


class LineAdapter:
    """Implements ``MessagingPort`` for LINE."""

    platform = Platform.LINE

    def __init__(self, channel_access_token: str, client: httpx.AsyncClient) -> None:
        """Store the channel access token and an HTTP client."""
        if not channel_access_token:
            raise ValueError("line channel access token is required")
        self._token = channel_access_token
        self._client = client

    # -- inbound ------------------------------------------------------------

    def parse_incoming(self, raw: object) -> IncomingMessage | None:
        """Normalize one LINE webhook *event*. Returns None for events we ignore.

        Note this takes a single event, not the whole webhook body -- LINE
        batches events in an ``events`` array, and ``iter_events`` unpacks it.
        """
        if not isinstance(raw, dict):
            return None
        if raw.get("type") != "message":
            # follow / unfollow / join / postback / beacon all arrive here.
            return None

        source = raw.get("source")
        if not isinstance(source, dict) or source.get("type") != "user":
            # Group and room events carry no stable per-person id we should log
            # against, so they are ignored rather than mis-attributed.
            return None
        user_id = source.get("userId")
        if not user_id:
            return None

        message = raw.get("message")
        if not isinstance(message, dict):
            return None

        reply_token = raw.get("replyToken") or None
        event_id = raw.get("webhookEventId") or None
        received_at = utc_now()
        kind = message.get("type")

        if kind == "location":
            lat, lon = message.get("latitude"), message.get("longitude")
            if lat is None or lon is None:
                return None
            return IncomingMessage(
                platform=Platform.LINE,
                platform_user_id=str(user_id),
                kind=IncomingKind.LOCATION,
                received_at=received_at,
                latitude=float(lat),
                longitude=float(lon),
                reply_token=reply_token,
                event_id=event_id,
            )

        if kind == "image":
            message_id = message.get("id")
            if not message_id:
                return None
            return IncomingMessage(
                platform=Platform.LINE,
                platform_user_id=str(user_id),
                kind=IncomingKind.PHOTO,
                received_at=received_at,
                photo_ref=str(message_id),
                reply_token=reply_token,
                event_id=event_id,
            )

        if kind != "text":
            # stickers, audio, video, files
            return None

        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return None

        if text.startswith("/"):
            head, _, rest = text.partition(" ")
            return IncomingMessage(
                platform=Platform.LINE,
                platform_user_id=str(user_id),
                kind=IncomingKind.COMMAND,
                received_at=received_at,
                text=text,
                command=head.lower(),
                args=rest.strip() or None,
                reply_token=reply_token,
                event_id=event_id,
            )

        return IncomingMessage(
            platform=Platform.LINE,
            platform_user_id=str(user_id),
            kind=IncomingKind.TEXT,
            received_at=received_at,
            text=text,
            reply_token=reply_token,
            event_id=event_id,
        )

    def iter_events(self, body: object) -> list[IncomingMessage]:
        """Unpack a webhook body into normalized messages.

        LINE batches events, and sends an empty batch as a connection check
        when you save the webhook URL in the console -- that must not error.
        """
        if not isinstance(body, dict):
            return []
        events = body.get("events")
        if not isinstance(events, list):
            return []
        parsed = (self.parse_incoming(event) for event in events)
        return [m for m in parsed if m is not None]

    # -- outbound -----------------------------------------------------------

    async def send(
        self,
        platform_user_id: str,
        message: OutgoingMessage,
        *,
        reply_token: str | None = None,
    ) -> bool:
        """Deliver a message, replying for free where possible.

        Uses the reply endpoint whenever a token is available and the message
        is not explicitly a push. A reply that falls back to push is logged at
        warning level, because that silently spends quota and the cause is
        always a caller that lost the token.
        """
        messages = self._build_messages(message)

        if reply_token and not message.is_push:
            return await self._post(
                "message/reply", {"replyToken": reply_token, "messages": messages}
            )

        if not message.is_push:
            _LOG.warning(
                "line reply had no token; falling back to a metered push for %s",
                platform_user_id,
            )
        return await self._post(
            "message/push", {"to": platform_user_id, "messages": messages}
        )

    async def fetch_photo(self, photo_ref: str) -> bytes:
        """Download an image's bytes from the content endpoint.

        Callers must resize before any vision call and must never persist the
        result -- see CLAUDE.md rule 1.
        """
        response = await self._client.get(
            f"{CONTENT_ROOT}/message/{photo_ref}/content", headers=self._headers()
        )
        response.raise_for_status()
        return response.content

    # -- message construction -----------------------------------------------

    def _build_messages(self, message: OutgoingMessage) -> list[dict[str, Any]]:
        """Turn one OutgoingMessage into LINE's message array.

        LINE caps a single request at five message objects. Our replies are far
        shorter than 5 x 5000 characters, but rather than silently dropping the
        tail if that ever changes, the last message carries a visible notice.
        """
        chunks = chunk_text(message.text, MAX_MESSAGE_CHARS)

        if len(chunks) > MAX_MESSAGES_PER_REQUEST:
            _LOG.error(
                "line reply needed %d messages; capping at %d",
                len(chunks),
                MAX_MESSAGES_PER_REQUEST,
            )
            chunks = chunks[:MAX_MESSAGES_PER_REQUEST]
            keep = MAX_MESSAGE_CHARS - len(TRUNCATION_NOTICE)
            chunks[-1] = chunks[-1][:keep] + TRUNCATION_NOTICE

        messages: list[dict[str, Any]] = [{"type": "text", "text": c} for c in chunks]

        quick_reply = _quick_reply(message)
        if quick_reply is not None:
            # Quick replies attach to the last message in the batch, so they
            # appear once the whole reply has been delivered.
            messages[-1]["quickReply"] = quick_reply
        return messages

    # -- transport ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _redact(self, text: str) -> str:
        """Remove the channel access token from a string before logging it."""
        return text.replace(self._token, "<token>")

    async def _post(self, path: str, payload: dict[str, Any]) -> bool:
        """POST to the Messaging API, returning success rather than raising."""
        try:
            response = await self._client.post(
                f"{API_ROOT}/{path}", json=payload, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            _LOG.warning("line %s failed: %s", path, self._redact(str(exc)))
            return False

        if response.status_code == 429:
            _LOG.warning("line %s rate limited", path)
            return False
        if response.status_code >= 400:
            _LOG.warning("line %s returned %s", path, response.status_code)
            return False
        return True


def _quick_reply(message: OutgoingMessage) -> dict[str, Any] | None:
    """Build LINE's quick-reply block, or None when the message needs none."""
    items: list[dict[str, Any]] = []

    if message.request_location:
        items.append(
            {
                "type": "action",
                "action": {"type": "location", "label": "Share location"},
            }
        )

    for choice in message.choices[: MAX_QUICK_REPLY_ITEMS - len(items)]:
        label = choice.label[:MAX_QUICK_REPLY_LABEL]
        action: dict[str, Any] = (
            {"type": "uri", "label": label, "uri": choice.url}
            if choice.url
            else {
                "type": "postback",
                "label": label,
                "data": choice.value[:MAX_POSTBACK_DATA],
            }
        )
        items.append({"type": "action", "action": action})

    return {"items": items} if items else None
