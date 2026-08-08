"""The app-facing REST API.

Driven through FastAPI's TestClient against a temporary database. No network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hydration.ai.schema import Confidence, ParsedDrink, ParseResult, Temperature, TimeOfDay
from hydration.api.app import WebhookConfig, create_app
from hydration.api.dispatch import Dispatcher
from hydration.core import auth, db, linking, logs, profile, seed
from hydration.core import users as users_mod
from hydration.core.models import LogEntry, LogSource, Platform
from hydration.handlers import HandlerDeps


def a_parse() -> ParseResult:
    return ParseResult(
        drinks=[
            ParsedDrink(
                drink_type="water",
                temperature=Temperature.UNKNOWN,
                quantity=1,
                size_ml=None,
                time_of_day=TimeOfDay.UNKNOWN,
                confidence=Confidence.HIGH,
            )
        ],
        needs_clarification=False,
        clarification_question=None,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "app.sqlite3")
    conn = db.open_database(path)
    seed.load_into(conn)
    conn.close()
    return path


@pytest.fixture
def client(db_path: str) -> TestClient:
    deps = HandlerDeps(parse=lambda text: a_parse(), link_base_url="https://l.example")
    app = create_app(Dispatcher({}, deps), WebhookConfig(db_path=db_path))
    return TestClient(app)


@pytest.fixture
def account(db_path: str) -> tuple[str, str]:
    """A linked app account. Returns ``(token, user_id)``."""
    conn = db.connect(db_path)
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-1", "Asia/Bangkok")
    token = auth.issue(conn, user_id)
    conn.commit()
    conn.close()
    return token, user_id


def hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- auth ------------------------------------------------------------------


def test_endpoints_require_a_token(client: TestClient) -> None:
    for path in ("/api/today", "/api/settings", "/api/catalog", "/api/goals"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/sync", json={"events": []}).status_code == 401
    assert client.post("/api/entries", json={"drink_id": "water_250"}).status_code == 401


def test_a_bogus_token_is_rejected(client: TestClient) -> None:
    assert client.get("/api/today", headers=hdr("not-a-token")).status_code == 401


def test_a_non_bearer_scheme_is_rejected(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    assert client.get("/api/today", headers={"Authorization": token}).status_code == 401


def test_a_valid_token_works(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    assert client.get("/api/today", headers=hdr(token)).status_code == 200


def test_link_code_redeems_to_a_token(client: TestClient, db_path: str) -> None:
    """The bot-to-app handoff, end to end."""
    conn = db.connect(db_path)
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-9")
    offer = linking.issue_token(conn, user_id, Platform.TELEGRAM, "https://l.example")
    conn.commit()
    conn.close()

    response = client.post("/api/link/redeem", json={"code": offer.code})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user_id
    assert client.get("/api/today", headers=hdr(body["token"])).status_code == 200


def test_a_code_cannot_be_redeemed_twice(client: TestClient, db_path: str) -> None:
    conn = db.connect(db_path)
    user_id, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "tg-9")
    offer = linking.issue_token(conn, user_id, Platform.TELEGRAM, "https://l.example")
    conn.commit()
    conn.close()

    client.post("/api/link/redeem", json={"code": offer.code})
    assert client.post("/api/link/redeem", json={"code": offer.code}).status_code == 400


def test_tokens_are_stored_hashed(db_path: str, account: tuple[str, str]) -> None:
    """A database dump must not hand over live account access."""
    token, _ = account
    conn = db.connect(db_path)
    stored = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM app_tokens")]
    assert token not in stored
    assert all(len(h) == 64 for h in stored)


def test_logout_revokes_the_token(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    assert client.post("/api/logout", headers=hdr(token)).status_code == 204
    assert client.get("/api/today", headers=hdr(token)).status_code == 401


# --- identity cannot be nominated by the client ---------------------------


def test_sync_ignores_a_user_id_in_the_body(
    client: TestClient, db_path: str, account: tuple[str, str]
) -> None:
    """The client never chooses whose day it writes into."""
    token, user_id = account
    conn = db.connect(db_path)
    victim, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "victim")
    conn.commit()
    conn.close()

    client.post(
        "/api/sync",
        headers=hdr(token),
        json={
            "events": [
                {
                    "type": "add",
                    "id": "11111111-1111-1111-1111-111111111111",
                    "user_id": victim,  # ignored — not part of the model
                    "drink_id": "water_250",
                    "quantity": 1,
                }
            ]
        },
    )

    conn = db.connect(db_path)
    owner = conn.execute("SELECT user_id FROM logs").fetchone()["user_id"]
    assert owner == user_id
    assert owner != victim


def test_one_user_cannot_remove_anothers_entry(
    client: TestClient, db_path: str, account: tuple[str, str]
) -> None:
    token, _ = account
    conn = db.connect(db_path)
    other, _ = users_mod.get_or_create_user(conn, Platform.TELEGRAM, "other")
    entry = LogEntry(
        user_id=other,
        logged_at=__import__("hydration.core.day", fromlist=["x"]).utc_now(),
        source=LogSource.APP,
        drink_id="water_250",
    )
    logs.upsert_entry(conn, entry)
    conn.commit()
    conn.close()

    client.delete(f"/api/entries/{entry.id}", headers=hdr(token))

    conn = db.connect(db_path)
    row = conn.execute("SELECT deleted_at FROM logs WHERE id = ?", (entry.id,)).fetchone()
    assert row["deleted_at"] is None, "another user's entry was tombstoned"


# --- sync ------------------------------------------------------------------


def sync(client: TestClient, token: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    response = client.post("/api/sync", headers=hdr(token), json={"events": events})
    assert response.status_code == 200, response.text
    return response.json()


def test_sync_applies_adds(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    body = sync(
        client,
        token,
        [
            {"type": "add", "id": "a" * 36, "drink_id": "water_250", "quantity": 2},
            {"type": "add", "id": "b" * 36, "drink_id": "brewed_coffee_240", "quantity": 1},
        ],
    )
    assert body["day_totals"] == {"water_250": 2.0, "brewed_coffee_240": 1.0}


def test_replaying_a_batch_changes_nothing(
    client: TestClient, account: tuple[str, str]
) -> None:
    """A flaky connection must not double the user's day."""
    token, _ = account
    events = [{"type": "add", "id": "c" * 36, "drink_id": "water_250", "quantity": 1}]

    first = sync(client, token, events)
    second = sync(client, token, events)
    assert first["day_totals"] == second["day_totals"] == {"water_250": 1.0}


