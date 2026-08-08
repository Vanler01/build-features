"""The messaging port every chat platform implements.

Core logic talks to this protocol and never to Telegram or LINE directly, so
adding a platform is one new file here rather than a sweep through handlers. It
is also what keeps platform quirks -- LINE's metered pushes, Telegram's 4096
character cap -- from leaking into business rules.

Messenger and WeChat are deliberately absent. Neither can send a recurring
reminder under its 2026 rules; see REQUIREMENTS.md §0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ..core.models import Platform

# Telegram's hard limit. LINE's is lower (5000 for text, but 2000 is the safe
# practical bound for a single bubble), so the smaller of the two governs and
# adapters chunk against their own limit.
TELEGRAM_MAX_CHARS = 4096


class IncomingKind(StrEnum):
    """What sort of thing the user sent."""

    TEXT = "text"
    PHOTO = "photo"
    LOCATION = "location"
    COMMAND = "command"


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """A message normalized away from any platform's wire format.

    ``platform_user_id`` is the platform's own id. It is never a user id -- it
    must go through ``users.resolve_user`` first.
    """

    platform: Platform
    platform_user_id: str
    kind: IncomingKind
    received_at: datetime
    text: str | None = None
    command: str | None = None
    args: str | None = None
    photo_ref: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reply_token: str | None = None

    def __post_init__(self) -> None:
        """Reject shapes that cannot be handled downstream."""
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        if self.kind is IncomingKind.LOCATION and (
            self.latitude is None or self.longitude is None
        ):
            raise ValueError("location messages need latitude and longitude")
        if self.kind is IncomingKind.PHOTO and not self.photo_ref:
            raise ValueError("photo messages need a photo_ref")


@dataclass(frozen=True, slots=True)
class Choice:
    """One option in a choice list (a nearby place, a drink to confirm)."""

    label: str
    value: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """A reply. ``is_push`` decides whether it costs LINE quota.

    A *reply* answers something the user just sent and is free on LINE. A *push*
    is unsolicited -- a reminder -- and is metered at 300/month on the free
    plan. Getting this flag wrong is how a bot silently burns its quota, so it
    is explicit rather than inferred.
    """

    text: str
    choices: list[Choice] = field(default_factory=list)
    is_push: bool = False
    request_location: bool = False


@runtime_checkable
class MessagingPort(Protocol):
    """What every chat adapter provides.

    Implementations must not raise on transport failure; they return False and
    let the caller decide, because a failed reminder is not a reason to crash a
    scheduler serving other users.
    """

    platform: Platform

    def parse_incoming(self, raw: object) -> IncomingMessage | None:
        """Normalize a platform update. Returns None for updates we ignore."""
        ...

    async def send(self, platform_user_id: str, message: OutgoingMessage) -> bool:
        """Deliver a message. Returns whether it was accepted."""
        ...

    async def fetch_photo(self, photo_ref: str) -> bytes:
        """Download a photo's bytes.

        Callers must resize before any vision call and must never persist the
        result -- see CLAUDE.md rule 1.
        """
        ...


def chunk_text(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split a reply into sendable chunks, preferring line boundaries.

    Adapters call this rather than truncating. An over-long message fails to
    send rather than arriving clipped, so silently dropping the tail would hide
    the failure instead of fixing it.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
