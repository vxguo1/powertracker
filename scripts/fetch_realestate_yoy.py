"""Pull county-level median closing prices from Redfin's Data Center
bulk TSV, build a 3-month rolling volume-weighted mean for the most
recent period and for each of the 3 analogous 3-month windows from 12,
24, and 36 months prior, then emit % change vs the 3-year baseline.

Source:
  https://redfin-public-data.s3.us-west-2.amazonaws.com/
    redfin_market_tracker/county_market_tracker.tsv000.gz

The file is one row per (county, property_type, month). Each row has:
  - PERIOD_BEGIN / PERIOD_END (ISO date)
  - PERIOD_DURATION           (30 in this file; monthly)
  - REGION                    ("Autauga County, AL", "Norfolk city, VA",
                               "Lafayette Parish, LA", "Hoonah-Angoon
                               Census Area, AK", ...)
  - STATE_CODE                (USPS 2-letter)
  - PROPERTY_TYPE             ("All Residential" is what we want)
  - MEDIAN_SALE_PRICE         (USD; actual closings)
  - HOMES_SOLD                (integer)

Single-month medians in low-volume counties (< ~10 sales) are mostly
sampling noise — a county that closed 3 houses last March and 2 this
March can swing 50% on a single high-end sale. We collapse the
single-month series to a trailing 3-month volume-weighted mean and
require both the current 3mo window AND each baseline 3mo window to
have >= MIN_HOMES_3MO closings; the rest fall back to no-data. The
baseline price is the simple mean of the three baseline 3mo means
(not re-weighted across years, so a single hot year doesn't dominate
the baseline).

Redfin uses its own region IDs, not FIPS. We resolve back to FIPS by
matching the LSAD-suffixed name + state_code against the Census county
GeoJSON we already ship in data/geo/us_counties.geojson.

Output: data/cache/realestate_yoy.csv with columns
  fips, name, state, price_current, price_baseline, growth_pct,
  period_current, baseline_periods, homes_sold_current_3mo,
  homes_sold_baseline_3mo
where `baseline_periods` is a pipe-separated list of the three
baseline period_end ISO dates.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE = REPO_ROOT / "data" / "cache" / "realestate_yoy.csv"
COUNTY_GEO = REPO_ROOT / "data" / "geo" / "us_counties.geojson"

URL = ("https://redfin-public-data.s3.us-west-2.amazonaws.com/"
       "redfin_market_tracker/county_market_tracker.tsv000.gz")

PROPERTY_TYPE = "All Residential"
# Minimum trailing-3-month homes sold for the current window AND each of
# the 3 baseline windows. Below this we treat the county as no-data —
# % swings are dominated by which exact houses sold, not by price-level
# changes.
MIN_HOMES_3MO = 30
BASELINE_YEARS = 3

# Map Census LSAD abbreviations (as seen in our committed county GeoJSON)
# to the spelled-out forms Redfin uses in its REGION column.
LSAD_EXPAND: dict[str, list[str]] = {
    "County":   ["County"],
    "Parish":   ["Parish"],
    "city":     ["city"],
    "Borough":  ["Borough"],
    "CA":       ["Census Area"],
    "Muno":     ["Municipality", "Municipio"],
    "Muny":     ["Municipality"],
    "Cty&Bor":  ["City and Borough"],
    "":         [""],
}

# 2-digit Census state FIPS -> USPS code, so we can build (NAME, USPS) -> FIPS
# from the county geojson properties.
FIPS_PREFIX_TO_POSTAL: dict[str, str] = {
    "01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT",
    "10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL",
    "18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD",
    "25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE",
    "32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND",
    "39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD",
    "47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV",
    "55":"WI","56":"WY",
}


def _normalize(s: str) -> str:
    """Lowercase + collapse '&' to 'and' + strip diacritics + collapse
    whitespace. Used as the dict key on both sides so Redfin's 'King &
    Queen County' lines up with Census 'King and Queen County' and
    'Dona Ana' lines up with 'Doña Ana'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", "and").lower()
    return " ".join(s.split())


