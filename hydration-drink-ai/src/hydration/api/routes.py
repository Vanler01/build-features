"""The app-facing REST API.

What the mobile app and, through it, the home-screen widget talk to. The bot
surfaces share every table underneath, which is what makes "start on the bot,
carry on in the app" true rather than aspirational.

Two things run through the whole module:

**The client never nominates identity.** Every route derives ``user_id`` from
the bearer token. A ``user_id`` in a request body is ignored, so a caller
cannot write into somebody else's day by asking nicely.

**Sync is entry events, not counts.** ``/sync`` is the widget's outbox drain:
adds carry a client-generated UUID and removals are tombstones, so replaying a
batch is harmless and arrival order does not matter. That is the same model the
core enforces; this endpoint just exposes it.
"""

# No `from __future__ import annotations` here, deliberately. PEP 563 turns
# annotations into strings, and FastAPI resolves them with get_type_hints at
# decoration time — which cannot see the `Auth` alias or the dependency
# callables defined inside build_router. The symptom is a 422 on every
# authenticated route, because the dependency is mistaken for a query
# parameter. Eager annotations keep the enclosing scope visible.

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..core import auth, catalog, db, linking, logs, profile
from ..core import day as day_util
from ..core import users as users_mod
from ..core.models import GoalKind, LogEntry, LogSource, Platform

_LOG = logging.getLogger(__name__)

MAX_SYNC_EVENTS = 500
MAX_HISTORY_DAYS = 365


# --- request/response models ----------------------------------------------


class RedeemRequest(BaseModel):
    """Exchange a bot link code for an app token."""

    code: str = Field(min_length=4, max_length=32)


class RedeemResponse(BaseModel):
    """The token is returned exactly once and is not recoverable."""

    token: str
    user_id: str


class AddEvent(BaseModel):
    """One drink logged on a client, identified by a client-generated UUID."""

    type: str = Field(pattern="^add$")
    id: str = Field(min_length=8, max_length=64)
    drink_id: str | None = None
    custom_name: str | None = None
    quantity: float = Field(gt=0, le=50)
    logged_at: str | None = None


class RemoveEvent(BaseModel):
    """A tombstone for an entry, by the id the client created it with."""

    type: str = Field(pattern="^remove$")
    id: str = Field(min_length=8, max_length=64)


class SyncRequest(BaseModel):
    """A batch from the widget's offline outbox."""

    events: list[AddEvent | RemoveEvent] = Field(max_length=MAX_SYNC_EVENTS)


class EntryRequest(BaseModel):
    """A single drink logged from the app UI."""

    drink_id: str | None = None
    custom_name: str | None = None
    quantity: float = Field(default=1.0, gt=0, le=50)


class SettingsRequest(BaseModel):
    """Partial settings update; omitted fields are left alone."""

    reminders_enabled: bool | None = None
    interval_min: int | None = Field(default=None, ge=15, le=720)
    window_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    window_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    nearby_enabled: bool | None = None
    nutrition_replies_enabled: bool | None = None
    undo_window_sec: int | None = Field(default=None, ge=1, le=30)
    timezone: str | None = None


class GoalRequest(BaseModel):
    """A goal to reach, or a cap not to exceed."""

    drink_category: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern="^(goal|limit)$")
    target: float = Field(gt=0, le=100)
    active: bool = True


class WeightRequest(BaseModel):
    """Opt-in body weight, in kilograms."""

    weight_kg: float


class AgeRequest(BaseModel):
    """A self-declared age check. The age itself is never stored."""

    country: str = Field(min_length=2, max_length=2)
    age: int = Field(gt=0, lt=130)


# --- dependencies ----------------------------------------------------------


