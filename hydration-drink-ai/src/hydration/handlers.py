"""The application layer: an incoming message in, replies out.

This is where adapters meet core. It is deliberately platform-agnostic -- it
receives a normalized ``IncomingMessage`` and returns ``OutgoingMessage``
objects, so the same routing serves Telegram and LINE without a branch. Adding
a platform never touches this file.

It is also free of network calls. Claude is injected as ``deps.parse``, which
means every test here runs against a plain function and no HTTP client.

Two rules from CLAUDE.md are enforced here rather than deeper down, because
this is the layer that knows which surface it is talking to:

  * rule 5 -- alcohol is app-only, so it must not be loggable from a bot
  * rule 10 -- "today" is resolved in the user's timezone, never the server's
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .adapters.port import IncomingKind, IncomingMessage, OutgoingMessage
from .ai.schema import ParseResult
from .ai.validate import ValidationOutcome, validate
from .core import catalog, day, linking, logs
from .core import users as users_mod
from .core.models import LogEntry, LogSource, Platform

_LOG = logging.getLogger(__name__)

RETRY_MESSAGE = "Something went wrong on my side — try that again in a moment."

HELP_TEXT = """\
Tell me what you drank and I'll log it — "2 coffees this morning, a water now".

/today — what you've had so far
/undo — remove the last thing I logged
/reminders on|off — nudges to drink water
/timezone Asia/Bangkok — so "today" means your today
/link — continue in the app
/help — this message"""


class ParseFailed(Exception):
    """The parser could not produce a result. Surfaced as a retry message."""


class Parser(Protocol):
    """Just enough of the Claude parser for this layer to depend on."""

    def __call__(self, text: str) -> ParseResult:
        """Parse a message into structured drink entries."""
        ...


class PhotoParser(Protocol):
    """Parses a drink photo. Separate from ``Parser`` so text works without it."""

    def __call__(self, image: bytes, caption: str | None) -> ParseResult:
        """Identify the drinks in a photo."""
        ...


@dataclass(frozen=True, slots=True)
class HandlerDeps:
    """Everything the handler needs from the outside world.

    ``parse_photo`` is optional so a deployment can run text-only: vision costs
    per image, and not every operator wants it on.

    There is deliberately no photo *fetcher* here. Downloading is per-platform
    and asynchronous, while this layer is synchronous, so a callable in this
    dataclass could never bridge the two cleanly. The transport already holds
    the right adapter and is already async, so it does the download and hands
    the bytes in — transport does transport, the handler does logic.
    """

    parse: Parser
    link_base_url: str
    now: Callable[[], datetime] = day.utc_now
    parse_photo: PhotoParser | None = None


def handle(
    conn: sqlite3.Connection,
    message: IncomingMessage,
    deps: HandlerDeps,
    photo_bytes: bytes | None = None,
) -> list[OutgoingMessage]:
    """Route one incoming message and return the replies to send.

    ``photo_bytes`` is supplied by the transport for photo messages, already
    downloaded. None means either that vision is switched off or that the
    download failed; the two are distinguished by whether ``deps.parse_photo``
    is configured.

    Never raises: any unexpected failure becomes a plain retry message, because
    a stack trace in a chat window helps nobody and leaks internals.
    """
    try:
        return _route(conn, message, deps, photo_bytes)
    except Exception:  # noqa: BLE001 — the boundary; everything below may fail
        # Log the failure but never the message body (CLAUDE.md: log IDs,
        # timestamps and outcomes, never user content).
        _LOG.exception("handler failed for platform=%s", message.platform)
        return [OutgoingMessage(text=RETRY_MESSAGE)]


def _route(
    conn: sqlite3.Connection,
    message: IncomingMessage,
    deps: HandlerDeps,
    photo_bytes: bytes | None,
) -> list[OutgoingMessage]:
    user_id, created = users_mod.get_or_create_user(
        conn, message.platform, message.platform_user_id
    )

    if message.kind is IncomingKind.COMMAND:
        return _command(conn, user_id, message, deps)

    if message.kind is IncomingKind.PHOTO:
        return _log_photo(conn, user_id, message, deps, photo_bytes)

    if message.kind is IncomingKind.LOCATION:
        # Nearby places is Phase 6.
        return [OutgoingMessage(text="Finding places nearby isn't switched on yet.")]

    if created:
        return [OutgoingMessage(text=_welcome())] + _log_text(conn, user_id, message, deps)

    return _log_text(conn, user_id, message, deps)


# -- commands ---------------------------------------------------------------


def _command(
    conn: sqlite3.Connection, user_id: str, message: IncomingMessage, deps: HandlerDeps
) -> list[OutgoingMessage]:
    command = (message.command or "").lower()
    args = (message.args or "").strip()
    timezone = users_mod.get_timezone(conn, user_id)
    now = deps.now()

    if command in ("/start", "/help"):
        return [OutgoingMessage(text=_welcome() if command == "/start" else HELP_TEXT)]

    if command in ("/today", "/summary"):
        return [OutgoingMessage(text=_summary(conn, user_id, timezone, now))]

    if command == "/undo":
        return [OutgoingMessage(text=_undo(conn, user_id, timezone, now))]

    if command == "/reminders":
        return [OutgoingMessage(text=_reminders(conn, user_id, args))]

    if command == "/timezone":
        return [OutgoingMessage(text=_timezone(conn, user_id, args))]

    if command == "/link":
        return [OutgoingMessage(text=_link(conn, user_id, message.platform, deps))]

    return [OutgoingMessage(text=f"I don't know {command}.\n\n{HELP_TEXT}")]


def _welcome() -> str:
    return (
        "Hi — I keep track of what you drink.\n\n"
        "Just tell me: \"a coffee and two waters\". "
        "Set /timezone so my \"today\" matches yours.\n\n" + HELP_TEXT
    )


def _summary(conn: sqlite3.Connection, user_id: str, timezone: str, now: datetime) -> str:
    totals = logs.day_totals(conn, user_id, timezone, when=now)
    if not totals:
        return "Nothing logged today yet."

    parts = [
        f"{qty:g} × {catalog.display_name(conn, key)}"
        for key, qty in sorted(totals.items(), key=lambda kv: -kv[1])
    ]
    return "Today: " + ", ".join(parts)


def _undo(conn: sqlite3.Connection, user_id: str, timezone: str, now: datetime) -> str:
    entry = logs.last_live_entry(conn, user_id, timezone, when=now)
    if entry is None:
        return "Nothing to undo today."

    name = catalog.display_name(conn, entry["drink_id"] or entry["custom_name"])
    logs.remove_entry(conn, entry["id"], user_id, when=now)
    return f"Removed {name}."


def _reminders(conn: sqlite3.Connection, user_id: str, args: str) -> str:
    settings = users_mod.get_settings(conn, user_id)
    choice = args.lower()

    if choice not in ("on", "off"):
        state = "on" if settings.reminders_enabled else "off"
        return f"Reminders are {state}. Use /reminders on or /reminders off."

    from dataclasses import replace

    users_mod.update_settings(conn, replace(settings, reminders_enabled=choice == "on"))
    return f"Reminders {choice}."


def _timezone(conn: sqlite3.Connection, user_id: str, args: str) -> str:
    if not args:
        current = users_mod.get_timezone(conn, user_id)
        return f"Your timezone is {current}. Set it with /timezone Asia/Bangkok."
    try:
        users_mod.set_timezone(conn, user_id, args)
    except ValueError:
        return f"I don't recognise {args!r}. Use a name like Asia/Bangkok."
    return f"Timezone set to {args}."


def _link(conn: sqlite3.Connection, user_id: str, platform: Platform, deps: HandlerDeps) -> str:
    try:
        offer = linking.issue_token(conn, user_id, platform, deps.link_base_url)
    except RuntimeError:
        return "You already have a link code open — use that one, or wait a few minutes."

    minutes = offer.expires_in_sec // 60
    return (
        f"Open this on your phone to continue in the app:\n{offer.url}\n\n"
        f"Or enter this code: {offer.code}\n"
        f"It works once and expires in {minutes} minutes."
    )


# -- free-text logging ------------------------------------------------------


def _log_photo(
    conn: sqlite3.Connection,
    user_id: str,
    message: IncomingMessage,
    deps: HandlerDeps,
    photo_bytes: bytes | None,
) -> list[OutgoingMessage]:
    """Parse and log a drink photo the transport has already downloaded.

    The image bytes are passed in, used, and dropped. They are never written to
    disk or the database (CLAUDE.md rule 1).
    """
    if deps.parse_photo is None:
        return [
            OutgoingMessage(
                text="I can't read photos here — tell me what it was and I'll log it."
            )
        ]

    if not photo_bytes:
        # Vision is on, so the transport tried and the download failed.
        return [OutgoingMessage(text=RETRY_MESSAGE)]

    try:
        parsed = deps.parse_photo(photo_bytes, message.text)
    except Exception as exc:  # noqa: BLE001 — any vision failure reads the same
        _LOG.warning("photo parse unavailable: %s", type(exc).__name__)
        return [OutgoingMessage(text=RETRY_MESSAGE)]

    return _write_entries(conn, user_id, validate(parsed), deps, LogSource.PHOTO)


def _log_text(
    conn: sqlite3.Connection, user_id: str, message: IncomingMessage, deps: HandlerDeps
) -> list[OutgoingMessage]:
    text = (message.text or "").strip()
    if not text:
        return [OutgoingMessage(text="Tell me what you drank and I'll log it.")]

    try:
        parsed = deps.parse(text)
    except Exception as exc:  # noqa: BLE001 — any parser failure is the same to the user
        _LOG.warning("parse unavailable: %s", type(exc).__name__)
        return [OutgoingMessage(text=RETRY_MESSAGE)]

    return _write_entries(conn, user_id, validate(parsed), deps, LogSource.TEXT)


def _write_entries(
    conn: sqlite3.Connection,
    user_id: str,
    outcome: ValidationOutcome,
    deps: HandlerDeps,
    source: LogSource,
) -> list[OutgoingMessage]:
    """Turn a validated parse into log rows and a confirmation."""
    if not outcome.ok:
        return [OutgoingMessage(text=outcome.question or RETRY_MESSAGE)]

    now = deps.now()
    settings = users_mod.get_settings(conn, user_id)

    logged: list[str] = []
    blocked: list[str] = []

    for drink in outcome.drinks:
        if catalog.is_alcohol(conn, drink.drink_type):
            # CLAUDE.md rule 5: a bot cannot gate age, so alcohol is app-only.
            blocked.append(drink.drink_type)
            continue

        row = catalog.resolve(conn, drink.drink_type)
        logs.upsert_entry(
            conn,
            LogEntry(
                user_id=user_id,
                logged_at=now,
                source=source,
                drink_id=row["id"] if row is not None else None,
                custom_name=None if row is not None else drink.drink_type,
                quantity=drink.quantity,
            ),
        )
        note = (
            catalog.nutrition_note(conn, drink.drink_type, drink.quantity)
            if settings.nutrition_replies_enabled
            else None
        )
        label = f"{drink.quantity:g} × {drink.drink_type}"
        logged.append(f"{label} ({note})" if note else label)

    return [OutgoingMessage(text=_confirmation(logged, blocked))]


def _confirmation(logged: list[str], blocked: list[str]) -> str:
    lines: list[str] = []
    if logged:
        lines.append("Logged " + ", ".join(logged) + ".")
    if blocked:
        # Stated as a fact about where the feature lives, not as a judgement
        # about drinking (CLAUDE.md rule 19).
        names = ", ".join(sorted(set(blocked)))
        lines.append(f"Alcohol ({names}) is logged in the app, not here.")
    return "\n".join(lines) if lines else "I didn't catch a drink in that one."
