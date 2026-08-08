"""Resolving a free-text drink name against the seed catalog.

The parser returns what the user said ("iced latte", "espresso tonic"); the
catalog holds curated entries with nutrition. This module is the join between
them, and the place where the alcohol gate lives.

The gate **fails closed**. ``CLAUDE.md`` rule 5 makes alcohol app-only because a
bot has no way to check anyone's age, so an unrecognised drink that is obviously
alcoholic must not slip through simply because nobody has added it to the
catalog yet.
"""

from __future__ import annotations

import re
import sqlite3

# Conservative backstop for names the catalog doesn't know. Deliberately not
# exhaustive -- it only has to catch the common cases that would otherwise be
# logged from a bot. Anything genuinely ambiguous is better handled by adding a
# catalog entry than by growing this list.
_ALCOHOL_WORDS = frozenset(
    {
        "beer", "lager", "ale", "stout", "ipa", "pilsner", "cider",
        "wine", "red wine", "white wine", "rose", "prosecco", "champagne",
        "sake", "soju", "makgeolli", "mead",
        "whisky", "whiskey", "bourbon", "scotch", "vodka", "gin", "rum",
        "tequila", "mezcal", "brandy", "cognac", "absinthe", "schnapps",
        "cocktail", "martini", "mojito", "margarita", "negroni", "highball",
        "sangria", "spritz", "shandy", "liqueur", "shot", "shots",
    }
)

# Soft drinks whose names contain an alcohol word. Without these, "ginger ale"
# and "root beer" -- both non-alcoholic and both common -- get refused on a
# bot, which reads as the tool being broken.
_NON_ALCOHOLIC_PHRASES = frozenset(
    {
        "ginger ale", "ginger beer", "root beer", "birch beer",
        "sarsaparilla", "malta", "kvass",
    }
)

# Markers that negate an alcohol word anywhere in the name: "non-alcoholic
# beer", "virgin mojito", "0.0 lager" (punctuation is stripped first, so 0.0
# normalises to "0 0").
_ALCOHOL_FREE_MARKERS = (
    "non alcoholic", "nonalcoholic", "alcohol free", "alcoholfree",
    "no alcohol", "zero alcohol", "virgin", "mocktail", "0 0",
)

_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def normalise(name: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace.

    "Iced Latte!" and "iced  latte" must resolve to the same catalog row.
    """
    lowered = _NON_WORD.sub(" ", name.strip().lower())
    return " ".join(lowered.split())


def resolve(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """Return the catalog row for a drink name, or None for a custom drink."""
    target = normalise(name)
    if not target:
        return None
    for row in conn.execute("SELECT * FROM drinks_catalog"):
        if normalise(row["name"]) == target:
            return row
    return None


def is_alcohol(conn: sqlite3.Connection, name: str) -> bool:
    """Whether a drink name should be treated as alcoholic.

    Catalog first, keyword backstop second. Returns True when unsure about an
    obviously alcoholic word, because the cost of a false positive (the user is
    told to log it in the app) is far lower than the cost of a false negative.
    """
    row = resolve(conn, name)
    if row is not None:
        return bool(row["is_alcohol"])

    normalised = normalise(name)

    # An explicit alcohol-free marker beats any keyword in the same name.
    if any(marker in normalised for marker in _ALCOHOL_FREE_MARKERS):
        return False

    # Soft drinks that happen to contain an alcohol word.
    if any(phrase in normalised for phrase in _NON_ALCOHOLIC_PHRASES):
        return False

    return bool(set(normalised.split()) & _ALCOHOL_WORDS)


def display_name(conn: sqlite3.Connection, key: str) -> str:
    """Human-readable name for a ``day_totals`` key (catalog id or custom name)."""
    row = conn.execute(
        "SELECT name FROM drinks_catalog WHERE id = ?", (key,)
    ).fetchone()
    return row["name"] if row else key


def nutrition_note(conn: sqlite3.Connection, name: str, quantity: float) -> str | None:
    """Return a short nutrition aside for a logged drink, or None when unknown.

    Returns None rather than a guess when the catalog has no entry or the
    fields are null -- an invented calorie count is worse than silence.
    """
    row = resolve(conn, name)
    if row is None:
        return None

    parts: list[str] = []
    if row["calories"] is not None:
        parts.append(f"{row['calories'] * quantity:g} cal")
    if row["caffeine_mg"]:
        parts.append(f"{row['caffeine_mg'] * quantity:g}mg caffeine")
    if not parts:
        return None
    return " · ".join(parts)