@contextmanager
def _connection(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = db.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def build_router(db_path: str) -> APIRouter:
    """Build the app API, bound to a database path."""
    router = APIRouter(prefix="/api")

    def current_user(
        authorization: Annotated[str, Header()] = "",
    ) -> tuple[str, str]:
        """Resolve the bearer token to a user id.

        Returns ``(user_id, timezone)`` so no route has to re-read it.
        """
        scheme, _, raw = authorization.partition(" ")
        if scheme.lower() != "bearer" or not raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token"
            )
        with _connection(db_path) as conn:
            user_id = auth.resolve(conn, raw)
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
                )
            return user_id, users_mod.get_timezone(conn, user_id)

    Auth = Annotated[tuple[str, str], Depends(current_user)]

    # -- linking ------------------------------------------------------------

    @router.post("/link/redeem", response_model=RedeemResponse)
    def redeem(body: RedeemRequest) -> RedeemResponse:
        """Exchange a bot link code for an app token."""
        with _connection(db_path) as conn:
            try:
                token, user_id = auth.redeem_link_code(conn, body.code)
            except ValueError as exc:
                # Deliberately the same message for unknown, expired and used
                # codes -- distinguishing them tells an attacker which guesses
                # exist. See linking.redeem_token.
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return RedeemResponse(token=token, user_id=user_id)

    @router.post("/link/code", status_code=status.HTTP_201_CREATED)
    def issue_code(auth_ctx: Auth, base_url: str = "") -> dict[str, Any]:
        """Issue a link code from the app, to bring a bot conversation across."""
        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            try:
                offer = linking.issue_token(
                    conn, user_id, Platform.APP, base_url or "https://link.example.com"
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
                ) from exc
            return {"code": offer.code, "url": offer.url, "expires_in": offer.expires_in_sec}

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(authorization: Annotated[str, Header()] = "") -> None:
        """Revoke the token used to make this call."""
        _, _, raw = authorization.partition(" ")
        with _connection(db_path) as conn:
            auth.revoke(conn, raw)

    # -- sync ---------------------------------------------------------------

    @router.post("/sync")
    def sync(auth_ctx: Auth, body: SyncRequest) -> dict[str, Any]:
        """Drain a client's outbox of entry events.

        Idempotent and order-independent: replaying a batch after a flaky
        connection changes nothing, which is what lets the widget queue taps
        offline and sync whenever.
        """
        user_id, timezone = auth_ctx
        with _connection(db_path) as conn:
            gate = profile.get_age_gate(conn, user_id)
            applied = 0
            refused: list[str] = []

            for event in body.events:
                if isinstance(event, RemoveEvent):
                    logs.remove_entry(conn, event.id, user_id)
                    applied += 1
                    continue

                name = _entry_name(conn, event.drink_id, event.custom_name)
                if name is None:
                    refused.append(event.id)
                    continue
                if catalog.is_alcohol(conn, name) and not gate.alcohol_unlocked:
                    # The app may log alcohol, but only once the age gate has
                    # been passed. Refused per entry rather than failing the
                    # whole batch, so one drink cannot block a day's sync.
                    refused.append(event.id)
                    continue

                logs.upsert_entry(
                    conn,
                    LogEntry(
                        id=event.id,
                        user_id=user_id,  # from the token, never the body
                        logged_at=(
                            day_util.from_iso(event.logged_at)
                            if event.logged_at
                            else day_util.utc_now()
                        ),
                        source=LogSource.WIDGET,
                        drink_id=event.drink_id,
                        custom_name=event.custom_name,
                        quantity=event.quantity,
                    ),
                )
                applied += 1

            return {
                "applied": applied,
                "refused": refused,
                "day_totals": logs.day_totals(conn, user_id, timezone),
            }

    # -- the day ------------------------------------------------------------

    @router.get("/today")
    def today(auth_ctx: Auth) -> dict[str, Any]:
        """Today's entries and totals, in the user's own day."""
        user_id, timezone = auth_ctx
        with _connection(db_path) as conn:
            entries = [
                {
                    "id": row["id"],
                    "drink_id": row["drink_id"],
                    "name": catalog.display_name(
                        conn, row["drink_id"] or row["custom_name"]
                    ),
                    "quantity": row["quantity"],
                    "logged_at": row["logged_at"],
                    "source": row["source"],
                }
                for row in logs.live_entries(conn, user_id, timezone)
            ]
            return {
                "date": day_util.local_date(day_util.utc_now(), timezone).isoformat(),
                "entries": entries,
                "totals": logs.day_totals(conn, user_id, timezone),
                "categories": logs.category_totals(conn, user_id, timezone),
                "water_target_ml": profile.suggested_water_ml(conn, user_id),
            }

    @router.get("/history")
    def history(auth_ctx: Auth, days: int = 7) -> dict[str, Any]:
        """Per-day category totals going back ``days``."""
        user_id, timezone = auth_ctx
        span = max(1, min(days, MAX_HISTORY_DAYS))
        now = day_util.utc_now()

        with _connection(db_path) as conn:
            out = []
            for offset in range(span):
                moment = now - timedelta(days=offset)
                out.append(
                    {
                        "date": day_util.local_date(moment, timezone).isoformat(),
                        "categories": logs.category_totals(
                            conn, user_id, timezone, when=moment
                        ),
                    }
                )
            return {"days": out}

    @router.post("/entries", status_code=status.HTTP_201_CREATED)
    def add_entry(auth_ctx: Auth, body: EntryRequest) -> dict[str, Any]:
        """Log a drink from the app."""
        user_id, timezone = auth_ctx
        with _connection(db_path) as conn:
            name = _entry_name(conn, body.drink_id, body.custom_name)
            if name is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="drink_id or custom_name is required",
                )
            if catalog.is_alcohol(conn, name):
                gate = profile.get_age_gate(conn, user_id)
                if not gate.alcohol_unlocked:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="alcohol logging is locked until the age check is done",
                    )

            entry = LogEntry(
                user_id=user_id,
                logged_at=day_util.utc_now(),
                source=LogSource.APP,
                drink_id=body.drink_id,
                custom_name=body.custom_name,
                quantity=body.quantity,
            )
            logs.upsert_entry(conn, entry)
            return {"id": entry.id, "totals": logs.day_totals(conn, user_id, timezone)}

    @router.delete("/entries/{entry_id}")
    def remove_entry(auth_ctx: Auth, entry_id: str) -> dict[str, Any]:
        """Remove an entry.

        A tombstone, not a delete: an offline client replaying the original add
        must not be able to bring it back.
        """
        user_id, timezone = auth_ctx
        with _connection(db_path) as conn:
            removed = logs.remove_entry(conn, entry_id, user_id)
            return {"removed": removed, "totals": logs.day_totals(conn, user_id, timezone)}

    # -- catalog ------------------------------------------------------------

    @router.get("/catalog")
    def drinks(auth_ctx: Auth) -> dict[str, Any]:
        """Return the drink catalog, for pickers and widget configuration."""
        _user_id, _tz = auth_ctx
        with _connection(db_path) as conn:
            return {
                "drinks": [
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "category": row["category"],
                        "serving_size_ml": row["serving_size_ml"],
                        "calories": row["calories"],
                        "sugar_g": row["sugar_g"],
                        "caffeine_mg": row["caffeine_mg"],
                        "is_alcohol": bool(row["is_alcohol"]),
                    }
                    for row in conn.execute(
                        "SELECT * FROM drinks_catalog ORDER BY category, name"
                    )
                ]
            }

    # -- settings and goals -------------------------------------------------

    @router.get("/settings")
    def get_settings(auth_ctx: Auth) -> dict[str, Any]:
        """Return current settings, plus the state the app needs to render them."""
        user_id, timezone = auth_ctx
        with _connection(db_path) as conn:
            settings = users_mod.get_settings(conn, user_id)
            gate = profile.get_age_gate(conn, user_id)
            return {
                "reminders_enabled": settings.reminders_enabled,
                "interval_min": settings.interval_min,
                "window_start": settings.window_start,
                "window_end": settings.window_end,
                "nearby_enabled": settings.nearby_enabled,
                "nutrition_replies_enabled": settings.nutrition_replies_enabled,
                "undo_window_sec": settings.undo_window_sec,
                "timezone": timezone,
                "weight_kg": profile.get_weight(conn, user_id),
                "water_target_ml": profile.suggested_water_ml(conn, user_id),
                "alcohol_unlocked": gate.alcohol_unlocked,
            }

    @router.put("/settings")
    def put_settings(auth_ctx: Auth, body: SettingsRequest) -> dict[str, str]:
        """Update settings. Omitted fields are left alone."""
        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            if body.timezone is not None:
                try:
                    users_mod.set_timezone(conn, user_id, body.timezone)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                    ) from exc

            changes = body.model_dump(exclude_none=True, exclude={"timezone"})
            if changes:
                users_mod.update_settings(
                    conn, replace(users_mod.get_settings(conn, user_id), **changes)
                )
            return {"status": "ok"}

    @router.get("/goals")
    def get_goals(auth_ctx: Auth) -> dict[str, Any]:
        """Return the user's goals and limits."""
        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            return {
                "goals": [
                    {
                        "drink_category": g.drink_category,
                        "kind": str(g.kind),
                        "target": g.target,
                    }
                    for g in users_mod.get_goals(conn, user_id)
                ]
            }

    @router.put("/goals")
    def put_goal(auth_ctx: Auth, body: GoalRequest) -> dict[str, str]:
        """Create or replace one goal or limit."""
        from ..core.models import Goal

        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            users_mod.set_goal(
                conn,
                Goal(
                    user_id=user_id,
                    drink_category=body.drink_category,
                    kind=GoalKind(body.kind),
                    target=body.target,
                    active=body.active,
                ),
            )
            return {"status": "ok"}

    # -- profile ------------------------------------------------------------

    @router.put("/profile/weight")
    def put_weight(auth_ctx: Auth, body: WeightRequest) -> dict[str, Any]:
        """Set body weight. Opt-in, and never leaves the backend."""
        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            try:
                profile.set_weight(conn, user_id, body.weight_kg)
            except profile.ProfileError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {
                "weight_kg": profile.get_weight(conn, user_id),
                "water_target_ml": profile.suggested_water_ml(conn, user_id),
                "note": "A starting point, not medical advice.",
            }

    @router.delete("/profile/weight", status_code=status.HTTP_204_NO_CONTENT)
    def delete_weight(auth_ctx: Auth) -> None:
        """Delete body weight. Immediate and total."""
        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            profile.delete_weight(conn, user_id)

    @router.post("/profile/age-check")
    def age_check(auth_ctx: Auth, body: AgeRequest) -> dict[str, Any]:
        """Run the self-declared age check.

        The age is compared and discarded — only the outcome and the country
        used are stored. This is not verification and must not be presented as
        such.
        """
        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            try:
                gate = profile.declare_age(conn, user_id, body.country, body.age)
            except profile.ProfileError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            return {
                "alcohol_unlocked": gate.alcohol_unlocked,
                "country": gate.country,
                "threshold": gate.threshold,
                "verified": False,
            }

    @router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
    def delete_account(auth_ctx: Auth) -> None:
        """Delete the account and everything belonging to it.

        No harder to reach than signing up. Cascades to logs, weight, the age
        gate, tokens and every platform identity.
        """
        user_id, _ = auth_ctx
        with _connection(db_path) as conn:
            users_mod.delete_account(conn, user_id)

    return router


def _entry_name(
    conn: sqlite3.Connection, drink_id: str | None, custom_name: str | None
) -> str | None:
    """Resolve what a client called a drink, for the alcohol check."""
    if drink_id:
        row = conn.execute(
            "SELECT name FROM drinks_catalog WHERE id = ?", (drink_id,)
        ).fetchone()
        return row["name"] if row else drink_id
    return custom_name or None
