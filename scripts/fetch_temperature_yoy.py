"""Pull state-level YoY change in trailing-12-month mean temperature
from NOAA's Climate at a Glance and emit a GeoJSON for the frontend.

Source: NCEI Climate at a Glance, statewide time series endpoint.
  https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/
    statewide/time-series/{STATE_ID}/tavg/12/{ENDING_MONTH}/{Y0-Y1}.csv

Each request returns one row per year for the named trailing-12-month
window ending in that month. We grab a few years of history, take the
two most-recent rows, and compute:

  deltaF = current_tavg - prior_tavg
  pct    = 100 * deltaF / prior_tavg   (Fahrenheit; arbitrary zero so
                                        this is informative but unit-
                                        dependent — display ΔF as the
                                        headline)

State coverage: NOAA's CONUS divisional dataset uses state IDs 1-48
(alphabetical, no AK/HI) plus 50 for Alaska. Hawaii's climate
divisions are tracked separately and not included here — that state
renders as no-data.

Output: app/temperature_yoy.geojson, same state-polygon shape as the
OD / homicide uptick layers so the same probe + paint code applies.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATES_GEOJSON = REPO_ROOT / "data" / "geo" / "us_states.geojson"
OUT = REPO_ROOT / "app" / "temperature_yoy.geojson"

# NOAA Climate at a Glance state IDs (alphabetical CONUS = 1-48; AK = 50;
# HI not represented in this divisional series).
NOAA_STATE_ID = {
    "AL":1,"AZ":2,"AR":3,"CA":4,"CO":5,"CT":6,"DE":7,"FL":8,"GA":9,
    "ID":10,"IL":11,"IN":12,"IA":13,"KS":14,"KY":15,"LA":16,"ME":17,
    "MD":18,"MA":19,"MI":20,"MN":21,"MS":22,"MO":23,"MT":24,"NE":25,
    "NV":26,"NH":27,"NJ":28,"NM":29,"NY":30,"NC":31,"ND":32,"OH":33,
    "OK":34,"OR":35,"PA":36,"RI":37,"SC":38,"SD":39,"TN":40,"TX":41,
    "UT":42,"VT":43,"VA":44,"WA":45,"WV":46,"WI":47,"WY":48,
    "AK":50,
}
# Postal -> state FIPS (matches the `id` field on us_states.json).
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

# Diverging palette: blue = cooler YoY, gray = stable, red = warmer.
# Year-over-year shifts in trailing-12-month mean are usually within
# +/-2 °F so the bands are tight; bigger swings get the deepest tones.
TIERS_HOT = [
    (2.0, "extreme warming",  "#7a0019"),
    (1.0, "strong warming",   "#d7263d"),
    (0.3, "warming",          "#f46036"),
]
TIERS_COLD = [
    (-2.0, "extreme cooling", "#0a3b75"),
    (-1.0, "strong cooling",  "#4a85c4"),
    (-0.3, "cooling",         "#a4c5e5"),
]
NEUTRAL_LABEL = "stable"
NEUTRAL_COLOR = "#e8e8e8"


def classify(delta_f: float | None) -> tuple[str, str]:
    if delta_f is None:
        return ("no_data", "#cfd1d4")
    if delta_f >= 0.3:
        for thresh, label, color in TIERS_HOT:
            if delta_f >= thresh:
                return (label, color)
        return TIERS_HOT[-1][1], TIERS_HOT[-1][2]
    if delta_f <= -0.3:
        for thresh, label, color in TIERS_COLD:
            if delta_f <= thresh:
                return (label, color)
        return TIERS_COLD[-1][1], TIERS_COLD[-1][2]
    return (NEUTRAL_LABEL, NEUTRAL_COLOR)


def fetch_state_series(noaa_id: int, ending_month: int,
                       year_range: str) -> list[tuple[int, float]]:
    """Returns [(yyyymm, value_f), ...] sorted oldest first."""
    url = ("https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/"
           f"statewide/time-series/{noaa_id}/tavg/12/{ending_month}/"
           f"{year_range}.csv")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            txt = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ! NOAA id={noaa_id}: {e}")
        return []
    out = []
    for row in csv.reader(io.StringIO(txt)):
        if not row or row[0].startswith("#") or row[0].lower().startswith("date"):
            continue
        try:
            yyyymm = int(row[0])
            val = float(row[1])
        except (ValueError, IndexError):
            continue
        out.append((yyyymm, val))
    out.sort()
    return out


def main() -> None:
    today = date.today()
    # Use the most-recently-completed full month as the ending month;
    # NOAA usually has the prior month available within ~10 days.
    ending_month = today.month - 1 or 12
    end_year = today.year if today.month > 1 else today.year - 1
    start_year = end_year - 4  # 5 years of history is plenty
    year_range = f"{start_year}-{end_year}"
    print(f"Window: trailing-12 ending each {ending_month:02d}/yyyy across "
          f"{year_range}")

    print("Fetching NOAA Climate at a Glance ...")
    by_state: dict[str, list[tuple[int, float]]] = {}
    for postal, nid in NOAA_STATE_ID.items():
        ser = fetch_state_series(nid, ending_month, year_range)
        if ser:
            by_state[postal] = ser

    with open(STATES_GEOJSON, "r", encoding="utf-8") as f:
        states_geo = json.load(f)
    postal_by_fips = {v: k for k, v in STATE_FIPS.items()}

    out_features = []
    summary: dict[str, int] = {}
    latest_period: int = 0

    for feat in states_geo["features"]:
        fips = str(feat.get("id") or "").zfill(2)
        name = feat["properties"].get("name", "?")
        postal = postal_by_fips.get(fips)
        props: dict = {
            "fips": fips, "postal": postal, "name": name,
            "level": "no_data", "fill_color": "#cfd1d4",
            "delta_f": None, "pct_yoy": None,
            "current_tavg": None, "prior_tavg": None,
            "latest_period": None,
        }
        series = by_state.get(postal or "", [])
        if len(series) >= 2:
            (prev_period, prev_v), (cur_period, cur_v) = series[-2], series[-1]
            if cur_period - prev_period >= 100:  # ~1 year apart
                delta = cur_v - prev_v
                pct = (delta / prev_v) * 100.0 if prev_v else None
                label, color = classify(delta)
                props.update({
                    "level": label, "fill_color": color,
                    "delta_f": round(delta, 2),
                    "pct_yoy": round(pct, 2) if pct is not None else None,
                    "current_tavg": round(cur_v, 2),
                    "prior_tavg": round(prev_v, 2),
                    "latest_period": cur_period,
                })
                latest_period = max(latest_period, cur_period)
        summary[props["level"]] = summary.get(props["level"], 0) + 1
        out_features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": props,
        })

    gj = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "NOAA NCEI Climate at a Glance, statewide time series",
            "indicator": "Trailing-12-month mean temperature (°F), tavg",
            "algorithm": (
                "Δ°F = current trailing-12 - prior trailing-12. "
                "% YoY computed against the prior-year °F value but is "
                "unit-dependent (arbitrary Fahrenheit zero) — display "
                "the Δ°F as the headline."
            ),
            "latest_period": (f"{latest_period // 100}-{latest_period % 100:02d}"
                              if latest_period else None),
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
