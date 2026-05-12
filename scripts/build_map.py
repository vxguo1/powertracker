"""Render data_centers.csv as an interactive HTML map.

Layers:
  - Markers per site, colored by ai_focus, sized by announced_mw,
    opacity by status. Toggle each ai_focus group from the layer control.
  - MW-weighted heatmap (toggleable).
  - Hot-zone overlays: nearby sites are clustered by haversine proximity
    (default ~80 mi), each cluster gets a tier S/A/B/C/D badge from total
    announced MW, drawn as a translucent ring scaled by MW.

Output: data/maps/data_centers.html
"""

import math
import sys
from pathlib import Path

import folium
import pandas as pd
from folium.plugins import HeatMap

REPO_ROOT = Path(__file__).resolve().parent.parent
SITES_CSV = REPO_ROOT / "data" / "sites" / "data_centers.csv"
OUT_DIR = REPO_ROOT / "data" / "maps"
OUT_FILE = OUT_DIR / "data_centers.html"

FOCUS_COLORS = {
    "primary": "#d7263d",
    "mixed": "#2e86ab",
    "minimal": "#9e9e9e",
}

STATUS_OPACITY = {
    "operational": 0.85,
    "under_construction": 0.65,
    "announced": 0.45,
    "planned": 0.35,
}

UNKNOWN_MW_RADIUS = 5
MIN_RADIUS = 4
MAX_RADIUS = 26

# Used as a heatmap-only weight floor when announced_mw is missing, so that
# sites without a stated MW still contribute to the density layer. Not used
# anywhere capacity is reported numerically.
DEFAULT_HEATMAP_MW = 150

# Hot-zone clustering: greedy single-link with haversine distance.
CLUSTER_RADIUS_MI = 80.0

# Tier cutoffs by sum of announced_mw within a cluster (only counts sites
# with a stated MW). A cluster with no stated MW falls into tier D.
TIERS = [
    ("S", 5000, "#7a0019"),  # >= 5 GW
    ("A", 2000, "#d7263d"),  # >= 2 GW
    ("B", 1000, "#f46036"),  # >= 1 GW
    ("C",  500, "#f5a623"),  # >= 500 MW
    ("D",    0, "#9e9e9e"),  # < 500 MW or unknown
]


def radius_for_mw(mw: float | None) -> float:
    if mw is None or math.isnan(mw):
        return UNKNOWN_MW_RADIUS
    r = math.sqrt(mw) * 0.6
    return max(MIN_RADIUS, min(MAX_RADIUS, r))


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def cluster_sites(df: pd.DataFrame, radius_mi: float) -> list[list[int]]:
    """Greedy single-link clustering: assign each site to the cluster whose
    nearest existing member is within radius_mi; otherwise start a new
    cluster. Order-dependent but fine for ~100 points."""
    clusters: list[list[int]] = []
    coords = list(zip(df["lat"].tolist(), df["lon"].tolist()))
    for i, (lat, lon) in enumerate(coords):
        placed = False
        for cluster in clusters:
            for j in cluster:
                if haversine_mi(lat, lon, coords[j][0], coords[j][1]) <= radius_mi:
                    cluster.append(i)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            clusters.append([i])
    return clusters


def tier_for_mw(total_mw: float) -> tuple[str, str]:
    for name, cutoff, color in TIERS:
        if total_mw >= cutoff:
            return name, color
    return "D", TIERS[-1][2]


def cluster_label(df: pd.DataFrame, idx: list[int]) -> str:
    """Name the cluster after the largest-MW site, falling back to the city
    that appears most often, falling back to first site."""
    sub = df.iloc[idx]
    with_mw = sub[sub["announced_mw"].notna()]
    if not with_mw.empty:
        top = with_mw.loc[with_mw["announced_mw"].idxmax()]
        return f"{top['city']}, {top['state']}"
    common_city = sub["city"].mode()
    if not common_city.empty:
        s = sub[sub["city"] == common_city.iloc[0]].iloc[0]
        return f"{s['city']}, {s['state']}"
    s = sub.iloc[0]
    return f"{s['city']}, {s['state']}"