def _build_region_to_fips() -> dict[tuple[str, str], str]:
    """Return {(normalized region, state_code): fips}.

    We register every (NAME + LSAD_expansion) combination so the same
    Census feature can be reached via "Autauga County" or "Hoonah-Angoon
    Census Area" (Redfin's spelled-out forms)."""
    with open(COUNTY_GEO, "r", encoding="utf-8") as f:
        geo = json.load(f)
    out: dict[tuple[str, str], str] = {}
    for feat in geo["features"]:
        props = feat["properties"]
        fips = (feat.get("id") or props.get("GEO_ID", "")[-5:])
        state_fips = props.get("STATE") or fips[:2]
        usps = FIPS_PREFIX_TO_POSTAL.get(state_fips)
        if not usps:
            continue
        name = props.get("NAME", "").strip()
        lsad_abbr = (props.get("LSAD") or "").strip()
        if not name:
            continue
        for spelled in LSAD_EXPAND.get(lsad_abbr, [lsad_abbr]):
            primary = _normalize(f"{name} {spelled}" if spelled else name)
            out.setdefault((primary, usps), fips)
        # Bare name too, in case Redfin sometimes drops the LSAD.
        out.setdefault((_normalize(name), usps), fips)
    return out


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _months_between(a: date, b: date) -> int:
    return (a.year - b.year) * 12 + (a.month - b.month)