def test_removal_before_its_add_still_wins(
    client: TestClient, account: tuple[str, str]
) -> None:
    """The out-of-order case an offline widget genuinely produces."""
    token, _ = account
    entry_id = "d" * 36
    sync(client, token, [{"type": "remove", "id": entry_id}])
    body = sync(
        client, token, [{"type": "add", "id": entry_id, "drink_id": "water_250", "quantity": 1}]
    )
    assert body["day_totals"] == {}


def test_sync_rejects_an_oversized_batch(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    events = [
        {"type": "add", "id": f"{i:036d}", "drink_id": "water_250", "quantity": 1}
        for i in range(600)
    ]
    response = client.post("/api/sync", headers=hdr(token), json={"events": events})
    assert response.status_code == 422


def test_sync_rejects_a_nonpositive_quantity(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    response = client.post(
        "/api/sync",
        headers=hdr(token),
        json={"events": [{"type": "add", "id": "e" * 36, "drink_id": "water_250", "quantity": 0}]},
    )
    assert response.status_code == 422


# --- the alcohol gate ------------------------------------------------------


def test_alcohol_is_refused_until_the_age_check(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    response = client.post(
        "/api/entries", headers=hdr(token), json={"drink_id": "beer_330", "quantity": 1}
    )
    assert response.status_code == 403


def test_alcohol_is_allowed_after_passing(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    check = client.post(
        "/api/profile/age-check", headers=hdr(token), json={"country": "TH", "age": 25}
    ).json()
    assert check["alcohol_unlocked"] is True
    assert check["threshold"] == 20

    response = client.post(
        "/api/entries", headers=hdr(token), json={"drink_id": "beer_330", "quantity": 1}
    )
    assert response.status_code == 201


def test_under_age_stays_locked(client: TestClient, account: tuple[str, str]) -> None:
    """Thailand is 20, so 19 does not pass there."""
    token, _ = account
    check = client.post(
        "/api/profile/age-check", headers=hdr(token), json={"country": "TH", "age": 19}
    ).json()
    assert check["alcohol_unlocked"] is False

    assert client.post(
        "/api/entries", headers=hdr(token), json={"drink_id": "beer_330", "quantity": 1}
    ).status_code == 403


def test_the_threshold_follows_the_country(
    client: TestClient, account: tuple[str, str]
) -> None:
    """18 in Germany, not in the US."""
    token, _ = account
    de = client.post(
        "/api/profile/age-check", headers=hdr(token), json={"country": "DE", "age": 18}
    ).json()
    us = client.post(
        "/api/profile/age-check", headers=hdr(token), json={"country": "US", "age": 18}
    ).json()
    assert de["alcohol_unlocked"] is True
    assert us["alcohol_unlocked"] is False


def test_the_age_check_never_claims_verification(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    body = client.post(
        "/api/profile/age-check", headers=hdr(token), json={"country": "TH", "age": 30}
    ).json()
    assert body["verified"] is False


def test_no_date_of_birth_is_ever_stored(
    client: TestClient, db_path: str, account: tuple[str, str]
) -> None:
    """CLAUDE.md rule 3 — once the check passes, the age has no reason to exist."""
    token, _ = account
    client.post(
        "/api/profile/age-check", headers=hdr(token), json={"country": "TH", "age": 37}
    )

    conn = db.connect(db_path)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(user_age_gate)")]
    assert "dob" not in columns and "birth_date" not in columns and "age" not in columns

    row = conn.execute("SELECT * FROM user_age_gate").fetchone()
    assert 37 not in tuple(row), "the stated age was persisted"


def test_alcohol_in_a_sync_batch_is_refused_per_entry(
    client: TestClient, account: tuple[str, str]
) -> None:
    """One locked drink must not block a whole day's sync."""
    token, _ = account
    body = sync(
        client,
        token,
        [
            {"type": "add", "id": "f" * 36, "drink_id": "water_250", "quantity": 1},
            {"type": "add", "id": "g" * 36, "drink_id": "beer_330", "quantity": 1},
        ],
    )
    assert body["day_totals"] == {"water_250": 1.0}
    assert "g" * 36 in body["refused"]


# --- day, history, entries -------------------------------------------------


def test_today_reports_entries_and_totals(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    client.post("/api/entries", headers=hdr(token), json={"drink_id": "water_250"})
    body = client.get("/api/today", headers=hdr(token)).json()

    assert body["totals"] == {"water_250": 1.0}
    assert body["entries"][0]["name"] == "Water"
    assert body["categories"] == {"water": 1.0}


def test_an_entry_can_be_removed(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    entry_id = client.post(
        "/api/entries", headers=hdr(token), json={"drink_id": "water_250"}
    ).json()["id"]

    body = client.delete(f"/api/entries/{entry_id}", headers=hdr(token)).json()
    assert body["removed"] is True
    assert body["totals"] == {}


def test_removal_is_a_tombstone_not_a_delete(
    client: TestClient, db_path: str, account: tuple[str, str]
) -> None:
    token, _ = account
    entry_id = client.post(
        "/api/entries", headers=hdr(token), json={"drink_id": "water_250"}
    ).json()["id"]
    client.delete(f"/api/entries/{entry_id}", headers=hdr(token))

    conn = db.connect(db_path)
    row = conn.execute("SELECT deleted_at FROM logs WHERE id = ?", (entry_id,)).fetchone()
    assert row is not None and row["deleted_at"] is not None


def test_history_returns_the_requested_span(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    body = client.get("/api/history?days=5", headers=hdr(token)).json()
    assert len(body["days"]) == 5


def test_history_span_is_bounded(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    body = client.get("/api/history?days=99999", headers=hdr(token)).json()
    assert len(body["days"]) == 365


def test_an_entry_needs_a_drink(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    assert client.post("/api/entries", headers=hdr(token), json={}).status_code == 400


# --- catalog, settings, goals ---------------------------------------------


def test_catalog_is_served(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    drinks = client.get("/api/catalog", headers=hdr(token)).json()["drinks"]
    assert len(drinks) >= 40
    assert any(d["is_alcohol"] for d in drinks)


def test_settings_round_trip(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    client.put(
        "/api/settings",
        headers=hdr(token),
        json={"reminders_enabled": False, "undo_window_sec": 6},
    )
    body = client.get("/api/settings", headers=hdr(token)).json()
    assert body["reminders_enabled"] is False
    assert body["undo_window_sec"] == 6


def test_a_partial_settings_update_leaves_the_rest_alone(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    before = client.get("/api/settings", headers=hdr(token)).json()
    client.put("/api/settings", headers=hdr(token), json={"undo_window_sec": 8})
    after = client.get("/api/settings", headers=hdr(token)).json()

    assert after["undo_window_sec"] == 8
    assert after["interval_min"] == before["interval_min"]


def test_an_invalid_timezone_is_rejected(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    response = client.put(
        "/api/settings", headers=hdr(token), json={"timezone": "Mars/Olympus"}
    )
    assert response.status_code == 400


def test_goals_round_trip(client: TestClient, account: tuple[str, str]) -> None:
    token, _ = account
    client.put(
        "/api/goals",
        headers=hdr(token),
        json={"drink_category": "water", "kind": "goal", "target": 8},
    )
    client.put(
        "/api/goals",
        headers=hdr(token),
        json={"drink_category": "coffee", "kind": "limit", "target": 3},
    )
    goals = client.get("/api/goals", headers=hdr(token)).json()["goals"]
    assert {g["kind"] for g in goals} == {"goal", "limit"}


# --- weight ----------------------------------------------------------------


def test_weight_is_optional_and_absent_by_default(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    body = client.get("/api/settings", headers=hdr(token)).json()
    assert body["weight_kg"] is None
    assert body["water_target_ml"] is None


def test_weight_produces_a_target_labelled_as_not_advice(
    client: TestClient, account: tuple[str, str]
) -> None:
    token, _ = account
    body = client.put("/api/profile/weight", headers=hdr(token), json={"weight_kg": 70}).json()
    assert body["water_target_ml"] == round(70 * profile.ML_PER_KG)
    assert "not medical advice" in body["note"]


def test_absurd_weight_is_rejected(client: TestClient, account: tuple[str, str]) -> None:
    """70 pounds typed as kilograms would produce a nonsense target."""
    token, _ = account
    for value in (2, 500):
        response = client.put(
            "/api/profile/weight", headers=hdr(token), json={"weight_kg": value}
        )
        assert response.status_code == 400


def test_weight_deletion_is_immediate_and_total(
    client: TestClient, db_path: str, account: tuple[str, str]
) -> None:
    token, _ = account
    client.put("/api/profile/weight", headers=hdr(token), json={"weight_kg": 70})
    assert client.delete("/api/profile/weight", headers=hdr(token)).status_code == 204

    conn = db.connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM user_health").fetchone()["n"] == 0
    body = client.get("/api/settings", headers=hdr(token)).json()
    assert body["water_target_ml"] is None


# --- account deletion ------------------------------------------------------


def test_account_deletion_cascades(
    client: TestClient, db_path: str, account: tuple[str, str]
) -> None:
    """No harder to reach than signing up, and it really removes everything."""
    token, user_id = account
    client.post("/api/entries", headers=hdr(token), json={"drink_id": "water_250"})
    client.put("/api/profile/weight", headers=hdr(token), json={"weight_kg": 70})

    assert client.delete("/api/account", headers=hdr(token)).status_code == 204

    conn = db.connect(db_path)
    for table in ("logs", "user_health", "app_tokens", "platform_identities"):
        count = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        assert count == 0, f"{table} still has rows"
    assert client.get("/api/today", headers=hdr(token)).status_code == 401
