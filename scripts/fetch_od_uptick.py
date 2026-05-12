"""Compute state-level overdose-uptick classifications and emit a
GeoJSON of state polygons ready for the MapLibre frontend.

The user's spec describes a weekly EMS-naloxone Z-score against a 52-
week baseline. NEMSIS doesn't publish state x week rates publicly, so
we adapt the same surveillance pattern to the closest accessible feed:

  CDC VSRR Provisional Drug Overdose Death Counts (dataset xkb8-kh2a)
    https://data.cdc.gov/resource/xkb8-kh2a.json
    one row per state x month x indicator; data_value is the
    *trailing 12-month* count for that ending month (so a spike one
    month propagates for a year — the Z-score reflects year-over-year
    acceleration, not week-to-week jitter).

Adapted algorithm:
  - Series:  trailing-12-month overdose deaths, monthly per state.
  - Baseline window:  months [t-72, t-12]  (60 months of history,
                      lagged 12 months so the baseline doesn't overlap
                      the same trailing window we're scoring).
  - z = (latest_value - baseline_mean) / baseline_stdev
  - Classification (same thresholds as the spec):
      z < 1.5       -> normal
      1.5 <= z < 2  -> elevated
      2.0 <= z < 3  -> significant
      z >= 3.0      -> severe (animated pulse)
  - Persistence:  the *prior* month's z must also exceed the same
                  threshold band. Cuts single-month blips.

Output: app/od_uptick.geojson — US-state polygons with level/z/value
properties. Default fill color is in the properties so the MapLibre
style can read it via ['get','fill_color'] without rebuilding the
match expression every time tier breakpoints change.
"""

from __future__ import annotations

import csv
import io
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import mean, pstdev

REPO_ROOT = Path(__file__).resolve().parent.parent
STATES_GEOJSON_URL = (
    "https://raw.githubusercontent.com/PublicaMundi/MappingAPI/"
    "master/data/geojson/us-states.json"
)
STATES_GEOJSON_CACHE = REPO_ROOT / "data" / "geo" / "us_states.geojson"
CDC_ENDPOINT = "https://data.cdc.gov/resource/xkb8-kh2a.json"
OUT = REPO_ROOT / "app" / "od_uptick.geojson"

# Same numeric thresholds the user spec'd; only the cadence (week ->
# month) changed.
TIERS = [
    (3.0, "severe",       "#7a0019"),  # darkest red, animated pulse
    (2.0, "significant",  "#d7263d"),  # red-orange
    (1.5, "elevated",     "#f46036"),  # orange
    (-99.0, "normal",     "#cfd1d4"),  # gray
]

MONTHS = ["January","February","March","April","May","June",
          "July","August","September","October","November","December"]
MONTH_IDX = {m: i + 1 for i, m in enumerate(MONTHS)}

# Postal -> state FIPS (matches the `id` field on us-states.json features).
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


def classify(z: float | None) -> tuple[str, str]:
    if z is None or math.isnan(z):
        return ("no_data", "#cfd1d4")
    for thresh, label, color in TIERS:
        if z >= thresh:
            return (label, color)
    return ("normal", "#cfd1d4")


# Drug-class indicators worth scoring. We Z-score each one separately
# per state and take the max across classes (a state is "uptick" if any
# drug class is rising sharply, even if total OD is flat or declining).
# "Number of Drug Overdose Deaths" is kept as the all-cause headline.
INDICATORS = [
    "Number of Drug Overdose Deaths",
    "Synthetic opioids, excl. methadone (T40.4)",
    "Heroin (T40.1)",
    "Natural & semi-synthetic opioids (T40.2)",
    "Methadone (T40.3)",
    "Cocaine (T40.5)",
    "Psychostimulants with abuse potential (T43.6)",
]


