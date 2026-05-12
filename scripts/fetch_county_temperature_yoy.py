"""Pull county-level trailing-12-month mean temperature from NOAA's
Climate at a Glance "all counties" bulk JSON for the current ending
month AND each of the 3 prior years' analogous months, then compute
Δ°F vs the 3-year baseline mean per county.

This replaces the per-state temperature_yoy layer with a finer
choropleth. Same NOAA dataset; the bulk endpoint returns all 3107
counties in a single request, so four HTTP calls cover the world.

Source:
  https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/
    county/mapping/110-tavg-{YYYYMM}-1.json

Each entry carries:
  - value:    trailing-12-month mean tavg (°F)
  - anomaly:  current minus 1991-2020 normal (°F)  ← also useful
  - rank:     percentile rank vs historical
  - mean:     1991-2020 normal

Output: data/cache/temperature_county_yoy.csv with columns
  fips, name, state, tavg_current, tavg_baseline, delta_f,
  anomaly_current, current_period, baseline_periods
where `fips` is the 5-digit US Census county FIPS (state_id<<3 + cty3)
and `baseline_periods` is a pipe-separated list of the three baseline
YYYYMM strings.
"""

from __future__ import annotations

import csv
import json
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE = REPO_ROOT / "data" / "cache" / "temperature_county_yoy.csv"
ENDPOINT = ("https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/"
            "county/mapping/110-tavg-{period}-1.json")

BASELINE_YEARS = 3

# NOAA's bulk JSON keys counties by `{STATE_ABBR}-{COUNTY3}` where the
# state abbreviation is the postal code and COUNTY3 is the last three
# digits of the FIPS. We need to translate back to the 5-digit FIPS the
# rest of the pipeline uses.
POSTAL_TO_FIPS_PREFIX = {
    "AL":"01","AK":"02","AZ":"04","AR":"05","CA":"06","CO":"08","CT":"09",
    "DE":"10","DC":"11","FL":"12","GA":"13","HI":"15","ID":"16","IL":"17",
    "IN":"18","IA":"19","KS":"20","KY":"21","LA":"22","ME":"23","MD":"24",
    "MA":"25","MI":"26","MN":"27","MS":"28","MO":"29","MT":"30","NE":"31",
    "NV":"32","NH":"33","NJ":"34","NM":"35","NY":"36","NC":"37","ND":"38",
    "OH":"39","OK":"40","OR":"41","PA":"42","RI":"44","SC":"45","SD":"46",
    "TN":"47","TX":"48","UT":"49","VT":"50","VA":"51","WA":"53","WV":"54",
    "WI":"55","WY":"56",
}


def fetch_bulk(period: str) -> dict:
    """period = 'YYYYMM'. Returns the parsed JSON `data` dict."""
    url = ENDPOINT.format(period=period)
    with urllib.request.urlopen(url, timeout=60) as r:
        d = json.load(r)
    return d.get("data", {})


def main() -> None:
    today = date.today()
    # Use the most recently completed month; NOAA usually has it within
    # ~10 days. Step back further if the latest endpoint returns 404 or
    # an obviously empty payload.
    month = today.month - 1 or 12
    year = today.year if today.month > 1 else today.year - 1

    cur_period = f"{year}{month:02d}"
    baseline_periods = [f"{year - k}{month:02d}"
                        for k in range(BASELINE_YEARS, 0, -1)]

    print(f"Fetching NOAA county bulk for {cur_period} ...")
    cur = fetch_bulk(cur_period)
    print(f"  {len(cur)} counties")
    baselines: list[dict] = []
    for bp in baseline_periods:
        print(f"Fetching NOAA county bulk for {bp} ...")
        d = fetch_bulk(bp)
        print(f"  {len(d)} counties")
        baselines.append(d)

    baseline_period_str = "|".join(baseline_periods)
    out_rows = []
    skipped = 0
    for key, cur_entry in cur.items():
        try:
            postal, cty3 = key.split("-")
        except ValueError:
            skipped += 1
            continue
        prefix = POSTAL_TO_FIPS_PREFIX.get(postal)
        if not prefix:
            skipped += 1
            continue
        fips = f"{prefix}{cty3.zfill(3)}"
        cur_v = cur_entry.get("value")
        if cur_v is None:
            skipped += 1
            continue
        # Require a value in every baseline year.
        baseline_vals = []
        missing = False
        for d in baselines:
            entry = d.get(key)
            if not entry or entry.get("value") is None:
                missing = True
                break
            baseline_vals.append(entry["value"])
        if missing:
            skipped += 1
            continue
        baseline_mean = sum(baseline_vals) / len(baseline_vals)
        out_rows.append({
            "fips": fips,
            "name": cur_entry.get("name", ""),
            "state": cur_entry.get("state", ""),
            "tavg_current": cur_v,
            "tavg_baseline": round(baseline_mean, 2),
            "delta_f": round(cur_v - baseline_mean, 2),
            "anomaly_current": cur_entry.get("anomaly"),
            "current_period": cur_period,
            "baseline_periods": baseline_period_str,
        })

    out_rows.sort(key=lambda r: r["fips"])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["fips", "name", "state", "tavg_current", "tavg_baseline",
                  "delta_f", "anomaly_current", "current_period",
                  "baseline_periods"]
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {len(out_rows)} county rows -> {CACHE}  ({skipped} skipped)")


if __name__ == "__main__":
    main()
