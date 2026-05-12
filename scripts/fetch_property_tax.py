"""Fetch median real-estate-tax-paid by county from the Census ACS 5-year
API for 2023 and 2024, compute YoY % change, and cache to disk.

Source: ACS 5-year, table B25103 (Median Real Estate Taxes Paid),
variable B25103_001E. Values are county medians of annual real-estate
tax bills for owner-occupied housing units, in dollars.

ACS 5-year endpoints overlap by 4 years, so 2023 vs 2024 is effectively
a 1-year shift in the rolling window — close enough to call YoY for an
overlay. Margins of error are non-trivial in small counties; we drop
rows where either year is missing.

Output: data/cache/property_tax_yoy.csv with columns
  fips, name, tax_2023, tax_2024, growth_pct
"""

from __future__ import annotations

import csv
import json
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE = REPO_ROOT / "data" / "cache" / "property_tax_yoy.csv"

API = "https://api.census.gov/data/{year}/acs/acs5?get=NAME,B25103_001E&for=county:*"


def fetch_year(year: int) -> dict[str, tuple[str, int]]:
    """Returns fips -> (county_name, median_tax_dollars)."""
    with urllib.request.urlopen(API.format(year=year), timeout=60) as resp:
        rows = json.load(resp)
    header, *data = rows
    name_i = header.index("NAME")
    val_i = header.index("B25103_001E")
    state_i = header.index("state")
    county_i = header.index("county")
    out: dict[str, tuple[str, int]] = {}
    for r in data:
        try:
            val = int(r[val_i])
        except (TypeError, ValueError):
            continue
        if val <= 0:
            continue  # Census null sentinel; skip
        fips = f"{r[state_i]}{r[county_i]}"
        out[fips] = (r[name_i], val)
    return out


def main() -> None:
    print("Fetching ACS 5-year 2023 ...")
    y23 = fetch_year(2023)
    print(f"  {len(y23)} counties")
    print("Fetching ACS 5-year 2024 ...")
    y24 = fetch_year(2024)
    print(f"  {len(y24)} counties")

    joined = []
    for fips in sorted(set(y23) & set(y24)):
        name, t23 = y23[fips]
        _, t24 = y24[fips]
        growth_pct = (t24 - t23) / t23 * 100.0
        joined.append((fips, name, t23, t24, growth_pct))

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fips", "name", "tax_2023", "tax_2024", "growth_pct"])
        w.writerows(joined)
    print(f"Wrote {len(joined)} rows -> {CACHE}")


if __name__ == "__main__":
    main()
