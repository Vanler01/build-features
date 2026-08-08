"""Bearer tokens for the mobile app.

Same discipline as ``linking``: the raw token is returned once and never
stored, only its SHA-256. Whoever holds one is the user, so a database dump
must not be enough to become them.

Tokens do not expire on a clock. A hydration tracker that logs you out weekly
gets deleted, and the honest mitigation for a lost phone is revocation the user
controls rather than an expiry that annoys everyone who did not lose theirs.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid

from . import day as day_util
from . import users as users_mod
from .models import Platform

TOKEN_BYTES = 32


def _hash(raw: str) -> str:
    """Hash a raw token for storage. Never store or log the raw value."""
    return hashlib.sha256(raw.encode()).hexdigest()


def issue(conn: sqlite3.Connection, user_id: str) -> str:
    """Mint a token for a user and return the raw value, once."""
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    conn.execute(
        "INSERT INTO app_tokens (token_hash, user_id, created_at) VALUES (?, ?, ?)",
        (_hash(raw), user_id, day_util.to_iso(day_util.utc_now())),
    )
    return raw


def resolve(conn: sqlite3.Connection, raw: str) -> str | None:
    """Return the user a token belongs to, or None if it is not valid.

    Also records last use, which is what makes "you were last active on this
    device" possible without storing anything else about the device.
    """
    if not raw:
        return None
    row = conn.execute(
        "SELECT user_id, revoked_at FROM app_tokens WHERE token_hash = ?", (_hash(raw),)
    ).fetchone()
    if row is None or row["revoked_at"] is not None:
        return None

    conn.execute(
        "UPDATE app_tokens SET last_used_at = ? WHERE token_hash = ?",
        (day_util.to_iso(day_util.utc_now()), _hash(raw)),
    )
    return row["user_id"]


def revoke(conn: sqlite3.Connection, raw: str) -> bool:
    """Revoke one token. Returns whether it was valid to begin with."""
    row = conn.execute(
        "UPDATE app_tokens SET revoked_at = ?"
        " WHERE token_hash = ? AND revoked_at IS NULL",
        (day_util.to_iso(day_util.utc_now()), _hash(raw)),
    )
    return row.rowcount > 0


def revoke_all(conn: sqlite3.Connection, user_id: str) -> int:
    """Revoke every token for a user. Returns how many were revoked."""
    row = conn.execute(
        "UPDATE app_tokens SET revoked_at = ?"
        " WHERE user_id = ? AND revoked_at IS NULL",
        (day_util.to_iso(day_util.utc_now()), user_id),
    )
    return row.rowcount


def redeem_link_code(conn: sqlite3.Connection, code: str) -> tuple[str, str]:
    """Exchange a bot link code for an app token. Returns ``(token, user_id)``.

    The app's platform identity is generated here rather than accepted from the
    client. A client-supplied identity would let a caller nominate which app
    account a redeemed code attaches to, and identity is not the client's to
    choose.
    """
    from . import linking

    app_key = str(uuid.uuid4())
    user_id = linking.redeem_token(conn, code, app_key)
    return issue(conn, user_id), user_id


def ensure_app_identity(conn: sqlite3.Connection, user_id: str) -> None:
    """Make sure the user has an app identity, for accounts created app-first."""
    for platform, _ in users_mod.identities_for(conn, user_id):
        if platform == str(Platform.APP):
            return
    users_mod.attach_identity(conn, user_id, Platform.APP, str(uuid.uuid4()))
