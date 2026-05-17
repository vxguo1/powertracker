"""Build app/rankings.html: top US counties absorbing AI data-center load.

Joins data/sites/data_centers.csv to:
- us_cities.csv + us_counties.geojson    -> city -> county -> FIPS
- utility_rate_yoy.csv                   -> utility -> residential rate change
- realestate_yoy.csv                     -> FIPS -> Redfin home-price change
- property_tax_yoy.csv                   -> FIPS -> property tax change

Aggregates sites by county and renders a static HTML ranking page. Page
is fully prerendered (no client JS for data) so search engines and LLM
crawlers index every county and its numbers.

Run:
    python scripts/build_rankings.py
"""

from __future__ import annotations

import csv
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES_CSV = ROOT / "data" / "sites" / "data_centers.csv"
US_CITIES = ROOT / "data" / "cache" / "us_cities.csv"
US_COUNTIES = ROOT / "data" / "geo" / "us_counties.geojson"
UTILITY_RATE = ROOT / "data" / "cache" / "utility_rate_yoy.csv"
REALESTATE = ROOT / "data" / "cache" / "realestate_yoy.csv"
PROPERTY_TAX = ROOT / "data" / "cache" / "property_tax_yoy.csv"
OUT_HTML = ROOT / "app" / "rankings.html"

# Two-digit Census state FIPS -> USPS abbreviation.
STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
    "72": "PR", "78": "VI",
}

STATE_ABBR_TO_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

# Cities in data_centers.csv that don't appear in us_cities.csv as a clean
# city/state row, or where the city straddles county lines. Manual map to
# the right county name. Kept terse; expand only when a site lookup fails.
CITY_COUNTY_OVERRIDES = {
    ("salem township", "PA"): "Luzerne",
    ("kline township", "PA"): "Schuylkill",
    ("new carlisle", "IN"): "St. Joseph",
    ("milam county", "TX"): "Milam",
    ("barker", "NY"): "Niagara",
    ("niagara", "NY"): "Niagara",
    ("point pleasant", "WV"): "Mason",
    ("sandston", "VA"): "Henrico",
    ("mount pleasant", "WI"): "Racine",
    ("haskell", "TX"): "Haskell",
    ("vega", "TX"): "Oldham",
    ("claude", "TX"): "Armstrong",
    ("dickens", "TX"): "Dickens",
    ("ellendale", "ND"): "Dickey",
    ("harwood", "ND"): "Cass",
    ("palmetto", "GA"): "Fulton",
    ("social circle", "GA"): "Walton",
    ("jeffersonville", "IN"): "Clark",
    ("granger", "IN"): "St. Joseph",
    ("papillion", "NE"): "Sarpy",
    ("cheyenne", "WY"): "Laramie",
    ("port washington", "WI"): "Ozaukee",
    ("kuna", "ID"): "Ada",
    ("eagle mountain", "UT"): "Utah",
    ("los lunas", "NM"): "Valencia",
    ("rosemount", "MN"): "Dakota",
    ("colorado city", "TX"): "Mitchell",
    ("plano", "TX"): "Collin",
    ("midlothian", "TX"): "Ellis",
    ("red oak", "TX"): "Ellis",
    ("temple", "TX"): "Bell",
    ("abilene", "TX"): "Taylor",
    ("albany", "TX"): "Shackelford",
    ("sweetwater", "TX"): "Nolan",
    ("childress", "TX"): "Childress",
    ("abernathy", "TX"): "Hale",
    ("santa teresa", "NM"): "Dona Ana",
    ("kenilworth", "NJ"): "Union",
    ("dalton", "GA"): "Whitfield",
    ("douglasville", "GA"): "Douglas",
    ("hilliard", "OH"): "Franklin",
    ("manassas", "VA"): "Prince William",
    ("stafford", "VA"): "Stafford",
    ("ashburn", "VA"): "Loudoun",
    ("boydton", "VA"): "Mecklenburg",
    ("chester", "VA"): "Chesterfield",
    ("maiden", "NC"): "Catawba",
    ("hickory", "NC"): "Catawba",
    ("forest city", "NC"): "Rutherford",
    ("lenoir", "NC"): "Caldwell",
    ("marble", "NC"): "Cherokee",
    ("moncks corner", "SC"): "Berkeley",
    ("montgomery", "AL"): "Montgomery",
    ("memphis", "TN"): "Shelby",
    ("gallatin", "TN"): "Sumner",
    ("bridgeport", "AL"): "Jackson",
    ("vernon", "TX"): "Wilbarger",
    ("muskogee", "OK"): "Muskogee",
    ("pryor", "OK"): "Mayes",
    ("la porte", "IN"): "LaPorte",
    ("storey county", "NV"): "Storey",
    ("sparks", "NV"): "Washoe",
    ("henderson", "NV"): "Clark",
    ("las vegas", "NV"): "Clark",
    ("hillsboro", "OR"): "Washington",
    ("hermiston", "OR"): "Umatilla",
    ("boardman", "OR"): "Morrow",
    ("umatilla", "OR"): "Umatilla",
    ("prineville", "OR"): "Crook",
    ("the dalles", "OR"): "Wasco",
    ("quincy", "WA"): "Grant",
    ("council bluffs", "IA"): "Pottawattamie",
    ("west des moines", "IA"): "Polk",
    ("waukee", "IA"): "Dallas",
    ("altoona", "IA"): "Polk",
    ("cedar rapids", "IA"): "Linn",
    ("dekalb", "IL"): "DeKalb",
    ("beaver dam", "WI"): "Dodge",
    ("mesa", "AZ"): "Maricopa",
    ("goodyear", "AZ"): "Maricopa",
    ("el mirage", "AZ"): "Maricopa",
    ("san antonio", "TX"): "Bexar",
    ("denton", "TX"): "Denton",
    ("heath", "OH"): "Licking",
    ("lordstown", "OH"): "Trumbull",
    ("new albany", "OH"): "Licking",
    ("columbus", "OH"): "Franklin",
    ("lancaster", "OH"): "Fairfield",
    ("lancaster", "PA"): "Lancaster",
    ("kansas city", "MO"): "Jackson",
    ("independence", "MO"): "Jackson",
    ("jamestown", "ND"): "Stutsman",
}

