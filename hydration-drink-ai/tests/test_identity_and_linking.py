"""Identity resolution and the bot -> app handoff.

The link token is the most security-sensitive object in this project: whoever
holds it becomes that user. Most of these tests are about the ways that can go
wrong.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from hydration.core import day, linking
from hydration.core import users as users_mod
from hydration.core.models import Platform

BASE_URL = "https://link.example.com"


# --- identity --------------------------------------------------------------


def test_same_platform_id_resolves_to_one_user(conn: sqlite3.Connection) -> None:
    first, created = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    second, created_again = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")

    assert created is True
    assert created_again is False
    assert first == second


def test_same_id_on_different_platforms_are_different_people(
    conn: sqlite3.Connection,
) -> None:
    """Telegram id 12345 and LINE id 12345 are unrelated strangers."""
    tg, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "12345")
    line, _ = users_mod.get_or_create_user(conn, Platform.LINE, "12345")
    assert tg != line


def test_one_user_can_hold_several_identities(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    users_mod.attach_identity(conn, user_id, Platform.LINE, "line-1")
    users_mod.attach_identity(conn, user_id, Platform.APP, "app-1")

    assert sorted(users_mod.identities_for(conn, user_id)) == [
        ("app", "app-1"),
        ("line", "line-1"),
        ("telegram", "tg-1"),
    ]


def test_stealing_an_identity_from_another_user_is_refused(
    conn: sqlite3.Connection,
) -> None:
    """Re-pointing an identity would move somebody's history onto another account."""
    owner, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    thief, _ = users_mod.get_or_create_user(conn, Platform.LINE, "line-1")

    with pytest.raises(ValueError, match="already linked"):
        users_mod.attach_identity(conn, thief, Platform.TELEGRAM, "tg-1")

    assert users_mod.resolve_user(conn, Platform.TELEGRAM, "tg-1") == owner


def test_reattaching_the_same_identity_is_a_no_op(conn: sqlite3.Connection) -> None:
    """Redemption must stay idempotent under retries."""
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    users_mod.attach_identity(conn, user_id, Platform.TELEGRAM, "tg-1")
    assert len(users_mod.identities_for(conn, user_id)) == 1


def test_new_user_gets_default_settings(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    settings = users_mod.get_settings(conn, user_id)
    assert settings.reminders_enabled is True
    assert settings.undo_window_sec == 4


def test_invalid_timezone_is_refused_at_the_boundary(conn: sqlite3.Connection) -> None:
    """An unvalidated zone breaks every later summary, far from this call."""
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    with pytest.raises(ValueError, match="IANA timezone"):
        users_mod.set_timezone(conn, user_id, "Mars/Olympus_Mons")

    users_mod.set_timezone(conn, user_id, "Asia/Bangkok")
    assert users_mod.get_timezone(conn, user_id) == "Asia/Bangkok"


def test_account_delete_cascades(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    users_mod.delete_account(conn, user_id)

    assert users_mod.resolve_user(conn, Platform.TELEGRAM, "tg-1") is None
    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM user_settings WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]
    assert remaining == 0


# --- link tokens -----------------------------------------------------------


def test_link_round_trip_joins_bot_and_app(conn: sqlite3.Connection) -> None:
    bot_user, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    offer = linking.issue_token(conn, bot_user, Platform.TELEGRAM, BASE_URL)

    linked = linking.redeem_token(conn, offer.code, "app-install-1")

    assert linked == bot_user
    assert users_mod.resolve_user(conn, Platform.APP, "app-install-1") == bot_user


def test_raw_token_is_never_stored(conn: sqlite3.Connection) -> None:
    """A database dump must not hand over live account access."""
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    offer = linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)

    stored = [row["token_hash"] for row in conn.execute("SELECT token_hash FROM link_tokens")]
    assert offer.code not in stored
    assert all(len(h) == 64 for h in stored), "expected sha256 hex digests"


