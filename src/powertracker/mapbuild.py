"""Folium map builder shared by the CLI script and the Streamlit app.

`load_data()` returns every DataFrame and GeoJSON the map needs in one
dict. `build_folium_map(data, filters)` builds the layered folium.Map. The
CLI saves it; the Streamlit app embeds it.

Loading prefers `data/cache/*.csv` (pre-computed by
`scripts/build_aggregates.py`) so the hosted app starts fast without
needing EIA/BEA raw data or an API key. Falls back to raw recomputation
if a cache file is missing.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import HeatMap

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SITES_CSV = REPO_ROOT / "data" / "sites" / "data_centers.csv"
CACHE_DIR = REPO_ROOT / "data" / "cache"
BA_GEOJSON = REPO_ROOT / "data" / "geo" / "ba_territories.geojson"
COUNTY_GEOJSON = REPO_ROOT / "data" / "geo" / "us_counties.geojson"
UTILITY_GEOJSON = REPO_ROOT / "data" / "geo" / "utility_territories.geojson"

_DIST_OWNERSHIP = {"Investor Owned", "Cooperative", "Municipal", "Federal", "Political Subdivision", "State"}
_NON_DIST_TYPES = {"MARKETER"}

GROWTH_BINS: list[tuple[float, str, str]] = [
    (-100.0, "#5b8db8", "< -2%"),
    (-2.0,   "#a8c5dd", "-2 to 0%"),
    ( 0.0,   "#eeeeee", "0 to 1%"),
    ( 1.0,   "#fff5b8", "1 to 3% (baseline)"),
    ( 3.0,   "#fbb04e", "3 to 5%"),
    ( 5.0,   "#f4733c", "5 to 8%"),
    ( 8.0,   "#d7263d", ">= 8% (anomalous)"),
]
NO_DATA_COLOR = "#dddddd"

FOCUS_COLORS = {"primary": "#d7263d", "mixed": "#2e86ab", "minimal": "#9e9e9e"}
STATUS_OPACITY = {"operational": 0.85, "under_construction": 0.65, "announced": 0.45, "proposed": 0.30, "planned": 0.30}

UNKNOWN_MW_RADIUS = 5
MIN_RADIUS = 4
MAX_RADIUS = 26
DEFAULT_HEATMAP_MW = 150
CLUSTER_RADIUS_MI = 80.0

TIERS = [
    ("S", 5000, "#7a0019"),
    ("A", 2000, "#d7263d"),
    ("B", 1000, "#f46036"),
    ("C",  500, "#f5a623"),
    ("D",    0, "#9e9e9e"),
]


@dataclass
class MapData:
    sites: pd.DataFrame
    ba_yoy: pd.DataFrame
    util_yoy: pd.DataFrame
    gdp_yoy: pd.DataFrame
    ba_geo: dict | None
    util_geo: dict | None
    county_geo: dict | None


@dataclass
class MapFilters:
    focus: set[str] | None = None       # subset of {primary, mixed, minimal}
    status: set[str] | None = None      # subset of {operational, under_construction, announced, proposed, planned}
    states: set[str] | None = None      # 2-letter state codes
    show_layers: set[str] = field(default_factory=lambda: {
        "ba_demand", "utility_rates", "gdp", "sites", "zones", "heatmap"
    })


# ---------- loaders ----------

def _load_geojson(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_data(use_cache: bool = True) -> MapData:
    """Load all data the map needs. Prefers cached aggregates.

    If `use_cache=False`, recomputes YoY from raw EIA/BEA data
    (requires the raw files under `data/raw/`).
    """
    sites = pd.read_csv(SITES_CSV)
    sites["announced_mw"] = pd.to_numeric(sites["announced_mw"], errors="coerce")

    ba_path = CACHE_DIR / "ba_demand_yoy.csv"
    util_path = CACHE_DIR / "utility_rate_yoy.csv"
    gdp_path = CACHE_DIR / "county_gdp_yoy.csv"

    if use_cache and ba_path.exists():
        ba_yoy = pd.read_csv(ba_path)
    else:
        from powertracker.demand import yoy_growth  # local import keeps app deps lean
        ba_yoy = yoy_growth(pd.Timestamp("today").normalize())

    if use_cache and util_path.exists():
        util_yoy = pd.read_csv(util_path)
    else:
        from powertracker.prices import yoy_residential
        util_yoy = yoy_residential(2024)

    if use_cache and gdp_path.exists():
        gdp_yoy = pd.read_csv(gdp_path, dtype={"fips": str})
    else:
        from powertracker.gdp import yoy_per_capita_gdp
        gdp_yoy = yoy_per_capita_gdp(2024)

    # fips needs to be a 5-character zero-padded string for the join.
    if "fips" in gdp_yoy.columns:
        gdp_yoy["fips"] = gdp_yoy["fips"].astype(str).str.zfill(5)

    return MapData(
        sites=sites,
        ba_yoy=ba_yoy,
        util_yoy=util_yoy,
        gdp_yoy=gdp_yoy,
        ba_geo=_load_geojson(BA_GEOJSON),
        util_geo=_load_geojson(UTILITY_GEOJSON),
        county_geo=_load_geojson(COUNTY_GEOJSON),
    )


# ---------- helpers ----------

def radius_for_mw(mw: float | None) -> float:
    if mw is None or pd.isna(mw):
        return UNKNOWN_MW_RADIUS
    r = math.sqrt(mw) * 0.6
    return max(MIN_RADIUS, min(MAX_RADIUS, r))


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _cluster_sites(df: pd.DataFrame, radius_mi: float = CLUSTER_RADIUS_MI) -> list[list[int]]:
    clusters: list[list[int]] = []
    coords = list(zip(df["lat"].tolist(), df["lon"].tolist()))
    for i, (lat, lon) in enumerate(coords):
        placed = False
        for cluster in clusters:
            for j in cluster:
                if _haversine_mi(lat, lon, coords[j][0], coords[j][1]) <= radius_mi:
                    cluster.append(i)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            clusters.append([i])
    return clusters


def _tier_for_mw(total_mw: float) -> tuple[str, str]:
    for name, cutoff, color in TIERS:
        if total_mw >= cutoff:
            return name, color
    return "D", TIERS[-1][2]


def _cluster_label(df: pd.DataFrame, idx: list[int]) -> str:
    sub = df.iloc[idx]
    with_mw = sub[sub["announced_mw"].notna()]
    if not with_mw.empty:
        top = with_mw.loc[with_mw["announced_mw"].idxmax()]
        return f"{top['city']}, {top['state']}"
    s = sub.iloc[0]
    return f"{s['city']}, {s['state']}"


def color_for_growth(pct: float | None) -> str:
    if pct is None or pd.isna(pct):
        return NO_DATA_COLOR
    chosen = NO_DATA_COLOR
    for lower, color, _ in GROWTH_BINS:
        if pct >= lower:
            chosen = color
        else:
            break
    return chosen


def _site_popup(row: pd.Series) -> str:
    mw = "n/a" if pd.isna(row.announced_mw) else f"{int(row.announced_mw):,} MW"
    notes = row.notes if isinstance(row.notes, str) and row.notes else ""
    return (
        f"<div style='font-family:system-ui;font-size:12px;min-width:240px'>"
        f"<div style='font-weight:600;font-size:13px;margin-bottom:4px'>{row['name']}</div>"
        f"<div><b>Operator:</b> {row.operator}</div>"
        f"<div><b>Location:</b> {row.city}, {row.state}</div>"
        f"<div><b>BA:</b> {row.ba_code} ({row.utility})</div>"
        f"<div><b>Capacity:</b> {mw}</div>"
        f"<div><b>Status:</b> {row.status} ({row.online_year})</div>"
        f"<div><b>AI focus:</b> {row.ai_focus}</div>"
        + (f"<div style='margin-top:4px;color:#444'>{notes}</div>" if notes else "")
        + f"<div style='margin-top:6px'><a href='{row.source}' target='_blank'>source</a></div>"
        f"</div>"
    )


def _mw_str(mw: float | None) -> str:
    return "n/a" if mw is None or pd.isna(mw) else f"{int(mw):,} MW"


def _cluster_popup(label: str, tier: str, total_mw: float, n: int, members: pd.DataFrame) -> str:
    rows = "".join(
        f"<div>- {r['name']} ({r['operator']}, {_mw_str(r['announced_mw'])})</div>"
        for _, r in members.iterrows()
    )
    return (
        f"<div style='font-family:system-ui;font-size:12px;min-width:260px'>"
        f"<div style='font-weight:600;font-size:13px;margin-bottom:4px'>"
        f"Tier {tier} - {label}</div>"
        f"<div><b>Sites:</b> {n}</div>"
        f"<div><b>Stated MW:</b> {int(total_mw):,}</div>"
        f"<div style='margin-top:6px;font-size:11px;color:#444'>{rows}</div>"
        f"</div>"
    )


def _bin_row(color: str, label: str) -> str:
    return (
        f"<div style='display:flex;align-items:center;margin:2px 0'>"
        f"<span style='display:inline-block;width:14px;height:10px;"
        f"background:{color};margin-right:6px;border:1px solid #999'></span>{label}</div>"
    )


def _build_legend() -> folium.Element:
    growth_rows = "".join(_bin_row(c, l) for _, c, l in GROWTH_BINS) + _bin_row(NO_DATA_COLOR, "no data")
    focus_rows = "".join(
        f"<div style='display:flex;align-items:center;margin:2px 0'>"
        f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;"
        f"background:{FOCUS_COLORS[k]};margin-right:6px'></span>{k}</div>"
        for k in ("primary", "mixed", "minimal")
    )
    tier_rows = "".join(
        f"<div style='display:flex;align-items:center;margin:2px 0'>"
        f"<span style='display:inline-block;width:14px;height:14px;border-radius:50%;"
        f"background:{color};color:#fff;text-align:center;font-size:10px;line-height:14px;"
        f"margin-right:6px;font-weight:700'>{name}</span>"
        f"{'>= ' + str(cutoff) + ' MW' if cutoff > 0 else '< 500 MW or unknown'}</div>"
        for name, cutoff, color in TIERS
    )
    html = f"""
    <div style="position: fixed; bottom: 24px; left: 24px; z-index: 1000;
                background: rgba(255,255,255,0.95); padding: 10px 12px;
                border: 1px solid #ccc; border-radius: 6px;
                font-family: system-ui; font-size: 12px; line-height: 1.4;
                max-width: 240px; max-height: 92vh; overflow-y: auto;">
      <div style="font-weight:600;margin-bottom:4px">% vs 3-yr baseline</div>
      {growth_rows}
      <div style="color:#444;font-size:11px;margin-top:4px">
        applies to BA demand (trailing 12mo vs mean of 3 prior),
        utility residential rate, and per-capita real GDP
      </div>
      <div style="font-weight:600;margin-top:8px;margin-bottom:4px">AI focus</div>
      {focus_rows}
      <div style="font-weight:600;margin-top:8px;margin-bottom:4px">Hot zone tier</div>
      {tier_rows}
      <div style="font-weight:600;margin-top:8px;margin-bottom:4px">Marker size</div>
      <div style="color:#444">area proportional to announced MW</div>
      <div style="font-weight:600;margin-top:8px;margin-bottom:4px">Opacity</div>
      <div style="color:#444">operational &gt; construction &gt; announced</div>
    </div>
    """
    return folium.Element(html)


# ---------- layer builders ----------

def _add_gdp_layer(m: folium.Map, data: MapData, filters: MapFilters) -> int:
    if "gdp" not in filters.show_layers or data.county_geo is None or data.gdp_yoy.empty:
        return 0
    gdp_by_fips = {row.fips: row for _, row in data.gdp_yoy.iterrows()}
    for feat in data.county_geo["features"]:
        fips = str(feat.get("id") or feat["properties"].get("GEO_ID", "")[-5:])
        row = gdp_by_fips.get(fips)
        name = feat["properties"].get("NAME", "?")
        if row is None:
            feat["properties"]["_fill"] = NO_DATA_COLOR
            feat["properties"]["_op"] = 0.20
            feat["properties"]["_tip"] = f"<b>{name} (FIPS {fips})</b><br>no GDP data"
        else:
            pct = float(row.growth_pct)
            sign = "+" if pct >= 0 else ""
            feat["properties"]["_fill"] = color_for_growth(pct)
            feat["properties"]["_op"] = 0.65
            feat["properties"]["_tip"] = (
                f"<b>{row.geoname}</b><br>"
                f"per-capita real GDP vs 3yr baseline: <b>{sign}{pct:.2f}%</b><br>"
                f"baseline (mean {int(row.baseline_start_year)}-{int(row.baseline_end_year)}): "
                f"${row.gdp_per_capita_baseline:,.0f}<br>"
                f"current: ${row.gdp_per_capita_current:,.0f}<br>"
                f"population: {row.population:,.0f}"
            )
    layer = folium.FeatureGroup(name=f"per-capita real GDP vs 3yr baseline (n={len(data.gdp_yoy)})", show=False)
    folium.GeoJson(
        data.county_geo,
        style_function=lambda f: {
            "fillColor": f["properties"]["_fill"],
            "fillOpacity": f["properties"]["_op"],
            "color": "#888",
            "weight": 0.3,
        },
        tooltip=folium.GeoJsonTooltip(fields=["_tip"], labels=False),
    ).add_to(layer)
    m.add_child(layer)
    return len(data.gdp_yoy)


def _add_utility_layer(m: folium.Map, data: MapData, filters: MapFilters) -> int:
    if "utility_rates" not in filters.show_layers or data.util_geo is None or data.util_yoy.empty:
        return 0
    yoy = data.util_yoy[data.util_yoy.ownership.isin(_DIST_OWNERSHIP)]
    yoy_us = {(int(r.utility_id), r.state): r for _, r in yoy.iterrows()}
    nat_agg = (
        yoy.groupby("utility_id")
        .apply(lambda d: (d.price_change_pct * d.sales_mwh).sum() / d.sales_mwh.sum(), include_groups=False)
        .to_dict()
    )
    kept: list[dict] = []
    for feat in data.util_geo["features"]:
        props = feat["properties"]
        if props.get("type") in _NON_DIST_TYPES:
            continue
        eid = props.get("eia_id")
        state = props.get("state")
        if eid is None:
            continue
        if filters.states and state not in filters.states:
            continue
        eid_i = int(eid)
        r = yoy_us.get((eid_i, state))
        nat = nat_agg.get(eid_i)
        uname = props.get("utility_name") or "?"
        utype = props.get("type") or "(unknown type)"
        if r is not None:
            pct = r.price_change_pct
            sign = "+" if pct >= 0 else ""
            props["_tip"] = (
                f"<b>{uname}</b> ({utype}, {state})<br>"
                f"baseline (mean {int(r.baseline_start_year)}-{int(r.baseline_end_year)}): "
                f"{r.price_baseline:.2f} c/kWh<br>"
                f"current: {r.price_current:.2f} c/kWh<br>"
                f"change: <b>{sign}{pct:.1f}%</b><br>"
                f"residential customers: {r.customers:,.0f}"
            )
        elif nat is not None:
            pct = nat
            sign = "+" if pct >= 0 else ""
            props["_tip"] = (
                f"<b>{uname}</b> ({utype}, {state})<br>"
                f"national sales-weighted change: <b>{sign}{pct:.1f}%</b><br>"
                f"(no row for this state)"
            )
        else:
            continue
        props["_fill"] = color_for_growth(pct)
        kept.append(feat)

    layer = folium.FeatureGroup(name=f"utility resi rate vs 3yr baseline (n={len(kept)})", show=False)
    folium.GeoJson(
        {"type": "FeatureCollection", "features": kept},
        style_function=lambda f: {
            "fillColor": f["properties"]["_fill"],
            "fillOpacity": 0.6,
            "color": "#666",
            "weight": 0.3,
        },
        tooltip=folium.GeoJsonTooltip(fields=["_tip"], labels=False),
    ).add_to(layer)
    m.add_child(layer)
    return len(kept)


def _add_ba_demand_layer(m: folium.Map, data: MapData, filters: MapFilters) -> int:
    if "ba_demand" not in filters.show_layers or data.ba_geo is None or data.ba_yoy.empty:
        return 0
    growth_by_ba = {row.ba: row for _, row in data.ba_yoy.iterrows()}
    for feat in data.ba_geo["features"]:
        ba = feat["properties"].get("ba_code")
        entry = growth_by_ba.get(ba)
        if entry is None:
            feat["properties"]["_fill"] = NO_DATA_COLOR
            feat["properties"]["_op"] = 0.20
            feat["properties"]["_tip"] = f"<b>{ba}</b><br>no demand data fetched"
        else:
            sign = "+" if entry.growth_pct >= 0 else ""
            feat["properties"]["_fill"] = color_for_growth(entry.growth_pct)
            feat["properties"]["_op"] = 0.55
            feat["properties"]["_tip"] = (
                f"<b>{ba}</b><br>"
                f"vs 3yr baseline: <b>{sign}{entry.growth_pct:.2f}%</b><br>"
                f"trailing 12mo mean: {entry.trailing_mw:,.0f} MW<br>"
                f"baseline (mean of 3 prior trailing-12 windows): {entry.baseline_mw:,.0f} MW"
            )
    layer = folium.FeatureGroup(name=f"BA demand vs 3yr baseline (n={len(data.ba_yoy)})", show=True)
    folium.GeoJson(
        data.ba_geo,
        style_function=lambda f: {
            "fillColor": f["properties"]["_fill"],
            "fillOpacity": f["properties"]["_op"],
            "color": "#666",
            "weight": 0.6,
        },
        tooltip=folium.GeoJsonTooltip(fields=["_tip"], labels=False),
    ).add_to(layer)
    m.add_child(layer)
    return len(data.ba_yoy)


def _add_site_markers(m: folium.Map, sites: pd.DataFrame, filters: MapFilters) -> dict[str, int]:
    counts: dict[str, int] = {}
    if "sites" not in filters.show_layers:
        return counts
    site_layers = {
        k: folium.FeatureGroup(name=f"sites: {k}", show=True)
        for k in ("primary", "mixed", "minimal")
    }
    for _, row in sites.iterrows():
        focus = row.ai_focus if row.ai_focus in FOCUS_COLORS else "mixed"
        color = FOCUS_COLORS[focus]
        opacity = STATUS_OPACITY.get(row.status, 0.7)
        folium.CircleMarker(
            location=(row.lat, row.lon),
            radius=radius_for_mw(row.announced_mw),
            color=color,
            weight=1.2,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            tooltip=f"{row['name']} ({row.operator})",
            popup=folium.Popup(_site_popup(row), max_width=320),
        ).add_to(site_layers[focus])
        counts[focus] = counts.get(focus, 0) + 1
    for k, layer in site_layers.items():
        layer.layer_name = f"sites: {k} (n={counts.get(k, 0)})"
        m.add_child(layer)
    return counts


def _add_heatmap(m: folium.Map, sites: pd.DataFrame, filters: MapFilters) -> None:
    if "heatmap" not in filters.show_layers:
        return
    heat_data = [
        [row.lat, row.lon, row.announced_mw if not pd.isna(row.announced_mw) else DEFAULT_HEATMAP_MW]
        for _, row in sites.iterrows()
    ]
    heat_layer = folium.FeatureGroup(name="MW heatmap", show=False)
    HeatMap(heat_data, radius=28, blur=22, min_opacity=0.3, max_zoom=6).add_to(heat_layer)
    m.add_child(heat_layer)


def _add_hot_zones(m: folium.Map, sites: pd.DataFrame, filters: MapFilters) -> list[dict]:
    summary: list[dict] = []
    if "zones" not in filters.show_layers:
        return summary
    clusters = _cluster_sites(sites)
    zone_layer = folium.FeatureGroup(name="hot zones (tiers)", show=True)
    for idx in clusters:
        sub = sites.iloc[idx]
        total_mw = float(sub["announced_mw"].fillna(0).sum())
        tier, tier_color = _tier_for_mw(total_mw)
        cx = float(sub["lat"].mean())
        cy = float(sub["lon"].mean())
        label = _cluster_label(sites, idx)
        summary.append({"label": label, "tier": tier, "sites": len(idx), "total_mw": int(total_mw)})
        if tier == "D" and len(idx) < 3:
            continue
        ring_radius_m = max(20_000, math.sqrt(max(total_mw, 100)) * 1_400)
        folium.Circle(
            location=(cx, cy),
            radius=ring_radius_m,
            color=tier_color,
            weight=1.5,
            fill=True,
            fill_color=tier_color,
            fill_opacity=0.10,
            tooltip=f"Tier {tier} - {label} ({len(idx)} sites, {int(total_mw):,} MW stated)",
            popup=folium.Popup(_cluster_popup(label, tier, total_mw, len(idx), sub), max_width=340),
        ).add_to(zone_layer)
        folium.map.Marker(
            location=(cx, cy),
            icon=folium.DivIcon(
                icon_size=(28, 28),
                icon_anchor=(14, 14),
                html=(
                    f"<div style='width:28px;height:28px;border-radius:50%;"
                    f"background:{tier_color};color:#fff;font-weight:700;"
                    f"font-family:system-ui;font-size:14px;line-height:28px;"
                    f"text-align:center;border:2px solid #fff;"
                    f"box-shadow:0 1px 4px rgba(0,0,0,0.3)'>{tier}</div>"
                ),
            ),
        ).add_to(zone_layer)
    m.add_child(zone_layer)
    return summary


# ---------- public entry ----------

def _filtered_sites(sites: pd.DataFrame, filters: MapFilters) -> pd.DataFrame:
    df = sites
    if filters.focus:
        df = df[df["ai_focus"].isin(filters.focus)]
    if filters.status:
        df = df[df["status"].isin(filters.status)]
    if filters.states:
        df = df[df["state"].isin(filters.states)]
    return df.reset_index(drop=True)


def _initial_view(filters: MapFilters, sites: pd.DataFrame) -> tuple[tuple[float, float], int]:
    """Center + zoom. State filter zooms to the state's site centroid."""
    if filters.states and not sites.empty:
        return (float(sites["lat"].mean()), float(sites["lon"].mean())), 6
    return (39.5, -97.0), 4


def build_folium_map(data: MapData, filters: MapFilters | None = None) -> tuple[folium.Map, dict]:
    """Build the layered folium.Map for the given data + filters.

    Returns (map, summary_dict) where summary_dict has counts useful for UI.
    """
    filters = filters or MapFilters()
    sites_f = _filtered_sites(data.sites, filters)

    center, zoom = _initial_view(filters, sites_f)
    m = folium.Map(location=list(center), zoom_start=zoom, tiles="CartoDB positron", control_scale=True)

    # Order matters for stacking: choropleths under markers/zones.
    n_gdp = _add_gdp_layer(m, data, filters)
    n_util = _add_utility_layer(m, data, filters)
    n_ba = _add_ba_demand_layer(m, data, filters)
    site_counts = _add_site_markers(m, sites_f, filters)
    _add_heatmap(m, sites_f, filters)
    zones = _add_hot_zones(m, sites_f, filters)

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(_build_legend())

    return m, {
        "n_sites": len(sites_f),
        "n_sites_total": len(data.sites),
        "n_ba": n_ba,
        "n_util": n_util,
        "n_gdp": n_gdp,
        "site_counts": site_counts,
        "zones": zones,
    }
