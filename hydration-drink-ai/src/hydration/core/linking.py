"""Bot -> app handoff.

A user chatting to the bot taps ``/link`` and continues in the app with their
drinks intact. The token that carries them across is the most security-sensitive
object in this project: anyone holding it becomes that user.

So:

  * the raw token is shown once and never stored -- only its SHA-256
  * it is single-use, and redeeming it twice fails
  * it expires quickly (10 minutes by default)
  * issuing is rate-limited, so a token cannot be brute-forced by flooding

The delivery order is deep link, then short code, then QR. A QR code is useless
in the common case, where the bot and the app are on the same phone and the user
cannot scan their own screen.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from . import day as day_util
from . import users as users_mod
from .models import Platform

TOKEN_TTL = timedelta(minutes=10)
MAX_ACTIVE_TOKENS_PER_USER = 3

# Crockford-style alphabet for the fallback code, which gets read aloud and
# retyped by hand. Excludes I/L/O/U and the digits 0/1: I, L and 1 are the same
# glyph in several fonts, O and 0 likewise, and dropping U keeps a random
# six-character string from spelling something unfortunate.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_CODE_LENGTH = 6


@dataclass(frozen=True, slots=True)
class LinkOffer:
    """What the bot shows the user. ``code`` and ``url`` carry the same token."""

    code: str
    url: str
    expires_in_sec: int


def _hash(raw: str) -> str:
    """Hash a raw token for storage. Never store or log the raw value."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _generate_code() -> str:
    """Generate a 6-character code from the unambiguous alphabet."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def issue_token(
    conn: sqlite3.Connection,
    user_id: str,
    platform: Platform,
    base_url: str,
    ttl: timedelta = TOKEN_TTL,
) -> LinkOffer:
    """Issue a single-use link token for a user.

    Raises ``RuntimeError`` if the user already has the maximum number of live
    tokens outstanding -- unbounded issuing would let an attacker widen the
    guessing surface simply by spamming ``/link``.
    """
    now = day_util.utc_now()
    _expire_stale(conn, user_id)

    live = conn.execute(
        "SELECT COUNT(*) AS n FROM link_tokens"
        " WHERE user_id = ? AND used_at IS NULL AND expires_at > ?",
        (user_id, day_util.to_iso(now)),
    ).fetchone()["n"]
    if live >= MAX_ACTIVE_TOKENS_PER_USER:
        raise RuntimeError("too many active link codes; wait for one to expire")

    code = _generate_code()
    conn.execute(
        "INSERT INTO link_tokens (token_hash, user_id, platform, expires_at)"
        " VALUES (?, ?, ?, ?)",
        (_hash(code), user_id, str(platform), day_util.to_iso(now + ttl)),
    )
    return LinkOffer(
        code=code,
        url=f"{base_url.rstrip('/')}/l/{quote(code)}",
        expires_in_sec=int(ttl.total_seconds()),
    )


def redeem_token(
    conn: sqlite3.Connection,
    code: str,
    app_user_key: str,
) -> str:
    """Redeem a link code, attaching the app identity to the bot's user.

    ``app_user_key`` identifies the app installation or account doing the
    redeeming. Returns the internal user id now shared by both surfaces.

    Raises ``ValueError`` for an unknown, expired, or already-used code. The
    message is deliberately the same for all three: distinguishing them tells an
    attacker whether a guessed code exists.
    """
    now = day_util.utc_now()
    row = conn.execute(
        "SELECT * FROM link_tokens WHERE token_hash = ?", (_hash(code.strip().upper()),)
    ).fetchone()

    if row is None or row["used_at"] is not None:
        raise ValueError("that code is not valid")
    if day_util.from_iso(row["expires_at"]) <= now:
        raise ValueError("that code is not valid")

    user_id = row["user_id"]
    existing_owner = users_mod.resolve_user(conn, Platform.APP, app_user_key)
    if existing_owner is not None and existing_owner != user_id:
        # This app install is already somebody else's account. Merging two
        # populated accounts is a product decision nobody has made, so refuse
        # rather than guess which history survives.
        raise ValueError("this app account is already linked to another user")

    conn.execute(
        "UPDATE link_tokens SET used_at = ? WHERE token_hash = ?",
        (day_util.to_iso(now), row["token_hash"]),
    )
    users_mod.attach_identity(conn, user_id, Platform.APP, app_user_key)
    return user_id


def _expire_stale(conn: sqlite3.Connection, user_id: str) -> None:
    """Delete expired unused tokens so they stop counting toward the cap."""
    conn.execute(
        "DELETE FROM link_tokens WHERE user_id = ? AND used_at IS NULL AND expires_at <= ?",
        (user_id, day_util.to_iso(day_util.utc_now())),
    )


def purge_expired(conn: sqlite3.Connection) -> int:
    """Delete every expired unused token. Returns how many were removed."""
    cursor = conn.execute(
        "DELETE FROM link_tokens WHERE used_at IS NULL AND expires_at <= ?",
        (day_util.to_iso(day_util.utc_now()),),
    )
    return cursor.rowcount
