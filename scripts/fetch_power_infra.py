"""Fetch US power infrastructure for the map: power plants, transmission
lines, and high-voltage substations. All three are derived from HIFLD /
EIA via ArcGIS REST feature services and saved as GeoJSON.

Outputs:
  app/power_plants.geojson               ~2.5k plants (>= 100 MW) - small enough
                                         for direct geojson serve
  data/cache/substations.geojson         ~47k substations (OSM Overpass,
                                         >= 69 kV) -> build_tiles.py packs
                                         into substations.pmtiles (~14 MB raw)
  data/cache/transmission_lines.geojson  ~95k line segments (EIA, all
                                         voltages) -> build_tiles.py packs
                                         into transmission_lines.pmtiles
                                         (raw geojson would be ~130 MB)

These layers update rarely (HIFLD refreshes annually-ish, EIA 860 is
annual in September), so we keep them committed and re-fetch via a
yearly GitHub Actions workflow.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
CACHE_DIR = REPO_ROOT / "data" / "cache"

# EIA-hosted ArcGIS Online org. Power plants use a 100 MW floor so the
# map doesn't drown in 1-5 MW community solar; transmission lines pull
# the full corpus and we filter to non-distribution voltages downstream.
EIA_BASE = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/ArcGIS/rest/services"
)
POWER_PLANTS_URL = (
    f"{EIA_BASE}/Power_Plants_in_the_US/FeatureServer/0/query"
)
TRANSMISSION_URL = (
    f"{EIA_BASE}/US_Electric_Power_Transmission_Lines/FeatureServer/0/query"
)

# HIFLD substations data is no longer publicly downloadable (DHS pulled
# the public archive in 2022). The Rutgers Center for Ocean Observing
# Leadership mirror at oceandata.rad.rutgers.edu still publishes ~8.7k
# substations but coverage is Northeast-only (~13 states). For US-wide
# transmission-level substations we use OpenStreetMap via the Overpass
# API instead - utilities and electric-grid mappers maintain
# power=substation features there with the voltage tag, and US coverage
# is comprehensive. We chunk by 4 quadrants to stay within Overpass
# server limits.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# CONUS quadrants. Alaska + Hawaii would need separate queries; skip
# them for now (no hyperscaler data-center clusters there).
US_QUADRANTS: list[tuple[float, float, float, float]] = [
    (36.0, -130.0, 50.0,  -98.0),  # NW
    (36.0,  -98.0, 50.0,  -65.0),  # NE
    (24.0, -130.0, 36.0,  -98.0),  # SW
    (24.0,  -98.0, 36.0,  -65.0),  # SE
]

MIN_PLANT_MW = 100
MIN_SUBSTATION_KV = 69


def _fetch_paginated(url: str, params: dict, page_size: int) -> list[dict]:
    """Pull every record from an ArcGIS REST feature service via
    resultOffset pagination. Returns a list of GeoJSON Feature dicts."""
    features: list[dict] = []
    offset = 0
    while True:
        q = dict(params)
        q["resultOffset"] = str(offset)
        q["resultRecordCount"] = str(page_size)
        full = f"{url}?{urllib.parse.urlencode(q)}"
        with urllib.request.urlopen(full, timeout=180) as r:
            payload = json.load(r)
        page = payload.get("features") or []
        if not page:
            break
        features.extend(page)
        got = len(page)
        print(f"    fetched {len(features):,} (page {got})")
        if got < page_size:
            break
        offset += got
        # Polite pacing - these services do throttle bulk pulls.
        time.sleep(0.25)
    return features


def _fetch_paginated_esri(url: str, params: dict, page_size: int) -> list[dict]:
    """Same as _fetch_paginated but pulls Esri JSON (f=json) and converts
    to GeoJSON Features in-process. Needed for MapServer endpoints like
    the Rutgers HIFLD mirror, where f=geojson silently drops numeric
    fields that contain null values (so MAX_VOLT comes back missing
    rather than as -999999 or the actual integer). Esri JSON preserves
    them, and the geometry conversion for Point features is trivial."""
    features: list[dict] = []
    offset = 0
    while True:
        q = dict(params)
        q["f"] = "json"
        q["resultOffset"] = str(offset)
        q["resultRecordCount"] = str(page_size)
        full = f"{url}?{urllib.parse.urlencode(q)}"
        with urllib.request.urlopen(full, timeout=180) as r:
            payload = json.load(r)
        page = payload.get("features") or []
        if not page:
            break
        # Esri Point: { "x": lon, "y": lat }
        for esri in page:
            geom = esri.get("geometry") or {}
            x, y = geom.get("x"), geom.get("y")
            if x is None or y is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": esri.get("attributes") or {},
            })
        got = len(page)
        print(f"    fetched {len(features):,} (page {got})")
        if got < page_size:
            break
        offset += got
        time.sleep(0.25)
    return features


def fetch_power_plants() -> dict:
    print(f"Power plants (>= {MIN_PLANT_MW} MW)...")
    fields = ",".join([
        "Plant_Code", "Plant_Name", "Utility_Na", "sector_nam",
        "City", "County", "State", "PrimSource", "tech_desc",
        "Install_MW", "Total_MW", "Source", "Period",
    ])
    params = {
        "where": f"Total_MW >= {MIN_PLANT_MW}",
        "outFields": fields,
        "outSR": "4326",
        "f": "geojson",
        "orderByFields": "OBJECTID",
    }
    features = _fetch_paginated(POWER_PLANTS_URL, params, page_size=2000)
    # Strip null/empty top-level junk; keep geometry + a curated property bag.
    cleaned = []
    for f in features:
        p = f.get("properties") or {}
        if not f.get("geometry"):
            continue
        props = {
            "plant_code": p.get("Plant_Code"),
            "name": p.get("Plant_Name"),
            "operator": p.get("Utility_Na"),
            "sector": p.get("sector_nam"),
            "city": p.get("City"),
            "county": p.get("County"),
            "state": p.get("State"),
            "primary_fuel": p.get("PrimSource"),
            "tech_desc": p.get("tech_desc"),
            "install_mw": p.get("Install_MW"),
            "total_mw": p.get("Total_MW"),
            "period": p.get("Period"),
        }
        cleaned.append({"type": "Feature", "geometry": f["geometry"], "properties": props})
    return {"type": "FeatureCollection", "features": cleaned}


def _parse_osm_voltage(raw: str | None) -> tuple[float | None, float | None]:
    """OSM voltage tag is in volts and can be a single int ("138000"), a
    multi-value string with `;` separators ("138000;345000;13800"), or
    occasionally a malformed string. Returns (max_kv, min_kv) restricted
    to the >=1 kV transmission-level values."""
    if not raw:
        return (None, None)
    parts: list[float] = []
    for token in str(raw).split(";"):
        token = token.strip()
        if not token:
            continue
        try:
            v = float(token)
        except ValueError:
            continue
        if v < 1000:  # Some OSM mappers use kV by accident; drop noise.
            continue
        parts.append(v / 1000.0)  # convert V -> kV
    if not parts:
        return (None, None)
    return (max(parts), min(parts))


def _fetch_overpass_quadrant(s: float, w: float, n: float, e: float) -> list[dict]:
    """Run a single Overpass query for power=substation in a bbox.
    Returns the raw `elements` list (nodes + ways with center)."""
    query = (
        f"[out:json][timeout:300];\n"
        f"(\n"
        f"  node[\"power\"=\"substation\"][\"voltage\"~\"^[0-9]\"]({s},{w},{n},{e});\n"
        f"  way[\"power\"=\"substation\"][\"voltage\"~\"^[0-9]\"]({s},{w},{n},{e});\n"
        f");\n"
        f"out center 50000;\n"
    )
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        OVERPASS_URL,
        data=data,
        headers={
            "User-Agent": "powertracker-fetcher/1.0 (github.com/vxguo1/powertracker)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=360) as r:
        payload = json.load(r)
    return payload.get("elements") or []


def fetch_substations() -> dict:
    print(f"Substations (OSM Overpass, max kV >= {MIN_SUBSTATION_KV})...")
    seen: set[int] = set()
    raw: list[dict] = []
    for i, (s, w, n, e) in enumerate(US_QUADRANTS):
        print(f"  quadrant {i+1}/{len(US_QUADRANTS)} ({s},{w}) -> ({n},{e}) ...")
        elements = _fetch_overpass_quadrant(s, w, n, e)
        for el in elements:
            oid = el.get("id")
            if oid in seen:
                continue
            seen.add(oid)
            raw.append(el)
        print(f"    cumulative: {len(raw):,} substations")
        time.sleep(2.0)  # Be polite to the shared public Overpass server.

    cleaned = []
    for el in raw:
        tags = el.get("tags") or {}
        max_kv, min_kv = _parse_osm_voltage(tags.get("voltage"))
        if max_kv is None or max_kv < MIN_SUBSTATION_KV:
            continue
        # Nodes have lat/lon directly; ways have a `center` block with
        # lat/lon (because we asked `out center`).
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        props = {
            "name": tags.get("name") or tags.get("ref") or f"Substation #{el.get('id')}",
            "operator": tags.get("operator"),
            "city": tags.get("addr:city"),
            "state": tags.get("addr:state") or tags.get("is_in:state"),
            "type": tags.get("substation"),  # e.g. "transmission", "distribution"
            "status": tags.get("disused:power") and "disused" or "in service",
            "max_volt": max_kv,
            "min_volt": min_kv,
            "osm_id": f"{el.get('type')}/{el.get('id')}",
        }
        cleaned.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    print(f"  kept {len(cleaned):,} substations after voltage filter")
    return {"type": "FeatureCollection", "features": cleaned}


def fetch_transmission_lines() -> dict:
    print("Transmission lines (all)...")
    fields = ",".join([
        "TYPE", "STATUS", "OWNER", "VOLTAGE", "VOLT_CLASS",
        "SUB_1", "SUB_2",
    ])
    params = {
        "where": "1=1",
        "outFields": fields,
        "outSR": "4326",
        "f": "geojson",
        "orderByFields": "OBJECTID",
    }
    features = _fetch_paginated(TRANSMISSION_URL, params, page_size=2000)
    cleaned = []
    for f in features:
        p = f.get("properties") or {}
        if not f.get("geometry"):
            continue
        voltage = p.get("VOLTAGE")
        # The HIFLD raw export uses -999999 for "unknown voltage". Clamp
        # to None so the tooltip renders cleanly and the bin function
        # below treats it as the lowest visible class.
        if isinstance(voltage, (int, float)) and voltage < 0:
            voltage = None
        props = {
            "type": p.get("TYPE"),
            "status": p.get("STATUS"),
            "owner": p.get("OWNER"),
            "voltage_kv": voltage,
            "volt_class": p.get("VOLT_CLASS"),
            "sub_1": p.get("SUB_1"),
            "sub_2": p.get("SUB_2"),
        }
        cleaned.append({"type": "Feature", "geometry": f["geometry"], "properties": props})
    return {"type": "FeatureCollection", "features": cleaned}


def main() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    plants = fetch_power_plants()
    out = APP_DIR / "power_plants.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(plants, f)
    print(f"  wrote {len(plants['features']):,} plants -> {out} "
          f"({out.stat().st_size/1024:.1f} KB)")

    subs = fetch_substations()
    out = CACHE_DIR / "substations.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(subs, f)
    print(f"  wrote {len(subs['features']):,} substations -> {out} "
          f"({out.stat().st_size/(1024*1024):.1f} MB) "
          f"[build_tiles.py packs this into PMTiles]")

    lines = fetch_transmission_lines()
    out = CACHE_DIR / "transmission_lines.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(lines, f)
    print(f"  wrote {len(lines['features']):,} lines -> {out} "
          f"({out.stat().st_size/(1024*1024):.1f} MB) "
          f"[build_tiles.py packs this into PMTiles]")


if __name__ == "__main__":
    main()
