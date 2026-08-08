"""Fill in the seed catalog's missing nutrition from Open Food Facts and USDA.

This is the tool ``hydration-drink-sourcer`` drives. Run it when you have
network access, and optionally an ``FDC_API_KEY``:

    python3 tools/source_catalog.py --dry-run          # show what it would fetch
    python3 tools/source_catalog.py --only coffee      # one category
    python3 tools/source_catalog.py                    # write data/drinks_seed.json

It only ever fills fields whose source is ``missing``. Existing sourced values
are left alone, so a re-run is safe and never silently rewrites a figure
somebody checked by hand.

**It does not invent anything.** A field it cannot source stays null, and the
report lists it. That list is the handoff to manual work, so it is printed in
full rather than tidied — see the sourcer agent's brief.

Caffeine is deliberately not fetched. USDA does not tag it consistently and
Open Food Facts rarely carries it for unpackaged drinks, so a fetched caffeine
figure would mostly be absent and occasionally wrong. It stays a hand-maintained
column, cross-checked against published references.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).parent.parent
SEED_PATH = ROOT / "data" / "drinks_seed.json"

OFF_SEARCH = "https://world.openfoodfacts.org/api/v2/search"
FDC_SEARCH = "https://api.nal.usda.gov/fdc/v1/foods/search"

# Open Food Facts asks for an identifying User-Agent; sending a browser string
# would be both dishonest and against the spirit of their terms.
USER_AGENT = "hydration-drink-ai/0.1 (catalog sourcing; contact via repo)"

REQUEST_DELAY_SEC = 1.0
TIMEOUT_SEC = 15.0

# Packaged categories Open Food Facts covers well; the rest are generic drinks
# better served by USDA.
OFF_CATEGORIES = {"soda", "juice", "energy", "sports", "milk", "beer", "wine"}

# Plausible calories per 100ml, by category. A fetch outside these bounds is a
# wrong-food match rather than a surprising drink -- the first version of this
# tool happily recorded a 3465-calorie iced latte because it matched a powder
# and scaled it. Nothing is written without passing this gate.
CALORIES_PER_100ML: dict[str, tuple[float, float]] = {
    "water": (0, 2),
    "coffee": (0, 90),      # black ~1, a milky latte ~55
    "tea": (0, 90),
    "matcha": (0, 90),
    "soda": (0, 55),
    "juice": (0, 75),
    "milk": (0, 95),
    "energy": (0, 60),
    "sports": (0, 40),
    "beer": (20, 75),
    "wine": (55, 120),
    "spirits": (150, 300),  # 40% ABV is about 231
}

# USDA's beverage rows are prefixed like this. Anything else -- crackers,
# desserts, baby food -- is a different food that merely mentions the drink.
USDA_BEVERAGE_PREFIXES = ("beverages,", "alcoholic beverage")

# Forms that are not the ready-to-drink product, and whose per-100g figures are
# therefore wildly higher than the drink's.
REJECT_WORDS = frozenset(
    {
        "powder", "powdered", "dry", "dried", "concentrate", "condensed",
        "babyfood", "baby", "cracker", "dessert", "supplement", "mix",
        "syrup", "pudding", "candy", "bar", "cereal", "evaporated", "topping",
    }
)

# Words that narrow a product to a specific variant. If a description carries
# one and our drink name does not, it is a different drink -- see
# _describes_the_drink for why that matters more than it sounds.
QUALIFIER_WORDS = frozenset(
    {
        "light", "lite", "diet", "low calorie", "reduced", "nonfat", "skim",
        "fat free", "decaffeinated", "decaf", "sweetened", "unsweetened",
        "chicory", "fortified", "flavored", "substitute", "imitation",
    }
)


def _kcal(nutrients: list[dict[str, Any]]) -> float | None:
    """Pull the kilocalorie Energy value, never the kilojoule one.

    USDA returns Energy twice, once per unit. Reading them into a dict lets the
    last one win at random, which is where the roughly 4x inflation came from.
    """
    for nutrient in nutrients:
        if nutrient.get("nutrientName") == "Energy" and nutrient.get("unitName") == "KCAL":
            value = nutrient.get("value")
            if isinstance(value, int | float):
                return float(value)
    return None


def _plausible(entry: dict[str, Any], calories_per_serving: float) -> bool:
    """Whether a fetched calorie figure is credible for this category."""
    bounds = CALORIES_PER_100ML.get(entry["category"])
    if bounds is None:
        return True
    per_100 = calories_per_serving / (entry["serving_size_ml"] / 100.0)
    low, high = bounds
    return low <= per_100 <= high


# The word a description must contain to be the right *kind* of drink. Without
# this, "Cold brew" matched "Beverages, tea, hibiscus, brewed" -- a plausible
# calorie count for entirely the wrong drink.
CATEGORY_WORD = {
    "coffee": "coffee",
    "tea": "tea",
    "matcha": "tea",
    "soda": "carbonated",
    "juice": "juice",
    "milk": "milk",
    "beer": "beer",
    "wine": "wine",
}


def _describes_the_drink(description: str, entry: dict[str, Any]) -> bool:
    """Whether a USDA row is plausibly the drink we asked about.

    Requires *every* distinctive word from the drink's name, not merely one.
    One-word matching let "Diet cola" take regular cola's figures and "Decaf
    coffee" take instant chicory's -- both plausible numbers for the wrong
    drink, which is worse than no number at all.
    """
    lowered = description.lower()
    if not lowered.startswith(USDA_BEVERAGE_PREFIXES):
        return False
    if any(word in lowered for word in REJECT_WORDS):
        return False

    # Alcohol lives under its own USDA prefix. Without this, "Beer" matched
    # "Beverages, carbonated, root beer" -- soda figures filed against an
    # alcoholic drink, and plausible enough to pass every other check.
    if bool(entry["is_alcohol"]) != lowered.startswith("alcoholic beverage"):
        return False

    required = CATEGORY_WORD.get(entry["category"])
    if required and required not in lowered:
        return False

    # A qualifier the description has and our drink name doesn't means it is a
    # narrower product: "Beer" matching "beer, light" recorded 29 kcal/100ml
    # for a drink that is really about 43. That passed the plausibility gate,
    # because light beer is a perfectly plausible beer -- just not this one.
    name = entry["name"].lower()
    if any(q in lowered and q not in name for q in QUALIFIER_WORDS):
        return False

    tokens = {t for t in name.split() if len(t) > 3}
    return all(token in lowered for token in tokens)


def _get(client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """GET with a polite delay, returning None rather than raising."""
    time.sleep(REQUEST_DELAY_SEC)
    try:
        response = client.get(url, params=params, timeout=TIMEOUT_SEC)
        if response.status_code != 200:
            print(f"    HTTP {response.status_code}", file=sys.stderr)
            return None
        return response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"    {type(exc).__name__}", file=sys.stderr)
        return None


def from_open_food_facts(client: httpx.Client, entry: dict[str, Any]) -> dict[str, Any]:
    """Look up calories and sugar per serving from Open Food Facts."""
    # Searching by category alone returned whatever product happened to be
    # first, which is how Ginger ale and Root beer both ended up with
    # Coca-Cola's barcode. The product name has to be part of the query.
    body = _get(
        client,
        OFF_SEARCH,
        {
            "search_terms": entry["name"],
            "categories_tags_en": entry["category"],
            "fields": "product_name,nutriments,code",
            "page_size": 5,
        },
    )
    if not body:
        return {}

    distinctive = {t for t in entry["name"].lower().split() if len(t) > 3}

    entry_name = entry["name"].lower()
    for product in body.get("products", []):
        name = (product.get("product_name") or "").lower()
        if not all(token in name for token in distinctive):
            continue
        # Same qualifier rule as the USDA path: a sugar-free energy drink is
        # not the energy drink we asked for, and 4 kcal/100ml against a real
        # 45 is exactly the kind of plausible wrongness the range gate misses.
        if any(q in name and q not in entry_name for q in QUALIFIER_WORDS):
            continue

        nutriments = product.get("nutriments") or {}
        kcal_100 = nutriments.get("energy-kcal_100g")
        sugar_100 = nutriments.get("sugars_100g")
        if not isinstance(kcal_100, int | float):
            continue

        # OFF reports per 100ml; the catalog stores per serving.
        scale = entry["serving_size_ml"] / 100.0
        calories = round(kcal_100 * scale, 1)
        if not _plausible(entry, calories):
            print(f"    rejected {calories} cal — outside the range for {entry['category']}")
            continue

        found: dict[str, Any] = {
            "calories": calories,
            "_source_calories": f"open_food_facts:{product.get('code')}",
        }
        if isinstance(sugar_100, int | float):
            found["sugar_g"] = round(sugar_100 * scale, 1)
            found["_source_sugar_g"] = f"open_food_facts:{product.get('code')}"
        return found
    return {}


def from_usda(client: httpx.Client, entry: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Look up calories and sugar from USDA FoodData Central."""
    body = _get(
        client,
        FDC_SEARCH,
        {
            "query": entry["name"],
            "dataType": "SR Legacy,Foundation",
            "pageSize": 3,
            "api_key": api_key,
        },
    )
    if not body:
        return {}

    for food in body.get("foods", []):
        description = food.get("description", "")
        if not _describes_the_drink(description, entry):
            continue

        nutrients = food.get("foodNutrients", [])
        kcal_100 = _kcal(nutrients)
        if kcal_100 is None:
            continue

        scale = entry["serving_size_ml"] / 100.0
        calories = round(kcal_100 * scale, 1)
        if not _plausible(entry, calories):
            print(f"    rejected {calories} cal from {description[:40]!r}")
            continue

        fdc_id = food.get("fdcId")
        found: dict[str, Any] = {
            "calories": calories,
            "_source_calories": f"usda:fdcId={fdc_id}",
            "_matched": description,
        }
        sugar = next(
            (
                n.get("value")
                for n in nutrients
                if n.get("nutrientName") == "Sugars, total including NLEA"
            ),
            None,
        )
        if isinstance(sugar, int | float):
            found["sugar_g"] = round(sugar * scale, 1)
            found["_source_sugar_g"] = f"usda:fdcId={fdc_id}"
        return found
    return {}


