"""Fetch EIA Form 861 annual utility filings (zip per year), then compute
residential electricity rate change for the latest year vs the mean of the
prior 3 years.

Each year's data publishes as `f861<year>.zip` from
https://www.eia.gov/electricity/data/eia861/. The zip contains
`Sales_Ult_Cust_<year>.xlsx` which `src/powertracker/prices.py` parses.
EIA-861 final annual data drops in October each year for the prior year.

Output: data/cache/utility_rate_yoy.csv via src/powertracker/prices.py.

Bump CURRENT_YEAR after the October release.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EIA861_RAW = REPO_ROOT / "data" / "raw" / "eia861"
CACHE = REPO_ROOT / "data" / "cache" / "utility_rate_yoy.csv"

sys.path.insert(0, str(REPO_ROOT / "src"))
from powertracker.prices import yoy_residential  # noqa: E402

CURRENT_YEAR = 2024
BASELINE_YEARS = 3

# EIA serves the current year's zip under /zip/ and prior years under
# /archive/zip/. We try both paths and accept the first that returns a
# real zip (the wrong path serves a ~65 KB HTML page with a 200 status,
# so we also filter on content-type).
_URLS = [
    "https://www.eia.gov/electricity/data/eia861/archive/zip/f861{year}.zip",
    "https://www.eia.gov/electricity/data/eia861/zip/f861{year}.zip",
]
_UA = "powertracker-eia861-fetcher/1.0 (+https://github.com/vxguo1/powertracker)"


def download_year(year: int) -> Path:
    EIA861_RAW.mkdir(parents=True, exist_ok=True)
    out = EIA861_RAW / f"f861{year}.zip"
    if out.exists() and out.stat().st_size > 100_000:
        print(f"  cached: {out} ({out.stat().st_size // 1024} KB)")
        return out

    last_err = None
    for url_tpl in _URLS:
        url = url_tpl.format(year=year)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=180) as resp:
                ctype = (resp.headers.get("content-type") or "").lower()
                if "zip" not in ctype and "octet-stream" not in ctype:
                    last_err = f"{url} -> content-type={ctype}"
                    continue
                print(f"Fetching {url} -> {out} ...")
                with open(out, "wb") as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
            print(f"  wrote {out.stat().st_size // 1024} KB")
            return out
        except Exception as e:
            last_err = f"{url}: {e}"
            continue
    raise RuntimeError(f"No working EIA-861 URL for {year}. Last: {last_err}")


def main() -> None:
    years = [CURRENT_YEAR - k for k in range(BASELINE_YEARS, -1, -1)]
    print(f"Years needed: {years}")
    for yr in years:
        download_year(yr)

    print(f"Computing residential rate YoY for {CURRENT_YEAR} "
          f"vs mean of prior {BASELINE_YEARS} years ...")
    df = yoy_residential(recent_year=CURRENT_YEAR, baseline_years=BASELINE_YEARS)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE, index=False)
    print(f"Wrote {len(df)} rows -> {CACHE}")


if __name__ == "__main__":
    main()
