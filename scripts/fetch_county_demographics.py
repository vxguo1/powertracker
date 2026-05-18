"""Fetch county population + median household income from the Census ACS
5-year API.

Source: ACS 5-year, table B01003 (Total Population), variable B01003_001E
and table B19013 (Median Household Income), variable B19013_001E. One
API request returns all ~3107 US counties for both variables.

The Census API now requires an API key on every request. Free key:
  https://api.census.gov/data/key_signup.html
Provide via the `CENSUS_API_KEY` env var, or read from
`C:\\Users\\PC\\OneDrive\\keys\\census_apikey.txt` (the keys-folder
convention used elsewhere in this repo).

Output: data/cache/county_demographics.csv with columns
  fips, name, population, median_hh_income, vintage_year
"""

from __future__ import annotations

import csv
import json
import os
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE = REPO_ROOT / "data" / "cache" / "county_demographics.csv"
KEY_FILE = Path("C:/Users/PC/OneDrive/keys/census_apikey.txt")

API = ("https://api.census.gov/data/{year}/acs/acs5"
       "?get=NAME,B01003_001E,B19013_001E&for=county:*")

CURRENT_YEAR = 2024


def _api_key() -> str | None:
    key = os.environ.get("CENSUS_API_KEY")
    if key:
        return key.strip()
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    return None


def _api_url(year: int) -> str:
    url = API.format(year=year)
    key = _api_key()
    if key:
        url = f"{url}&key={key}"
    return url


def fetch_year(year: int) -> list[tuple[str, str, int | None, int | None]]:
    with urllib.request.urlopen(_api_url(year), timeout=60) as resp:
        rows = json.load(resp)
    header, *data = rows
    name_i = header.index("NAME")
    pop_i = header.index("B01003_001E")
    inc_i = header.index("B19013_001E")
    state_i = header.index("state")
    county_i = header.index("county")
    out: list[tuple[str, str, int | None, int | None]] = []
    for r in data:
        fips = f"{r[state_i]}{r[county_i]}"
        try:
            pop = int(r[pop_i])
            if pop <= 0:
                pop = None
        except (TypeError, ValueError):
            pop = None
        try:
            inc = int(r[inc_i])
            if inc <= 0:
                inc = None  # Census null sentinel
        except (TypeError, ValueError):
            inc = None
        out.append((fips, r[name_i], pop, inc))
    return out


def main() -> None:
    print(f"Fetching ACS 5-year {CURRENT_YEAR} (B01003 + B19013) ...")
    rows = fetch_year(CURRENT_YEAR)
    print(f"  {len(rows)} counties")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fips", "name", "population", "median_hh_income",
                    "vintage_year"])
        for fips, name, pop, inc in sorted(rows):
            w.writerow([
                fips,
                name,
                pop if pop is not None else "",
                inc if inc is not None else "",
                CURRENT_YEAR,
            ])
    print(f"Wrote {len(rows)} rows -> {CACHE}")


if __name__ == "__main__":
    main()
