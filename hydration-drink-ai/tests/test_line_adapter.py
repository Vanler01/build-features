"""LINE adapter tests.

Every HTTP call is mocked. LINE's free tier is 300 pushes a month, so a test
that reached the real API would spend real quota.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from hydration.adapters import line as ln
from hydration.adapters.port import Choice, IncomingKind, MessagingPort, OutgoingMessage
from hydration.core.models import Platform

TOKEN = "line-channel-access-token-not-real"
SECRET = "line-channel-secret-not-real"


def make_client(status: int = 200) -> MagicMock:
    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(status_code=status))
    client.get = AsyncMock()
    return client


def adapter(client: MagicMock | None = None) -> ln.LineAdapter:
    return ln.LineAdapter(TOKEN, client or make_client())


def event(message: dict[str, Any], *, reply_token: str | None = "rt-1") -> dict[str, Any]:
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": "U123"},
        "message": message,
    }


def sent_payload(client: MagicMock) -> dict[str, Any]:
    return client.post.call_args.kwargs["json"]


def sent_path(client: MagicMock) -> str:
    return client.post.call_args.args[0]


# --- port conformance ------------------------------------------------------


def test_adapter_satisfies_the_port() -> None:
    assert isinstance(adapter(), MessagingPort)
    assert adapter().platform is Platform.LINE


def test_empty_token_is_refused() -> None:
    with pytest.raises(ValueError, match="token is required"):
        ln.LineAdapter("", make_client())


# --- signature verification ------------------------------------------------


def test_valid_signature_passes() -> None:
    body = b'{"events":[]}'
    sig = base64.b64encode(
        hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    assert ln.verify_signature(SECRET, body, sig) is True


def test_tampered_body_fails() -> None:
    """Anyone who learns the webhook URL can POST fabricated events to it."""
    body = b'{"events":[]}'
    sig = base64.b64encode(
        hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    assert ln.verify_signature(SECRET, b'{"events":[{"forged":1}]}', sig) is False


def test_wrong_secret_fails() -> None:
    body = b'{"events":[]}'
    sig = base64.b64encode(
        hmac.new(b"other-secret", body, hashlib.sha256).digest()
    ).decode()
    assert ln.verify_signature(SECRET, body, sig) is False


def test_missing_signature_or_secret_fails_closed() -> None:
    assert ln.verify_signature(SECRET, b"{}", "") is False
    assert ln.verify_signature("", b"{}", "sig") is False


# --- inbound parsing -------------------------------------------------------


def test_text_message() -> None:
    msg = adapter().parse_incoming(event({"type": "text", "id": "1", "text": "two waters"}))
    assert msg is not None
    assert msg.kind is IncomingKind.TEXT
    assert msg.platform_user_id == "U123"
    assert msg.text == "two waters"


def test_reply_token_is_captured() -> None:
    """Without it every reply becomes a metered push."""
    msg = adapter().parse_incoming(event({"type": "text", "id": "1", "text": "hi"}))
    assert msg is not None
    assert msg.reply_token == "rt-1"


def test_command_is_detected() -> None:
    msg = adapter().parse_incoming(event({"type": "text", "id": "1", "text": "/link now"}))
    assert msg is not None
    assert msg.kind is IncomingKind.COMMAND
    assert msg.command == "/link"
    assert msg.args == "now"


def test_image_message() -> None:
    msg = adapter().parse_incoming(event({"type": "image", "id": "img-9"}))
    assert msg is not None
    assert msg.kind is IncomingKind.PHOTO
    assert msg.photo_ref == "img-9"


def test_location_message() -> None:
    msg = adapter().parse_incoming(
        event({"type": "location", "id": "1", "latitude": 13.75, "longitude": 100.5})
    )
    assert msg is not None
    assert msg.kind is IncomingKind.LOCATION
    assert (msg.latitude, msg.longitude) == (13.75, 100.5)


def test_group_and_room_events_are_ignored() -> None:
    """No stable per-person id, so logging against one would mis-attribute drinks."""
    for source_type in ("group", "room"):
        raw = event({"type": "text", "id": "1", "text": "hi"})
        raw["source"] = {"type": source_type, "groupId": "G1"}
        assert adapter().parse_incoming(raw) is None


def test_non_message_events_are_ignored() -> None:
    for kind in ("follow", "unfollow", "join", "postback", "beacon"):
        assert adapter().parse_incoming({"type": kind, "source": {"type": "user"}}) is None


def test_unsupported_message_types_are_ignored() -> None:
    for kind in ("sticker", "audio", "video", "file"):
        assert adapter().parse_incoming(event({"type": kind, "id": "1"})) is None


def test_malformed_events_are_ignored_not_raised() -> None:
    for raw in (None, "text", {}, {"type": "message"}, event({})):
        assert adapter().parse_incoming(raw) is None


def test_iter_events_unpacks_a_batch() -> None:
    body = {
        "destination": "U0",
        "events": [
            event({"type": "text", "id": "1", "text": "one"}),
            {"type": "follow", "source": {"type": "user", "userId": "U9"}},
            event({"type": "text", "id": "2", "text": "two"}),
        ],
    }
    messages = adapter().iter_events(body)
    assert [m.text for m in messages] == ["one", "two"]


def test_empty_webhook_verification_batch_does_not_error() -> None:
    """LINE posts an empty batch when you save the webhook URL in the console."""
    assert adapter().iter_events({"destination": "U0", "events": []}) == []
    assert adapter().iter_events({}) == []
    assert adapter().iter_events("nonsense") == []


# --- reply vs push: the money question -------------------------------------


@pytest.mark.asyncio
async def test_reply_token_uses_the_free_reply_endpoint() -> None:
    client = make_client()
    await adapter(client).send("U123", OutgoingMessage(text="Logged."), reply_token="rt-1")

    assert sent_path(client).endswith("message/reply")
    assert sent_payload(client)["replyToken"] == "rt-1"


@pytest.mark.asyncio
async def test_reminder_uses_the_metered_push_endpoint() -> None:
    client = make_client()
    await adapter(client).send("U123", OutgoingMessage(text="Water?", is_push=True))

    assert sent_path(client).endswith("message/push")
    assert sent_payload(client)["to"] == "U123"


@pytest.mark.asyncio
async def test_a_push_ignores_any_reply_token() -> None:
    """A reminder is unsolicited even if a token happens to be lying around."""
    client = make_client()
    await adapter(client).send(
        "U123", OutgoingMessage(text="Water?", is_push=True), reply_token="rt-1"
    )
    assert sent_path(client).endswith("message/push")


@pytest.mark.asyncio
async def test_a_lost_reply_token_falls_back_to_push_loudly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Silently spending quota is the failure this warning exists to catch."""
    client = make_client()
    with caplog.at_level("WARNING"):
        await adapter(client).send("U123", OutgoingMessage(text="Logged."))

    assert sent_path(client).endswith("message/push")
    assert "metered push" in caplog.text


