"""Build per-county and per-site OG cards + landing pages.

Outputs:
  app/og/county/<state>-<slug>.png    1200x630 PNG per host county
  app/og/site/<slug>.png              1200x630 PNG per data-center campus
  app/county/<state>-<slug>.html      Landing page per county (OG meta -> PNG)
  app/site/<slug>.html                Landing page per campus (OG meta -> PNG)

These act as the share targets. Every URL on social ends up as a card that
shows the actual stats for that place, not the generic site banner.

Run after data_centers.csv / the cached YoY CSVs change:
    python scripts/build_locations.py
"""

from __future__ import annotations

import csv
import html
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_rankings import (  # type: ignore  # noqa: E402
    SITES_CSV,
    REALESTATE,
    PROPERTY_TAX,
    STATE_ABBR_TO_NAME,
    load_city_to_county,
    load_county_to_fips,
    load_utility_rates,
    load_fips_pct,
    lookup_fips,
    match_utility,
    operator_family,
)

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
OG_COUNTY_DIR = APP / "og" / "county"
OG_SITE_DIR = APP / "og" / "site"
COUNTY_DIR = APP / "county"
SITE_DIR = APP / "site"
TAKEAWAYS_YAML = ROOT / "data" / "takeaways.yaml"


_TAKEAWAYS: dict | None = None


def load_takeaways() -> dict:
    """Load data/takeaways.yaml lazily. Returns {} if the file is absent."""
    global _TAKEAWAYS
    if _TAKEAWAYS is None:
        if TAKEAWAYS_YAML.exists():
            with open(TAKEAWAYS_YAML, encoding="utf-8") as f_in:
                _TAKEAWAYS = yaml.safe_load(f_in) or {}
        else:
            _TAKEAWAYS = {}
    return _TAKEAWAYS


def render_takeaways_html(slug: str) -> str:
    """Build the 'Key takeaways' section for a county. Empty string when the
    slug has no entry in takeaways.yaml. The section sits between the stats
    grid and the campus list. Voice: methodology-forward, each bullet ends
    with a source line in muted color."""
    entries = load_takeaways().get(slug)
    if not entries or not entries.get("takeaways"):
        return ""
    items = []
    for t in entries["takeaways"]:
        text = (t.get("text") or "").strip()
        src = (t.get("source") or "").strip()
        if not text:
            continue
        items.append(
            f'<li><span class="t">{html.escape(text)}</span>'
            f'<span class="s">Source: {html.escape(src)}</span></li>'
        )
    if not items:
        return ""
    body = "\n    ".join(items)
    return (
        '<h2 class="section">Key takeaways</h2>\n'
        '  <ul class="takeaways">\n    '
        + body
        + '\n  </ul>'
    )


def render_demographics_html(slug: str) -> str:
    """Build the 'Local socioeconomics' section for a county. Same shape and
    styling as render_takeaways_html but pulls from the `demographics` key.
    Empty string when the slug has no demographics entry."""
    entries = load_takeaways().get(slug)
    if not entries or not entries.get("demographics"):
        return ""
    items = []
    for t in entries["demographics"]:
        text = (t.get("text") or "").strip()
        src = (t.get("source") or "").strip()
        if not text:
            continue
        items.append(
            f'<li><span class="t">{html.escape(text)}</span>'
            f'<span class="s">Source: {html.escape(src)}</span></li>'
        )
    if not items:
        return ""
    body = "\n    ".join(items)
    return (
        '<h2 class="section">Local socioeconomics</h2>\n'
        '  <ul class="takeaways">\n    '
        + body
        + '\n  </ul>'
    )


W, H = 1200, 630
BG = (255, 255, 255)
ACCENT = (215, 38, 61)        # #d7263d
INK = (26, 26, 35)             # #1a1a23
INK_MUTED = (90, 90, 110)      # #5a5a6e
INK_SOFT = (139, 139, 154)     # #8b8b9a
PANEL = (245, 245, 247)        # #f5f5f7
PANEL_INK = (26, 26, 35)
BORDER = (227, 227, 232)
HOT = (215, 38, 61)
HOT_BG = (251, 227, 231)
WARM = (184, 110, 31)
WARM_BG = (253, 240, 216)
COOL = (31, 111, 85)
COOL_BG = (216, 239, 228)

FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
FONT_REG = "C:/Windows/Fonts/segoeui.ttf"
FONT_SEMI = "C:/Windows/Fonts/segoeuisl.ttf"

# --- Mini-map colors (subdued, matches map basemap palette).
MAP_BG = (250, 250, 252)
MAP_BORDER = (220, 220, 228)
STATE_LINE = (200, 200, 210)
COUNTY_LINE = (190, 190, 200)
HOST_COUNTY_FILL = (253, 234, 238)   # tinted pink
HOST_COUNTY_OUTLINE = (215, 38, 61)
DC_OUTER = (215, 38, 61)
DC_INNER = (215, 38, 61)
NEAR_DC_OUTER = (215, 38, 61, 80)

# Power-plant fuel colors (mirrors the EIA map convention).
FUEL_COLOR = {
    "natural gas":  (255, 167, 38),
    "coal":         (97, 60, 38),
    "nuclear":      (180, 95, 220),
    "petroleum":    (140, 60, 30),
    "hydroelectric":(46, 134, 171),
    "wind":         (38, 166, 154),
    "solar":        (255, 213, 79),
    "biomass":      (124, 179, 66),
    "geothermal":   (192, 80, 77),
    "batteries":    (130, 130, 145),
    "other":        (170, 170, 180),
}


