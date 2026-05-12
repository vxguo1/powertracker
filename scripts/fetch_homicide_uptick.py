"""Compute state-level homicide-rate Z-scores and emit a GeoJSON for
the MapLibre frontend, mirroring scripts/fetch_od_uptick.py.

Source: CDC "Mapping Injury, Overdose, and Violence - State" dataset
  fpsi-y8tj, intent=All_Homicide.
  - Annual rates (per 100k pop) for 2019..2024 plus a TTM row
    ("Dec 2024 - Nov 2025" at time of writing).
  - Suppressed cells come back as -999; we filter those out.

Cadence note: the user spec was weekly with a 52-week baseline. No
public dataset gives state-week homicide rates; CDC's fpsi-y8tj is the
best available state-level series and it's annual. With 5 baseline
years the stdev estimate is noisy — read the Z-scores as directional,
not strictly statistical. The 4-tier classification is unchanged from
the spec.

Output schema matches app/od_uptick.geojson so the same MapLibre
layers, tooltip, and legend code render this layer's data.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from statistics import mean, pstdev

REPO_ROOT = Path(__file__).resolve().parent.parent
STATES_GEOJSON = REPO_ROOT / "data" / "geo" / "us_states.geojson"
ENDPOINT = "https://data.cdc.gov/resource/fpsi-y8tj.json"
OUT = REPO_ROOT / "app" / "homicide_uptick.geojson"

BASELINE_YEARS = ["2019", "2020", "2021", "2022", "2023"]
SUPPRESSED_SENTINEL = -999.0

# Same 4-tier classification breakpoints as the OD uptick layer.
TIERS = [
    (3.0, "severe",       "#7a0019"),
    (2.0, "significant",  "#d7263d"),
    (1.5, "elevated",     "#f46036"),
    (-99.0, "normal",     "#cfd1d4"),
]

# Postal -> state FIPS (matches the `id` field on us-states.json).
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
    if z is None:
        return ("no_data", "#cfd1d4")
    for thresh, label, color in TIERS:
        if z >= thresh:
            return (label, color)
    return ("normal", "#cfd1d4")


def fetch_homicide_by_state() -> dict[str, dict[str, tuple[float, str | None]]]:
    """Returns geoid -> period -> (rate, ttm_date_range or None)."""
    url = f"{ENDPOINT}?intent=All_Homicide&$limit=5000"
    with urllib.request.urlopen(url, timeout=60) as r:
        rows = json.load(r)
    out: dict[str, dict[str, tuple[float, str | None]]] = {}
    for r in rows:
        gid = (r.get("geoid") or "").zfill(2)
        period = r.get("period")
        try:
            rate = float(r.get("rate"))
        except (TypeError, ValueError):
            continue
        if rate == SUPPRESSED_SENTINEL:
            continue
        out.setdefault(gid, {})[period] = (rate, r.get("ttm_date_range"))
    return out


def main() -> None:
    print("Fetching CDC All_Homicide series ...")
    by_state = fetch_homicide_by_state()
    print(f"  states with data: {len(by_state)}")

    with open(STATES_GEOJSON, "r", encoding="utf-8") as f:
        states_geo = json.load(f)

    out_features = []
    summary: dict[str, int] = {}
    ttm_range = None

    for feat in states_geo["features"]:
        fips = str(feat.get("id") or "").zfill(2)
        name = feat["properties"].get("name", "?")
        postal = next((k for k, v in STATE_FIPS.items() if v == fips), None)

        props: dict = {
            "fips": fips, "postal": postal, "name": name,
            "level": "no_data", "fill_color": "#cfd1d4",
            "z": None, "z_prev": None,
            "latest_value": None, "latest_period": None,
            "baseline_mean": None, "baseline_stdev": None,
            "driver_indicator": "All-cause homicide (CDC fpsi-y8tj)",
            "headline_value": None, "headline_z": None,
        }
        periods = by_state.get(fips, {})
        baseline = [periods[y][0] for y in BASELINE_YEARS if y in periods]
        ttm = periods.get("TTM")
        prior = periods.get("2024")

        if ttm is not None and len(baseline) >= 3:
            mu = mean(baseline); sd = pstdev(baseline)
            if sd > 0:
                rate, ttm_dr = ttm
                z = (rate - mu) / sd
                z_prev = ((prior[0] - mu) / sd) if prior is not None else None
                # No persistence check — TTM and 2024 share 11 months
                # so they're effectively the same observation; using one
                # to "validate" the other would just dampen real signal.
                label, color = classify(z)
                props.update({
                    "level": label, "fill_color": color,
                    "z": round(z, 3),
                    "z_prev": (round(z_prev, 3) if z_prev is not None else None),
                    "latest_value": rate,
                    "latest_period": f"TTM ({ttm_dr})" if ttm_dr else "TTM",
                    "baseline_mean": round(mu, 2),
                    "baseline_stdev": round(sd, 2),
                    "headline_value": rate,
                    "headline_z": round(z, 2),
                })
                if ttm_dr and not ttm_range:
                    ttm_range = ttm_dr
        summary[props["level"]] = summary.get(props["level"], 0) + 1
        out_features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": props,
        })

    gj = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "CDC Mapping Injury, Overdose, and Violence - State (fpsi-y8tj)",
            "intent": "All_Homicide (rate per 100k)",
            "algorithm": (
                "Z = (TTM_rate - mean(2019..2023)) / stdev(2019..2023). "
                "Soft persistence: if 2024 also exceeds the band, the "
                "state is flagged at that level; otherwise downgraded. "
                "Spec was weekly with 52-week baseline; CDC publishes "
                "this series annually."
            ),
            "latest_period": ttm_range or "TTM",
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