# --- message construction --------------------------------------------------


@pytest.mark.asyncio
async def test_text_is_sent_as_a_text_message() -> None:
    client = make_client()
    await adapter(client).send("U123", OutgoingMessage(text="Logged."), reply_token="rt")

    assert sent_payload(client)["messages"] == [{"type": "text", "text": "Logged."}]


@pytest.mark.asyncio
async def test_long_text_is_chunked_at_line_s_own_limit() -> None:
    """LINE allows 5000 per message, not Telegram's 4096."""
    client = make_client()
    await adapter(client).send("U123", OutgoingMessage(text="x" * 6000), reply_token="rt")

    messages = sent_payload(client)["messages"]
    assert len(messages) == 2
    assert all(len(m["text"]) <= ln.MAX_MESSAGE_CHARS for m in messages)


@pytest.mark.asyncio
async def test_batch_cap_truncates_visibly_rather_than_dropping(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_client()
    with caplog.at_level("ERROR"):
        await adapter(client).send(
            "U123", OutgoingMessage(text="y" * 40_000), reply_token="rt"
        )

    messages = sent_payload(client)["messages"]
    assert len(messages) == ln.MAX_MESSAGES_PER_REQUEST
    assert messages[-1]["text"].endswith(ln.TRUNCATION_NOTICE)
    assert "capping" in caplog.text


@pytest.mark.asyncio
async def test_choices_become_quick_replies_on_the_last_message() -> None:
    client = make_client()
    await adapter(client).send(
        "U123",
        OutgoingMessage(
            text="Nearby:", choices=[Choice(label="Blue Bottle", value="p1", url="https://m/x")]
        ),
        reply_token="rt",
    )

    action = sent_payload(client)["messages"][-1]["quickReply"]["items"][0]["action"]
    assert action == {"type": "uri", "label": "Blue Bottle", "uri": "https://m/x"}


@pytest.mark.asyncio
async def test_valueless_choices_become_postbacks() -> None:
    client = make_client()
    await adapter(client).send(
        "U123",
        OutgoingMessage(text="Pick:", choices=[Choice(label="Water", value="water_250")]),
        reply_token="rt",
    )
    action = sent_payload(client)["messages"][-1]["quickReply"]["items"][0]["action"]
    assert action["type"] == "postback"
    assert action["data"] == "water_250"


@pytest.mark.asyncio
async def test_quick_reply_labels_are_capped_at_20_chars() -> None:
    client = make_client()
    await adapter(client).send(
        "U123",
        OutgoingMessage(text="Pick:", choices=[Choice(label="A" * 60, value="v")]),
        reply_token="rt",
    )
    action = sent_payload(client)["messages"][-1]["quickReply"]["items"][0]["action"]
    assert len(action["label"]) <= ln.MAX_QUICK_REPLY_LABEL


@pytest.mark.asyncio
async def test_quick_reply_items_are_capped_at_13() -> None:
    client = make_client()
    await adapter(client).send(
        "U123",
        OutgoingMessage(
            text="Pick:", choices=[Choice(label=f"c{i}", value=str(i)) for i in range(30)]
        ),
        reply_token="rt",
    )
    items = sent_payload(client)["messages"][-1]["quickReply"]["items"]
    assert len(items) <= ln.MAX_QUICK_REPLY_ITEMS


@pytest.mark.asyncio
async def test_location_request_uses_a_location_action() -> None:
    client = make_client()
    await adapter(client).send(
        "U123", OutgoingMessage(text="Where?", request_location=True), reply_token="rt"
    )
    action = sent_payload(client)["messages"][-1]["quickReply"]["items"][0]["action"]
    assert action["type"] == "location"


@pytest.mark.asyncio
async def test_plain_message_carries_no_quick_reply() -> None:
    client = make_client()
    await adapter(client).send("U123", OutgoingMessage(text="Logged."), reply_token="rt")
    assert "quickReply" not in sent_payload(client)["messages"][-1]


# --- failure handling ------------------------------------------------------


@pytest.mark.asyncio
async def test_network_error_returns_false() -> None:
    client = make_client()
    client.post.side_effect = httpx.ConnectError("boom")
    assert await adapter(client).send("U123", OutgoingMessage(text="hi")) is False


@pytest.mark.asyncio
async def test_rate_limit_returns_false() -> None:
    assert (
        await adapter(make_client(status=429)).send("U123", OutgoingMessage(text="hi"))
        is False
    )


@pytest.mark.asyncio
async def test_quota_exhausted_returns_false_rather_than_raising() -> None:
    """LINE answers 429 once the monthly push allowance is gone."""
    client = make_client(status=429)
    assert (
        await adapter(client).send("U123", OutgoingMessage(text="Water?", is_push=True))
        is False
    )


def test_token_is_stripped_from_log_output() -> None:
    a = adapter()
    assert TOKEN not in a._redact(f"auth failed with Bearer {TOKEN}")


@pytest.mark.asyncio
async def test_token_never_reaches_a_log_record(caplog: pytest.LogCaptureFixture) -> None:
    client = make_client()
    client.post.side_effect = httpx.ConnectError(f"bad auth {TOKEN}")
    with caplog.at_level("WARNING"):
        await adapter(client).send("U123", OutgoingMessage(text="hi"), reply_token="rt")

    assert caplog.records
    assert TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_auth_header_is_a_bearer_token() -> None:
    client = make_client()
    await adapter(client).send("U123", OutgoingMessage(text="hi"), reply_token="rt")
    headers = client.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.asyncio
async def test_fetch_photo_uses_the_content_host() -> None:
    """Content lives on api-data.line.me, not the main API host."""
    client = make_client()
    download = MagicMock(content=b"jpegbytes")
    download.raise_for_status = MagicMock()
    client.get = AsyncMock(return_value=download)

    assert await adapter(client).fetch_photo("img-9") == b"jpegbytes"
    assert client.get.call_args.args[0].startswith(ln.CONTENT_ROOT)


# --- cross-adapter consistency ---------------------------------------------


def test_both_adapters_produce_the_same_normalized_shape() -> None:
    """The port's whole point: core sees one message type, not two."""
    from hydration.adapters.telegram import TelegramAdapter

    tg_msg = TelegramAdapter("1:AAtok", make_client()).parse_incoming(
        {"update_id": 1, "message": {"from": {"id": 42}, "text": "/today"}}
    )
    line_msg = adapter().parse_incoming(event({"type": "text", "id": "1", "text": "/today"}))

    assert tg_msg is not None and line_msg is not None
    assert tg_msg.kind is line_msg.kind is IncomingKind.COMMAND
    assert tg_msg.command == line_msg.command == "/today"
    assert tg_msg.platform is Platform.TELEGRAM
    assert line_msg.platform is Platform.LINE


def test_webhook_body_is_json_serialisable_as_line_sends_it() -> None:
    """Guards the fixture shape against drifting from LINE's real payload."""
    body = {"destination": "U0", "events": [event({"type": "text", "id": "1", "text": "hi"})]}
    assert adapter().iter_events(json.loads(json.dumps(body)))
