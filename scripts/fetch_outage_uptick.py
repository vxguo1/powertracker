"""Compute state-level power-outage Z-scores from NOAA Storm Events as a
weather-driven outage proxy.

No federal feed publishes monthly state-level customer-out counts at a
free, scriptable endpoint anymore - the DOE OE-417 site at
`oe.netl.doe.gov` no longer resolves, and Oak Ridge EAGLE-I requires a
registered account. The closest accessible proxy is NOAA's Storm Events
Database: per-event records that include the disturbance type, state,
and date. Count outage-driving storm events per state per month and
the resulting series tracks roughly the same "is grid stress unusually
high here" signal we'd get from customer-out data, with the explicit
caveat that a state can score high simply because storm activity was
unusual even if grids held up.

  https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/

Adapted algorithm (matches scripts/fetch_od_uptick.py shape):
  - Per-state monthly counts of outage-driving event types.
  - Series: trailing-12-month sum, monthly.
  - Baseline window: months [t-72, t-12] (60 months lagged 12 to avoid
    overlap with the trailing-12 target).
  - z = (latest_value - baseline_mean) / baseline_stdev
  - Classification thresholds match OD/homicide:
      z < 1.5       -> normal
      1.5 <= z < 2  -> elevated
      2.0 <= z < 3  -> significant
      z >= 3.0      -> severe (animated pulse)
  - Persistence: prior month must also exceed the same band.

Output: app/outage_uptick.geojson - US-state polygons with level/z/value
properties matching the OD and homicide layers, so the MapLibre style
can render them with the existing fill/outline/pulse paint pipeline.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

REPO_ROOT = Path(__file__).resolve().parent.parent
STATES_GEOJSON = REPO_ROOT / "data" / "geo" / "us_states.geojson"
OUT = REPO_ROOT / "app" / "outage_uptick.geojson"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "noaa_storm_events"

NOAA_BASE = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"

# We need 60 months of baseline + 12 months of trailing-12 + a year or
# two of warm-up. Pulling 8 years covers the [t-72, t-12] window plus
# the current TTM endpoint with margin.
START_YEAR = 2018
END_YEAR = 2026

# Event types known to cause significant power outages. NOAA's Storm
# Events catalog has ~50 types; we keep the ones with a strong outage
# signal and exclude purely meteorological observations (Drought, Heat,
# Dense Fog) that don't directly stress the grid at this scale.
OUTAGE_EVENT_TYPES = {
    "Thunderstorm Wind", "Marine Thunderstorm Wind",
    "Tornado", "Funnel Cloud",
    "High Wind", "Strong Wind", "Marine High Wind", "Marine Strong Wind",
    "Ice Storm", "Winter Storm", "Blizzard",
    "Heavy Snow", "Lake-Effect Snow",
    "Hurricane", "Hurricane (Typhoon)",
    "Tropical Storm", "Tropical Depression",
    "Wildfire",
    "Lightning",
    "Flash Flood",
}

# Same 4-tier classification as the OD and homicide uptick layers.
TIERS = [
    (3.0, "severe",       "#7a0019"),
    (2.0, "significant",  "#d7263d"),
    (1.5, "elevated",     "#f46036"),
    (-99.0, "normal",     "#cfd1d4"),
]

# Postal -> FIPS, matching the `id` field on us-states.json features.
STATE_FIPS = {
    "AL":"01","AK":"02","AZ":"04","AR":"05","CA":"06","CO":"08","CT":"09",
    "DE":"10","DC":"11","FL":"12","GA":"13","HI":"15","ID":"16","IL":"17",
    "IN":"18","IA":"19","KS":"20","KY":"21","LA":"22","ME":"23","MD":"24",
    "MA":"25","MI":"26","MN":"27","MS":"28","MO":"29","MT":"30","NE":"31",
    "NV":"32","NH":"33","NJ":"34","NM":"35","NY":"36","NC":"37","ND":"38",
    "OH":"39","OK":"40","OR":"41","PA":"42","RI":"44","SC":"45","SD":"46",
    "TN":"47","TX":"48","UT":"49","VT":"50","VA":"51","WA":"53","WV":"54",
    "WI":"55","WY":"56",
}
VALID_FIPS = set(STATE_FIPS.values())


def classify(z: float | None) -> tuple[str, str]:
    if z is None:
        return ("no_data", "#cfd1d4")
    for thresh, label, color in TIERS:
        if z >= thresh:
            return (label, color)
    return ("normal", "#cfd1d4")


def list_year_files() -> dict[int, str]:
    """Discover the latest c-date filename per year in NOAA's listing."""
    req = urllib.request.Request(NOAA_BASE, headers={"User-Agent": "powertracker"})
    body = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", errors="replace")
    latest: dict[int, tuple[str, str]] = {}
    for m in re.finditer(
        r"(StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz)", body
    ):
        fname, y, c = m.group(1), int(m.group(2)), m.group(3)
        if not (START_YEAR <= y <= END_YEAR):
            continue
        if y not in latest or c > latest[y][1]:
            latest[y] = (fname, c)
    return {y: f for y, (f, _) in latest.items()}