def f(size: int, bold: bool = False, semi: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_SEMI if semi else FONT_REG
    return ImageFont.truetype(path, size)


def tw(d: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont) -> int:
    l, t, r, b = d.textbbox((0, 0), s, font=font)
    return r - l


def th(d: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont) -> int:
    l, t, r, b = d.textbbox((0, 0), s, font=font)
    return b - t


def draw_bolt(d: ImageDraw.ImageDraw, x: int, y: int, scale: float) -> None:
    pts_24 = [(13, 2), (3, 14), (12, 14), (11, 22), (21, 10), (12, 10), (13, 2)]
    d.polygon([(x + px * scale, y + py * scale) for (px, py) in pts_24], fill=ACCENT)


# ----------------------------------------------------------------------
# Mini-map renderer
# ----------------------------------------------------------------------

# Module-level caches so we load each big geojson once across all cards.
_STATE_POLYS: list[tuple[tuple[float, float, float, float], list]] | None = None
_COUNTY_POLYS: dict[str, tuple[tuple[float, float, float, float], list]] | None = None
_PLANTS: list[dict] | None = None
_ALL_SITES: list[dict] | None = None


def _ring_bbox(rings: list) -> tuple[float, float, float, float]:
    """Compute (min_lon, min_lat, max_lon, max_lat) across a list of rings."""
    xs = [pt[0] for ring in rings for pt in ring]
    ys = [pt[1] for ring in rings for pt in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def _feature_polys(feature: dict) -> list[list]:
    """Return a list of rings (each ring is a list of [lon, lat]) for a
    Polygon or MultiPolygon feature. Inner holes ignored - fine for a
    silhouette-grade visualization."""
    geom = feature["geometry"]
    out = []
    if geom["type"] == "Polygon":
        out.append(geom["coordinates"][0])
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            out.append(poly[0])
    return out


def _load_states() -> list[tuple[tuple[float, float, float, float], list]]:
    global _STATE_POLYS
    if _STATE_POLYS is None:
        path = ROOT / "data" / "geo" / "us_states.geojson"
        data = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for ft in data["features"]:
            rings = _feature_polys(ft)
            if not rings:
                continue
            out.append((_ring_bbox(rings), rings))
        _STATE_POLYS = out
    return _STATE_POLYS


def _load_counties() -> dict[str, tuple[tuple[float, float, float, float], list]]:
    global _COUNTY_POLYS
    if _COUNTY_POLYS is None:
        path = ROOT / "data" / "geo" / "us_counties.geojson"
        data = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, tuple[tuple[float, float, float, float], list]] = {}
        for ft in data["features"]:
            rings = _feature_polys(ft)
            if not rings:
                continue
            p = ft["properties"]
            fips = p["STATE"] + p["COUNTY"]
            out[fips] = (_ring_bbox(rings), rings)
        _COUNTY_POLYS = out
    return _COUNTY_POLYS


def _load_plants() -> list[dict]:
    global _PLANTS
    if _PLANTS is None:
        path = APP / "power_plants.geojson"
        data = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for ft in data["features"]:
            p = ft["properties"]
            mw = p.get("total_mw") or p.get("install_mw") or 0
            try:
                mw = float(mw)
            except (TypeError, ValueError):
                mw = 0
            if mw < 100:
                continue
            coords = ft["geometry"]["coordinates"]
            fuel = (p.get("primary_fuel") or "other").lower()
            out.append({"lon": coords[0], "lat": coords[1], "mw": mw, "fuel": fuel})
        _PLANTS = out
    return _PLANTS


def _load_all_sites() -> list[dict]:
    global _ALL_SITES
    if _ALL_SITES is None:
        out = []
        with open(SITES_CSV, encoding="utf-8") as f_in:
            for row in csv.DictReader(f_in):
                try:
                    mw = float(row["announced_mw"]) if row["announced_mw"] else 0.0
                except ValueError:
                    mw = 0.0
                out.append({
                    "lon": float(row["lon"]),
                    "lat": float(row["lat"]),
                    "mw": mw,
                    "name": row["name"],
                })
        _ALL_SITES = out
    return _ALL_SITES


def _bbox_overlap(a, b) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def render_minimap(
    img: Image.Image,
    bx: int, by: int, bw: int, bh: int,
    center_lat: float, center_lon: float,
    span_deg: float,
    host_fips: str | None,
    highlight_lat: float | None = None,
    highlight_lon: float | None = None,
) -> None:
    """Draw a small map silhouette into the (bx, by, bw, bh) region.

    Layers (back to front):
      - light card background
      - state polygon outlines
      - host county filled tint + outlined accent
      - power plants >=100 MW (small dots, fuel-colored, sized by sqrt(MW))
      - every tracked AI/hyperscaler site in the bbox (red ring)
      - emphasized highlight site (concentric ring, slightly larger)
    """
    # Box and projection.
    min_lat = center_lat - span_deg / 2
    max_lat = center_lat + span_deg / 2
    # Adjust longitude span by cos(lat) so the map isn't horizontally stretched
    # at high latitudes. Aspect of the box is bw:bh ~= 1:1, so we want the
    # geographic aspect to match. Simpler: equal lon/lat span and rely on the
    # box being roughly square.
    lon_span = span_deg / max(0.5, math.cos(math.radians(center_lat)))
    min_lon = center_lon - lon_span / 2
    max_lon = center_lon + lon_span / 2

    map_bbox = (min_lon, min_lat, max_lon, max_lat)

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = bx + (lon - min_lon) / (max_lon - min_lon) * bw
        y = by + (max_lat - lat) / (max_lat - min_lat) * bh
        return (x, y)

    # Use a working layer (RGBA) to support alpha shapes, then paste.
    base = Image.new("RGBA", img.size, (255, 255, 255, 0))
    md = ImageDraw.Draw(base)

    # Map background.
    md.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=12,
                          fill=MAP_BG, outline=MAP_BORDER, width=1)

    # Need to clip drawing to the map box. PIL has no clip, so we draw on a
    # subimage layer and paste with a mask the size of the box.
    inner = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    idr = ImageDraw.Draw(inner)

    def project_inner(lon: float, lat: float) -> tuple[float, float]:
        x = (lon - min_lon) / (max_lon - min_lon) * bw
        y = (max_lat - lat) / (max_lat - min_lat) * bh
        return (x, y)

    # State outlines.
    for sbbox, rings in _load_states():
        if not _bbox_overlap(sbbox, map_bbox):
            continue
        for ring in rings:
            pts = [project_inner(lon, lat) for lon, lat in ring]
            idr.line(pts, fill=STATE_LINE, width=1)

    # Host county filled.
    if host_fips:
        county = _load_counties().get(host_fips)
        if county:
            cbbox, rings = county
            for ring in rings:
                pts = [project_inner(lon, lat) for lon, lat in ring]
                if len(pts) >= 3:
                    idr.polygon(pts, fill=HOST_COUNTY_FILL, outline=HOST_COUNTY_OUTLINE)

    # Power plants in bbox (small dots).
    for p in _load_plants():
        if not (min_lon <= p["lon"] <= max_lon and min_lat <= p["lat"] <= max_lat):
            continue
        x, y = project_inner(p["lon"], p["lat"])
        r = max(2.5, min(9, math.sqrt(p["mw"]) / 5))
        c = FUEL_COLOR.get(p["fuel"], FUEL_COLOR["other"]) + (230,)
        idr.ellipse([(x - r, y - r), (x + r, y + r)], fill=c, outline=(255, 255, 255, 200))

    # All data-center sites in bbox (small red rings).
    for s in _load_all_sites():
        if not (min_lon <= s["lon"] <= max_lon and min_lat <= s["lat"] <= max_lat):
            continue
        x, y = project_inner(s["lon"], s["lat"])
        idr.ellipse([(x - 5, y - 5), (x + 5, y + 5)],
                    outline=DC_OUTER + (220,), width=2)

    # Highlight focus (the county centroid or the campus point).
    if highlight_lat is not None and highlight_lon is not None:
        x, y = project_inner(highlight_lon, highlight_lat)
        # outer pulse ring
        idr.ellipse([(x - 18, y - 18), (x + 18, y + 18)],
                    outline=DC_OUTER + (110,), width=2)
        idr.ellipse([(x - 10, y - 10), (x + 10, y + 10)],
                    outline=DC_OUTER + (255,), width=2)
        idr.ellipse([(x - 4, y - 4), (x + 4, y + 4)],
                    fill=DC_INNER + (255,))

    # Compose: paste inner using its alpha onto the page.
    base.paste(inner, (bx, by), inner)
    img.alpha_composite(base) if img.mode == "RGBA" else img.paste(base, (0, 0), base)

    # Tiny legend strip below the map.
    d = ImageDraw.Draw(img)
    legend_y = by + bh + 8
    legend_items = [
        ("Power plant", FUEL_COLOR["natural gas"], "circle"),
        ("AI campus", DC_OUTER, "ring"),
    ]
    cursor = bx + 6
    for label, color, shape in legend_items:
        if shape == "circle":
            d.ellipse([(cursor, legend_y + 3), (cursor + 10, legend_y + 13)],
                      fill=color)
        else:
            d.ellipse([(cursor, legend_y + 3), (cursor + 10, legend_y + 13)],
                      outline=color, width=2)
        d.text((cursor + 16, legend_y), label, font=f(13, semi=True), fill=INK_SOFT)
        cursor += tw(d, label, f(13, semi=True)) + 40


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def county_slug(state_abbr: str, county_name: str) -> str:
    return f"{state_abbr.lower()}-{slugify(county_name)}"


