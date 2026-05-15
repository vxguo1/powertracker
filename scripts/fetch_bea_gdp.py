"""Fetch BEA Regional Economic Accounts CAGDP1 + CAINC1 zips, then compute
county per-capita real GDP for the latest year vs the mean of the prior
3 years.

Sources:
  - CAGDP1: county GDP by industry (we use LineCode 1 for real chained-dollar
    GDP, LineCode 3 for current-dollar GDP).
  - CAINC1: county personal income, including population (LineCode 2).

Both files publish as single-CSV-inside-ZIP downloads covering 1969-present
(CAINC1) and 2001-present (CAGDP1). BEA releases new county-year data
each December covering the prior calendar year.

Output: data/cache/county_gdp_yoy.csv via src/powertracker/gdp.py.

Bump CURRENT_YEAR once the December BEA release lands; the 3-year baseline
auto-shifts. The hardcoded CSV filenames inside the zips embed the year
range (`CAGDP1__ALL_AREAS_2001_2024.csv`), so when 2025 data drops both
this script's CSV constants and the matching constants in
`src/powertracker/gdp.py` need updating in lockstep.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BEA_RAW = REPO_ROOT / "data" / "raw" / "bea"
CACHE = REPO_ROOT / "data" / "cache" / "county_gdp_yoy.csv"

sys.path.insert(0, str(REPO_ROOT / "src"))
from powertracker.gdp import yoy_per_capita_gdp  # noqa: E402

CURRENT_YEAR = 2024
BASELINE_YEARS = 3

DOWNLOADS = {
    "CAGDP1.zip": "https://apps.bea.gov/regional/zip/CAGDP1.zip",
    "CAINC1.zip": "https://apps.bea.gov/regional/zip/CAINC1.zip",
}

_UA = "powertracker-bea-fetcher/1.0 (+https://github.com/vxguo1/powertracker)"


def download(name: str, url: str) -> Path:
    BEA_RAW.mkdir(parents=True, exist_ok=True)
    out = BEA_RAW / name
    print(f"Fetching {url} -> {out} ...")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as resp, open(out, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    print(f"  wrote {out.stat().st_size // 1024} KB")
    return out


def main() -> None:
    for name, url in DOWNLOADS.items():
        download(name, url)

    print(f"Computing per-capita real GDP for {CURRENT_YEAR} "
          f"vs mean of prior {BASELINE_YEARS} years ...")
    df = yoy_per_capita_gdp(recent_year=CURRENT_YEAR, baseline_years=BASELINE_YEARS)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE, index=False)
    print(f"Wrote {len(df)} rows -> {CACHE}")


if __name__ == "__main__":
    main()