def fetch_year(fname: str) -> bytes:
    """Cached fetch. The c-date is in the filename so a re-issued NOAA
    file lands at a new cache path on its own."""
    cache = CACHE_DIR / fname
    if cache.exists() and cache.stat().st_size > 0:
        return cache.read_bytes()
    print(f"  downloading {fname} ...")
    req = urllib.request.Request(NOAA_BASE + fname, headers={"User-Agent": "powertracker"})
    data = urllib.request.urlopen(req, timeout=600).read()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return data


def accumulate_monthly() -> dict[str, dict[int, int]]:
    """Return state_fips -> period_idx (year*12+month) -> event_count."""
    files = list_year_files()
    print(f"NOAA Storm Events: {len(files)} annual files in range")
    monthly: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for y in sorted(files):
        data = fetch_year(files[y])
        kept = 0
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            reader = csv.DictReader(io.TextIOWrapper(gz, encoding="utf-8"))
            for row in reader:
                if row.get("EVENT_TYPE", "") not in OUTAGE_EVENT_TYPES:
                    continue
                fips = (row.get("STATE_FIPS") or "").zfill(2)
                if fips not in VALID_FIPS:
                    continue  # filters marine zones, PR, GU, etc.
                ym = row.get("BEGIN_YEARMONTH", "")
                if len(ym) != 6 or not ym.isdigit():
                    continue
                yr, mo = int(ym[:4]), int(ym[4:])
                if not (1 <= mo <= 12):
                    continue
                monthly[fips][yr * 12 + mo] += 1
                kept += 1
        print(f"  {y}: {kept:,} outage-driving events")
    return monthly


def trailing12_series(monthly: dict[int, int]) -> list[tuple[int, float]]:
    """Convert {period_idx: count} to a (period_idx, trailing-12-sum)
    series, sorted oldest first. Months with no events count as 0."""
    if not monthly:
        return []
    lo, hi = min(monthly), max(monthly)
    out: list[tuple[int, float]] = []
    for idx in range(lo + 11, hi + 1):
        s = sum(monthly.get(idx - k, 0) for k in range(12))
        out.append((idx, float(s)))
    return out


def zscore_for_month(series: list[tuple[int, float]], target_idx: int) -> tuple[float, float, float] | None:
    lo, hi = target_idx - 72, target_idx - 12
    window = [v for i, v in series if lo <= i <= hi]
    if len(window) < 24:
        return None
    mu = mean(window)
    sd = pstdev(window)
    if sd == 0:
        return None
    target_val = next((v for i, v in series if i == target_idx), None)
    if target_val is None:
        return None
    return ((target_val - mu) / sd, mu, sd)


