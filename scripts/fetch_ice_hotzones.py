"""Fetch recent ICE arrests from the Big Local News mirror of the
Deportation Data Project's processed data, aggregate to county, and
emit a hot-zones GeoJSON keyed by detention county centroid.

Source: https://data.biglocalnews.org/deportation-data/arrests/{ST}_ice_arrests.csv
Each CSV has one row per ICE arrest (Oct 2022 - early Mar 2026 as of
this run), with apprehension_date, apprehension_method_recoded,
detention_county, detention_state, etc.

We filter to "raid-style" arrests (at-large + non-custodial transfers
i.e. not in-jail handoffs) within the last 30 days of available data,
group by (state, county), look up the county centroid from
data/geo/us_counties.geojson, and emit point features with a tier
scaled by arrest count.

Output: data/cache/ice_hotzones.geojson with features.kind in
{"ring","marker"} mirroring the existing data-center hot-zones format.
"""

from __future__ import annotations

import csv
import io
import json
import math
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COUNTY_GEOJSON = REPO_ROOT / "data" / "geo" / "us_counties.geojson"
OUT = REPO_ROOT / "app" / "ice_hotzones.geojson"

STATES = [
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in",
    "ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv",
    "nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn",
    "tx","ut","vt","va","wa","wv","wi","wy","dc",
]
STATE_NAME_BY_POSTAL = {
    "al":"ALABAMA","ak":"ALASKA","az":"ARIZONA","ar":"ARKANSAS","ca":"CALIFORNIA",
    "co":"COLORADO","ct":"CONNECTICUT","de":"DELAWARE","fl":"FLORIDA","ga":"GEORGIA",
    "hi":"HAWAII","id":"IDAHO","il":"ILLINOIS","in":"INDIANA","ia":"IOWA",
    "ks":"KANSAS","ky":"KENTUCKY","la":"LOUISIANA","me":"MAINE","md":"MARYLAND",
    "ma":"MASSACHUSETTS","mi":"MICHIGAN","mn":"MINNESOTA","ms":"MISSISSIPPI",
    "mo":"MISSOURI","mt":"MONTANA","ne":"NEBRASKA","nv":"NEVADA","nh":"NEW HAMPSHIRE",
    "nj":"NEW JERSEY","nm":"NEW MEXICO","ny":"NEW YORK","nc":"NORTH CAROLINA",
    "nd":"NORTH DAKOTA","oh":"OHIO","ok":"OKLAHOMA","or":"OREGON","pa":"PENNSYLVANIA",
    "ri":"RHODE ISLAND","sc":"SOUTH CAROLINA","sd":"SOUTH DAKOTA","tn":"TENNESSEE",
    "tx":"TEXAS","ut":"UTAH","vt":"VERMONT","va":"VIRGINIA","wa":"WASHINGTON",
    "wv":"WEST VIRGINIA","wi":"WISCONSIN","wy":"WYOMING","dc":"DISTRICT OF COLUMBIA",
}

# Numeric tier labels (1-5) so the markers don't visually collide with
# the data-center hot-zone tiers (S/A/B/C/D) that share the same shape.
TIERS = [
    ("1", 200, "#7a0019"),
    ("2",  75, "#d7263d"),
    ("3",  30, "#f46036"),
    ("4",  10, "#f5a623"),
    ("5",   1, "#9e9e9e"),
]


def fetch_state(st: str) -> list[dict]:
    url = f"https://data.biglocalnews.org/deportation-data/arrests/{st}_ice_arrests.csv"
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            txt = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  {st}: HTTP {e.code} (skipping)")
        return []
    rows = list(csv.DictReader(io.StringIO(txt)))
    return rows