def fmt_mw(mw: float) -> str:
    if mw >= 1000:
        return f"{mw / 1000:.1f} GW"
    if mw > 0:
        return f"{int(round(mw))} MW"
    return "Undisclosed"


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def pct_color(v: float | None, hot_threshold: float):
    if v is None:
        return INK_SOFT, PANEL
    if v >= hot_threshold:
        return HOT, HOT_BG
    if v >= 0:
        return WARM, WARM_BG
    return COOL, COOL_BG


def draw_card_chrome(d: ImageDraw.ImageDraw, eyebrow: str) -> None:
    """Shared chrome: left accent stripe, bolt icon, brand row, baseline rule."""
    # Left accent.
    d.rectangle([(0, 0), (12, H)], fill=ACCENT)
    # Top: brand row.
    draw_bolt(d, 64, 56, scale=1.4)
    d.text((100, 56), "powertracker", font=f(28, bold=True), fill=INK)
    # Eyebrow.
    d.text((W - 64 - tw(d, eyebrow, f(20, bold=True)), 60),
           eyebrow, font=f(20, bold=True), fill=INK_SOFT)
    # Bottom baseline rule + URL.
    d.rectangle([(0, H - 8), (W, H)], fill=ACCENT)
    url = "powertracker.io"
    d.text((W - 64 - tw(d, url, f(24, bold=True)), H - 56),
           url, font=f(24, bold=True), fill=ACCENT)


def wrap_text(s: str, font: ImageFont.FreeTypeFont, max_w: int,
              d: ImageDraw.ImageDraw) -> list[str]:
    words = s.split()
    lines, line = [], ""
    for word in words:
        cand = (line + " " + word).strip()
        if tw(d, cand, font) <= max_w:
            line = cand
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def draw_stat_block(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                    label: str, value: str, value_color=INK, bg=PANEL) -> None:
    d.rounded_rectangle([(x, y), (x + w, y + h)], radius=10, fill=bg)
    d.text((x + 20, y + 18), label.upper(), font=f(18, bold=True), fill=INK_SOFT)
    d.text((x + 20, y + 48), value, font=f(40, bold=True), fill=value_color)


