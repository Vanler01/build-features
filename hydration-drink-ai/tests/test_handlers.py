"""Handler-layer tests.

The parser is injected, so nothing here touches Claude or a network. That is
the point of the injection: routing is testable as a plain function.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from hydration import handlers
from hydration.adapters.port import IncomingKind, IncomingMessage
from hydration.ai.schema import Confidence, ParsedDrink, ParseResult, Temperature, TimeOfDay
from hydration.core import logs
from hydration.core import users as users_mod
from hydration.core.models import Platform

NOON_BKK = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)
BASE_URL = "https://link.example.com"


def parsed(*drinks: tuple[str, float], ask: str | None = None) -> ParseResult:
    return ParseResult(
        drinks=[
            ParsedDrink(
                drink_type=name,
                temperature=Temperature.UNKNOWN,
                quantity=qty,
                size_ml=None,
                time_of_day=TimeOfDay.UNKNOWN,
                confidence=Confidence.HIGH,
            )
            for name, qty in drinks
        ],
        needs_clarification=ask is not None,
        clarification_question=ask,
    )


def deps(result: ParseResult | None = None, *, boom: bool = False) -> handlers.HandlerDeps:
    def parse(text: str) -> ParseResult:
        if boom:
            raise RuntimeError("claude unavailable")
        return result if result is not None else parsed(("water", 1))

    return handlers.HandlerDeps(parse=parse, link_base_url=BASE_URL, now=lambda: NOON_BKK)


def incoming(
    text: str | None = None,
    *,
    kind: IncomingKind = IncomingKind.TEXT,
    command: str | None = None,
    args: str | None = None,
    uid: str = "tg-1",
) -> IncomingMessage:
    return IncomingMessage(
        platform=Platform.TELEGRAM,
        platform_user_id=uid,
        kind=kind,
        received_at=NOON_BKK,
        text=text,
        command=command,
        args=args,
        photo_ref="f1" if kind is IncomingKind.PHOTO else None,
        latitude=13.7 if kind is IncomingKind.LOCATION else None,
        longitude=100.5 if kind is IncomingKind.LOCATION else None,
    )


def command(name: str, args: str | None = None) -> IncomingMessage:
    return incoming(name, kind=IncomingKind.COMMAND, command=name, args=args)


def bangkok_user(conn: sqlite3.Connection) -> str:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    users_mod.set_timezone(conn, user_id, "Asia/Bangkok")
    return user_id


# --- first contact ---------------------------------------------------------


def test_first_message_creates_a_user_and_welcomes(conn: sqlite3.Connection) -> None:
    replies = handlers.handle(conn, incoming("a water"), deps())
    assert "keep track" in replies[0].text
    assert users_mod.resolve_user(conn, Platform.TELEGRAM, "tg-1") is not None


def test_first_message_still_logs_the_drink(conn: sqlite3.Connection) -> None:
    """A welcome must not swallow what the user actually said."""
    replies = handlers.handle(conn, incoming("a water"), deps())
    assert any("Logged" in r.text for r in replies)


# --- logging ---------------------------------------------------------------


def test_text_is_logged_and_confirmed(conn: sqlite3.Connection, catalog: None) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming("two waters"), deps(parsed(("water", 2))))

    assert "Logged" in replies[0].text
    user_id = users_mod.resolve_user(conn, Platform.TELEGRAM, "tg-1")
    assert logs.day_totals(conn, user_id, "Asia/Bangkok", when=NOON_BKK) == {"water_250": 2.0}


def test_known_drink_resolves_to_a_catalog_id(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    handlers.handle(conn, incoming("coffee"), deps(parsed(("Brewed coffee", 1))))

    row = conn.execute("SELECT drink_id, custom_name FROM logs").fetchone()
    assert row["drink_id"] == "coffee_240"
    assert row["custom_name"] is None


def test_unknown_drink_is_kept_as_a_custom_name(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    handlers.handle(conn, incoming("espresso tonic"), deps(parsed(("espresso tonic", 1))))

    row = conn.execute("SELECT drink_id, custom_name FROM logs").fetchone()
    assert row["drink_id"] is None
    assert row["custom_name"] == "espresso tonic"


def test_nutrition_note_appears_when_the_toggle_is_on(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming("coffee"), deps(parsed(("Brewed coffee", 1))))
    assert "95mg caffeine" in replies[0].text


def test_nutrition_note_is_suppressed_when_the_toggle_is_off(
    conn: sqlite3.Connection, catalog: None
) -> None:
    from dataclasses import replace

    user_id = bangkok_user(conn)
    settings = users_mod.get_settings(conn, user_id)
    users_mod.update_settings(conn, replace(settings, nutrition_replies_enabled=False))

    replies = handlers.handle(conn, incoming("coffee"), deps(parsed(("Brewed coffee", 1))))
    assert "caffeine" not in replies[0].text


def test_unknown_drink_gets_no_invented_nutrition(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming("espresso tonic"), deps(parsed(("espresso tonic", 1))))
    assert "cal" not in replies[0].text


def test_ambiguous_message_asks_instead_of_logging(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(
        conn, incoming("had some stuff"), deps(parsed(ask="How many, and what?"))
    )

    assert replies[0].text == "How many, and what?"
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0


def test_implausible_parse_is_not_written(conn: sqlite3.Connection) -> None:
    """Schema-valid but absurd — the bound belongs between parse and write."""
    bangkok_user(conn)
    handlers.handle(conn, incoming("coffee"), deps(parsed(("coffee", 400))))
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0


# --- the alcohol gate ------------------------------------------------------


def test_catalog_alcohol_is_refused_on_a_bot(
    conn: sqlite3.Connection, catalog: None
) -> None:
    """CLAUDE.md rule 5 — a bot cannot check anyone's age."""
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming("a beer"), deps(parsed(("Beer", 1))))

    assert "app" in replies[0].text.lower()
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0


