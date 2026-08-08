"""Tests for the catalog sourcing matcher.

Every case here is a real wrong match the tool made against the live APIs
before it was fixed. They are worth pinning because each one produced a
*plausible* number for the wrong drink — the failure mode that gets past a
range check and into the catalog, where nothing downstream can tell it from a
real figure.

The network functions aren't exercised; the matching predicates are, which is
where all the bugs were.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_PATH = Path(__file__).parent.parent / "tools" / "source_catalog.py"
_spec = importlib.util.spec_from_file_location("source_catalog", _PATH)
assert _spec is not None and _spec.loader is not None
sourcing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sourcing)


def drink(
    name: str, category: str, ml: int = 240, *, alcohol: bool = False
) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "serving_size_ml": ml,
        "is_alcohol": alcohol,
    }


# --- kcal vs kJ ------------------------------------------------------------


def test_kcal_is_selected_not_kilojoules() -> None:
    """USDA returns Energy twice. Reading it into a dict let kJ win at random,
    which is where the roughly 4x inflated calorie counts came from."""
    nutrients = [
        {"nutrientName": "Energy", "unitName": "kJ", "value": 1860.0},
        {"nutrientName": "Energy", "unitName": "KCAL", "value": 446.0},
    ]
    assert sourcing._kcal(nutrients) == 446.0


def test_kcal_is_found_regardless_of_order() -> None:
    nutrients = [
        {"nutrientName": "Energy", "unitName": "KCAL", "value": 167.0},
        {"nutrientName": "Energy", "unitName": "kJ", "value": 699.0},
    ]
    assert sourcing._kcal(nutrients) == 167.0


def test_missing_kcal_returns_none_rather_than_a_kilojoule_figure() -> None:
    assert sourcing._kcal([{"nutrientName": "Energy", "unitName": "kJ", "value": 699.0}]) is None
    assert sourcing._kcal([]) is None


# --- plausibility gate -----------------------------------------------------


def test_absurd_latte_is_rejected() -> None:
    """The original run recorded a 3465-calorie iced latte from a powder."""
    assert not sourcing._plausible(drink("Iced latte", "coffee", 350), 3465.0)


def test_real_latte_is_accepted() -> None:
    assert sourcing._plausible(drink("Iced latte", "coffee", 350), 180.0)


@pytest.mark.parametrize(
    ("name", "category", "ml", "calories"),
    [
        ("Milk", "milk", 250, 1115.0),
        ("Orange juice", "juice", 250, 465.0),
        ("Decaf coffee", "coffee", 240, 621.6),
        ("Sake", "spirits", 180, 1009.8),
        ("Sports drink", "sports", 500, 690.0),
    ],
)
def test_original_garbage_values_are_all_rejected(
    name: str, category: str, ml: int, calories: float
) -> None:
    assert not sourcing._plausible(drink(name, category, ml), calories)


def test_spirits_are_allowed_to_be_calorie_dense() -> None:
    """The gate must not simply reject anything large — vodka really is ~231."""
    assert sourcing._plausible(drink("Vodka", "spirits", 44, alcohol=True), 101.6)


def test_unknown_category_is_not_gated() -> None:
    assert sourcing._plausible(drink("Something", "unmapped", 100), 5000.0)


# --- description matching --------------------------------------------------


def test_non_beverage_rows_are_rejected() -> None:
    """"Milk" matched "Crackers, milk"; "Orange juice" matched baby food."""
    assert not sourcing._describes_the_drink("Crackers, milk", drink("Milk", "milk"))
    assert not sourcing._describes_the_drink(
        "Babyfood, juice, orange", drink("Orange juice", "juice")
    )


def test_powders_and_concentrates_are_rejected() -> None:
    assert not sourcing._describes_the_drink(
        "Beverages, milk, dry, whole", drink("Milk", "milk")
    )
    assert not sourcing._describes_the_drink(
        "Beverages, orange juice, frozen concentrate", drink("Orange juice", "juice")
    )


def test_wrong_drink_kind_is_rejected() -> None:
    """Cold brew matched "Beverages, tea, hibiscus, brewed" — a coffee taking
    a tea's figures, with an entirely believable calorie count."""
    assert not sourcing._describes_the_drink(
        "Beverages, tea, hibiscus, brewed", drink("Cold brew", "coffee")
    )


def test_all_distinctive_words_are_required_not_just_one() -> None:
    """One-word matching let Diet cola take regular cola's 122 calories."""
    assert not sourcing._describes_the_drink(
        "Beverages, carbonated, cola, fast-food cola", drink("Diet cola", "soda")
    )
    assert not sourcing._describes_the_drink(
        "Beverages, coffee, instant, chicory", drink("Decaf coffee", "coffee")
    )


def test_extra_qualifiers_are_rejected() -> None:
    """"Beer" matched "beer, light" — 29 kcal/100ml for a drink that is ~43,
    and light beer is a perfectly plausible beer, so nothing else caught it."""
    assert not sourcing._describes_the_drink(
        "Alcoholic beverage, beer, light", drink("Beer", "beer", 330, alcohol=True)
    )


def test_a_qualifier_we_asked_for_is_allowed() -> None:
    assert sourcing._describes_the_drink(
        "Alcoholic beverage, beer, light", drink("Light beer", "beer", 330, alcohol=True)
    )


def test_alcohol_and_soft_drinks_do_not_cross_match() -> None:
    """"Beer" matched "Beverages, carbonated, root beer" — soda figures filed
    against an alcoholic drink."""
    assert not sourcing._describes_the_drink(
        "Beverages, carbonated, root beer", drink("Beer", "beer", 330, alcohol=True)
    )
    assert not sourcing._describes_the_drink(
        "Alcoholic beverage, beer, regular", drink("Root beer", "soda", 330)
    )


def test_genuine_matches_still_pass() -> None:
    """The filters must not reject everything — these are the real ones."""
    for description, entry in [
        ("Beverages, coffee, brewed, espresso, restaurant-prepared",
         drink("Espresso", "coffee", 30)),
        ("Beverages, tea, black, ready to drink", drink("Black tea", "tea")),
        ("Beverages, carbonated, ginger ale", drink("Ginger ale", "soda", 330)),
        ("Alcoholic beverage, distilled, vodka, 80 proof",
         drink("Vodka", "spirits", 44, alcohol=True)),
    ]:
        assert sourcing._describes_the_drink(description, entry), description