def _fetch_indicator(ind: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    page = 50000
    while True:
        params = urllib.parse.urlencode({
            "$where": f"indicator='{ind}'",
            "$select": "state,year,month,data_value",
            "$limit": page,
            "$offset": offset,
        })
        url = f"{CDC_ENDPOINT}?{params}"
        with urllib.request.urlopen(url, timeout=60) as r:
            batch = json.load(r)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def fetch_cdc_series() -> dict[str, dict[str, list[tuple[int, float]]]]:
    """Returns state postal -> indicator -> list of (year*12+month, val)
    sorted oldest first."""
    by_state_ind: dict[str, dict[str, list[tuple[int, float]]]] = {}
    for ind in INDICATORS:
        rows = _fetch_indicator(ind)
        print(f"  {ind[:50]:<52} {len(rows)} rows")
        for r in rows:
            st = (r.get("state") or "").strip().upper()
            if st not in STATE_FIPS:
                continue
            m_name = r.get("month")
            try:
                yr = int(r["year"])
            except (KeyError, ValueError):
                continue
            if m_name not in MONTH_IDX:
                continue
            v = r.get("data_value")
            if v in (None, "", "Suppressed"):
                continue
            try:
                val = float(v)
            except ValueError:
                continue
            period_idx = yr * 12 + MONTH_IDX[m_name]
            by_state_ind.setdefault(st, {}).setdefault(ind, []).append((period_idx, val))
    for st in by_state_ind:
        for ind in by_state_ind[st]:
            by_state_ind[st][ind].sort()
    return by_state_ind


def latest_two(series: list[tuple[int, float]]) -> tuple[tuple[int, float], tuple[int, float]] | None:
    """Return ((t-1 idx, val), (t idx, val)) for the two most recent
    consecutive months, or None if not available."""
    if len(series) < 2:
        return None
    last_idx, last_val = series[-1]
    prev_idx, prev_val = series[-2]
    if last_idx - prev_idx != 1:
        return None  # gap; can't enforce persistence
    return ((prev_idx, prev_val), (last_idx, last_val))


def zscore_for_month(series: list[tuple[int, float]], target_idx: int) -> tuple[float, float, float] | None:
    """Compute z = (val[target] - mean(window)) / stdev(window) where
    window = months [target-72, target-12], i.e. 60 months of history
    lagged 12 to avoid trailing-12 overlap with the target month."""
    lo, hi = target_idx - 72, target_idx - 12
    window = [v for i, v in series if lo <= i <= hi]
    if len(window) < 24:  # need at least ~2y of usable history
        return None
    mu = mean(window)
    sd = pstdev(window)
    if sd == 0:
        return None
    target_val = next((v for i, v in series if i == target_idx), None)
    if target_val is None:
        return None
    return ((target_val - mu) / sd, mu, sd)


def _classify_indicator(series: list[tuple[int, float]]) -> tuple[float, float, float, float, int, int] | None:
    """For a single state+indicator series, return
    (z_cur, z_prev, latest_val, baseline_mean, baseline_stdev, latest_idx)
    or None if not enough history."""
    pair = latest_two(series)
    if not pair:
        return None
    (prev_idx, _), (cur_idx, _) = pair
    z_cur = zscore_for_month(series, cur_idx)
    z_prev = zscore_for_month(series, prev_idx)
    if not (z_cur and z_prev):
        return None
    z, mu, sd = z_cur
    return (z, z_prev[0], series[-1][1], mu, sd, cur_idx)


def main() -> None:
    print("Fetching CDC VSRR overdose series ...")
    by_state = fetch_cdc_series()
    print(f"  states with data: {len(by_state)}")

    if not STATES_GEOJSON_CACHE.exists():
        print(f"Fetching state polygons ...")
        STATES_GEOJSON_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(STATES_GEOJSON_URL, timeout=60) as r:
            STATES_GEOJSON_CACHE.write_bytes(r.read())
    with open(STATES_GEOJSON_CACHE, "r", encoding="utf-8") as f:
        states_geo = json.load(f)

    # FIPS code -> state postal for joining
    postal_by_fips = {v: k for k, v in STATE_FIPS.items()}

    out_features = []
    summary: dict[str, int] = {}
    latest_month_seen = (0, 0)  # (year, month)

    order = ["no_data", "normal", "elevated", "significant", "severe"]

    for feat in states_geo["features"]:
        fips = str(feat.get("id") or "").zfill(2)
        postal = postal_by_fips.get(fips)
        name = feat["properties"].get("name", "?")

        props: dict = {
            "fips": fips, "postal": postal, "name": name,
            "level": "no_data", "fill_color": "#cfd1d4",
            "z": None, "z_prev": None,
            "latest_value": None, "latest_period": None,
            "baseline_mean": None, "baseline_stdev": None,
            "driver_indicator": None,
            "headline_value": None,
            "headline_z": None,
        }

        ind_series = by_state.get(postal or "", {})
        # Headline = all-cause OD count for the tooltip context.
        headline = ind_series.get("Number of Drug Overdose Deaths") or []
        if headline:
            cls = _classify_indicator(headline)
            if cls:
                props["headline_value"] = int(headline[-1][1])
                props["headline_z"] = round(cls[0], 2)

        # Pick the indicator with the most severe persisted z. A state
        # qualifies as "uptick" if any drug class is rising AND was already
        # rising the prior month.
        best = None  # (final_label_idx, cur_z, prev_z, val, mu, sd, idx, ind)
        for ind, series in ind_series.items():
            cls = _classify_indicator(series)
            if not cls:
                continue
            z, z_p, val, mu, sd, idx = cls
            cur_label, _ = classify(z)
            prev_label, _ = classify(z_p)
            final_label = order[min(order.index(cur_label), order.index(prev_label))]
            label_idx = order.index(final_label)
            key = (label_idx, z)
            if best is None or key > best[0]:
                best = (key, ind, z, z_p, val, mu, sd, idx, final_label)

        if best is not None:
            _, ind, z, z_p, val, mu, sd, idx, final_label = best
            _, color = classify({"normal": -1, "elevated": 1.5,
                                 "significant": 2.0, "severe": 3.0
                                 }.get(final_label, -99))
            props.update({
                "level": final_label, "fill_color": color,
                "z": round(z, 3), "z_prev": round(z_p, 3),
                "latest_value": int(val),
                "latest_period": f"{idx // 12}-{idx % 12:02d}",
                "baseline_mean": round(mu, 1),
                "baseline_stdev": round(sd, 2),
                "driver_indicator": ind,
            })
            y, m = idx // 12, idx % 12
            latest_month_seen = max(latest_month_seen, (y, m))
        summary[props["level"]] = summary.get(props["level"], 0) + 1

        out_features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": props,
        })

    gj = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "CDC VSRR Provisional Drug Overdose Death Counts (xkb8-kh2a)",
            "indicators_scored": INDICATORS,
            "algorithm": (
                "For each state and each drug-class indicator, compute "
                "Z = (current - baseline_mean) / baseline_stdev where "
                "baseline = months [t-72, t-12]. Persistence: prior month "
                "must also exceed the threshold. Final state level = the "
                "most severe class that meets persistence. Adapted from a "
                "52-week / 6-week-lag weekly spec to monthly cadence "
                "because NEMSIS week-resolution data is not public."
            ),
            "latest_period": f"{latest_month_seen[0]}-{latest_month_seen[1]:02d}",
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