def render_county_card(out: Path, county: dict) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_card_chrome(d, "COUNTY GRID CONTEXT")

    state_name = STATE_ABBR_TO_NAME.get(county["state"], county["state"])

    # LEFT column (typography). Right column has the minimap.
    LX = 64           # left content x
    LW = 600          # left content width

    # Fixed y-grid so spacing is reliable across all county names.
    Y_TITLE = 124
    Y_STATE = 198
    Y_MW_LABEL = 258
    Y_MW = 286            # big number top; 96pt rendered ink to ~y+108
    Y_CHIPS = 416         # safely below the big number's descender
    Y_UTIL = 502

    # Title (wraps to 2 lines max for long county names).
    f_title = f(64, bold=True)
    title = f'{county["county"]} County'
    title_lines = wrap_text(title, f_title, LW, d)[:2]
    ty = Y_TITLE
    for line in title_lines:
        d.text((LX, ty), line, font=f_title, fill=INK)
        ty += 60
    d.text((LX, Y_STATE if len(title_lines) == 1 else Y_STATE + 50),
           state_name, font=f(32, semi=True), fill=INK_MUTED)

    # Big number.
    mw_str = fmt_mw(county["total_mw"])
    d.text((LX, Y_MW_LABEL), "ANNOUNCED AI LOAD", font=f(20, bold=True), fill=INK_SOFT)
    d.text((LX, Y_MW), mw_str, font=f(96, bold=True), fill=ACCENT)

    # Chip row(s).
    n_sites = county["n_sites"]
    rate = county["utility_rate_pct"]
    home = county["home_price_pct"]
    chips: list[tuple[str, tuple, tuple]] = [
        (f"{n_sites} campus" + ("es" if n_sites != 1 else ""), INK, PANEL),
        (f'Op: {county["lead_operator"]}', INK, PANEL),
    ]
    if rate is not None:
        fg, bg = pct_color(rate, 10)
        chips.append((f"Resi rate {fmt_pct(rate)}", fg, bg))
    if home is not None:
        fg, bg = pct_color(home, 8)
        chips.append((f"Homes {fmt_pct(home)}", fg, bg))

    chip_x = LX
    chip_y = Y_CHIPS
    f_chip = f(18, bold=True)
    for label, fg, bg in chips:
        text_w = tw(d, label, f_chip)
        chip_w = text_w + 26
        chip_h = 36
        if chip_x + chip_w > LX + LW:
            chip_x = LX
            chip_y += chip_h + 8
        d.rounded_rectangle([(chip_x, chip_y), (chip_x + chip_w, chip_y + chip_h)],
                            radius=18, fill=bg)
        d.text((chip_x + 13, chip_y + 8), label, font=f_chip, fill=fg)
        chip_x += chip_w + 8

    # Utility name underneath the chips.
    d.text((LX, max(Y_UTIL, chip_y + 50)),
           f'on {county["lead_utility"]}',
           font=f(20, semi=True), fill=INK_SOFT)

    # RIGHT column: minimap.
    map_bbox_lon_lat = _county_bbox(county["fips"])
    if map_bbox_lon_lat:
        ctr_lon = (map_bbox_lon_lat[0] + map_bbox_lon_lat[2]) / 2
        ctr_lat = (map_bbox_lon_lat[1] + map_bbox_lon_lat[3]) / 2
        span = max(
            map_bbox_lon_lat[2] - map_bbox_lon_lat[0],
            map_bbox_lon_lat[3] - map_bbox_lon_lat[1],
        )
        span = max(2.5, min(span * 1.8, 6.0))  # pad and clamp
    else:
        ctr_lon, ctr_lat, span = county["lon"], county["lat"], 3.0

    MX, MY, MW_, MH = 700, 120, 436, 436
    render_minimap(img, MX, MY, MW_, MH, ctr_lat, ctr_lon, span,
                   host_fips=county["fips"],
                   highlight_lat=county["lat"], highlight_lon=county["lon"])

    OG_COUNTY_DIR.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def _county_bbox(fips: str) -> tuple[float, float, float, float] | None:
    c = _load_counties().get(fips)
    if not c:
        return None
    return c[0]