# Operator -> family. Collapses 'Microsoft', 'Microsoft/OpenAI', and
# 'SoftBank/OpenAI/Oracle/Crusoe' into the meaningful labels.
def operator_family(s: str) -> str:
    if not s:
        return "Other"
    s = s.split("/")[0].strip()
    return s


def normalize_city(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def load_city_to_county() -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    with open(US_CITIES, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[(normalize_city(row["CITY"]), row["STATE_CODE"])] = row["COUNTY"]
    return out


def load_county_to_fips() -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    with open(US_COUNTIES, encoding="utf-8") as f:
        data = json.load(f)
    for ft in data["features"]:
        p = ft["properties"]
        abbr = STATE_FIPS_TO_ABBR.get(p["STATE"])
        if not abbr:
            continue
        fips = p["STATE"] + p["COUNTY"]
        name = p["NAME"].lower()
        out[(abbr, name)] = fips
        # Saint <-> St. aliases (the Census uses "St. Joseph"; us_cities.csv
        # sometimes uses "Saint Joseph"). Be lenient on both sides.
        if name.startswith("saint "):
            out[(abbr, "st. " + name[6:])] = fips
            out[(abbr, "st " + name[6:])] = fips
        elif name.startswith("st. "):
            out[(abbr, "saint " + name[4:])] = fips
            out[(abbr, "st " + name[4:])] = fips
        # Dona Ana vs Doña Ana (the Census file uses ASCII, but be safe).
        if "ñ" in name:
            out[(abbr, name.replace("ñ", "n"))] = fips
    return out


def lookup_fips(city: str, state: str, c2c: dict, c2f: dict) -> tuple[str | None, str | None]:
    key = (normalize_city(city), state)
    county = CITY_COUNTY_OVERRIDES.get(key) or c2c.get(key)
    if not county:
        return None, None
    fips = c2f.get((state, county.lower()))
    if not fips:
        alt = county.lower().replace("saint ", "st. ")
        fips = c2f.get((state, alt))
    return county, fips


# Utility name in data_centers.csv -> aliases that may appear in EIA-861.
UTILITY_ALIASES = {
    "AEP Ohio": ["Ohio Power Co"],
    "AEP Texas": ["AEP Texas Inc", "AEP Texas Central Co", "AEP Texas North Co"],
    "Duke Energy Carolinas": ["Duke Energy Carolinas, LLC"],
    "Duke Energy Indiana": ["Duke Energy Indiana, LLC"],
    "Duke Energy Florida": ["Duke Energy Florida, LLC"],
    "Dominion Energy Virginia": ["Virginia Electric & Power Co"],
    "Georgia Power": ["Georgia Power Co"],
    "Alabama Power": ["Alabama Power Co"],
    "Entergy Louisiana": ["Entergy Louisiana, LLC"],
    "PPL": ["PPL Electric Utilities Corp"],
    "Pacific Power": ["PacifiCorp"],
    "Rocky Mountain Power": ["PacifiCorp"],
    "Salt River Project": ["Salt River Project"],
    "Arizona Public Service": ["Arizona Public Service Co"],
    "NV Energy": ["Nevada Power Co", "Sierra Pacific Power Co"],
    "Idaho Power": ["Idaho Power Co"],
    "Black Hills Energy": ["Black Hills Power Inc", "Cheyenne Light Fuel & Power"],
    "Indiana Michigan Power": ["Indiana Michigan Power Co"],
    "MidAmerican Energy": ["MidAmerican Energy Co"],
    "We Energies": ["Wisconsin Electric Power Co"],
    "Alliant Energy": ["Wisconsin Power & Light Co", "Interstate Power & Light Co"],
    "Xcel Energy": ["Northern States Power Co - Minnesota", "Public Service Co of Colorado"],
    "Xcel Energy SPS": ["Southwestern Public Service Co"],
    "FirstEnergy": ["Ohio Edison Co", "Toledo Edison Co", "Cleveland Electric Illum Co"],
    "Appalachian Power": ["Appalachian Power Co"],
    "OPPD": ["Omaha Public Power District"],
    "GRDA": ["Grand River Dam Authority"],
    "Evergy": ["Evergy Metro Inc", "Kansas City Power & Light Co", "Evergy Missouri West"],
    "CPS Energy": ["City of San Antonio - (TX)"],
    "PNM": ["Public Service Co of NM"],
    "El Paso Electric": ["El Paso Electric Co"],
    "TVA": ["Tennessee Valley Authority"],
    "TVA direct": ["Tennessee Valley Authority"],
    "MLGW": ["Memphis Light Gas & Water Div"],
    "Grant County PUD": ["PUD No 2 of Grant County"],
    "Northern Wasco PUD": ["Northern Wasco County PUD"],
    "Umatilla Electric Cooperative": ["Umatilla Electric Coop Assn"],
    "Berkeley Electric Cooperative": ["Berkeley Electric Coop Inc"],
    "Otter Tail Power": ["Otter Tail Power Co"],
    "Oncor": ["Oncor Electric Delivery Co LLC"],
    "Denton Municipal Electric": ["City of Denton - (TX)"],
    "PSE&G": ["Public Service Elec & Gas Co"],
    "ComEd": ["Commonwealth Edison Co"],
    "Portland General Electric": ["Portland General Electric Co"],
    "Gallatin Department of Electricity": ["Gallatin Dept of Electricity"],
    "Oklahoma Gas & Electric": ["Oklahoma Gas & Electric Co"],
    "City of Dalton Utilities": ["City of Dalton - (GA)"],
    "NYSEG/NYPA": ["New York State Elec & Gas Corp"],
    "National Grid": ["Niagara Mohawk Power Corp"],
}


def load_utility_rates() -> dict[tuple[str, str], float]:
    """Returns {(utility_name, state): price_change_pct}."""
    out: dict[tuple[str, str], float] = {}
    with open(UTILITY_RATE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                v = float(row["price_change_pct"])
            except ValueError:
                continue
            out[(row["utility_name"].strip(), row["state"])] = v
    return out


def match_utility(utility: str, state: str, rates: dict) -> float | None:
    if not utility:
        return None
    if (utility, state) in rates:
        return rates[(utility, state)]
    for alias in UTILITY_ALIASES.get(utility, []):
        if (alias, state) in rates:
            return rates[(alias, state)]
    # Last-resort: substring on first word of utility name.
    needle = utility.lower().split()[0]
    candidates = [v for (name, st), v in rates.items() if st == state and needle in name.lower()]
    if len(candidates) == 1:
        return candidates[0]
    return None


def load_fips_pct(path: Path, col: str) -> dict[str, float]:
    out: dict[str, float] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row["fips"]] = float(row[col])
            except (ValueError, KeyError):
                continue
    return out


def main() -> None:
    c2c = load_city_to_county()
    c2f = load_county_to_fips()
    rates = load_utility_rates()
    homes = load_fips_pct(REALESTATE, "growth_pct")
    taxes = load_fips_pct(PROPERTY_TAX, "growth_pct")

    sites: list[dict] = []
    unresolved: list[str] = []
    with open(SITES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            city, state = row["city"], row["state"]
            county, fips = lookup_fips(city, state, c2c, c2f)
            if not fips:
                unresolved.append(f"{row['name']} ({city}, {state})")
                continue
            try:
                mw = float(row["announced_mw"]) if row["announced_mw"] else 0.0
            except ValueError:
                mw = 0.0
            sites.append({
                "name": row["name"],
                "operator": row["operator"],
                "operator_family": operator_family(row["operator"]),
                "city": city,
                "state": state,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "utility": row["utility"],
                "announced_mw": mw,
                "status": row["status"],
                "online_year": row["online_year"],
                "county": county,
                "fips": fips,
            })

    if unresolved:
        print("WARNING: unresolved sites (will not appear in rankings):")
        for u in unresolved:
            print(f"  - {u}")

    # Aggregate by county.
    by_county: dict[str, dict] = defaultdict(lambda: {
        "fips": "",
        "county": "",
        "state": "",
        "sites": [],
        "total_mw": 0.0,
        "operators": [],
        "utilities": [],
        "statuses": defaultdict(int),
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
        c["statuses"][s["status"]] += 1

    # Compute join fields.
    for c in by_county.values():
        c["n_sites"] = len(c["sites"])
        # Lead operator: pick the one with the most announced MW; ties go
        # to the one with more campuses, then alphabetical for determinism.
        op_mw: dict[str, float] = defaultdict(float)
        op_count: dict[str, int] = defaultdict(int)
        for s in c["sites"]:
            op_mw[s["operator_family"]] += s["announced_mw"]
            op_count[s["operator_family"]] += 1
        c["lead_operator"] = max(
            op_mw.keys(),
            key=lambda op: (op_mw[op], op_count[op], -ord(op[0]) if op else 0),
        )
        c["lead_utility"] = max(set(c["utilities"]), key=c["utilities"].count)
        c["unique_operators"] = sorted(set(c["operators"]))
        c["utility_rate_pct"] = match_utility(c["lead_utility"], c["state"], rates)
        c["home_price_pct"] = homes.get(c["fips"])
        c["property_tax_pct"] = taxes.get(c["fips"])
        # Centroid (mean lat/lon across sites) for map deep link.
        c["lat"] = sum(s["lat"] for s in c["sites"]) / len(c["sites"])
        c["lon"] = sum(s["lon"] for s in c["sites"]) / len(c["sites"])

    # Rank: sort by total_mw desc, tiebreak by n_sites desc.
    ranked = sorted(
        by_county.values(),
        key=lambda c: (c["total_mw"], c["n_sites"]),
        reverse=True,
    )

    # Lede stats.
    total_sites = len(sites)
    total_counties = len(by_county)
    total_mw = sum(s["announced_mw"] for s in sites)
    total_states = len({s["state"] for s in sites})
    mw_in_top10 = sum(c["total_mw"] for c in ranked[:10])
    concentration_pct = (mw_in_top10 / total_mw * 100) if total_mw else 0

    # States ranked by total announced MW (for the secondary breakdown).
    by_state: dict[str, float] = defaultdict(float)
    by_state_sites: dict[str, int] = defaultdict(int)
    for s in sites:
        by_state[s["state"]] += s["announced_mw"]
        by_state_sites[s["state"]] += 1
    state_rank = sorted(
        ((st, mw, by_state_sites[st]) for st, mw in by_state.items()),
        key=lambda x: (x[1], x[2]),
        reverse=True,
    )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = render_html(ranked[:30], state_rank[:15], {
        "total_sites": total_sites,
        "total_counties": total_counties,
        "total_mw": total_mw,
        "total_states": total_states,
        "concentration_pct": concentration_pct,
        "mw_in_top10": mw_in_top10,
        "today": today,
    })
    OUT_HTML.write_text(out, encoding="utf-8")
    print(f"wrote {OUT_HTML} ({len(ranked)} counties ranked, top 30 shown)")


def fmt_mw(mw: float) -> str:
    if mw >= 1000:
        return f"{mw / 1000:.1f} GW"
    return f"{int(round(mw))} MW"


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "&mdash;"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def pct_class(v: float | None, hot_threshold: float = 8) -> str:
    if v is None:
        return ""
    if v >= hot_threshold:
        return "hot"
    if v >= 0:
        return "warm"
    return "cool"


def render_html(ranked: list[dict], state_rank: list[tuple], stats: dict) -> str:
    rows_html = []
    for i, c in enumerate(ranked, 1):
        state_name = STATE_ABBR_TO_NAME.get(c["state"], c["state"])
        ops = ", ".join(c["unique_operators"][:3])
        if len(c["unique_operators"]) > 3:
            ops += f" + {len(c['unique_operators']) - 3}"
        status_chips = []
        for status, n in sorted(c["statuses"].items(), key=lambda x: -x[1]):
            label = {"operational": "live", "under_construction": "building", "announced": "announced"}.get(status, status)
            status_chips.append(f'<span class="chip chip-{status}">{n} {label}</span>')
        mw_str = fmt_mw(c["total_mw"]) if c["total_mw"] > 0 else "&mdash;"
        map_url = f"/?lat={c['lat']:.3f}&lon={c['lon']:.3f}&z=9"

        site_lines = []
        for s in sorted(c["sites"], key=lambda x: -x["announced_mw"]):
            mw_pill = f" &middot; <strong>{fmt_mw(s['announced_mw'])}</strong>" if s["announced_mw"] > 0 else ""
            site_lines.append(
                f'<li><span class="site-name">{html.escape(s["name"])}</span>'
                f' <span class="site-op">{html.escape(s["operator"])}</span>'
                f'{mw_pill}</li>'
            )
        site_list = "\n".join(site_lines)

        rate_pct = c["utility_rate_pct"]
        home_pct = c["home_price_pct"]
        tax_pct = c["property_tax_pct"]

        rows_html.append(f"""
        <article class="rank" id="rank-{i}">
          <div class="rank-num">{i}</div>
          <div class="rank-body">
            <header class="rank-head">
              <h2 class="rank-title">
                <a href="{map_url}">{html.escape(c["county"])} County, {state_name}</a>
              </h2>
              <div class="rank-chips">{"".join(status_chips)}</div>
            </header>
            <div class="rank-stats">
              <div class="stat-block stat-mw">
                <div class="stat-label">Announced load</div>
                <div class="stat-value">{mw_str}</div>
              </div>
              <div class="stat-block">
                <div class="stat-label">Campuses</div>
                <div class="stat-value">{c["n_sites"]}</div>
              </div>
              <div class="stat-block">
                <div class="stat-label">Lead operator</div>
                <div class="stat-value op">{html.escape(c["lead_operator"])}</div>
              </div>
              <div class="stat-block">
                <div class="stat-label">Utility</div>
                <div class="stat-value util">{html.escape(c["lead_utility"])}</div>
              </div>
              <div class="stat-block stat-pct {pct_class(rate_pct, 10)}">
                <div class="stat-label">Resi rate &Delta; (3y)</div>
                <div class="stat-value">{fmt_pct(rate_pct)}</div>
              </div>
              <div class="stat-block stat-pct {pct_class(home_pct, 8)}">
                <div class="stat-label">Home price &Delta; (3y)</div>
                <div class="stat-value">{fmt_pct(home_pct)}</div>
              </div>
              <div class="stat-block stat-pct {pct_class(tax_pct, 15)}">
                <div class="stat-label">Property tax &Delta; (3y)</div>
                <div class="stat-value">{fmt_pct(tax_pct)}</div>
              </div>
            </div>
            <details class="rank-sites">
              <summary>Operators: {html.escape(ops)} &middot; {c["n_sites"]} campus{"es" if c["n_sites"] != 1 else ""}</summary>
              <ul>{site_list}</ul>
            </details>
          </div>
        </article>
        """.strip())

    rows_block = "\n".join(rows_html)

    # State rollup table.
    state_rows = []
    for i, (st, mw, n) in enumerate(state_rank, 1):
        state_rows.append(
            f'<tr><td>{i}</td><td><strong>{STATE_ABBR_TO_NAME.get(st, st)}</strong></td>'
            f'<td class="num">{fmt_mw(mw) if mw > 0 else "&mdash;"}</td>'
            f'<td class="num">{n}</td></tr>'
        )
    state_block = "\n".join(state_rows)

    # JSON-LD ItemList for the ranking. LLM crawlers and Google rank
    # ItemList-marked pages well for "best X" / "top X" queries.
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "@id": "https://powertracker.io/rankings#itemlist",
        "name": "US counties absorbing the most announced AI data-center load",
        "description": (
            f"Top {len(ranked)} US counties ranked by total announced megawatts "
            f"across publicly disclosed AI and hyperscaler data-center campuses, "
            f"joined to utility residential rate change, Redfin home-price change, "
            f"and Census property tax change."
        ),
        "numberOfItems": len(ranked),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "name": f"{c['county']} County, {STATE_ABBR_TO_NAME.get(c['state'], c['state'])}",
                "url": f"https://powertracker.io/rankings#rank-{i}",
            }
            for i, c in enumerate(ranked, 1)
        ],
    }

    total_gw = stats["total_mw"] / 1000
    top10_gw = stats["mw_in_top10"] / 1000
    today = stats["today"]

    # Quick takeaway facts for the LLM-citable opening block. Kept terse;
    # every number traces to the rendered table below.
    page_title = "Top 30 US counties absorbing AI data-center load - powertracker"
    meta_desc = (
        f"30 US counties hosting publicly announced AI / hyperscaler data-center "
        f"campuses, ranked by total announced megawatts. {total_gw:.1f} GW of "
        f"new load across {stats['total_counties']} counties; {stats['concentration_pct']:.0f}% "
        f"in the top 10. Each row joined to utility rate, home price, and "
        f"property tax change."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">

  <title>{html.escape(page_title)}</title>
  <meta name="description" content="{html.escape(meta_desc)}">
  <link rel="canonical" href="https://powertracker.io/rankings">
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
  <meta name="theme-color" content="#d7263d">
  <meta name="author" content="powertracker">
  <meta name="keywords" content="AI data centers ranking, hyperscaler buildout, US counties, gigawatts, utility rates, electricity grid, data center location, Stargate, Meta Hyperion, Project Rainier">

  <meta property="og:type" content="article">
  <meta property="og:site_name" content="powertracker">
  <meta property="og:url" content="https://powertracker.io/rankings">
  <meta property="og:title" content="{html.escape(page_title)}">
  <meta property="og:description" content="{html.escape(meta_desc)}">
  <meta property="og:image" content="https://powertracker.io/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="en_US">
  <meta property="article:published_time" content="{today}">
  <meta property="article:modified_time" content="{today}">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(page_title)}">
  <meta name="twitter:description" content="{html.escape(meta_desc)}">
  <meta name="twitter:image" content="https://powertracker.io/og-image.png">

  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="mask-icon" href="/favicon.svg" color="#d7263d">
  <link rel="sitemap" type="application/xml" href="/sitemap.xml">
  <link rel="alternate" type="application/rss+xml" title="powertracker weekly digest" href="/feed.xml">
  <link rel="alternate" type="text/markdown" title="LLM index (llms.txt)" href="/llms.txt">
  <link rel="alternate" type="text/markdown" title="LLM full corpus (llms-full.txt)" href="/llms-full.txt">

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@graph": [
      {{
        "@type": "WebPage",
        "@id": "https://powertracker.io/rankings#webpage",
        "url": "https://powertracker.io/rankings",
        "name": {json.dumps(page_title)},
        "description": {json.dumps(meta_desc)},
        "inLanguage": "en-US",
        "isPartOf": {{ "@id": "https://powertracker.io/#website" }},
        "about": {{ "@id": "https://powertracker.io/#dataset" }},
        "breadcrumb": {{ "@id": "https://powertracker.io/rankings#breadcrumb" }},
        "datePublished": "{today}",
        "dateModified": "{today}"
      }},
      {{
        "@type": "BreadcrumbList",
        "@id": "https://powertracker.io/rankings#breadcrumb",
        "itemListElement": [
          {{ "@type": "ListItem", "position": 1, "name": "Map", "item": "https://powertracker.io/" }},
          {{ "@type": "ListItem", "position": 2, "name": "Rankings", "item": "https://powertracker.io/rankings" }}
        ]
      }}
    ]
  }}
  </script>

  <script type="application/ld+json">
  {json.dumps(item_list, indent=2)}
  </script>

  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --text-xs:   0.6875rem;
      --text-sm:   0.8125rem;
      --text-base: 0.9375rem;
      --text-lg:   1.0625rem;
      --text-xl:   1.25rem;
      --text-2xl:  1.75rem;
      --text-3xl:  2.5rem;
      --font-stack: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
      --c-page:    #f5f5f7;
      --c-surface: #ffffff;
      --c-ink:     #1a1a23;
      --c-ink-muted: #5a5a6e;
      --c-ink-soft:  #8b8b9a;
      --c-border:    #e3e3e8;
      --c-accent:    #d7263d;
      --c-tag:       #eeeef3;
      --c-hot:       #d7263d;
      --c-hot-bg:    #fbe3e7;
      --c-warm:      #b86e1f;
      --c-warm-bg:   #fdf0d8;
      --c-cool:      #1f6f55;
      --c-cool-bg:   #d8efe4;
      --shadow-sm: 0 1px 2px rgba(20,20,40,0.06);
      --shadow-md: 0 6px 18px -4px rgba(20,20,40,0.12), 0 2px 6px rgba(20,20,40,0.06);
    }}
    html, body {{
      font-family: var(--font-stack);
      font-size: var(--text-base);
      line-height: 1.55;
      color: var(--c-ink);
      background: var(--c-page);
      -webkit-font-smoothing: antialiased;
    }}
    a {{ color: var(--c-accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .page {{ max-width: 1040px; margin: 0 auto; padding: 32px 24px 80px; }}
    header.site {{ margin-bottom: 36px; display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }}
    header.site .brand {{ font-size: var(--text-xl); font-weight: 700; letter-spacing: -0.015em; }}
    header.site .tagline {{ font-size: var(--text-sm); color: var(--c-ink-muted); margin-top: 4px; }}
    header.site nav a {{ font-size: var(--text-sm); margin-left: 14px; }}

    .hero {{ margin-bottom: 32px; }}
    .hero h1 {{ font-size: clamp(1.75rem, 4vw, 2.5rem); font-weight: 800; letter-spacing: -0.02em; line-height: 1.15; color: var(--c-ink); }}
    .hero .lede {{ margin-top: 14px; font-size: var(--text-lg); color: var(--c-ink-muted); max-width: 720px; }}

    .summary {{
      background: var(--c-surface); border: 1px solid var(--c-border);
      border-radius: 10px; padding: 18px 20px; box-shadow: var(--shadow-sm);
      margin-bottom: 32px; display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px;
    }}
    .summary .stat .label {{ font-size: var(--text-xs); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--c-ink-soft); }}
    .summary .stat .value {{ font-size: var(--text-xl); font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; color: var(--c-ink); }}

    .section-head {{ font-size: var(--text-xs); font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--c-ink-soft); margin: 32px 0 14px; padding-top: 12px; border-top: 1px solid var(--c-border); }}

    .rank {{
      display: flex; gap: 18px; background: var(--c-surface);
      border: 1px solid var(--c-border); border-radius: 10px;
      padding: 20px 22px; box-shadow: var(--shadow-sm); margin-bottom: 14px;
      transition: box-shadow 0.15s ease, transform 0.15s ease;
    }}
    .rank:hover {{ box-shadow: var(--shadow-md); }}
    .rank:target {{ border-color: var(--c-accent); box-shadow: 0 0 0 2px rgba(215,38,61,0.15), var(--shadow-md); }}
    .rank-num {{
      font-size: var(--text-2xl); font-weight: 800; color: var(--c-accent);
      min-width: 42px; font-variant-numeric: tabular-nums;
      line-height: 1; padding-top: 4px;
    }}
    .rank-body {{ flex: 1; min-width: 0; }}
    .rank-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }}
    .rank-title {{ font-size: var(--text-xl); font-weight: 700; letter-spacing: -0.01em; }}
    .rank-title a {{ color: var(--c-ink); }}
    .rank-title a:hover {{ color: var(--c-accent); }}
    .rank-chips {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .chip {{
      font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.02em;
      padding: 3px 9px; border-radius: 999px; white-space: nowrap;
      background: var(--c-tag); color: var(--c-ink-muted);
    }}
    .chip-operational {{ background: #d5ecdb; color: #1b5a30; }}
    .chip-under_construction {{ background: #fdf0d8; color: #7a3a10; }}
    .chip-announced {{ background: #e6e6f5; color: #443d72; }}

    .rank-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; }}
    .stat-block {{
      background: #fafafc; border: 1px solid #ececf2; border-radius: 6px; padding: 10px 12px;
    }}
    .stat-block .stat-label {{ font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--c-ink-soft); }}
    .stat-block .stat-value {{ font-size: var(--text-base); font-weight: 700; margin-top: 3px; font-variant-numeric: tabular-nums; color: var(--c-ink); }}
    .stat-block .stat-value.op, .stat-block .stat-value.util {{ font-weight: 600; font-size: var(--text-sm); }}
    .stat-mw .stat-value {{ font-size: var(--text-lg); color: var(--c-accent); }}
    .stat-pct.hot {{ background: var(--c-hot-bg); border-color: var(--c-hot-bg); }}
    .stat-pct.hot .stat-value {{ color: var(--c-hot); }}
    .stat-pct.warm {{ background: var(--c-warm-bg); border-color: var(--c-warm-bg); }}
    .stat-pct.warm .stat-value {{ color: var(--c-warm); }}
    .stat-pct.cool {{ background: var(--c-cool-bg); border-color: var(--c-cool-bg); }}
    .stat-pct.cool .stat-value {{ color: var(--c-cool); }}

    .rank-sites {{ margin-top: 14px; font-size: var(--text-sm); }}
    .rank-sites summary {{ cursor: pointer; color: var(--c-ink-muted); font-weight: 500; padding: 4px 0; }}
    .rank-sites summary:hover {{ color: var(--c-accent); }}
    .rank-sites ul {{ margin: 8px 0 0 6px; padding-left: 16px; }}
    .rank-sites li {{ margin: 4px 0; color: var(--c-ink-muted); }}
    .rank-sites .site-name {{ color: var(--c-ink); font-weight: 600; }}
    .rank-sites .site-op {{ color: var(--c-ink-soft); font-size: var(--text-xs); margin-left: 4px; }}

    .state-table {{
      width: 100%; background: var(--c-surface); border: 1px solid var(--c-border);
      border-radius: 10px; box-shadow: var(--shadow-sm); border-collapse: separate;
      border-spacing: 0; overflow: hidden;
    }}
    .state-table th, .state-table td {{
      padding: 10px 14px; text-align: left; font-size: var(--text-sm);
      border-bottom: 1px solid var(--c-border);
    }}
    .state-table th {{ font-size: var(--text-xs); font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--c-ink-soft); background: #fafafc; }}
    .state-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .state-table tr:last-child td {{ border-bottom: none; }}

    .method {{
      background: var(--c-surface); border: 1px solid var(--c-border); border-left: 3px solid var(--c-accent);
      border-radius: 10px; padding: 18px 22px; margin-top: 32px; font-size: var(--text-sm); color: var(--c-ink-muted); line-height: 1.6;
    }}
    .method h3 {{ font-size: var(--text-base); color: var(--c-ink); margin-bottom: 8px; }}
    .method p + p {{ margin-top: 10px; }}
    .method strong {{ color: var(--c-ink); }}

    footer.foot {{ margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--c-border); font-size: var(--text-xs); color: var(--c-ink-soft); line-height: 1.7; }}
    footer.foot a {{ color: var(--c-ink-muted); }}
    footer.foot a:hover {{ color: var(--c-accent); }}

    @media (max-width: 640px) {{
      .rank {{ flex-direction: column; padding: 16px; }}
      .rank-num {{ padding-top: 0; }}
      .rank-stats {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>

<div class="page">
  <header class="site">
    <div>
      <div class="brand">powertracker &mdash; rankings</div>
      <div class="tagline">Where the AI data-center buildout is concentrating, county by county.</div>
    </div>
    <nav>
      <a href="/">&larr; map</a>
      <a href="/weekly/">weekly</a>
      <a href="/sources">sources</a>
      <a href="https://github.com/vxguo1/powertracker" target="_blank" rel="noopener">github</a>
    </nav>
  </header>

  <section class="hero">
    <h1>The 30 US counties absorbing the AI buildout</h1>
    <p class="lede">
      Across <strong>{stats['total_sites']} publicly known</strong> AI and hyperscaler campuses
      in <strong>{stats['total_counties']} counties</strong> across <strong>{stats['total_states']} states</strong>,
      operators have announced <strong>{total_gw:.1f} gigawatts</strong> of new electricity load.
      <strong>{stats['concentration_pct']:.0f}%</strong> of that load is concentrated in just the
      top 10 counties below &mdash; each one a place where one or two campuses could
      double or triple the local grid&apos;s peak demand.
    </p>
  </section>

  <div class="summary">
    <div class="stat"><div class="label">Tracked campuses</div><div class="value">{stats['total_sites']}</div></div>
    <div class="stat"><div class="label">Counties hosting</div><div class="value">{stats['total_counties']}</div></div>
    <div class="stat"><div class="label">States</div><div class="value">{stats['total_states']}</div></div>
    <div class="stat"><div class="label">Announced load</div><div class="value">{total_gw:.1f} GW</div></div>
    <div class="stat"><div class="label">Top-10 share</div><div class="value">{stats['concentration_pct']:.0f}%</div></div>
  </div>

  <h2 class="section-head">Top 30 counties by announced megawatts</h2>
  {rows_block}

  <h2 class="section-head">By state</h2>
  <table class="state-table">
    <thead>
      <tr><th>#</th><th>State</th><th class="num">Announced load</th><th class="num">Campuses</th></tr>
    </thead>
    <tbody>
      {state_block}
    </tbody>
  </table>

  <div class="method">
    <h3>How this is computed</h3>
    <p>
      <strong>Campus list.</strong> Hand-curated from press releases, FOIA filings,
      local zoning records and news coverage. Every site carries a source URL in
      <a href="https://github.com/vxguo1/powertracker/blob/main/data/sites/data_centers.csv"
         target="_blank" rel="noopener">data/sites/data_centers.csv</a>.
      &quot;Announced load&quot; is the publicly disclosed megawatt figure where the
      operator or utility has stated one; many campuses (especially older
      hyperscaler builds) have never published a number and contribute zero to
      the MW total even though they show up in the campus count.
    </p>
    <p>
      <strong>County rollup.</strong> Each campus is mapped from its city/state
      to a Census FIPS code via <code>us_cities.csv</code> + manual overrides for
      townships and unincorporated sites. Counties are then ranked by the sum of
      announced megawatts across all campuses they host.
    </p>
    <p>
      <strong>Resi rate &Delta;.</strong> The percent change in the county&apos;s lead utility&apos;s
      <em>residential</em> electricity price between 2024 and the mean of 2021&ndash;2023,
      from EIA Form 861. Captures whether households in the county are already
      paying more for power on a multi-year baseline.
    </p>
    <p>
      <strong>Home price &Delta;.</strong> Percent change in the county&apos;s trailing-3-month
      median sale price (volume-weighted by <code>HOMES_SOLD</code>) against the
      mean of the prior three same-month windows at t&minus;12 / t&minus;24 / t&minus;36 months.
      From Redfin Data Center. Counties with &lt; 30 sales in any of those four windows
      are dropped to no-data.
    </p>
    <p>
      <strong>Property tax &Delta;.</strong> Percent change in the county&apos;s median
      real-estate tax (Census ACS B25103) between the latest 5-year endpoint and
      the mean of the prior three. ACS 5-year windows overlap by 4 years &mdash;
      treat magnitude as suggestive.
    </p>
    <p>
      None of these &Delta;s are caused by data centers alone. They are read-outs of
      what the host community has been paying for electricity and housing in
      the years the campus was being planned and built &mdash; the context that&apos;s
      missing from most press-release coverage.
    </p>
  </div>

  <footer class="foot">
    <p>
      Rankings rebuilt {today} from
      <a href="/sources">all data sources</a>.
      Map, campus list, refresh workflows and full pipeline are open source at
      <a href="https://github.com/vxguo1/powertracker" target="_blank" rel="noopener">github.com/vxguo1/powertracker</a>.
      Every row in the campus list carries a citation URL.
    </p>
    <p style="margin-top:8px;">
      Found a missing site, a wrong number, or want to add a layer? File an
      issue or a PR. The schema is open.
    </p>
  </footer>
</div>

</body>
</html>
"""


if __name__ == "__main__":
    main()
