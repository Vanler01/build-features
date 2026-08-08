"""Convergence properties for the sync model.

The plan calls this the highest-risk component: three surfaces write to the same
day, and if the model is wrong the failure is silent -- drinks quietly double or
vanish, and nobody notices until a user complains about a number.

The property under test is that the log is a set of idempotent, commutative
events. Concretely:

  * applying the same event twice == applying it once
  * applying a set of events in any order gives the same totals
  * a removal wins regardless of when it arrives relative to its add
"""

from __future__ import annotations

import itertools
import sqlite3
from datetime import timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hydration.core import db, logs
from hydration.core.day import to_iso, utc_now
from hydration.core.models import LogEntry, LogSource

BANGKOK = "Asia/Bangkok"


def _fresh_db_with_user(user_id: str = "u1") -> sqlite3.Connection:
    conn = db.connect(":memory:")
    db.migrate(conn)
    conn.execute(
        "INSERT INTO users (id, timezone, created_at) VALUES (?, ?, ?)",
        (user_id, BANGKOK, to_iso(utc_now())),
    )
    return conn


def _entry(user_id: str, name: str, offset_min: int = 0) -> LogEntry:
    return LogEntry(
        user_id=user_id,
        logged_at=utc_now() - timedelta(minutes=offset_min),
        source=LogSource.WIDGET,
        custom_name=name,
    )


def test_duplicate_add_applied_exactly_once(conn: sqlite3.Connection, user: str) -> None:
    entry = _entry(user, "water")

    assert logs.upsert_entry(conn, entry) is True
    assert logs.upsert_entry(conn, entry) is False
    assert logs.upsert_entry(conn, entry) is False

    assert logs.day_totals(conn, user, BANGKOK) == {"water": 1.0}


def test_removal_is_idempotent(conn: sqlite3.Connection, user: str) -> None:
    entry = _entry(user, "water")
    logs.upsert_entry(conn, entry)

    assert logs.remove_entry(conn, entry.id, user) is True
    assert logs.remove_entry(conn, entry.id, user) is False

    assert logs.day_totals(conn, user, BANGKOK) == {}


def test_removal_arriving_before_its_add_still_wins(
    conn: sqlite3.Connection, user: str
) -> None:
    """The out-of-order case an offline widget actually produces.

    A user taps to add, taps again to undo, then the two events sync in the
    wrong order. Without an absorbing tombstone the drink would be resurrected.
    """
    entry = _entry(user, "water")

    logs.remove_entry(conn, entry.id, user)  # removal first
    logs.upsert_entry(conn, entry)  # add arrives late

    assert logs.day_totals(conn, user, BANGKOK) == {}


def test_tombstoned_entry_is_never_revived(conn: sqlite3.Connection, user: str) -> None:
    entry = _entry(user, "water")
    logs.upsert_entry(conn, entry)
    logs.remove_entry(conn, entry.id, user)

    for _ in range(5):
        logs.upsert_entry(conn, entry)

    assert logs.day_totals(conn, user, BANGKOK) == {}


def test_all_orderings_of_a_mixed_batch_converge() -> None:
    """Exhaustive permutation check over a realistic multi-source batch.

    Widget adds two waters offline, the app removes one of them, and the bot
    logs a coffee. Whatever order those reach the backend, the day must read
    one water and one coffee.
    """
    widget_a = _entry("u1", "water", offset_min=30)
    widget_b = _entry("u1", "water", offset_min=20)
    bot = _entry("u1", "coffee", offset_min=10)

    events = [
        ("add", widget_a),
        ("add", widget_b),
        ("add", bot),
        ("remove", (widget_b.id, "u1")),
    ]

    results = []
    for ordering in itertools.permutations(events):
        conn = _fresh_db_with_user()
        logs.apply_events(conn, list(ordering))
        results.append(logs.day_totals(conn, "u1", BANGKOK))
        conn.close()

    assert all(r == {"water": 1.0, "coffee": 1.0} for r in results), (
        f"orderings diverged: {[r for r in results if r != results[0]]}"
    )


@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    n_adds=st.integers(min_value=1, max_value=6),
    remove_indices=st.lists(st.integers(min_value=0, max_value=5), max_size=4),
    shuffle_seed=st.integers(min_value=0, max_value=10_000),
)
def test_replay_in_any_order_is_deterministic(
    n_adds: int, remove_indices: list[int], shuffle_seed: int
) -> None:
    """Generated batches must converge regardless of delivery order.

    Applies the same event set twice -- once in generation order, once shuffled
    and duplicated -- and requires identical totals.
    """
    import random

    entries = [_entry("u1", f"drink{i % 3}", offset_min=i) for i in range(n_adds)]
    to_remove = {i for i in remove_indices if i < n_adds}

    events: list[tuple[str, object]] = [("add", e) for e in entries]
    events += [("remove", (entries[i].id, "u1")) for i in to_remove]

    conn_a = _fresh_db_with_user()
    logs.apply_events(conn_a, events)
    totals_a = logs.day_totals(conn_a, "u1", BANGKOK)
    conn_a.close()

    shuffled = events + events  # duplicate delivery, then reorder
    random.Random(shuffle_seed).shuffle(shuffled)

    conn_b = _fresh_db_with_user()
    logs.apply_events(conn_b, shuffled)
    totals_b = logs.day_totals(conn_b, "u1", BANGKOK)
    conn_b.close()

    assert totals_a == totals_b


def test_quantity_must_be_positive() -> None:
    """Removals are tombstones, never negative quantities."""
    with pytest.raises(ValueError, match="quantity must be positive"):
        LogEntry(
            user_id="u1",
            logged_at=utc_now(),
            source=LogSource.WIDGET,
            custom_name="water",
            quantity=-1,
        )


def test_entry_requires_a_drink_reference() -> None:
    with pytest.raises(ValueError, match="drink_id or custom_name"):
        LogEntry(user_id="u1", logged_at=utc_now(), source=LogSource.WIDGET)


def test_naive_timestamps_are_rejected() -> None:
    """A naive datetime is the classic source of off-by-a-timezone bugs."""
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        LogEntry(
            user_id="u1",
            logged_at=datetime(2026, 8, 8, 12, 0),
            source=LogSource.WIDGET,
            custom_name="water",
        )
