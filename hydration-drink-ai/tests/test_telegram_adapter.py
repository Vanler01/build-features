"""Telegram adapter tests.

Every HTTP call is mocked. No test here may reach api.telegram.org.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from hydration.adapters import telegram as tg
from hydration.adapters.port import Choice, IncomingKind, MessagingPort, OutgoingMessage
from hydration.core.models import Platform

TOKEN = "1234567890:AAFAKE-not-a-real-token"


def make_client(
    *, result: dict[str, Any] | None = None, status: int = 200, ok: bool = True
) -> MagicMock:
    client = MagicMock()
    response = MagicMock(status_code=status)
    response.json.return_value = {"ok": ok, "result": result if result is not None else {}}
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock()
    return client


def adapter(client: MagicMock | None = None) -> tg.TelegramAdapter:
    return tg.TelegramAdapter(TOKEN, client or make_client())


def update(message: dict[str, Any]) -> dict[str, Any]:
    return {"update_id": 1, "message": {"from": {"id": 42}, **message}}


# --- port conformance ------------------------------------------------------


def test_adapter_satisfies_the_port() -> None:
    assert isinstance(adapter(), MessagingPort)
    assert adapter().platform is Platform.TELEGRAM


def test_empty_token_is_refused() -> None:
    with pytest.raises(ValueError, match="token is required"):
        tg.TelegramAdapter("", make_client())


# --- inbound parsing -------------------------------------------------------


def test_plain_text_message() -> None:
    msg = adapter().parse_incoming(update({"text": "two waters and a latte"}))
    assert msg is not None
    assert msg.kind is IncomingKind.TEXT
    assert msg.platform_user_id == "42"
    assert msg.text == "two waters and a latte"
    assert msg.received_at.tzinfo is not None


def test_command_is_distinguished_from_text() -> None:
    msg = adapter().parse_incoming(update({"text": "/link"}))
    assert msg is not None
    assert msg.kind is IncomingKind.COMMAND
    assert msg.command == "/link"


def test_group_chat_command_suffix_is_stripped() -> None:
    """In a group Telegram sends /log@MyBot — leaving @MyBot breaks every command."""
    msg = adapter().parse_incoming(update({"text": "/log@HydrationBot two waters"}))
    assert msg is not None
    assert msg.command == "/log"
    assert msg.args == "two waters"


def test_command_without_args_has_none_args() -> None:
    msg = adapter().parse_incoming(update({"text": "/summary"}))
    assert msg is not None
    assert msg.args is None


def test_photo_uses_the_largest_size_not_the_thumbnail() -> None:
    """photo[] ascends by size; photo[0] is a thumbnail nobody can parse a drink from."""
    msg = adapter().parse_incoming(
        update(
            {
                "photo": [
                    {"file_id": "thumb", "width": 90},
                    {"file_id": "medium", "width": 320},
                    {"file_id": "full", "width": 1280},
                ]
            }
        )
    )
    assert msg is not None
    assert msg.kind is IncomingKind.PHOTO
    assert msg.photo_ref == "full"


def test_photo_caption_is_carried_through() -> None:
    msg = adapter().parse_incoming(
        update({"photo": [{"file_id": "full"}], "caption": "morning latte"})
    )
    assert msg is not None
    assert msg.text == "morning latte"


def test_location_message() -> None:
    msg = adapter().parse_incoming(
        update({"location": {"latitude": 13.7563, "longitude": 100.5018}})
    )
    assert msg is not None
    assert msg.kind is IncomingKind.LOCATION
    assert (msg.latitude, msg.longitude) == (13.7563, 100.5018)


def test_unhandled_update_types_are_ignored_not_raised() -> None:
    """Telegram sends poll/channel/edited updates down the same webhook."""
    for raw in (
        {"update_id": 1},
        {"update_id": 1, "channel_post": {"text": "hi"}},
        {"update_id": 1, "message": {"text": "no sender"}},
        {"update_id": 1, "message": {"from": {"id": 1}}},
        {"update_id": 1, "message": {"from": {"id": 1}, "text": "   "}},
        "not a dict",
        None,
    ):
        assert adapter().parse_incoming(raw) is None


def test_malformed_location_is_ignored() -> None:
    assert adapter().parse_incoming(update({"location": {"latitude": 1.0}})) is None


def test_edited_message_is_still_parsed() -> None:
    raw = {"update_id": 1, "edited_message": {"from": {"id": 42}, "text": "3 waters"}}
    msg = adapter().parse_incoming(raw)
    assert msg is not None
    assert msg.text == "3 waters"


def test_long_input_is_accepted_not_rejected() -> None:
    """Telegram allows 4096 chars; the parser must not assume short input."""
    msg = adapter().parse_incoming(update({"text": "water " * 600}))
    assert msg is not None


# --- outbound --------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_posts_plain_text() -> None:
    client = make_client()
    assert await adapter(client).send("42", OutgoingMessage(text="Logged."))

    payload = client.post.call_args.kwargs["json"]
    assert payload["chat_id"] == "42"
    assert payload["text"] == "Logged."
    assert "parse_mode" not in payload, "markdown escaping is a silent-failure source"


@pytest.mark.asyncio
async def test_overlong_reply_is_chunked_not_truncated() -> None:
    client = make_client()
    await adapter(client).send("42", OutgoingMessage(text="x" * 9000))

    assert client.post.await_count == 3
    sent = "".join(c.kwargs["json"]["text"] for c in client.post.call_args_list)
    assert len(sent) == 9000, "content was dropped rather than split"


@pytest.mark.asyncio
async def test_keyboard_only_rides_the_final_chunk() -> None:
    client = make_client()
    await adapter(client).send(
        "42",
        OutgoingMessage(text="y" * 9000, choices=[Choice(label="A", value="a")]),
    )
    markups = ["reply_markup" in c.kwargs["json"] for c in client.post.call_args_list]
    assert markups == [False, False, True]


@pytest.mark.asyncio
async def test_choices_with_urls_become_link_buttons() -> None:
    client = make_client()
    await adapter(client).send(
        "42",
        OutgoingMessage(
            text="Nearby:",
            choices=[Choice(label="Blue Bottle", value="p1", url="https://maps/x")],
        ),
    )
    button = client.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Blue Bottle", "url": "https://maps/x"}


@pytest.mark.asyncio
async def test_callback_data_is_capped_at_64_bytes() -> None:
    """Over 64 bytes Telegram rejects the send with no visible error."""
    client = make_client()
    await adapter(client).send(
        "42", OutgoingMessage(text="Pick:", choices=[Choice(label="L", value="v" * 200)])
    )
    button = client.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"][0][0]
    assert len(button["callback_data"].encode()) <= tg.MAX_CALLBACK_BYTES


@pytest.mark.asyncio
async def test_multibyte_callback_data_is_truncated_without_breaking_utf8() -> None:
    client = make_client()
    await adapter(client).send(
        "42", OutgoingMessage(text="Pick:", choices=[Choice(label="L", value="ก" * 100)])
    )
    data = client.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"][0][0]
    assert len(data["callback_data"].encode()) <= tg.MAX_CALLBACK_BYTES
    data["callback_data"].encode().decode()  # must not raise


@pytest.mark.asyncio
async def test_location_request_uses_a_one_time_keyboard() -> None:
    """Location is opt-in per message, never a standing grant."""
    client = make_client()
    await adapter(client).send("42", OutgoingMessage(text="Where?", request_location=True))

    markup = client.post.call_args.kwargs["json"]["reply_markup"]
    assert markup["keyboard"][0][0]["request_location"] is True
    assert markup["one_time_keyboard"] is True


# --- failure handling ------------------------------------------------------


@pytest.mark.asyncio
async def test_network_error_returns_false_rather_than_raising() -> None:
    """One user's failure must not take down a scheduler serving everyone."""
    client = make_client()
    client.post.side_effect = httpx.ConnectError("boom")
    assert await adapter(client).send("42", OutgoingMessage(text="hi")) is False