def test_a_code_works_exactly_once(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    offer = linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)

    linking.redeem_token(conn, offer.code, "app-1")
    with pytest.raises(ValueError, match="not valid"):
        linking.redeem_token(conn, offer.code, "app-2")


def test_expired_code_is_refused(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    offer = linking.issue_token(
        conn, user_id, Platform.TELEGRAM, BASE_URL, ttl=timedelta(seconds=-1)
    )
    with pytest.raises(ValueError, match="not valid"):
        linking.redeem_token(conn, offer.code, "app-1")


def test_unknown_expired_and_used_codes_are_indistinguishable(
    conn: sqlite3.Connection,
) -> None:
    """Different messages would tell an attacker which guesses exist."""
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    used = linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)
    linking.redeem_token(conn, used.code, "app-1")
    expired = linking.issue_token(
        conn, user_id, Platform.TELEGRAM, BASE_URL, ttl=timedelta(seconds=-1)
    )

    messages = set()
    for code in ("ZZZZZZ", used.code, expired.code):
        with pytest.raises(ValueError) as exc:
            linking.redeem_token(conn, code, "app-x")
        messages.add(str(exc.value))
    assert len(messages) == 1, messages


def test_issuing_is_rate_limited(conn: sqlite3.Connection) -> None:
    """Unbounded issuing widens the guessing surface."""
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    for _ in range(linking.MAX_ACTIVE_TOKENS_PER_USER):
        linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)

    with pytest.raises(RuntimeError, match="too many active"):
        linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)


def test_expired_tokens_stop_counting_against_the_cap(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    for _ in range(linking.MAX_ACTIVE_TOKENS_PER_USER):
        linking.issue_token(
            conn, user_id, Platform.TELEGRAM, BASE_URL, ttl=timedelta(seconds=-1)
        )
    assert linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL).code


def test_redeeming_onto_a_populated_app_account_is_refused(
    conn: sqlite3.Connection,
) -> None:
    """Merging two populated accounts is a decision nobody has made yet."""
    bot_user, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    users_mod.get_or_create_user(conn, Platform.APP, "app-1")
    offer = linking.issue_token(conn, bot_user, Platform.TELEGRAM, BASE_URL)

    with pytest.raises(ValueError, match="already linked to another user"):
        linking.redeem_token(conn, offer.code, "app-1")


def test_code_is_case_insensitive_and_trims(conn: sqlite3.Connection) -> None:
    """The fallback path is typed by hand."""
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    offer = linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)
    assert linking.redeem_token(conn, f"  {offer.code.lower()} ", "app-1") == user_id


def test_code_alphabet_avoids_lookalike_characters() -> None:
    """A code read aloud must not turn O into 0, or L into 1."""
    assert not (set("IL01OU") & set(linking._CODE_ALPHABET))
    assert len(linking._CODE_ALPHABET) >= 30, "keep enough entropy for a 6-char code"


def test_deep_link_carries_the_code(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    offer = linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)
    assert offer.url == f"{BASE_URL}/l/{offer.code}"


def test_purge_removes_only_expired_unused_tokens(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    live = linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)
    linking.issue_token(
        conn, user_id, Platform.TELEGRAM, BASE_URL, ttl=timedelta(seconds=-1)
    )

    assert linking.purge_expired(conn) == 1
    assert linking.redeem_token(conn, live.code, "app-1") == user_id


def test_tokens_die_with_the_account(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    offer = linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)
    users_mod.delete_account(conn, user_id)

    with pytest.raises(ValueError, match="not valid"):
        linking.redeem_token(conn, offer.code, "app-1")


def test_expiry_is_stored_in_utc(conn: sqlite3.Connection) -> None:
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1")
    linking.issue_token(conn, user_id, Platform.TELEGRAM, BASE_URL)
    row = conn.execute("SELECT expires_at FROM link_tokens").fetchone()
    assert day.from_iso(row["expires_at"]).tzinfo is not None