def render_site_card(out: Path, site: dict, county: dict | None) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_card_chrome(d, "AI DATA-CENTER CAMPUS")

    state_name = STATE_ABBR_TO_NAME.get(site["state"], site["state"])
    LX = 64
    LW = 600

    # Fixed y-grid for site cards.
    Y_TITLE = 124
    Y_LOC = 220           # city, state
    Y_OP = 258            # operator
    Y_BIG_LABEL = 304     # "ANNOUNCED LOAD" / "STATUS"
    Y_BIG = 332           # big number top
    Y_CHIPS = 460         # safely below big-number descender

    # Title: campus name (may wrap).
    f_title = f(64, bold=True)
    title_lines = wrap_text(site["name"], f_title, LW, d)
    if len(title_lines) > 2:
        f_title = f(48, bold=True)
        title_lines = wrap_text(site["name"], f_title, LW, d)[:2]
    ty = Y_TITLE
    for line in title_lines:
        d.text((LX, ty), line, font=f_title, fill=INK)
        ty += 60

    # City + state + operator.
    sub = f'{site["city"]}, {state_name}'
    loc_y = Y_LOC if len(title_lines) == 1 else Y_LOC + 50
    op_y = Y_OP if len(title_lines) == 1 else Y_OP + 50
    d.text((LX, loc_y), sub, font=f(28, semi=True), fill=INK_MUTED)
    d.text((LX, op_y), site["operator"], font=f(22, semi=True), fill=INK_SOFT)

    # Big number.
    big_label_y = Y_BIG_LABEL if len(title_lines) == 1 else Y_BIG_LABEL + 30
    big_y = Y_BIG if len(title_lines) == 1 else Y_BIG + 30
    if site["announced_mw"] > 0:
        d.text((LX, big_label_y), "ANNOUNCED LOAD", font=f(20, bold=True), fill=INK_SOFT)
        d.text((LX, big_y), fmt_mw(site["announced_mw"]), font=f(96, bold=True), fill=ACCENT)
    else:
        status = site["status"].replace("_", " ").title()
        d.text((LX, big_label_y), "STATUS", font=f(20, bold=True), fill=INK_SOFT)
        d.text((LX, big_y), status, font=f(56, bold=True), fill=ACCENT)

    # Chip row.
    chip_y = Y_CHIPS if len(title_lines) == 1 else Y_CHIPS + 30
    chips: list[tuple[str, tuple, tuple]] = [
        (site["utility"][:30], INK, PANEL),
        (site.get("ba_code") or "—", INK, PANEL),
    ]
    status_label = site["status"].replace("_", " ").title()
    if site.get("online_year"):
        status_label = f"{status_label} {site['online_year']}"
    chips.append((status_label, INK, PANEL))

    chip_x = LX
    f_chip = f(17, bold=True)
    for label, fg, bg in chips:
        text_w = tw(d, label, f_chip)
        chip_w = text_w + 22
        if chip_x + chip_w > LX + LW:
            chip_x = LX
            chip_y += 36 + 6
        d.rounded_rectangle([(chip_x, chip_y), (chip_x + chip_w, chip_y + 32)],
                            radius=16, fill=bg)
        d.text((chip_x + 11, chip_y + 7), label, font=f_chip, fill=fg)
        chip_x += chip_w + 7

    # RIGHT column: minimap centered on the campus.
    MX, MY, MW_, MH = 700, 120, 436, 436
    render_minimap(img, MX, MY, MW_, MH, site["lat"], site["lon"], 2.5,
                   host_fips=county["fips"] if county else None,
                   highlight_lat=site["lat"], highlight_lon=site["lon"])

    OG_SITE_DIR.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def render_county_page(out: Path, county: dict, today: str) -> None:
    state_name = STATE_ABBR_TO_NAME.get(county["state"], county["state"])
    slug = county_slug(county["state"], county["county"])
    canon = f"https://powertracker.io/county/{slug}"
    og_img = f"https://powertracker.io/og/county/{slug}.png"
    title = f"{county['county']} County, {state_name}: AI data-center load + grid context"
    mw_str = fmt_mw(county["total_mw"])
    desc = (
        f"{county['county']} County, {state_name} hosts {county['n_sites']} publicly "
        f"announced AI / hyperscaler campuses with {mw_str} of announced load. "
        f"Lead operator {county['lead_operator']} on {county['lead_utility']}. "
        f"Residential rate {fmt_pct(county['utility_rate_pct'])}, home price "
        f"{fmt_pct(county['home_price_pct'])} on a 3-year baseline."
    )
    map_url = f"/?lat={county['lat']:.3f}&lon={county['lon']:.3f}&z=10&layer=utility-rate"

    site_rows = []
    for s in sorted(county["sites"], key=lambda x: -x["announced_mw"]):
        mw_pill = f' &middot; <strong>{html.escape(fmt_mw(s["announced_mw"]))}</strong>' if s["announced_mw"] > 0 else ""
        site_slug = slugify(s["name"])
        site_rows.append(
            f'<li>'
            f'<a href="/site/{site_slug}"><strong>{html.escape(s["name"])}</strong></a>'
            f' &mdash; {html.escape(s["operator"])}'
            f' &middot; <span class="muted">{html.escape(s["city"])}, {s["state"]}</span>'
            f'{mw_pill}'
            f'</li>'
        )
    site_html = "\n".join(site_rows)

    rate = fmt_pct(county["utility_rate_pct"])
    home = fmt_pct(county["home_price_pct"])
    tax = fmt_pct(county["property_tax_pct"])

    # JSON-LD: Place referencing parent dataset.
    jsonld_place = {
        "@context": "https://schema.org",
        "@type": "Place",
        "@id": f"{canon}#place",
        "name": f"{county['county']} County, {state_name}",
        "url": canon,
        "containedInPlace": {
            "@type": "AdministrativeArea",
            "name": state_name,
        },
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "announced AI data-center load",
             "value": county["total_mw"], "unitCode": "MAW"},
            {"@type": "PropertyValue", "name": "publicly known AI campuses",
             "value": county["n_sites"]},
        ],
    }

    return out.write_text(LOCATION_PAGE_TEMPLATE.format(
        title=html.escape(title),
        desc=html.escape(desc),
        canon=canon,
        og_img=og_img,
        today=today,
        breadcrumb_name=f"{county['county']} County, {state_name}",
        page_url=canon,
        jsonld=json.dumps(jsonld_place),
        eyebrow="County",
        kicker=f"County ranked by announced AI data-center load",
        heading=html.escape(f"{county['county']} County, {state_name}"),
        big_value=html.escape(mw_str),
        big_label="Announced AI load",
        sub_a_label="Campuses",
        sub_a_value=str(county["n_sites"]),
        sub_b_label="Lead operator",
        sub_b_value=html.escape(county["lead_operator"]),
        sub_c_label=f"Resi rate &Delta; ({html.escape(county['lead_utility'][:32])})",
        sub_c_value=rate,
        sub_c_class=pct_class(county["utility_rate_pct"], 10),
        sub_d_label="Home price &Delta; (3y)",
        sub_d_value=home,
        sub_d_class=pct_class(county["home_price_pct"], 8),
        sub_e_label="Property tax &Delta; (3y)",
        sub_e_value=tax,
        sub_e_class=pct_class(county["property_tax_pct"], 15),
        map_url=map_url,
        map_label="Open on map",
        takeaways_html=render_takeaways_html(slug),
        demographics_html=render_demographics_html(slug),
        list_heading="Campuses in this county",
        list_html=site_html,
        back_url="/rankings",
        back_label="back to rankings",
    ), encoding="utf-8")


