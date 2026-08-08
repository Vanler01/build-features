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
    body = _get(
        client,
        OFF_SEARCH,
        {
            "categories_tags_en": entry["category"],
            "fields": "product_name,nutriments,code",
            "page_size": 5,
        },
    )
    if not body:
        return {}

    for product in body.get("products", []):
        nutriments = product.get("nutriments") or {}
        kcal_100 = nutriments.get("energy-kcal_100g")
        sugar_100 = nutriments.get("sugars_100g")
        if kcal_100 is None:
            continue
        # OFF reports per 100ml; the catalog stores per serving.
        scale = entry["serving_size_ml"] / 100.0
        found: dict[str, Any] = {
            "calories": round(kcal_100 * scale, 1),
            "_source_calories": f"open_food_facts:{product.get('code')}",
        }
        if sugar_100 is not None:
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
        by_name = {n.get("nutrientName"): n.get("value") for n in food.get("foodNutrients", [])}
        kcal_100 = by_name.get("Energy")
        if kcal_100 is None:
            continue
        scale = entry["serving_size_ml"] / 100.0
        fdc_id = food.get("fdcId")
        found: dict[str, Any] = {
            "calories": round(kcal_100 * scale, 1),
            "_source_calories": f"usda:fdcId={fdc_id}",
        }
        sugar = by_name.get("Sugars, total including NLEA")
        if sugar is not None:
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