def main() -> None:
    print("Fetching state CSVs ...")
    all_rows: list[dict] = []
    for st in STATES:
        rows = fetch_state(st)
        print(f"  {st}: {len(rows)} rows")
        all_rows.extend(rows)
    print(f"Total: {len(all_rows)} arrests")

    # Find the latest apprehension_date in the dataset, then keep the
    # 30-day window ending there. The dataset is snapshotted, so this
    # is "last 30 days of available data" rather than literal calendar
    # past 30 days.
    dates = []
    for r in all_rows:
        s = r.get("apprehension_date") or ""
        try:
            dates.append(date.fromisoformat(s))
        except ValueError:
            continue
    if not dates:
        raise SystemExit("no parseable apprehension_date values")
    latest = max(dates)
    cutoff = latest - timedelta(days=30)
    print(f"Window: {cutoff.isoformat()} .. {latest.isoformat()}")

    # Filter: in-window AND at-large (the "raid"-style arrest). Custodial
    # is mostly jail-to-ICE transfers, which aren't raids.
    counts: dict[tuple[str, str], int] = defaultdict(int)
    in_window = 0
    for r in all_rows:
        try:
            d = date.fromisoformat(r.get("apprehension_date") or "")
        except ValueError:
            continue
        if not (cutoff <= d <= latest):
            continue
        method = (r.get("apprehension_method_recoded") or "").strip().lower()
        if not method.startswith("at-large"):
            continue
        county = (r.get("detention_county") or "").strip()
        state_name = (r.get("detention_state") or "").strip().upper()
        if not county or not state_name:
            continue
        counts[(state_name, county)] += 1
        in_window += 1
    print(f"At-large in window: {in_window} across {len(counts)} county buckets")

    # Build a fips -> centroid lookup from us_counties.geojson. We also
    # build a (state_name, county_name) -> fips map so we can join.
    with open(COUNTY_GEOJSON, "r", encoding="utf-8") as f:
        gj = json.load(f)
    state_name_by_fips_prefix = {  # 2-digit state FIPS -> upper state name
        "01":"ALABAMA","02":"ALASKA","04":"ARIZONA","05":"ARKANSAS","06":"CALIFORNIA",
        "08":"COLORADO","09":"CONNECTICUT","10":"DELAWARE","11":"DISTRICT OF COLUMBIA",
        "12":"FLORIDA","13":"GEORGIA","15":"HAWAII","16":"IDAHO","17":"ILLINOIS",
        "18":"INDIANA","19":"IOWA","20":"KANSAS","21":"KENTUCKY","22":"LOUISIANA",
        "23":"MAINE","24":"MARYLAND","25":"MASSACHUSETTS","26":"MICHIGAN",
        "27":"MINNESOTA","28":"MISSISSIPPI","29":"MISSOURI","30":"MONTANA",
        "31":"NEBRASKA","32":"NEVADA","33":"NEW HAMPSHIRE","34":"NEW JERSEY",
        "35":"NEW MEXICO","36":"NEW YORK","37":"NORTH CAROLINA","38":"NORTH DAKOTA",
        "39":"OHIO","40":"OKLAHOMA","41":"OREGON","42":"PENNSYLVANIA",
        "44":"RHODE ISLAND","45":"SOUTH CAROLINA","46":"SOUTH DAKOTA","47":"TENNESSEE",
        "48":"TEXAS","49":"UTAH","50":"VERMONT","51":"VIRGINIA","53":"WASHINGTON",
        "54":"WEST VIRGINIA","55":"WISCONSIN","56":"WYOMING",
    }

    def centroid(coords) -> tuple[float, float]:
        # Crude centroid: mean of all polygon vertices. Good enough for
        # placing a marker.
        xs, ys = [], []
        def walk(c):
            if isinstance(c, (list, tuple)):
                if len(c) >= 2 and isinstance(c[0], (int, float)) and isinstance(c[1], (int, float)):
                    xs.append(c[0]); ys.append(c[1])
                else:
                    for sub in c: walk(sub)
        walk(coords)
        if not xs: return (0.0, 0.0)
        return (sum(xs)/len(xs), sum(ys)/len(ys))

    centroids: dict[tuple[str, str], tuple[float, float, str]] = {}
    for feat in gj["features"]:
        fips = str(feat.get("id") or feat["properties"].get("GEO_ID", "")[-5:])
        name = (feat["properties"].get("NAME") or "").strip()
        if len(fips) < 2: continue
        state_name = state_name_by_fips_prefix.get(fips[:2])
        if not state_name: continue
        lon, lat = centroid(feat["geometry"]["coordinates"])
        centroids[(state_name, name.upper())] = (lon, lat, fips)

    # Aggregate counts to centroids. detention_county in the CSV often
    # ends in " County" or " Parish" or "Municipality" — strip common
    # suffixes to match the county geo NAME field.
    def normalize_county(c: str) -> str:
        c = c.strip().upper()
        for suffix in (" COUNTY", " PARISH", " BOROUGH", " CENSUS AREA",
                       " MUNICIPALITY", " CITY AND BOROUGH"):
            if c.endswith(suffix):
                c = c[: -len(suffix)]
        return c.strip()

    features = []
    unmatched = 0
    for (state, county), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        key = (state, normalize_county(county))
        loc = centroids.get(key)
        if not loc:
            unmatched += 1
            continue
        lon, lat, fips = loc

        # Tier picks the first row where n >= threshold (tiers are sorted
        # high to low).
        tier_label, tier_color = "D", "#9e9e9e"
        for label, thresh, color in TIERS:
            if n >= thresh:
                tier_label, tier_color = label, color
                break

        # Ring radius in degrees roughly proportional to sqrt(n) so area
        # scales with magnitude. Cap at ~120 mi visual.
        deg_per_mi = 1.0 / 69.0
        ring_mi = min(120.0, max(15.0, 4.0 * math.sqrt(n)))
        ring_deg = ring_mi * deg_per_mi

        ring_coords = []
        for k in range(33):
            theta = 2 * math.pi * k / 32
            ring_coords.append([
                lon + ring_deg * math.cos(theta) / math.cos(math.radians(lat)),
                lat + ring_deg * math.sin(theta),
            ])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring_coords]},
            "properties": {
                "kind": "ring", "tier": tier_label, "tier_color": tier_color,
                "n_arrests": n, "county": county.title(), "state": state.title(),
                "fips": fips,
                "label": f"{tier_label}: {n} at-large arrest{'' if n==1 else 's'}",
            },
        })
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "kind": "marker", "tier": tier_label, "tier_color": tier_color,
                "n_arrests": n, "county": county.title(), "state": state.title(),
                "fips": fips,
                "label": f"{tier_label}: {n} at-large arrest{'' if n==1 else 's'}",
            },
        })
    print(f"Built {len(features)//2} hot-zones; {unmatched} unmatched counties")

    gj_out = {
        "type": "FeatureCollection",
        "metadata": {
            "window_start": cutoff.isoformat(),
            "window_end": latest.isoformat(),
            "n_total_in_window": in_window,
            "source": "Deportation Data Project via Big Local News",
        },
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(gj_out, f)
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
