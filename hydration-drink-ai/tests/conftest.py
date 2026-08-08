"""Shared fixtures. No test in this suite may touch a network or a real API."""

from __future__ import annotations

import sqlite3

import pytest

from hydration.core import db
from hydration.core.day import to_iso, utc_now


@pytest.fixture
def conn() -> sqlite3.Connection:
    """An in-memory database with the schema applied."""
    connection = db.connect(":memory:")
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def user(conn: sqlite3.Connection) -> str:
    """A user in Asia/Bangkok (UTC+7) -- deliberately not the server's zone."""
    user_id = "user-under-test"
    conn.execute(
        "INSERT INTO users (id, timezone, bedtime, created_at) VALUES (?, ?, ?, ?)",
        (user_id, "Asia/Bangkok", "23:00", to_iso(utc_now())),
    )
    return user_id


@pytest.fixture
def catalog(conn: sqlite3.Connection) -> None:
    """A minimal catalog covering a goal drink, a limiter drink, and alcohol."""
    rows = [
        ("water_250", "Water", "water", 250, 0.0, 0.0, 0.0, 0),
        ("coffee_240", "Brewed coffee", "coffee", 240, 3.0, 0.0, 95.0, 0),
        ("beer_330", "Beer", "beer", 330, 145.0, 0.0, 0.0, 1),
    ]
    conn.executemany(
        "INSERT INTO drinks_catalog (id, name, category, serving_size_ml, calories,"
        " sugar_g, caffeine_mg, is_alcohol, source_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')",
        rows,
    )
