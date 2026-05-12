"""Generate PMTiles vector tile pyramids for the MapLibre frontend.

Pipeline:
  1. Load each source GeoJSON.
  2. Inject per-feature YoY/rate/GDP attributes from the cached aggregates
     so the tiles carry everything the map renderer needs (no client-side
     join). Also stamp a coarse `_bin` integer so the frontend can match it
     against a fixed color palette via a MapLibre `match` expression.
  3. Write enriched GeoJSONs to a temp dir.
  4. Run `tippecanoe` (Docker) -> .mbtiles per layer.
  5. Run `go-pmtiles convert` (Docker) -> .pmtiles per layer.
  6. Emit a tiny `sites.geojson` for the point layer (small enough to load
     inline in the frontend).

Output: `app/tiles/{ba,utility,county}.pmtiles` and `app/sites.geojson`.

Requires Docker. Pull on first run:
  docker pull klokantech/tippecanoe
  docker pull ghcr.io/protomaps/go-pmtiles:latest
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from powertracker.mapbuild import _DIST_OWNERSHIP, GROWTH_BINS, load_data  # noqa: E402

OUT_DIR = REPO_ROOT / "app" / "tiles"
SITES_OUT = REPO_ROOT / "app" / "sites.geojson"
TMP_DIR = REPO_ROOT / "data" / "tiles_tmp"
ELECTION_CSV = REPO_ROOT / "data" / "cache" / "election_2024_county.csv"

NO_DATA_BIN = -1

# Diverging GOP-margin bins for the 2024 presidential map. Margin = per_gop -
# per_dem (signed percentage points). Bin indices 0..6 map onto a blue->red
# palette in the MapLibre style. Kept here (not in mapbuild.py) because they
# only affect tile-time enrichment for the election layer.
ELECTION_BINS: list[tuple[float, str]] = [
    (-100.0, "Dem +25 or more"),
    (-25.0,  "Dem +10 to +25"),
    (-10.0,  "Dem +3 to +10"),
    ( -3.0,  "tossup (within 3)"),
    (  3.0,  "Rep +3 to +10"),
    ( 10.0,  "Rep +10 to +25"),
    ( 25.0,  "Rep +25 or more"),
]


def growth_bin(pct: float | None) -> int:
    """Bin index into GROWTH_BINS, or NO_DATA_BIN if missing."""
    if pct is None or pd.isna(pct):
        return NO_DATA_BIN
    chosen = NO_DATA_BIN
    for i, (lower, _, _) in enumerate(GROWTH_BINS):
        if pct >= lower:
            chosen = i
        else:
            break
    return chosen


def election_bin(margin_pct: float | None) -> int:
    """Bin index into ELECTION_BINS (GOP margin in pp), or NO_DATA_BIN."""
    if margin_pct is None or pd.isna(margin_pct):
        return NO_DATA_BIN
    chosen = NO_DATA_BIN
    for i, (lower, _) in enumerate(ELECTION_BINS):
        if margin_pct >= lower:
            chosen = i
        else:
            break
    return chosen


# ---------- per-layer feature enrichment ----------

def _enrich_ba(geo: dict, ba_yoy: pd.DataFrame) -> dict:
    lookup = {r.ba: r for _, r in ba_yoy.iterrows()}
    for feat in geo["features"]:
        ba = feat["properties"].get("ba_code")
        r = lookup.get(ba)
        props = feat["properties"]
        # Clear anything we don't want shipped in tiles to keep size down.
        for k in list(props.keys()):
            if k not in ("ba_code", "region"):
                props.pop(k, None)
        if r is None:
            props["growth_pct"] = None
            props["bin"] = NO_DATA_BIN
        else:
            props["growth_pct"] = float(r.growth_pct)
            props["trailing_mw"] = float(r.trailing_mw)
            props["prior_mw"] = float(r.prior_mw)
            props["bin"] = growth_bin(float(r.growth_pct))
    return geo


def _enrich_utility(geo: dict, util_yoy: pd.DataFrame) -> dict:
    yoy = util_yoy[util_yoy["ownership"].isin(_DIST_OWNERSHIP)]
    yoy_us = {(int(r.utility_id), r.state): r for _, r in yoy.iterrows()}
    nat_agg = (
        yoy.groupby("utility_id")
        .apply(lambda d: (d.price_change_pct * d.sales_mwh).sum() / d.sales_mwh.sum(), include_groups=False)
        .to_dict()
    )
    kept = []
    for feat in geo["features"]:
        props = feat["properties"]
        if props.get("type") == "MARKETER":
            continue
        eid = props.get("eia_id")
        state = props.get("state")
        if eid is None:
            continue
        r = yoy_us.get((int(eid), state))
        nat = nat_agg.get(int(eid))
        if r is not None:
            props["price_2023"] = float(r.price_2023)
            props["price_2024"] = float(r.price_2024)
            props["change_pct"] = float(r.price_change_pct)
            props["customers"] = int(r.customers) if not pd.isna(r.customers) else None
            props["source"] = "state"
            props["bin"] = growth_bin(float(r.price_change_pct))
        elif nat is not None:
            props["change_pct"] = float(nat)
            props["source"] = "national"
            props["bin"] = growth_bin(float(nat))
        else:
            continue
        # Strip fields we don't ship to keep tile size down.
        for k in list(props.keys()):
            if k not in {"eia_id", "utility_name", "type", "state",
                          "price_2023", "price_2024", "change_pct",
                          "customers", "source", "bin"}:
                props.pop(k, None)
        kept.append(feat)
    geo["features"] = kept
    return geo


def _enrich_election(geo: dict, election: pd.DataFrame) -> dict:
    """Build a fresh GeoJSON of county polygons annotated with 2024
    presidential results. We copy `geo` (not mutate) because the county
    layer uses the same source for its GDP enrichment."""
    election = election.copy()
    election["county_fips"] = election["county_fips"].astype(str).str.zfill(5)
    lookup = {r.county_fips: r for _, r in election.iterrows()}
    out_features = []
    for feat in geo["features"]:
        fips = str(feat.get("id") or feat["properties"].get("GEO_ID", "")[-5:])
        name = feat["properties"].get("NAME", "?")
        r = lookup.get(fips)
        props: dict = {"fips": fips, "name": name}
        if r is None:
            props["margin_pct"] = None
            props["bin"] = NO_DATA_BIN
        else:
            margin_pct = float(r.per_point_diff) * 100.0
            props["margin_pct"] = margin_pct
            props["per_gop"] = float(r.per_gop)
            props["per_dem"] = float(r.per_dem)
            props["votes_gop"] = int(r.votes_gop)
            props["votes_dem"] = int(r.votes_dem)
            props["total_votes"] = int(r.total_votes)
            props["state"] = r.state_name
            props["bin"] = election_bin(margin_pct)
        out_features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": out_features}


def _enrich_county(geo: dict, gdp_yoy: pd.DataFrame) -> dict:
    if "fips" in gdp_yoy.columns:
        gdp_yoy = gdp_yoy.copy()
        gdp_yoy["fips"] = gdp_yoy["fips"].astype(str).str.zfill(5)
    lookup = {r.fips: r for _, r in gdp_yoy.iterrows()}
    for feat in geo["features"]:
        fips = str(feat.get("id") or feat["properties"].get("GEO_ID", "")[-5:])
        r = lookup.get(fips)
        props = feat["properties"]
        # Keep only NAME (for tooltip) from the source feature.
        name = props.get("NAME", "?")
        props.clear()
        props["fips"] = fips
        props["name"] = name
        if r is None:
            props["growth_pct"] = None
            props["bin"] = NO_DATA_BIN
        else:
            props["geoname"] = r.geoname
            props["growth_pct"] = float(r.growth_pct)
            props["gdp_per_capita_2023"] = float(r.gdp_per_capita_2023)
            props["gdp_per_capita_2024"] = float(r.gdp_per_capita_2024)
            props["population"] = float(r.population_2024)
            props["bin"] = growth_bin(float(r.growth_pct))
    return geo


# ---------- Docker invocations ----------

def _docker_paths(local: Path) -> tuple[str, str]:
    """Return (linux-style mount path, posix-style bind mount source) usable
    on Windows Docker Desktop. Docker accepts native Windows absolute paths
    in -v on recent versions, so we just stringify."""
    return str(local.resolve()), local.resolve().as_posix()


def _run_tippecanoe(geojson_path: Path, mbtiles_path: Path, layer_name: str, max_zoom: int) -> None:
    """Run tippecanoe in Docker, mounting the repo so it can read input and
    write output in place."""
    work_dir = REPO_ROOT.resolve()
    rel_in = geojson_path.resolve().relative_to(work_dir).as_posix()
    rel_out = mbtiles_path.resolve().relative_to(work_dir).as_posix()
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_dir}:/work",
        "-w", "/work",
        "klokantech/tippecanoe",
        "tippecanoe",
        "-o", f"/work/{rel_out}",
        "--force",
        "--layer", layer_name,
        "-Z", "3",
        "-z", str(max_zoom),
        "--drop-densest-as-needed",
        "--no-tile-size-limit",
        f"/work/{rel_in}",
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def _run_pmtiles_convert(mbtiles_path: Path, pmtiles_path: Path) -> None:
    work_dir = REPO_ROOT.resolve()
    rel_in = mbtiles_path.resolve().relative_to(work_dir).as_posix()
    rel_out = pmtiles_path.resolve().relative_to(work_dir).as_posix()
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_dir}:/work",
        "-w", "/work",
        "ghcr.io/protomaps/go-pmtiles:latest",
        "convert",
        f"/work/{rel_in}",
        f"/work/{rel_out}",
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


# ---------- main pipeline ----------

def _build_one(name: str, geojson: dict, layer_name: str, max_zoom: int) -> Path:
    src = TMP_DIR / f"{name}.geojson"
    with open(src, "w", encoding="utf-8") as f:
        json.dump(geojson, f)
    mbt = TMP_DIR / f"{name}.mbtiles"
    if mbt.exists():
        mbt.unlink()
    _run_tippecanoe(src, mbt, layer_name, max_zoom)
    pm = OUT_DIR / f"{name}.pmtiles"
    if pm.exists():
        pm.unlink()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _run_pmtiles_convert(mbt, pm)
    print(f"  {name}.pmtiles {pm.stat().st_size/1024:.1f} KB")
    return pm


def main() -> None:
    data = load_data(use_cache=True)
    if data.ba_geo is None or data.util_geo is None or data.county_geo is None:
        sys.exit("Missing GeoJSON sources under data/geo/")

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print("BA layer ...")
    _build_one("ba", _enrich_ba(data.ba_geo, data.ba_yoy), "ba", max_zoom=8)

    print("\nUtility layer ...")
    _build_one("utility", _enrich_utility(data.util_geo, data.util_yoy), "utility", max_zoom=10)

    print("\nCounty layer ...")
    _build_one("county", _enrich_county(data.county_geo, data.gdp_yoy), "county", max_zoom=9)

    if ELECTION_CSV.exists():
        print("\nElection layer ...")
        election = pd.read_csv(ELECTION_CSV, dtype={"county_fips": str})
        _build_one("election", _enrich_election(data.county_geo, election), "election", max_zoom=9)
    else:
        print(f"\nSkipping election layer ({ELECTION_CSV} missing).")

    shutil.rmtree(TMP_DIR, ignore_errors=True)

    # Sites: small enough to ship as a static GeoJSON (no tippecanoe needed).
    sites = data.sites
    sites_geo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(r.lon), float(r.lat)]},
                "properties": {
                    "name": r["name"],
                    "operator": r.operator,
                    "city": r.city,
                    "state": r.state,
                    "ba_code": r.ba_code,
                    "utility": r.utility,
                    "announced_mw": None if pd.isna(r.announced_mw) else float(r.announced_mw),
                    "status": r.status,
                    "online_year": None if pd.isna(r.online_year) else int(r.online_year),
                    "ai_focus": r.ai_focus,
                    "notes": r.notes if isinstance(r.notes, str) else "",
                    "source": r.source if isinstance(r.source, str) else "",
                },
            }
            for _, r in sites.iterrows()
        ],
    }
    SITES_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(SITES_OUT, "w", encoding="utf-8") as f:
        json.dump(sites_geo, f)
    print(f"\nSites: {len(sites)} -> {SITES_OUT} ({SITES_OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