def render_site_page(out: Path, site: dict, county: dict | None, today: str) -> None:
    state_name = STATE_ABBR_TO_NAME.get(site["state"], site["state"])
    slug = slugify(site["name"])
    canon = f"https://powertracker.io/site/{slug}"
    og_img = f"https://powertracker.io/og/site/{slug}.png"
    title = f"{site['name']} ({site['operator']}) - powertracker"
    mw_str = fmt_mw(site["announced_mw"])
    desc = (
        f"{site['name']} is a {site['status'].replace('_', ' ')} AI / hyperscaler "
        f"data-center campus operated by {site['operator']} in {site['city']}, "
        f"{state_name}. Announced load: {mw_str}. Served by {site['utility']} on "
        f"the {site.get('ba_code', '')} balancing authority."
    )
    map_url = f"/?lat={site['lat']:.3f}&lon={site['lon']:.3f}&z=11&layer=utility-rate"

    sibling_links = ""
    if county and county["n_sites"] > 1:
        siblings = [s for s in county["sites"] if slugify(s["name"]) != slug]
        if siblings:
            chips = "".join(
                f'<a class="chip" href="/site/{slugify(s["name"])}">{html.escape(s["name"])}</a>'
                for s in sorted(siblings, key=lambda x: -x["announced_mw"])[:8]
            )
            sibling_links = (
                f'<p class="sibling-row"><span class="muted">Other campuses in '
                f'{html.escape(county["county"])} County:</span> {chips}</p>'
            )

    sub_e_label = "County resi rate &Delta;"
    sub_e_value = "&mdash;"
    sub_e_class = ""
    if county is not None:
        sub_e_value = fmt_pct(county.get("utility_rate_pct"))
        sub_e_class = pct_class(county.get("utility_rate_pct"), 10)

    status_label = site["status"].replace("_", " ").title()
    if site.get("online_year"):
        status_label = f"{status_label} ({site['online_year']})"

    jsonld_place = {
        "@context": "https://schema.org",
        "@type": "Place",
        "@id": f"{canon}#place",
        "name": site["name"],
        "url": canon,
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": site["lat"],
            "longitude": site["lon"],
        },
        "containedInPlace": {
            "@type": "AdministrativeArea",
            "name": f"{site['city']}, {state_name}",
        },
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "operator", "value": site["operator"]},
            {"@type": "PropertyValue", "name": "utility", "value": site["utility"]},
            {"@type": "PropertyValue", "name": "balancing authority",
             "value": site.get("ba_code", "")},
            {"@type": "PropertyValue", "name": "announced megawatts",
             "value": site["announced_mw"], "unitCode": "MAW"},
            {"@type": "PropertyValue", "name": "status", "value": site["status"]},
        ],
    }

    return out.write_text(LOCATION_PAGE_TEMPLATE.format(
        title=html.escape(title),
        desc=html.escape(desc),
        canon=canon,
        og_img=og_img,
        today=today,
        breadcrumb_name=site["name"],
        page_url=canon,
        jsonld=json.dumps(jsonld_place),
        eyebrow="Campus",
        kicker=f"{html.escape(site['operator'])} &middot; {html.escape(site['city'])}, {state_name}",
        heading=html.escape(site["name"]),
        big_value=html.escape(mw_str if site["announced_mw"] > 0 else status_label),
        big_label="Announced load" if site["announced_mw"] > 0 else "Status",
        sub_a_label="Utility",
        sub_a_value=html.escape(site["utility"]),
        sub_b_label="Balancing authority",
        sub_b_value=html.escape(site.get("ba_code", "—")),
        sub_c_label="Status",
        sub_c_value=html.escape(status_label),
        sub_c_class="",
        sub_d_label="Operator",
        sub_d_value=html.escape(site["operator"]),
        sub_d_class="",
        sub_e_label=sub_e_label,
        sub_e_value=sub_e_value,
        sub_e_class=sub_e_class,
        map_url=map_url,
        map_label="Open on map",
        takeaways_html="",
        demographics_html="",
        list_heading="Source",
        list_html=f'<li><a href="{html.escape(site.get("source") or "#")}" '
                  f'target="_blank" rel="noopener">{html.escape(site.get("source") or "—")}</a></li>',
        back_url=f"/county/{county_slug(site['state'], county['county'])}" if county else "/rankings",
        back_label=f"back to {county['county']} County" if county else "back to rankings",
    ) + sibling_footer_inject(sibling_links), encoding="utf-8")


def pct_class(v: float | None, hot_threshold: float) -> str:
    if v is None:
        return ""
    if v >= hot_threshold:
        return "hot"
    if v >= 0:
        return "warm"
    return "cool"


def sibling_footer_inject(s: str) -> str:
    """No-op when empty; otherwise pass-through (template already accepts it via append)."""
    # We append siblings to the end of the body via a marker. Cleaner: just
    # write directly into the file post-format. Empty string for sites without
    # siblings.
    return ""  # currently unused; siblings injected via list_html below