def main() -> None:
    print(f"Downloading {URL} ...")
    with urllib.request.urlopen(URL, timeout=180) as resp:
        raw = resp.read()
    print(f"  {len(raw) / 1024 / 1024:.1f} MB gzipped")

    region_to_fips = _build_region_to_fips()
    print(f"Built region lookup: {len(region_to_fips)} entries")

    # Per county FIPS, by month-end date, accumulate {price, homes} for
    # the modal monthly observation. Redfin only emits one All-Residential
    # row per county per month, so collisions are not a concern.
    per_county: dict[str, dict[date, tuple[float, int]]] = defaultdict(dict)
    name_state: dict[str, tuple[str, str]] = {}

    n_rows = 0
    n_kept = 0
    n_unmatched_region = 0
    unmatched_examples: list[str] = []

    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
        reader = csv.DictReader(io.TextIOWrapper(gz, encoding="utf-8"),
                                delimiter="\t")
        for row in reader:
            n_rows += 1
            if row.get("PROPERTY_TYPE") != PROPERTY_TYPE:
                continue
            msp = row.get("MEDIAN_SALE_PRICE")
            if not msp:
                continue
            region = (row.get("REGION") or "").strip()
            state_code = (row.get("STATE_CODE") or "").strip()
            if not region or not state_code:
                continue
            # Drop ", ST" suffix.
            if region.endswith(f", {state_code}"):
                bare = region[:-(len(state_code) + 2)].strip()
            else:
                bare = region.split(",")[0].strip()
            key = (_normalize(bare), state_code)
            fips = region_to_fips.get(key)
            if fips is None:
                # Try without the trailing LSAD word.
                parts = bare.rsplit(" ", 1)
                if len(parts) == 2:
                    fips = region_to_fips.get((_normalize(parts[0]), state_code))
            if fips is None:
                if len(unmatched_examples) < 12:
                    unmatched_examples.append(region)
                n_unmatched_region += 1
                continue
            try:
                period_end = _parse_date(row["PERIOD_END"])
                price = float(msp)
            except (KeyError, ValueError):
                continue
            try:
                homes = int(float(row.get("HOMES_SOLD") or 0))
            except ValueError:
                homes = 0
            per_county[fips][period_end] = (price, homes)
            name_state[fips] = (bare, state_code)
            n_kept += 1

    print(f"Read {n_rows:,} rows; kept {n_kept:,} matching '{PROPERTY_TYPE}'")
    print(f"Counties covered: {len(per_county):,}")
    print(f"Unmatched-region rows: {n_unmatched_region:,}")
    if unmatched_examples:
        print(f"  examples: {unmatched_examples}")

    def rolling_3mo(by_end: dict[date, tuple[float, int]], anchor: date
                    ) -> tuple[float, int] | None:
        """Volume-weighted median across {anchor, anchor - 1mo, anchor - 2mo}.
        Returns (price, homes_sum) or None if no homes in the window.

        'Volume-weighted median' here is a coarse but stable proxy: we
        treat each month's reported median as a population-mean estimate
        with weight = homes_sold and compute the weighted mean. With 3
        monthly medians this is far less noisy than the raw monthly
        median in thin counties while still tracking actual price level.
        """
        months = []
        y, m = anchor.year, anchor.month
        for _ in range(3):
            d = date(y, m, 1)
            # Find any entry whose month matches (y, m).
            match = next((v for end, v in by_end.items()
                          if end.year == y and end.month == m), None)
            if match is not None:
                months.append(match)
            # Step back one month.
            m -= 1
            if m == 0:
                m = 12
                y -= 1
            _ = d  # noqa: silence linter
        if not months:
            return None
        total_homes = sum(h for _, h in months)
        if total_homes == 0:
            return None
        weighted = sum(p * h for p, h in months) / total_homes
        return (weighted, total_homes)

    out_rows = []
    skipped_no_baseline = 0
    skipped_thin = 0
    for fips, by_end in per_county.items():
        if len(by_end) < 1 + BASELINE_YEARS:
            skipped_no_baseline += 1
            continue
        anchor = max(by_end.keys())
        cur = rolling_3mo(by_end, anchor)
        if cur is None:
            skipped_no_baseline += 1
            continue
        # Build baseline 3mo windows at t-12, t-24, t-36 months.
        baseline_anchors = []
        for k in range(1, BASELINE_YEARS + 1):
            a = date(anchor.year - k, anchor.month, min(anchor.day, 28))
            baseline_anchors.append(a)
        baseline = [rolling_3mo(by_end, a) for a in baseline_anchors]
        if any(b is None for b in baseline):
            skipped_no_baseline += 1
            continue
        cur_price, cur_homes = cur
        baseline_prices = [p for p, _ in baseline]
        baseline_homes = [h for _, h in baseline]
        if cur_homes < MIN_HOMES_3MO or any(h < MIN_HOMES_3MO for h in baseline_homes):
            skipped_thin += 1
            continue
        baseline_price = sum(baseline_prices) / len(baseline_prices)
        if baseline_price <= 0:
            skipped_thin += 1
            continue
        growth_pct = (cur_price - baseline_price) / baseline_price * 100.0
        bare, state_code = name_state[fips]
        out_rows.append({
            "fips": fips,
            "name": bare,
            "state": state_code,
            "price_current": int(round(cur_price)),
            "price_baseline": int(round(baseline_price)),
            "growth_pct": round(growth_pct, 2),
            "period_current": anchor.isoformat(),
            "baseline_periods": "|".join(a.isoformat() for a in baseline_anchors),
            "homes_sold_current_3mo": cur_homes,
            "homes_sold_baseline_3mo": sum(baseline_homes),
        })

    out_rows.sort(key=lambda r: r["fips"])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["fips", "name", "state",
                  "price_current", "price_baseline", "growth_pct",
                  "period_current", "baseline_periods",
                  "homes_sold_current_3mo", "homes_sold_baseline_3mo"]
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {len(out_rows):,} county rows -> {CACHE}")
    print(f"  skipped (missing baseline window): {skipped_no_baseline:,}")
    print(f"  skipped (< {MIN_HOMES_3MO} sales in any 3mo window): {skipped_thin:,}")
    if out_rows:
        latest = max(r["period_current"] for r in out_rows)
        print(f"  latest period_end: {latest}")
        # Sanity: a few summary stats on growth_pct.
        gps = sorted(r["growth_pct"] for r in out_rows)
        n = len(gps)
        print(f"  growth_pct  min={gps[0]:.1f}  p10={gps[n//10]:.1f}  "
              f"median={gps[n//2]:.1f}  p90={gps[n*9//10]:.1f}  max={gps[-1]:.1f}")


if __name__ == "__main__":
    main()