def popup_html(row: pd.Series) -> str:
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


def cluster_popup_html(label: str, tier: str, total_mw: float, n: int, members: pd.DataFrame) -> str:
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


def build_legend() -> folium.Element:
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
                max-width: 220px;">
      <div style="font-weight:600;margin-bottom:4px">AI focus</div>
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


def main() -> None:
    if not SITES_CSV.exists():
        sys.exit(f"sites csv not found: {SITES_CSV}")

    df = pd.read_csv(SITES_CSV)
    df["announced_mw"] = pd.to_numeric(df["announced_mw"], errors="coerce")

    m = folium.Map(
        location=[39.5, -97.0],
        zoom_start=4,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # ---- per-site markers, grouped by ai_focus ----
    site_layers = {
        k: folium.FeatureGroup(name=f"sites: {k} (n={int((df.ai_focus == k).sum())})", show=True)
        for k in ("primary", "mixed", "minimal")
    }
    for _, row in df.iterrows():
        focus = row.ai_focus if row.ai_focus in FOCUS_COLORS else "mixed"
        color = FOCUS_COLORS[focus]
        opacity = STATUS_OPACITY.get(row.status, 0.7)
        marker = folium.CircleMarker(
            location=(row.lat, row.lon),
            radius=radius_for_mw(row.announced_mw),
            color=color,
            weight=1.2,
            fill=True,
            fill_color=color,
            fill_opacity=opacity,
            tooltip=f"{row['name']} ({row.operator})",
            popup=folium.Popup(popup_html(row), max_width=320),
        )
        site_layers[focus].add_child(marker)
    for layer in site_layers.values():
        m.add_child(layer)

    # ---- heatmap weighted by announced MW (with fallback floor) ----
    heat_data = [
        [row.lat, row.lon, row.announced_mw if not pd.isna(row.announced_mw) else DEFAULT_HEATMAP_MW]
        for _, row in df.iterrows()
    ]
    heat_layer = folium.FeatureGroup(name="MW heatmap", show=False)
    HeatMap(
        heat_data,
        radius=28,
        blur=22,
        min_opacity=0.3,
        max_zoom=6,
    ).add_to(heat_layer)
    m.add_child(heat_layer)

    # ---- hot-zone tier overlays ----
    clusters = cluster_sites(df, CLUSTER_RADIUS_MI)
    zone_layer = folium.FeatureGroup(name="hot zones (tiers)", show=True)
    cluster_summary: list[dict] = []
    drawn = 0
    for idx in clusters:
        sub = df.iloc[idx]
        total_mw = float(sub["announced_mw"].fillna(0).sum())
        tier, tier_color = tier_for_mw(total_mw)
        cx = float(sub["lat"].mean())
        cy = float(sub["lon"].mean())
        label = cluster_label(df, idx)

        cluster_summary.append(
            {"label": label, "tier": tier, "sites": len(idx), "total_mw": int(total_mw)}
        )

        # Suppress overlays for tier-D singletons - the site marker already
        # represents them and the empty rings just add clutter.
        if tier == "D" and len(idx) < 3:
            continue
        drawn += 1

        # Ring sized by MW; min radius keeps single-site clusters visible.
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
            popup=folium.Popup(
                cluster_popup_html(label, tier, total_mw, len(idx), sub),
                max_width=340,
            ),
        ).add_to(zone_layer)

        # Tier badge label at the centroid.
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

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(build_legend())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    m.save(str(OUT_FILE))
    print(f"wrote {OUT_FILE} ({len(df)} sites, {len(clusters)} clusters, {drawn} zones drawn)")

    # Console summary, top clusters first.
    cluster_summary.sort(key=lambda c: (-c["total_mw"], -c["sites"]))
    print("\ntop hot zones:")
    print(f"  {'tier':<5}{'label':<28}{'sites':>6}{'  stated_mw':>14}")
    for c in cluster_summary[:15]:
        print(f"  {c['tier']:<5}{c['label']:<28}{c['sites']:>6}{c['total_mw']:>14,}")


if __name__ == "__main__":
    main()