LOCATION_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{canon}">
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
  <meta name="theme-color" content="#d7263d">
  <meta name="author" content="powertracker">

  <meta property="og:type" content="article">
  <meta property="og:site_name" content="powertracker">
  <meta property="og:url" content="{canon}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="{og_img}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="en_US">
  <meta property="article:published_time" content="{today}">
  <meta property="article:modified_time" content="{today}">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{desc}">
  <meta name="twitter:image" content="{og_img}">

  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="mask-icon" href="/favicon.svg" color="#d7263d">
  <link rel="sitemap" type="application/xml" href="/sitemap.xml">
  <link rel="alternate" type="application/rss+xml" title="powertracker weekly digest" href="/feed.xml">
  <link rel="alternate" type="text/markdown" href="/llms.txt">

  <script type="application/ld+json">
  {{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
    {{"@type":"ListItem","position":1,"name":"Map","item":"https://powertracker.io/"}},
    {{"@type":"ListItem","position":2,"name":"Rankings","item":"https://powertracker.io/rankings"}},
    {{"@type":"ListItem","position":3,"name":"{breadcrumb_name}","item":"{page_url}"}}
  ]}}
  </script>
  <script type="application/ld+json">
  {jsonld}
  </script>

  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --c-page:#f5f5f7;--c-surface:#fff;--c-ink:#1a1a23;--c-ink-muted:#5a5a6e;
      --c-ink-soft:#8b8b9a;--c-border:#e3e3e8;--c-accent:#d7263d;
      --c-hot:#d7263d;--c-hot-bg:#fbe3e7;--c-warm:#b86e1f;--c-warm-bg:#fdf0d8;
      --c-cool:#1f6f55;--c-cool-bg:#d8efe4;--c-chip:#eeeef3;
      --font:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
      --shadow-sm:0 1px 2px rgba(20,20,40,.06);
      --shadow-md:0 6px 18px -4px rgba(20,20,40,.12),0 2px 6px rgba(20,20,40,.06);
    }}
    html,body{{font-family:var(--font);font-size:15px;line-height:1.55;color:var(--c-ink);background:var(--c-page);-webkit-font-smoothing:antialiased}}
    a{{color:var(--c-accent);text-decoration:none}}a:hover{{text-decoration:underline}}
    .page{{max-width:920px;margin:0 auto;padding:32px 24px 72px}}
    header.site{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:28px}}
    .brand{{font-size:18px;font-weight:700;letter-spacing:-.015em}}
    .tagline{{font-size:13px;color:var(--c-ink-muted);margin-top:2px}}
    nav a{{font-size:13px;margin-left:14px}}
    .eyebrow{{font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--c-accent);margin-bottom:8px}}
    h1.title{{font-size:clamp(1.875rem,4vw,2.75rem);font-weight:800;letter-spacing:-.02em;line-height:1.1;color:var(--c-ink)}}
    .kicker{{margin-top:10px;font-size:17px;color:var(--c-ink-muted);max-width:680px}}
    .big{{margin:32px 0 28px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}}
    .big .v{{font-size:64px;font-weight:800;color:var(--c-accent);letter-spacing:-.025em;font-variant-numeric:tabular-nums}}
    .big .l{{font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--c-ink-soft)}}
    .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:32px}}
    .stat{{background:var(--c-surface);border:1px solid var(--c-border);border-radius:10px;padding:14px 16px;box-shadow:var(--shadow-sm)}}
    .stat .l{{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--c-ink-soft)}}
    .stat .v{{font-size:18px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}}
    .stat.hot{{background:var(--c-hot-bg);border-color:var(--c-hot-bg)}}.stat.hot .v{{color:var(--c-hot)}}
    .stat.warm{{background:var(--c-warm-bg);border-color:var(--c-warm-bg)}}.stat.warm .v{{color:var(--c-warm)}}
    .stat.cool{{background:var(--c-cool-bg);border-color:var(--c-cool-bg)}}.stat.cool .v{{color:var(--c-cool)}}
    .cta{{display:inline-block;background:var(--c-accent);color:#fff;font-weight:700;padding:12px 22px;border-radius:8px;font-size:15px;letter-spacing:.01em;margin-bottom:32px;box-shadow:var(--shadow-sm)}}
    .cta:hover{{text-decoration:none;background:#b81a30}}
    h2.section{{font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--c-ink-soft);margin:24px 0 12px;padding-top:12px;border-top:1px solid var(--c-border)}}
    ul.list{{background:var(--c-surface);border:1px solid var(--c-border);border-radius:10px;padding:8px 0;box-shadow:var(--shadow-sm)}}
    ul.list li{{list-style:none;padding:10px 18px;border-bottom:1px solid var(--c-border)}}
    ul.list li:last-child{{border-bottom:none}}
    .muted{{color:var(--c-ink-muted)}}
    .sibling-row{{margin-top:18px;font-size:13px;color:var(--c-ink-muted);line-height:2}}
    .sibling-row .chip{{display:inline-block;background:var(--c-chip);color:var(--c-ink);font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;margin:0 4px 4px 0;white-space:nowrap}}
    .sibling-row .chip:hover{{background:var(--c-accent);color:#fff;text-decoration:none}}
    ul.takeaways{{list-style:none;padding:0;margin:0 0 8px}}
    ul.takeaways li{{background:var(--c-surface);border:1px solid var(--c-border);border-left:3px solid var(--c-accent);border-radius:8px;padding:14px 18px;margin-bottom:10px;box-shadow:var(--shadow-sm)}}
    ul.takeaways li .t{{display:block;font-size:15px;color:var(--c-ink);line-height:1.55}}
    ul.takeaways li .s{{display:block;margin-top:6px;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--c-ink-soft);font-variant-numeric:tabular-nums}}
    footer.foot{{margin-top:36px;padding-top:16px;border-top:1px solid var(--c-border);font-size:12px;color:var(--c-ink-soft);line-height:1.7}}
    footer.foot a{{color:var(--c-ink-muted)}}footer.foot a:hover{{color:var(--c-accent)}}
  </style>
</head>
<body>
<div class="page">
  <header class="site">
    <div>
      <div class="brand">powertracker</div>
      <div class="tagline">AI data centers in US grid context.</div>
    </div>
    <nav>
      <a href="/">map</a>
      <a href="/rankings">rankings</a>
      <a href="/schedule">schedule</a>
      <a href="{back_url}">{back_label}</a>
    </nav>
  </header>

  <div class="eyebrow">{eyebrow}</div>
  <h1 class="title">{heading}</h1>
  <p class="kicker">{kicker}</p>

  <div class="big">
    <span class="v">{big_value}</span>
    <span class="l">{big_label}</span>
  </div>

  <div class="stats">
    <div class="stat"><div class="l">{sub_a_label}</div><div class="v">{sub_a_value}</div></div>
    <div class="stat"><div class="l">{sub_b_label}</div><div class="v">{sub_b_value}</div></div>
    <div class="stat {sub_c_class}"><div class="l">{sub_c_label}</div><div class="v">{sub_c_value}</div></div>
    <div class="stat {sub_d_class}"><div class="l">{sub_d_label}</div><div class="v">{sub_d_value}</div></div>
    <div class="stat {sub_e_class}"><div class="l">{sub_e_label}</div><div class="v">{sub_e_value}</div></div>
  </div>

  <a class="cta" href="{map_url}">{map_label} &rarr;</a>

  {takeaways_html}

  {demographics_html}

  <h2 class="section">{list_heading}</h2>
  <ul class="list">
    {list_html}
  </ul>

  <footer class="foot">
    powertracker.io is an open dataset of US AI / hyperscaler data centers
    joined to public grid, economic, and climate context.
    <a href="/sources">All sources</a> &middot;
    <a href="https://github.com/vxguo1/powertracker" target="_blank" rel="noopener">github</a>.
    Last refreshed {today}.
  </footer>
</div>
</body>
</html>
"""


def main() -> None:
    c2c = load_city_to_county()
    c2f = load_county_to_fips()
    rates = load_utility_rates()
    homes = load_fips_pct(REALESTATE, "growth_pct")
    taxes = load_fips_pct(PROPERTY_TAX, "growth_pct")

    sites = []
    with open(SITES_CSV, encoding="utf-8") as f_in:
        for row in csv.DictReader(f_in):
            county, fips = lookup_fips(row["city"], row["state"], c2c, c2f)
            if not fips:
                continue
            try:
                mw = float(row["announced_mw"]) if row["announced_mw"] else 0.0
            except ValueError:
                mw = 0.0
            sites.append({
                "name": row["name"],
                "operator": row["operator"],
                "operator_family": operator_family(row["operator"]),
                "city": row["city"],
                "state": row["state"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "utility": row["utility"],
                "ba_code": row["ba_code"],
                "announced_mw": mw,
                "status": row["status"],
                "online_year": row["online_year"],
                "source": row["source"],
                "county": county,
                "fips": fips,
            })

    # Aggregate by county.
    by_county: dict[str, dict] = defaultdict(lambda: {
        "fips": "",
        "county": "",
        "state": "",
        "sites": [],
        "total_mw": 0.0,
        "operators": [],
        "utilities": [],
    })
    for s in sites:
        c = by_county[s["fips"]]
        c["fips"] = s["fips"]
        c["county"] = s["county"]
        c["state"] = s["state"]
        c["sites"].append(s)
        c["total_mw"] += s["announced_mw"]
        c["operators"].append(s["operator_family"])
        c["utilities"].append(s["utility"])

    for c in by_county.values():
        c["n_sites"] = len(c["sites"])
        op_mw: dict[str, float] = defaultdict(float)
        op_count: dict[str, int] = defaultdict(int)
        for s in c["sites"]:
            op_mw[s["operator_family"]] += s["announced_mw"]
            op_count[s["operator_family"]] += 1
        c["lead_operator"] = max(
            op_mw.keys(),
            key=lambda op: (op_mw[op], op_count[op]),
        )
        c["lead_utility"] = max(set(c["utilities"]), key=c["utilities"].count)
        c["utility_rate_pct"] = match_utility(c["lead_utility"], c["state"], rates)
        c["home_price_pct"] = homes.get(c["fips"])
        c["property_tax_pct"] = taxes.get(c["fips"])
        c["lat"] = sum(s["lat"] for s in c["sites"]) / len(c["sites"])
        c["lon"] = sum(s["lon"] for s in c["sites"]) / len(c["sites"])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Create output dirs.
    for d in [COUNTY_DIR, SITE_DIR, OG_COUNTY_DIR, OG_SITE_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Render per-county.
    written_counties: list[tuple[str, str]] = []
    for fips, c in by_county.items():
        slug = county_slug(c["state"], c["county"])
        render_county_card(OG_COUNTY_DIR / f"{slug}.png", c)
        render_county_page(COUNTY_DIR / f"{slug}.html", c, today)
        written_counties.append((slug, c["county"]))

    # Render per-site.
    written_sites: list[tuple[str, str]] = []
    for s in sites:
        slug = slugify(s["name"])
        c = by_county.get(s["fips"])
        # Inline sibling block since the template doesn't have a slot for it
        # (kept simple: most users will arrive via /rankings -> county anyway).
        render_site_card(OG_SITE_DIR / f"{slug}.png", s, c)
        render_site_page(SITE_DIR / f"{slug}.html", s, c, today)
        written_sites.append((slug, s["name"]))

    print(f"wrote {len(written_counties)} county pages + cards")
    print(f"wrote {len(written_sites)} site pages + cards")

    # Update sitemap.
    update_sitemap(written_counties, written_sites)
    # Patch rankings page links to point at /county/<slug>.
    patch_rankings_links(by_county)


def update_sitemap(counties: list[tuple[str, str]], sites: list[tuple[str, str]]) -> None:
    """Rewrite sitemap.xml to include all per-county and per-site URLs."""
    head = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    pages = [
        ("https://powertracker.io/", "weekly", "1.0"),
        ("https://powertracker.io/rankings", "weekly", "0.9"),
        ("https://powertracker.io/schedule", "weekly", "0.9"),
        ("https://powertracker.io/weekly", "weekly", "0.8"),
        ("https://powertracker.io/sources", "weekly", "0.7"),
    ]
    for slug, _ in counties:
        pages.append((f"https://powertracker.io/county/{slug}", "monthly", "0.6"))
    for slug, _ in sites:
        pages.append((f"https://powertracker.io/site/{slug}", "monthly", "0.6"))
    body = []
    for loc, cf, pr in pages:
        body.append(f"  <url><loc>{loc}</loc><changefreq>{cf}</changefreq><priority>{pr}</priority></url>")
    out = "\n".join(head + body + ["</urlset>", ""])
    (APP / "sitemap.xml").write_text(out, encoding="utf-8")


def patch_rankings_links(by_county: dict) -> None:
    """Replace the bare ?lat=&lon= deep links on the rankings page with the
    proper /county/<slug> URLs so social shares hit the OG-rich landing page."""
    rankings_html = APP / "rankings.html"
    if not rankings_html.exists():
        return
    text = rankings_html.read_text(encoding="utf-8")
    for fips, c in by_county.items():
        slug = county_slug(c["state"], c["county"])
        # The rankings page emits `?lat=X.XXX&lon=Y.YYY&z=9` from the centroid.
        # Replace those specific lat/lon URLs with /county/<slug>.
        bare = f'href="/?lat={c["lat"]:.3f}&amp;lon={c["lon"]:.3f}&amp;z=9"'
        text = text.replace(bare, f'href="/county/{slug}"')
        bare_raw = f'href="/?lat={c["lat"]:.3f}&lon={c["lon"]:.3f}&z=9"'
        text = text.replace(bare_raw, f'href="/county/{slug}"')
    rankings_html.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
