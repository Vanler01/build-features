"""Webhook routes, dispatch dedupe, and the reminder loop.

No network: adapters are fakes, and the app is driven through FastAPI's
TestClient against a temporary database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hydration.adapters.line import LineAdapter
from hydration.adapters.port import IncomingKind, IncomingMessage, OutgoingMessage
from hydration.adapters.telegram import TelegramAdapter
from hydration.ai.schema import Confidence, ParsedDrink, ParseResult, Temperature, TimeOfDay
from hydration.api.app import WebhookConfig, create_app
from hydration.api.dispatch import Dispatcher
from hydration.core import db, events
from hydration.core import users as users_mod
from hydration.core.models import Platform
from hydration.handlers import HandlerDeps
from hydration.scheduler import reminders, runner

NOON_BKK = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)
TG_SECRET = "telegram-webhook-secret"
LINE_SECRET = "line-channel-secret"


class FakeAdapter:
    """Records what it was asked to send instead of sending it."""

    def __init__(self, platform: Platform, ok: bool = True) -> None:
        self.platform = platform
        self.ok = ok
        self.sent: list[tuple[str, OutgoingMessage, str | None]] = []
        self.raises = False
        self.fetched: list[str] = []
        self.photo = b""
        self.photo_raises = False

    def parse_incoming(self, raw: object) -> IncomingMessage | None:
        return None

    async def send(
        self, platform_user_id: str, message: OutgoingMessage, *, reply_token: str | None = None
    ) -> bool:
        if self.raises:
            raise RuntimeError("transport exploded")
        self.sent.append((platform_user_id, message, reply_token))
        return self.ok

    async def fetch_photo(self, photo_ref: str) -> bytes:
        self.fetched.append(photo_ref)
        if self.photo_raises:
            raise RuntimeError("download failed")
        return self.photo


def a_parse(name: str = "water", qty: float = 1) -> ParseResult:
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
        ],
        needs_clarification=False,
        clarification_question=None,
    )


def a_deps() -> HandlerDeps:
    return HandlerDeps(
        parse=lambda text: a_parse(),
        link_base_url="https://link.example.com",
        now=lambda: NOON_BKK,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.sqlite3")
    conn = db.open_database(path)
    conn.close()
    return path


def tg_message(text: str = "a water", update_id: int = 100) -> IncomingMessage:
    return IncomingMessage(
        platform=Platform.TELEGRAM,
        platform_user_id="42",
        kind=IncomingKind.TEXT,
        received_at=NOON_BKK,
        text=text,
        event_id=str(update_id),
    )


# --- event dedupe ----------------------------------------------------------


def test_an_event_can_be_claimed_once(conn: sqlite3.Connection) -> None:
    assert events.claim(conn, Platform.TELEGRAM, "u-1") is True
    assert events.claim(conn, Platform.TELEGRAM, "u-1") is False


def test_the_same_id_on_different_platforms_is_not_a_duplicate(
    conn: sqlite3.Connection,
) -> None:
    assert events.claim(conn, Platform.TELEGRAM, "1") is True
    assert events.claim(conn, Platform.LINE, "1") is True


def test_a_released_claim_can_be_retried(conn: sqlite3.Connection) -> None:
    """Otherwise a transient failure swallows the message permanently."""
    events.claim(conn, Platform.TELEGRAM, "u-1")
    events.release(conn, Platform.TELEGRAM, "u-1")
    assert events.claim(conn, Platform.TELEGRAM, "u-1") is True


def test_missing_event_id_is_allowed_through(conn: sqlite3.Connection) -> None:
    """Better a possible duplicate than refusing to serve the user at all."""
    assert events.claim(conn, Platform.TELEGRAM, "") is True
    assert events.claim(conn, Platform.TELEGRAM, "") is True


def test_pruning_drops_only_old_claims(conn: sqlite3.Connection) -> None:
    events.claim(conn, Platform.TELEGRAM, "fresh")
    conn.execute(
        "INSERT INTO processed_events (platform, event_id, processed_at) VALUES (?,?,?)",
        ("telegram", "stale", "2020-01-01T00:00:00+00:00"),
    )
    assert events.prune(conn) == 1
    assert events.claim(conn, Platform.TELEGRAM, "fresh") is False


# --- dispatch --------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_handles_and_replies(conn: sqlite3.Connection) -> None:
    adapter = FakeAdapter(Platform.TELEGRAM)
    d = Dispatcher({Platform.TELEGRAM: adapter}, a_deps())

    assert await d.dispatch(conn, tg_message()) is True
    assert adapter.sent, "no reply was sent"


@pytest.mark.asyncio
async def test_a_redelivered_update_is_not_logged_twice(
    conn: sqlite3.Connection,
) -> None:
    """The bug this whole mechanism exists for: retries mint a fresh entry
    UUID each time, so the logs table cannot spot the duplicate itself."""
    adapter = FakeAdapter(Platform.TELEGRAM)
    d = Dispatcher({Platform.TELEGRAM: adapter}, a_deps())

    await d.dispatch(conn, tg_message(update_id=7))
    handled_again = await d.dispatch(conn, tg_message(update_id=7))

    assert handled_again is False
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 1


@pytest.mark.asyncio
async def test_distinct_updates_are_both_logged(conn: sqlite3.Connection) -> None:
    adapter = FakeAdapter(Platform.TELEGRAM)
    d = Dispatcher({Platform.TELEGRAM: adapter}, a_deps())

    await d.dispatch(conn, tg_message(update_id=1))
    await d.dispatch(conn, tg_message(update_id=2))

    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 2


@pytest.mark.asyncio
async def test_the_reply_token_reaches_the_adapter(conn: sqlite3.Connection) -> None:
    """On LINE this is the difference between a free reply and metered push."""
    adapter = FakeAdapter(Platform.LINE)
    d = Dispatcher({Platform.LINE: adapter}, a_deps())
    message = IncomingMessage(
        platform=Platform.LINE,
        platform_user_id="U1",
        kind=IncomingKind.TEXT,
        received_at=NOON_BKK,
        text="a water",
        reply_token="rt-9",
        event_id="e-1",
    )

    await d.dispatch(conn, message)
    assert adapter.sent[0][2] == "rt-9"


@pytest.mark.asyncio
async def test_an_unconfigured_platform_is_skipped(conn: sqlite3.Connection) -> None:
    d = Dispatcher({}, a_deps())
    assert await d.dispatch(conn, tg_message()) is False


# --- photo download (transport's job, not the handler's) -------------------


def photo_message(event_id: str = "p-1") -> IncomingMessage:
    return IncomingMessage(
        platform=Platform.TELEGRAM,
        platform_user_id="42",
        kind=IncomingKind.PHOTO,
        received_at=NOON_BKK,
        photo_ref="file-abc",
        event_id=event_id,
    )


def vision_deps(seen: list[bytes]) -> HandlerDeps:
    def parse_photo(image: bytes, caption: str | None) -> ParseResult:
        seen.append(image)
        return a_parse("latte")

    return HandlerDeps(
        parse=lambda text: a_parse(),
        link_base_url="https://link.example.com",
        now=lambda: NOON_BKK,
        parse_photo=parse_photo,
    )


@pytest.mark.asyncio
async def test_the_transport_downloads_and_hands_bytes_to_vision(
    conn: sqlite3.Connection,
) -> None:
    """The wiring this whole change exists for: fetch_photo is async and
    per-platform, so the transport calls it and the sync handler receives the
    bytes already downloaded."""
    seen: list[bytes] = []
    adapter = FakeAdapter(Platform.TELEGRAM)
    adapter.photo = b"\xff\xd8jpeg"
    d = Dispatcher({Platform.TELEGRAM: adapter}, vision_deps(seen))

    await d.dispatch(conn, photo_message())

    assert adapter.fetched == ["file-abc"]
    assert seen == [b"\xff\xd8jpeg"]
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 1


@pytest.mark.asyncio
async def test_no_download_happens_when_vision_is_off(
    conn: sqlite3.Connection,
) -> None:
    """A text-only deployment must not pay for bytes it would discard."""
    adapter = FakeAdapter(Platform.TELEGRAM)
    d = Dispatcher({Platform.TELEGRAM: adapter}, a_deps())

    await d.dispatch(conn, photo_message())

    assert adapter.fetched == []
    assert "can't read photos" in adapter.sent[0][1].text


@pytest.mark.asyncio
async def test_a_failed_download_replies_with_a_retry(
    conn: sqlite3.Connection,
) -> None:
    seen: list[bytes] = []
    adapter = FakeAdapter(Platform.TELEGRAM)
    adapter.photo_raises = True
    d = Dispatcher({Platform.TELEGRAM: adapter}, vision_deps(seen))

    await d.dispatch(conn, photo_message())

    assert seen == [], "vision should not run without bytes"
    assert adapter.sent[0][1].text == handlers_retry_message()
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 0


@pytest.mark.asyncio
async def test_text_messages_trigger_no_download(conn: sqlite3.Connection) -> None:
    seen: list[bytes] = []
    adapter = FakeAdapter(Platform.TELEGRAM)
    d = Dispatcher({Platform.TELEGRAM: adapter}, vision_deps(seen))

    await d.dispatch(conn, tg_message())
    assert adapter.fetched == []


def handlers_retry_message() -> str:
    from hydration.handlers import RETRY_MESSAGE

    return RETRY_MESSAGE


# --- webhook routes --------------------------------------------------------


@pytest.fixture
def client(db_path: str) -> TestClient:
    adapters = {
        Platform.TELEGRAM: TelegramAdapter("1:AAfake", MockClient()),
        Platform.LINE: LineAdapter("line-token", MockClient()),
    }
    app = create_app(
        Dispatcher(adapters, a_deps()),
        WebhookConfig(
            db_path=db_path,
            telegram_secret=TG_SECRET,
            line_channel_secret=LINE_SECRET,
        ),
    )
    return TestClient(app)


class MockResponse:
    """A successful HTTP response, shaped for both adapters."""

    status_code = 200

    @staticmethod
    def json() -> dict[str, object]:
        return {"ok": True, "result": {}}

    @staticmethod
    def raise_for_status() -> None:
        return None


class MockClient:
    """Stands in for httpx.AsyncClient.

    The routes really do send replies through the real adapters — that is part
    of what these tests cover — so this records the calls rather than refusing
    them.
    """

    def __init__(self) -> None:
        self.posts: list[tuple[object, dict[str, object]]] = []

    async def post(self, url: object, **kwargs: object) -> MockResponse:
        self.posts.append((url, kwargs))
        return MockResponse()

    async def get(self, url: object, **kwargs: object) -> MockResponse:
        return MockResponse()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_telegram_webhook_requires_the_secret_token(client: TestClient) -> None:
    """Without this anyone who learns the URL can forge drink logs."""
    response = client.post("/webhook/telegram", json={"update_id": 1})
    assert response.status_code == 403


def test_telegram_webhook_rejects_a_wrong_secret(client: TestClient) -> None:
    response = client.post(
        "/webhook/telegram",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert response.status_code == 403


def test_telegram_webhook_accepts_a_valid_update(client: TestClient, db_path: str) -> None:
    response = client.post(
        "/webhook/telegram",
        json={
            "update_id": 55,
            "message": {"from": {"id": 42}, "text": "two waters"},
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET},
    )
    assert response.status_code == 200

    conn = db.connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 1


def test_unparseable_telegram_body_still_answers_200(client: TestClient) -> None:
    """A retry would deliver the same bytes; 200 stops the loop."""
    response = client.post(
        "/webhook/telegram",
        content=b"not json",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": TG_SECRET,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


def test_unhandled_telegram_update_answers_200(client: TestClient) -> None:
    response = client.post(
        "/webhook/telegram",
        json={"update_id": 1, "channel_post": {"text": "hi"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": TG_SECRET},
    )
    assert response.status_code == 200


def _line_signed(body: dict[str, object]) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    sig = base64.b64encode(
        hmac.new(LINE_SECRET.encode(), raw, hashlib.sha256).digest()
    ).decode()
    return raw, sig


def test_line_webhook_requires_a_signature(client: TestClient) -> None:
    response = client.post("/webhook/line", json={"events": []})
    assert response.status_code == 403


def test_line_webhook_rejects_a_tampered_body(client: TestClient) -> None:
    _, sig = _line_signed({"events": []})
    response = client.post(
        "/webhook/line",
        content=json.dumps({"events": [{"forged": True}]}).encode(),
        headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 403


def test_line_webhook_accepts_a_signed_batch(client: TestClient, db_path: str) -> None:
    raw, sig = _line_signed(
        {
            "destination": "U0",
            "events": [
                {
                    "type": "message",
                    "webhookEventId": "evt-1",
                    "replyToken": "rt-1",
                    "source": {"type": "user", "userId": "U123"},
                    "message": {"type": "text", "id": "1", "text": "a water"},
                }
            ],
        }
    )
    response = client.post(
        "/webhook/line",
        content=raw,
        headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 200

    conn = db.connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 1


def test_line_console_verification_batch_answers_200(client: TestClient) -> None:
    """LINE posts an empty batch when you save the webhook URL."""
    raw, sig = _line_signed({"destination": "U0", "events": []})
    response = client.post(
        "/webhook/line",
        content=raw,
        headers={"X-Line-Signature": sig, "Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_line_redelivery_is_not_logged_twice(client: TestClient, db_path: str) -> None:
    raw, sig = _line_signed(
        {
            "events": [
                {
                    "type": "message",
                    "webhookEventId": "evt-dup",
                    "replyToken": "rt",
                    "source": {"type": "user", "userId": "U1"},
                    "message": {"type": "text", "id": "1", "text": "a water"},
                }
            ]
        }
    )
    headers = {"X-Line-Signature": sig, "Content-Type": "application/json"}
    client.post("/webhook/line", content=raw, headers=headers)
    client.post("/webhook/line", content=raw, headers=headers)

    conn = db.connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM logs").fetchone()["n"] == 1


# --- scheduler -------------------------------------------------------------


def bangkok_user(conn: sqlite3.Connection, platform_id: str = "tg-1") -> str:
    user_id, _ = users_mod.get_or_create_user(
        conn, Platform.TELEGRAM, platform_id, "Asia/Bangkok"
    )
    return user_id


@pytest.mark.asyncio
async def test_a_due_reminder_is_sent(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    adapter = FakeAdapter(Platform.TELEGRAM)

    delivered = await runner.send_due(conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK)

    assert delivered == 1
    assert adapter.sent[0][1].is_push is True, "a reminder is unsolicited"


@pytest.mark.asyncio
async def test_a_sent_reminder_is_not_resent_next_tick(conn: sqlite3.Connection) -> None:
    bangkok_user(conn)
    adapter = FakeAdapter(Platform.TELEGRAM)

    await runner.send_due(conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK)
    again = await runner.send_due(
        conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK + timedelta(minutes=1)
    )
    assert again == 0


@pytest.mark.asyncio
async def test_the_next_reminder_arrives_after_the_interval(
    conn: sqlite3.Connection,
) -> None:
    bangkok_user(conn)
    adapter = FakeAdapter(Platform.TELEGRAM)

    await runner.send_due(conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK)
    later = await runner.send_due(
        conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK + timedelta(minutes=121)
    )
    assert later == 1


@pytest.mark.asyncio
async def test_last_sent_survives_a_restart(conn: sqlite3.Connection) -> None:
    """Held in memory, a restart re-nudges everyone — real money on LINE."""
    bangkok_user(conn)
    adapter = FakeAdapter(Platform.TELEGRAM)
    await runner.send_due(conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK)

    # A fresh runner reads state back from the database, not from memory.
    assert runner.load_last_sent(conn), "last_sent_at was not persisted"
    again = await runner.send_due(
        conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK + timedelta(minutes=5)
    )
    assert again == 0


@pytest.mark.asyncio
async def test_a_failed_send_is_retried_rather_than_counted(
    conn: sqlite3.Connection,
) -> None:
    """Marking a failed reminder as sent would silently skip the user."""
    bangkok_user(conn)
    failing = FakeAdapter(Platform.TELEGRAM, ok=False)

    assert await runner.send_due(conn, {Platform.TELEGRAM: failing}, now=NOON_BKK) == 0
    assert runner.load_last_sent(conn) == {}

    working = FakeAdapter(Platform.TELEGRAM)
    assert await runner.send_due(
        conn, {Platform.TELEGRAM: working}, now=NOON_BKK + timedelta(minutes=1)
    ) == 1


@pytest.mark.asyncio
async def test_a_failed_send_does_not_spend_quota(conn: sqlite3.Connection) -> None:
    user_id = bangkok_user(conn)
    users_mod.attach_identity(conn, user_id, Platform.LINE, "U1")
    failing = FakeAdapter(Platform.LINE, ok=False)

    before = reminders.push_allowance_remaining(conn, user_id, Platform.LINE)
    await runner.send_due(conn, {Platform.LINE: failing}, now=NOON_BKK)
    after = reminders.push_allowance_remaining(conn, user_id, Platform.LINE)

    assert before == after


@pytest.mark.asyncio
async def test_a_successful_line_send_spends_exactly_one(
    conn: sqlite3.Connection,
) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.LINE, "U1", "Asia/Bangkok")
    adapter = FakeAdapter(Platform.LINE)

    before = reminders.push_allowance_remaining(conn, user_id, Platform.LINE)
    await runner.send_due(conn, {Platform.LINE: adapter}, now=NOON_BKK)
    after = reminders.push_allowance_remaining(conn, user_id, Platform.LINE)

    assert before - after == 1


@pytest.mark.asyncio
async def test_one_users_exception_does_not_stop_the_others(
    conn: sqlite3.Connection,
) -> None:
    """A scheduler that dies on a bad chat id stops serving everyone."""
    bangkok_user(conn, "tg-1")
    bangkok_user(conn, "tg-2")
    adapter = FakeAdapter(Platform.TELEGRAM)
    adapter.raises = True

    assert await runner.send_due(conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK) == 0

    adapter.raises = False
    assert await runner.send_due(
        conn, {Platform.TELEGRAM: adapter}, now=NOON_BKK + timedelta(minutes=1)
    ) == 2


@pytest.mark.asyncio
async def test_nothing_is_sent_outside_the_active_window(
    conn: sqlite3.Connection,
) -> None:
    bangkok_user(conn)
    adapter = FakeAdapter(Platform.TELEGRAM)
    three_am_bkk = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)

    assert await runner.send_due(conn, {Platform.TELEGRAM: adapter}, now=three_am_bkk) == 0
