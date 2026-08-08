"""Opt-in body weight and the self-declared alcohol age gate.

Both are app-only, and both are the most sensitive things this product holds,
so the rules in ``CLAUDE.md`` §Data and privacy are enforced here rather than
left to callers:

* Weight is health data. Optional, deletable, and it never leaves the backend —
  only the derived hydration target does. It is never sent to a bot platform,
  never put in a Claude prompt, and never logged.
* The age gate stores that a check passed and which country's threshold was
  used. **It never stores a date of birth.** Once the check passes, the age
  itself has no reason to exist, and keeping it would turn a yes/no into a
  permanent record of how old somebody is.
* The check is self-declared and is never described as verified.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import day as day_util

# Legal drinking ages, ISO 3166-1 alpha-2. Not exhaustive by design -- it
# covers the markets this is built for and falls back to the most common
# threshold. Where a country distinguishes beer/wine from spirits, the higher
# age is used, because this gate is one boolean rather than per-drink.
LEGAL_DRINKING_AGE: dict[str, int] = {
    "TH": 20, "JP": 20, "KR": 19, "US": 21, "CA": 19, "IN": 21, "LK": 21,
    "ID": 21, "MY": 21, "SG": 18, "PH": 18, "VN": 18, "TW": 18, "CN": 18,
    "GB": 18, "IE": 18, "FR": 18, "DE": 18, "IT": 18, "ES": 18, "NL": 18,
    "SE": 18, "NO": 18, "PL": 18, "PT": 18, "AU": 18, "NZ": 18, "ZA": 18,
    "BR": 18, "MX": 18, "AR": 18, "AT": 18, "CH": 18, "BE": 18, "DK": 18,
}
DEFAULT_DRINKING_AGE = 18

# A plausible adult weight range. Outside it the user has mistyped a unit --
# 70 pounds entered as kilograms, say -- and a hydration target derived from
# that would be nonsense.
MIN_WEIGHT_KG = 25.0
MAX_WEIGHT_KG = 300.0

# Millilitres of water per kilogram per day. A widely cited rule of thumb, not
# a clinical figure, which is why the app labels it a starting point.
ML_PER_KG = 33.0


class ProfileError(ValueError):
    """A profile value the user needs to correct."""


@dataclass(frozen=True, slots=True)
class AgeGate:
    """Whether alcohol logging is unlocked, and under which country's rule."""

    alcohol_unlocked: bool
    country: str | None
    threshold: int | None


def legal_age(country: str) -> int:
    """Return the drinking age for a country code, or the common fallback."""
    return LEGAL_DRINKING_AGE.get((country or "").upper(), DEFAULT_DRINKING_AGE)


def set_weight(conn: sqlite3.Connection, user_id: str, weight_kg: float) -> None:
    """Record a user's weight. Opt-in, and range-checked."""
    if not MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG:
        raise ProfileError(
            f"weight must be between {MIN_WEIGHT_KG:g} and {MAX_WEIGHT_KG:g} kg"
        )
    conn.execute(
        "INSERT INTO user_health (user_id, weight_kg, weight_updated_at)"
        " VALUES (?, ?, ?)"
        " ON CONFLICT (user_id) DO UPDATE SET"
        "   weight_kg = excluded.weight_kg,"
        "   weight_updated_at = excluded.weight_updated_at",
        (user_id, float(weight_kg), day_util.to_iso(day_util.utc_now())),
    )


def get_weight(conn: sqlite3.Connection, user_id: str) -> float | None:
    """Return the user's weight, or None if they never gave one."""
    row = conn.execute(
        "SELECT weight_kg FROM user_health WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["weight_kg"] if row and row["weight_kg"] is not None else None


def delete_weight(conn: sqlite3.Connection, user_id: str) -> None:
    """Delete the user's weight. Immediate and total, not a soft flag."""
    conn.execute("DELETE FROM user_health WHERE user_id = ?", (user_id,))


def suggested_water_ml(conn: sqlite3.Connection, user_id: str) -> int | None:
    """Return a daily water target derived from weight, or None without one.

    A starting point, not medical advice — the app must present it that way.
    """
    weight = get_weight(conn, user_id)
    return round(weight * ML_PER_KG) if weight is not None else None


def get_age_gate(conn: sqlite3.Connection, user_id: str) -> AgeGate:
    """Return the user's alcohol gate state."""
    row = conn.execute(
        "SELECT alcohol_unlocked, country FROM user_age_gate WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return AgeGate(alcohol_unlocked=False, country=None, threshold=None)
    country = row["country"]
    return AgeGate(
        alcohol_unlocked=bool(row["alcohol_unlocked"]),
        country=country,
        threshold=legal_age(country) if country else None,
    )


def declare_age(
    conn: sqlite3.Connection, user_id: str, country: str, stated_age: int
) -> AgeGate:
    """Run the self-declared age check and record only its outcome.

    ``stated_age`` is used for the comparison and then discarded. It is never
    written anywhere, which is the whole point: the database learns whether the
    user may log alcohol, not how old they are.
    """
    if not country or len(country) != 2:
        raise ProfileError("country must be a two-letter code, e.g. TH")
    if not 0 < stated_age < 130:
        raise ProfileError("that age doesn't look right")

    threshold = legal_age(country)
    unlocked = stated_age >= threshold

    conn.execute(
        "INSERT INTO user_age_gate (user_id, alcohol_unlocked, country, checked_at)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT (user_id) DO UPDATE SET"
        "   alcohol_unlocked = excluded.alcohol_unlocked,"
        "   country = excluded.country, checked_at = excluded.checked_at",
        (
            user_id,
            int(unlocked),
            country.upper(),
            day_util.to_iso(day_util.utc_now()),
        ),
    )
    return AgeGate(alcohol_unlocked=unlocked, country=country.upper(), threshold=threshold)
