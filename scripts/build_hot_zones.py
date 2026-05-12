"""Build app/hot_zones.geojson from data/sites/data_centers.csv.

Clusters sites within ~80mi and assigns a tier based on total announced MW
(same logic as the Folium map). Emits both Polygon ring features and Point
marker features so the MapLibre app can render the ring + tier letter
without doing geometry math client-side.

Run after refreshing the data center catalog. Does not require Docker.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from powertracker.mapbuild import (  # noqa: E402
    _cluster_label,
    _cluster_sites,
    _tier_for_mw,
)

SITES_CSV = REPO_ROOT / "data" / "sites" / "data_centers.csv"
OUT_PATH = REPO_ROOT / "app" / "hot_zones.geojson"

EARTH_RADIUS_M = 6_371_000.0
RING_VERTICES = 64


def _ring_polygon(lat: float, lon: float, radius_m: float, n: int = RING_VERTICES) -> list[list[float]]:
    """Geodesic circle around (lat, lon) approximated as a closed polygon ring.

    Returned coordinates are [lon, lat] (GeoJSON order).
    """
    coords: list[list[float]] = []
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    d_R = radius_m / EARTH_RADIUS_M
    for i in range(n):
        bearing = 2 * math.pi * i / n
        lat2 = math.asin(
            math.sin(lat1) * math.cos(d_R)
            + math.cos(lat1) * math.sin(d_R) * math.cos(bearing)
        )
        lon2 = lon1 + math.atan2(
            math.sin(bearing) * math.sin(d_R) * math.cos(lat1),
            math.cos(d_R) - math.sin(lat1) * math.sin(lat2),
        )
        coords.append([math.degrees(lon2), math.degrees(lat2)])
    coords.append(coords[0])
    return coords


def main() -> None:
    sites = pd.read_csv(SITES_CSV)
    sites["announced_mw"] = pd.to_numeric(sites["announced_mw"], errors="coerce")
    sites = sites.dropna(subset=["lat", "lon"]).reset_index(drop=True)

    clusters = _cluster_sites(sites)
    features: list[dict] = []
    kept = 0
    for idx in clusters:
        sub = sites.iloc[idx]
        total_mw = float(sub["announced_mw"].fillna(0).sum())
        tier, tier_color = _tier_for_mw(total_mw)
        # Match Folium: hide low-signal tier-D clusters with fewer than 3 sites.
        if tier == "D" and len(idx) < 3:
            continue
        center_lat = float(sub["lat"].mean())
        center_lon = float(sub["lon"].mean())
        label = _cluster_label(sites, idx)
        # Same scaling as the Folium version: floor 20 km, otherwise grows with sqrt(MW).
        radius_m = max(20_000.0, math.sqrt(max(total_mw, 100.0)) * 1_400.0)
        ring = _ring_polygon(center_lat, center_lon, radius_m)

        props = {
            "tier": tier,
            "tier_color": tier_color,
            "total_mw": int(total_mw),
            "n_sites": len(idx),
            "label": label,
            "radius_m": int(radius_m),
        }

        # Polygon ring (rendered as fill + outline)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {**props, "kind": "ring"},
        })
        # Point marker (rendered as circle + letter at the centroid)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [center_lon, center_lat]},
            "properties": {**props, "kind": "marker"},
        })
        kept += 1

    out = {"type": "FeatureCollection", "features": features}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f)
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"hot_zones: {kept} clusters ({len(features)} features) -> {OUT_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
