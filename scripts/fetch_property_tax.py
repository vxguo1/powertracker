"""Fetch median real-estate-tax-paid by county from the Census ACS 5-year
API for the latest year plus the prior 3 years, then compute % change vs
the 3-year baseline mean.

Source: ACS 5-year, table B25103 (Median Real Estate Taxes Paid),
variable B25103_001E. Values are county medians of annual real-estate
tax bills for owner-occupied housing units, in dollars.

ACS 5-year endpoints overlap by 4 years, so consecutive years share most
of their underlying sample. A 3-year baseline averages three near-
identical numbers — the resulting "growth" is therefore mostly the
shift of the newest ACS year against itself one year prior, attenuated.
We apply the same recipe as the other YoY layers for consistency; treat
this layer's magnitudes as suggestive only.

Output: data/cache/property_tax_yoy.csv with columns
  fips, name, tax_baseline, tax_current, growth_pct,
  baseline_start_year, baseline_end_year, current_year
"""

from __future__ import annotations

import csv
import json
import os
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE = REPO_ROOT / "data" / "cache" / "property_tax_yoy.csv"

# Census tightened policy: the data API now requires a key on every
# request (used to be optional). Free registration:
#   https://api.census.gov/data/key_signup.html
API = "https://api.census.gov/data/{year}/acs/acs5?get=NAME,B25103_001E&for=county:*"

CURRENT_YEAR = 2024
BASELINE_YEARS = 3  # 2021, 2022, 2023


def _api_url(year: int) -> str:
    url = API.format(year=year)
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        url = f"{url}&key={key}"
    return url


def fetch_year(year: int) -> dict[str, tuple[str, int]]:
    """Returns fips -> (county_name, median_tax_dollars)."""
    with urllib.request.urlopen(_api_url(year), timeout=60) as resp:
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
    baseline_years = [CURRENT_YEAR - k for k in range(BASELINE_YEARS, 0, -1)]
    print(f"Current year: ACS {CURRENT_YEAR}")
    print(f"Baseline years: {baseline_years} (mean)")

    per_year: dict[int, dict[str, tuple[str, int]]] = {}
    for yr in baseline_years + [CURRENT_YEAR]:
        print(f"Fetching ACS 5-year {yr} ...")
        per_year[yr] = fetch_year(yr)
        print(f"  {len(per_year[yr])} counties")

    common = set(per_year[CURRENT_YEAR])
    for yr in baseline_years:
        common &= set(per_year[yr])

    joined = []
    for fips in sorted(common):
        name, t_cur = per_year[CURRENT_YEAR][fips]
        baseline_vals = [per_year[yr][fips][1] for yr in baseline_years]
        t_baseline = sum(baseline_vals) / len(baseline_vals)
        growth_pct = (t_cur - t_baseline) / t_baseline * 100.0
        joined.append((fips, name, round(t_baseline, 2), t_cur,
                       round(growth_pct, 4),
                       baseline_years[0], baseline_years[-1], CURRENT_YEAR))

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fips", "name", "tax_baseline", "tax_current",
                    "growth_pct", "baseline_start_year",
                    "baseline_end_year", "current_year"])
        w.writerows(joined)
    print(f"Wrote {len(joined)} rows -> {CACHE}")


if __name__ == "__main__":
    main()