def test_alcohol_missing_from_the_catalog_still_fails_closed(
    conn: sqlite3.Connection, catalog: None
) -> None:
    """An unseeded drink must not slip through just because nobody added it."""
    bangkok_user(conn)
    handlers.handle(conn, incoming("a negroni"), deps(parsed(("negroni", 1))))
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0


def test_mixed_message_logs_the_soft_drinks_and_blocks_the_alcohol(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    replies = handlers.handle(
        conn, incoming("a water and a beer"), deps(parsed(("water", 1), ("Beer", 1)))
    )

    assert "Logged" in replies[0].text
    user_id = users_mod.resolve_user(conn, Platform.TELEGRAM, "tg-1")
    assert logs.day_totals(conn, user_id, "Asia/Bangkok", when=NOON_BKK) == {"water_250": 1.0}


def test_alcohol_refusal_states_a_fact_without_lecturing(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming("a beer"), deps(parsed(("Beer", 1))))

    lowered = replies[0].text.lower()
    for scold in ("should", "too much", "unhealthy", "sorry", "limit"):
        assert scold not in lowered, f"reads as a judgement: {replies[0].text!r}"


@pytest.mark.parametrize(
    "name",
    [
        "ginger ale",
        "ginger beer",
        "root beer",
        "non-alcoholic beer",
        "alcohol-free wine",
        "virgin mojito",
        "0.0 lager",
    ],
)
def test_non_alcoholic_lookalikes_are_not_blocked(
    conn: sqlite3.Connection, catalog: None, name: str
) -> None:
    """These all contain an alcohol word and are all soft drinks."""
    bangkok_user(conn)
    handlers.handle(conn, incoming(name), deps(parsed((name, 1))))
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 1, (
        f"{name!r} was refused as alcohol"
    )


@pytest.mark.parametrize(
    "name", ["negroni", "old fashioned whiskey", "red wine", "sake", "gin and tonic"]
)
def test_alcohol_keywords_still_fail_closed(
    conn: sqlite3.Connection, catalog: None, name: str
) -> None:
    bangkok_user(conn)
    handlers.handle(conn, incoming(name), deps(parsed((name, 1))))
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0, (
        f"{name!r} was logged from a bot"
    )


# --- commands --------------------------------------------------------------


def test_today_summary_uses_the_users_timezone(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    handlers.handle(conn, incoming("water"), deps(parsed(("water", 3))))

    replies = handlers.handle(conn, command("/today"), deps())
    assert "3 × Water" in replies[0].text


def test_today_with_nothing_logged(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, command("/today"), deps())
    assert "Nothing logged" in replies[0].text


def test_undo_removes_the_last_entry(conn: sqlite3.Connection, catalog: None) -> None:
    user_id = bangkok_user(conn)
    handlers.handle(conn, incoming("water"), deps(parsed(("water", 1))))
    handlers.handle(conn, incoming("coffee"), deps(parsed(("Brewed coffee", 1))))

    replies = handlers.handle(conn, command("/undo"), deps())

    assert "Brewed coffee" in replies[0].text
    assert logs.day_totals(conn, user_id, "Asia/Bangkok", when=NOON_BKK) == {"water_250": 1.0}


def test_undo_with_nothing_to_undo(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, command("/undo"), deps())
    assert "Nothing to undo" in replies[0].text


def test_undo_writes_a_tombstone_rather_than_deleting(
    conn: sqlite3.Connection, catalog: None
) -> None:
    """The row must survive so a replayed add cannot resurrect the drink."""
    bangkok_user(conn)
    handlers.handle(conn, incoming("water"), deps(parsed(("water", 1))))
    handlers.handle(conn, command("/undo"), deps())

    row = conn.execute("SELECT deleted_at FROM logs").fetchone()
    assert row is not None and row["deleted_at"] is not None


def test_reminders_toggle_round_trip(conn: sqlite3.Connection) -> None:
    user_id = bangkok_user(conn)

    assert "off" in handlers.handle(conn, command("/reminders", "off"), deps())[0].text
    assert users_mod.get_settings(conn, user_id).reminders_enabled is False

    handlers.handle(conn, command("/reminders", "on"), deps())
    assert users_mod.get_settings(conn, user_id).reminders_enabled is True


def test_reminders_without_args_reports_state(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, command("/reminders"), deps())
    assert "Reminders are on" in replies[0].text


def test_timezone_is_validated(conn: sqlite3.Connection) -> None:
    user_id = bangkok_user(conn)
    replies = handlers.handle(conn, command("/timezone", "Mars/Olympus"), deps())

    assert "don't recognise" in replies[0].text
    assert users_mod.get_timezone(conn, user_id) == "Asia/Bangkok"


def test_timezone_can_be_set(conn: sqlite3.Connection) -> None:
    user_id = bangkok_user(conn)
    handlers.handle(conn, command("/timezone", "Europe/Berlin"), deps())
    assert users_mod.get_timezone(conn, user_id) == "Europe/Berlin"


def test_link_returns_a_url_and_a_code(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    text = handlers.handle(conn, command("/link"), deps())[0].text

    assert BASE_URL in text
    assert "once" in text and "expires" in text


def test_link_rate_limit_is_explained_not_crashed(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    for _ in range(5):
        replies = handlers.handle(conn, command("/link"), deps())
    assert "already have a link code" in replies[0].text


def test_unknown_command_offers_help(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, command("/teapot"), deps())
    assert "/teapot" in replies[0].text
    assert "/today" in replies[0].text


# --- not-yet-built surfaces ------------------------------------------------


def test_photo_without_vision_configured_is_acknowledged(
    conn: sqlite3.Connection,
) -> None:
    """Vision costs per image, so a deployment may run text-only."""
    replies = handlers.handle(conn, incoming(kind=IncomingKind.PHOTO), deps())
    assert "can't read photos" in replies[0].text


IMAGE = b"fake-image-bytes"


def photo_deps(
    result: ParseResult | None = None, *, vision_boom: bool = False
) -> handlers.HandlerDeps:
    """Vision configured. The transport downloads, so no fetcher is needed."""

    def parse_photo(image: bytes, caption: str | None) -> ParseResult:
        if vision_boom:
            raise RuntimeError("vision unavailable")
        return result if result is not None else parsed(("latte", 1))

    return handlers.HandlerDeps(
        parse=lambda text: parsed(("water", 1)),
        link_base_url=BASE_URL,
        now=lambda: NOON_BKK,
        parse_photo=parse_photo,
    )


def test_photo_is_logged_when_vision_is_configured(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming(kind=IncomingKind.PHOTO), photo_deps(), IMAGE)

    assert "Logged" in replies[0].text
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 1


def test_photo_entries_record_their_source(
    conn: sqlite3.Connection, catalog: None
) -> None:
    """So a bad source can be traced and purged later."""
    bangkok_user(conn)
    handlers.handle(conn, incoming(kind=IncomingKind.PHOTO), photo_deps(), IMAGE)
    assert conn.execute("SELECT source FROM logs").fetchone()["source"] == "photo"


def test_photo_caption_reaches_the_vision_parser(
    conn: sqlite3.Connection, catalog: None
) -> None:
    seen: dict[str, str | None] = {}

    def parse_photo(image: bytes, caption: str | None) -> ParseResult:
        seen["caption"] = caption
        return parsed(("latte", 1))

    bangkok_user(conn)
    d = handlers.HandlerDeps(
        parse=lambda text: parsed(("water", 1)),
        link_base_url=BASE_URL,
        now=lambda: NOON_BKK,
        parse_photo=parse_photo,
    )
    msg = incoming("morning latte", kind=IncomingKind.PHOTO)
    handlers.handle(conn, msg, d, IMAGE)
    assert seen["caption"] == "morning latte"


def test_alcohol_in_a_photo_is_refused_too(
    conn: sqlite3.Connection, catalog: None
) -> None:
    """The age gate cannot be bypassed by photographing the drink."""
    bangkok_user(conn)
    replies = handlers.handle(
        conn, incoming(kind=IncomingKind.PHOTO), photo_deps(parsed(("Beer", 1))), IMAGE
    )
    assert "app" in replies[0].text.lower()
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0


def test_a_failed_download_becomes_a_plain_retry(conn: sqlite3.Connection) -> None:
    """Vision is on, so no bytes means the transport's download failed."""
    bangkok_user(conn)
    replies = handlers.handle(
        conn, incoming(kind=IncomingKind.PHOTO), photo_deps(), None
    )
    assert replies[0].text == handlers.RETRY_MESSAGE


def test_vision_failure_becomes_a_plain_retry(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(
        conn, incoming(kind=IncomingKind.PHOTO), photo_deps(vision_boom=True), IMAGE
    )
    assert replies[0].text == handlers.RETRY_MESSAGE


def test_unreadable_photo_asks_rather_than_guessing(
    conn: sqlite3.Connection, catalog: None
) -> None:
    bangkok_user(conn)
    replies = handlers.handle(
        conn,
        incoming(kind=IncomingKind.PHOTO),
        photo_deps(parsed(ask="I can't tell what that is — what was it?")),
        IMAGE,
    )
    assert "can't tell" in replies[0].text
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0


def test_location_is_acknowledged_rather_than_dropped(conn: sqlite3.Connection) -> None:
    replies = handlers.handle(conn, incoming(kind=IncomingKind.LOCATION), deps())
    assert "isn't switched on yet" in replies[0].text


def test_location_is_never_persisted(conn: sqlite3.Connection) -> None:
    """No location history — CLAUDE.md rule 7."""
    handlers.handle(conn, incoming(kind=IncomingKind.LOCATION), deps())
    user_id = users_mod.resolve_user(conn, Platform.TELEGRAM, "tg-1")
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    assert "last_known_location" not in row.keys()


# --- failure handling ------------------------------------------------------


def test_parser_failure_becomes_a_plain_retry(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming("two waters"), deps(boom=True))

    assert replies[0].text == handlers.RETRY_MESSAGE
    assert "Traceback" not in replies[0].text


def test_unexpected_failure_never_escapes_the_handler(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_a: object, **_k: object) -> None:
        raise RuntimeError("database on fire")

    monkeypatch.setattr(handlers.users_mod, "get_or_create_user", explode)
    replies = handlers.handle(conn, incoming("water"), deps())
    assert replies[0].text == handlers.RETRY_MESSAGE


def test_message_body_is_never_logged(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    """Log IDs, timestamps and outcomes — never user content."""
    bangkok_user(conn)
    secret = "three double espressos at my therapist's office"

    with caplog.at_level("DEBUG"):
        handlers.handle(conn, incoming(secret), deps(boom=True))

    assert secret not in caplog.text


def test_empty_text_is_handled(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    replies = handlers.handle(conn, incoming("   "), deps())
    assert "Tell me what you drank" in replies[0].text