@pytest.mark.asyncio
async def test_rate_limit_returns_false() -> None:
    client = make_client(status=429)
    client.post.return_value.json.return_value = {
        "ok": False,
        "parameters": {"retry_after": 30},
    }
    assert await adapter(client).send("42", OutgoingMessage(text="hi")) is False


@pytest.mark.asyncio
async def test_api_level_not_ok_returns_false() -> None:
    """HTTP 200 with ok:false is Telegram's normal way of reporting failure."""
    client = make_client(ok=False)
    assert await adapter(client).send("42", OutgoingMessage(text="hi")) is False


# --- token safety ----------------------------------------------------------


def test_token_is_stripped_from_log_output() -> None:
    a = adapter()
    assert TOKEN not in a._redact(f"connect failed for {a._url('sendMessage')}")
    assert "<token>" in a._redact(a._url("sendMessage"))


@pytest.mark.asyncio
async def test_token_never_reaches_a_log_record(caplog: pytest.LogCaptureFixture) -> None:
    client = make_client()
    client.post.side_effect = httpx.ConnectError(f"failed posting to {TOKEN}")
    with caplog.at_level("WARNING"):
        await adapter(client).send("42", OutgoingMessage(text="hi"))

    assert caplog.records, "expected a warning to be logged"
    assert TOKEN not in caplog.text


# --- photo download --------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_photo_resolves_then_downloads() -> None:
    client = make_client(result={"file_path": "photos/x.jpg"})
    download = MagicMock(content=b"\xff\xd8jpegbytes")
    download.raise_for_status = MagicMock()
    client.get = AsyncMock(return_value=download)

    data = await adapter(client).fetch_photo("file-123")

    assert data == b"\xff\xd8jpegbytes"
    assert client.post.call_args.kwargs["json"] == {"file_id": "file-123"}


@pytest.mark.asyncio
async def test_fetch_photo_raises_when_the_file_cannot_be_resolved() -> None:
    client = make_client(ok=False)
    with pytest.raises(RuntimeError, match="could not resolve"):
        await adapter(client).fetch_photo("file-123")