def source_entry(client: httpx.Client, entry: dict[str, Any], fdc_key: str) -> bool:
    """Fill an entry's missing fields in place. Returns whether anything changed."""
    needs = [f for f in ("calories", "sugar_g") if entry["source"].get(f) == "missing"]
    if not needs:
        return False

    print(f"  {entry['name']} ({entry['category']}) — needs {', '.join(needs)}")
    found = (
        from_open_food_facts(client, entry)
        if entry["category"] in OFF_CATEGORIES
        else (from_usda(client, entry, fdc_key) if fdc_key else {})
    )
    if not found and fdc_key and entry["category"] in OFF_CATEGORIES:
        found = from_usda(client, entry, fdc_key)

    if found.get("_matched"):
        print(f"    matched {found['_matched'][:60]!r}")

    changed = False
    for field in needs:
        if field in found:
            entry[field] = found[field]
            entry["source"][field] = found[f"_source_{field}"]
            entry["fetched_at"] = time.strftime("%Y-%m-%d")
            print(f"    {field} = {found[field]}  ({entry['source'][field]})")
            changed = True
    if not changed:
        print("    nothing found — leaving null")
    return changed


def main() -> int:
    """Run the sourcing pass."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="fetch nothing; list gaps")
    parser.add_argument("--only", help="limit to one category")
    args = parser.parse_args()

    entries = json.loads(SEED_PATH.read_text())
    if args.only:
        targets = [e for e in entries if e["category"] == args.only]
    else:
        targets = entries

    gaps = [
        e for e in targets
        if any(e["source"].get(f) == "missing" for f in ("calories", "sugar_g", "caffeine_mg"))
    ]
    print(f"{len(entries)} entries, {len(gaps)} with unsourced fields\n")

    if args.dry_run:
        for entry in gaps:
            missing = [
                f for f in ("calories", "sugar_g", "caffeine_mg")
                if entry["source"].get(f) == "missing"
            ]
            print(f"  {entry['id']:<24} {', '.join(missing)}")
        return 0

    fdc_key = os.environ.get("FDC_API_KEY", "")
    if not fdc_key:
        print("FDC_API_KEY not set — generic drinks will be skipped.")
        print("Get a free key at https://fdc.nal.usda.gov/api-key-signup.html\n")

    changed = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for entry in gaps:
            if source_entry(client, entry, fdc_key):
                changed += 1

    if changed:
        SEED_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
        print(f"\nUpdated {changed} entries in {SEED_PATH}")
    else:
        print("\nNothing sourced; file unchanged.")

    still_missing = [
        f"{e['id']}.{f}"
        for e in entries
        for f in ("calories", "sugar_g", "caffeine_mg")
        if e["source"].get(f) == "missing"
    ]
    print(f"\nStill unsourced ({len(still_missing)}) — this list is the handoff:")
    for item in still_missing:
        print(f"  {item}")
    print("\nRun hydration-drink-data-validator before shipping any of this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
