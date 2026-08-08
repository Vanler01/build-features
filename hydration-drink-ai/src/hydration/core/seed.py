"""Loading the seed drink catalog into the database.

The catalog is a committed JSON file rather than a live API call: it is faster,
works offline, and cannot be rate-limited (REQUIREMENTS.md §8).

The loader's job is to refuse dishonest data. Every nutrition figure carries a
per-field ``source``, and a value present without one is rejected — that is the
check that stops a guessed number entering the catalog and being trusted
forever after by nutrition replies, goals and the app (CLAUDE.md rule 12).

Per-field provenance rather than per-entry, because a latte's calories and its
caffeine genuinely come from different places, and a single entry-level source
would be a lie about one of them.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SEED_PATH = Path(__file__).parent.parent.parent.parent / "data" / "drinks_seed.json"

NUTRITION_FIELDS = ("calories", "sugar_g", "caffeine_mg")
REQUIRED_FIELDS = ("id", "name", "category", "serving_size_ml", "is_alcohol", "source")

# A source of "missing" means nobody has sourced it yet, which is honest and
# allowed — as long as the value is null. Anything else must name where it came
# from. "claude" is never acceptable: that is a guess wearing a source's badge.
UNSOURCED = "missing"
FORBIDDEN_SOURCES = frozenset({"claude", "ai", "model", "guess", "estimate", ""})


class SeedError(ValueError):
    """The seed file is malformed or contains an unsourced value."""


@dataclass(frozen=True, slots=True)
class SeedReport:
    """What a load did, and what still needs sourcing."""

    loaded: int
    with_nutrition: int
    awaiting_sourcing: list[str]

    @property
    def complete(self) -> bool:
        """Whether every entry has its nutrition sourced."""
        return not self.awaiting_sourcing


def validate_entry(entry: dict[str, Any]) -> None:
    """Raise ``SeedError`` if an entry is malformed or dishonestly sourced."""
    missing = [f for f in REQUIRED_FIELDS if f not in entry]
    if missing:
        raise SeedError(f"{entry.get('id', '<no id>')}: missing {missing}")

    source = entry["source"]
    if not isinstance(source, dict):
        raise SeedError(f"{entry['id']}: source must be an object keyed by field")

    if not isinstance(entry["serving_size_ml"], int) or entry["serving_size_ml"] <= 0:
        raise SeedError(f"{entry['id']}: serving_size_ml must be a positive integer")

    for field in NUTRITION_FIELDS:
        value = entry.get(field)
        origin = source.get(field)

        if origin is None:
            raise SeedError(f"{entry['id']}: {field} has no source entry")
        if str(origin).lower() in FORBIDDEN_SOURCES:
            raise SeedError(
                f"{entry['id']}: {field} claims source {origin!r} — "
                "nutrition may not come from a model"
            )
        if value is None and origin != UNSOURCED:
            raise SeedError(f"{entry['id']}: {field} is null but claims source {origin!r}")
        if value is not None and origin == UNSOURCED:
            raise SeedError(
                f"{entry['id']}: {field} has a value but is marked {UNSOURCED!r} — "
                "an unsourced number is a guess"
            )
        if value is not None and (not isinstance(value, int | float) or value < 0):
            raise SeedError(f"{entry['id']}: {field} must be a non-negative number")


def load_seed_file(path: Path | str = DEFAULT_SEED_PATH) -> list[dict[str, Any]]:
    """Read and validate the seed file without touching the database."""
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, list):
        raise SeedError("seed file must contain a list of entries")

    seen: set[str] = set()
    for entry in raw:
        validate_entry(entry)
        if entry["id"] in seen:
            raise SeedError(f"duplicate id: {entry['id']}")
        seen.add(entry["id"])
    return raw


def load_into(
    conn: sqlite3.Connection, path: Path | str = DEFAULT_SEED_PATH
) -> SeedReport:
    """Load the seed catalog, replacing entries with the same id.

    Idempotent: running it again after a sourcing pass updates values in place
    rather than duplicating rows.
    """
    entries = load_seed_file(path)

    for entry in entries:
        conn.execute(
            "INSERT INTO drinks_catalog (id, name, category, subtype, serving_size_ml,"
            " calories, sugar_g, caffeine_mg, is_alcohol, source_json, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET"
            "   name = excluded.name, category = excluded.category,"
            "   subtype = excluded.subtype, serving_size_ml = excluded.serving_size_ml,"
            "   calories = excluded.calories, sugar_g = excluded.sugar_g,"
            "   caffeine_mg = excluded.caffeine_mg, is_alcohol = excluded.is_alcohol,"
            "   source_json = excluded.source_json, fetched_at = excluded.fetched_at",
            (
                entry["id"], entry["name"], entry["category"], entry.get("subtype"),
                entry["serving_size_ml"], entry.get("calories"), entry.get("sugar_g"),
                entry.get("caffeine_mg"), int(bool(entry["is_alcohol"])),
                json.dumps(entry["source"], sort_keys=True), entry.get("fetched_at"),
            ),
        )

    awaiting = sorted(
        e["id"] for e in entries if any(e.get(f) is None for f in NUTRITION_FIELDS)
    )
    return SeedReport(
        loaded=len(entries),
        with_nutrition=len(entries) - len(awaiting),
        awaiting_sourcing=awaiting,
    )