def latest_two(series: list[tuple[int, float]]) -> tuple[tuple[int, float], tuple[int, float]] | None:
    if len(series) < 2:
        return None
    last_idx, last_val = series[-1]
    prev_idx, prev_val = series[-2]
    if last_idx - prev_idx != 1:
        return None
    return ((prev_idx, prev_val), (last_idx, last_val))


def main() -> None:
    print("Aggregating NOAA Storm Events ...")
    monthly_by_fips = accumulate_monthly()
    print(f"  states with any data: {len(monthly_by_fips)}")

    with open(STATES_GEOJSON, "r", encoding="utf-8") as f:
        states_geo = json.load(f)

    postal_by_fips = {v: k for k, v in STATE_FIPS.items()}

    out_features = []
    summary: dict[str, int] = {}
    latest_seen = 0
    order = ["no_data", "normal", "elevated", "significant", "severe"]

    for feat in states_geo["features"]:
        fips = str(feat.get("id") or "").zfill(2)
        name = feat["properties"].get("name", "?")
        postal = postal_by_fips.get(fips)

        props: dict = {
            "fips": fips, "postal": postal, "name": name,
            "level": "no_data", "fill_color": "#cfd1d4",
            "z": None, "z_prev": None,
            "latest_value": None, "latest_period": None,
            "baseline_mean": None, "baseline_stdev": None,
            "driver_indicator": "Outage-driving storm events (count, trailing 12mo)",
            "headline_value": None, "headline_z": None,
        }

        m = monthly_by_fips.get(fips, {})
        if m:
            series = trailing12_series(m)
            pair = latest_two(series)
            if pair:
                (prev_idx, _), (cur_idx, cur_val) = pair
                z_cur = zscore_for_month(series, cur_idx)
                z_prev = zscore_for_month(series, prev_idx)
                if z_cur and z_prev:
                    z, mu, sd = z_cur
                    cur_label, _ = classify(z)
                    prev_label, _ = classify(z_prev[0])
                    final_label = order[min(order.index(cur_label), order.index(prev_label))]
                    _, color = classify({
                        "normal": -1, "elevated": 1.5,
                        "significant": 2.0, "severe": 3.0,
                    }.get(final_label, -99))
                    props.update({
                        "level": final_label, "fill_color": color,
                        "z": round(z, 3), "z_prev": round(z_prev[0], 3),
                        "latest_value": int(cur_val),
                        "latest_period": f"{cur_idx // 12}-{cur_idx % 12:02d}",
                        "baseline_mean": round(mu, 1),
                        "baseline_stdev": round(sd, 2),
                        "headline_value": int(cur_val),
                        "headline_z": round(z, 2),
                    })
                    if cur_idx > latest_seen:
                        latest_seen = cur_idx
        summary[props["level"]] = summary.get(props["level"], 0) + 1
        out_features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": props,
        })

    gj = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "NOAA Storm Events Database",
            "source_url": NOAA_BASE,
            "event_types_counted": sorted(OUTAGE_EVENT_TYPES),
            "algorithm": (
                "For each state, count outage-driving storm events per "
                "month and form a trailing-12-month sum. Z = (current - "
                "baseline_mean) / baseline_stdev where baseline = months "
                "[t-72, t-12]. Persistence: prior month must also exceed "
                "the same threshold band."
            ),
            "caveat": (
                "Weather-event proxy, not measured customer-out counts. "
                "A state scores high if storm activity was unusual even "
                "if grids held up. Federal customer-out data (DOE OE-417) "
                "is no longer published at a free public endpoint."
            ),
            "latest_period": (f"{latest_seen // 12}-{latest_seen % 12:02d}"
                              if latest_seen else None),
            "counts_by_level": summary,
        },
        "features": out_features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(gj, f)
    print(f"Wrote {OUT}  ({OUT.stat().st_size/1024:.1f} KB)")
    print(f"Tier summary: {summary}")


if __name__ == "__main__":
    main()
