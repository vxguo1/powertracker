"""Crowd-source ICE raid hot zones from Reddit posts in the past 30 days.

This replaces the FOIA-sourced fetch_ice_hotzones.py for live coverage.
The Reddit data is noisy and biased toward where active immigrant-
rights communities post, but it covers the literal past 30 days
whereas FOIA data lags by months.

Pipeline:
  1. Query Reddit's unauthenticated search.json across several phrasings
     ("ICE raid", "ICE arrest", "ICE checkpoint", ...). Reddit returns
     up to 100 results per query.
  2. Drop posts older than 30 days, drop duplicates by permalink.
  3. Extract a (city, state) location for each post:
       a. If the subreddit name matches a US city, use that.
       b. Otherwise scan the title and selftext for "City, ST" or
          "City, State" patterns against the cities CSV.
  4. Geocode via the cities CSV and aggregate counts by city.
  5. Emit app/ice_hotzones.geojson with the same ring/marker schema
     that the frontend already expects, plus a per-feature `examples`
     property carrying a few post titles for the tooltip.

Output schema: identical to scripts/fetch_ice_hotzones.py so the
MapLibre layers don't need to change. The legend/tooltip in
app/index.html mentions Reddit + the date window.
"""

from __future__ import annotations

import csv
import json
import math
import re
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CITIES_CSV = REPO_ROOT / "data" / "cache" / "us_cities.csv"
OUT = REPO_ROOT / "app" / "ice_hotzones.geojson"

QUERIES = [
    '"ICE raid"',
    '"ICE raids"',
    '"ICE arrest"',
    '"ICE arrests"',
    '"ICE checkpoint"',
    '"ICE detained"',
    '"ICE agents"',
    '"immigration raid"',
]
UA = "powertracker/0.1 (data overlay; contact via github)"

STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","DC":"District of Columbia",
    "FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois",
    "IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana",
    "ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota",
    "MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada",
    "NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York",
    "NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon",
    "PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota",
    "TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia",
    "WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
}
STATE_NAME_TO_CODE = {v.upper(): k for k, v in STATE_NAMES.items()}

# Hand-picked subreddit -> (city, state). Reddit has thousands of city
# subreddits with idiosyncratic names; this list covers the biggest
# metros plus the subs that surfaced in test queries.
SUBREDDIT_CITY: dict[str, tuple[str, str]] = {
    "losangeles": ("Los Angeles", "CA"),
    "sandiego": ("San Diego", "CA"),
    "sanfrancisco": ("San Francisco", "CA"),
    "sacramento": ("Sacramento", "CA"),
    "oakland": ("Oakland", "CA"),
    "orangecounty": ("Santa Ana", "CA"),
    "longbeach": ("Long Beach", "CA"),
    "fresno": ("Fresno", "CA"),
    "bayarea": ("San Francisco", "CA"),
    "whittier": ("Whittier", "CA"),
    "burbank": ("Burbank", "CA"),
    "glendale": ("Glendale", "CA"),
    "compton": ("Compton", "CA"),
    "houston": ("Houston", "TX"),
    "dallas": ("Dallas", "TX"),
    "austin": ("Austin", "TX"),
    "sanantonio": ("San Antonio", "TX"),
    "elpaso": ("El Paso", "TX"),
    "fortworth": ("Fort Worth", "TX"),
    "chicago": ("Chicago", "IL"),
    "nyc": ("New York", "NY"),
    "newyorkcity": ("New York", "NY"),
    "queens": ("New York", "NY"),
    "brooklyn": ("New York", "NY"),
    "thebronx": ("New York", "NY"),
    "staten_island": ("New York", "NY"),
    "longisland": ("Hempstead", "NY"),
    "miami": ("Miami", "FL"),
    "orlando": ("Orlando", "FL"),
    "tampa": ("Tampa", "FL"),
    "jacksonville": ("Jacksonville", "FL"),
    "atlanta": ("Atlanta", "GA"),
    "boston": ("Boston", "MA"),
    "philadelphia": ("Philadelphia", "PA"),
    "pittsburgh": ("Pittsburgh", "PA"),
    "washingtondc": ("Washington", "DC"),
    "nova": ("Arlington", "VA"),
    "baltimore": ("Baltimore", "MD"),
    "seattle": ("Seattle", "WA"),
    "portland": ("Portland", "OR"),
    "denver": ("Denver", "CO"),
    "phoenix": ("Phoenix", "AZ"),
    "tucson": ("Tucson", "AZ"),
    "mesa": ("Mesa", "AZ"),
    "lasvegas": ("Las Vegas", "NV"),
    "reno": ("Reno", "NV"),
    "minneapolis": ("Minneapolis", "MN"),
    "stpaul": ("Saint Paul", "MN"),
    "detroit": ("Detroit", "MI"),
    "cleveland": ("Cleveland", "OH"),
    "columbus": ("Columbus", "OH"),
    "cincinnati": ("Cincinnati", "OH"),
    "milwaukee": ("Milwaukee", "WI"),
    "kansascity": ("Kansas City", "MO"),
    "stlouis": ("Saint Louis", "MO"),
    "neworleans": ("New Orleans", "LA"),
    "memphis": ("Memphis", "TN"),
    "nashville": ("Nashville", "TN"),
    "raleigh": ("Raleigh", "NC"),
    "charlotte": ("Charlotte", "NC"),
    "richmond": ("Richmond", "VA"),
    "albuquerque": ("Albuquerque", "NM"),
    "saltlakecity": ("Salt Lake City", "UT"),
    "morriscountyicenews": ("Morristown", "NJ"),
}


def reddit_search(query: str, t: str = "month", limit: int = 100,
                  sort: str = "new") -> list[dict]:
    url = ("https://www.reddit.com/search.json"
           f"?q={urllib.request.quote(query)}&t={t}&sort={sort}&limit={limit}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  ! {query}: HTTP {e.code}")
        return []
    return [c["data"] for c in data.get("data", {}).get("children", [])]


def load_cities() -> tuple[dict[str, list[tuple[str, str, float, float]]],
                            dict[tuple[str, str], tuple[float, float]]]:
    """Returns:
      - by_name_upper:   city upper-case -> list of (state_code, county, lat, lon)
      - by_pair:         (city upper, state code) -> (lat, lon) [unique]"""
    by_name: dict[str, list[tuple[str, str, float, float]]] = defaultdict(list)
    by_pair: dict[tuple[str, str], tuple[float, float]] = {}
    with open(CITIES_CSV, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            city = (row["CITY"] or "").strip()
            state = (row["STATE_CODE"] or "").strip().upper()
            try:
                lat = float(row["LATITUDE"]); lon = float(row["LONGITUDE"])
            except ValueError:
                continue
            cnty = (row["COUNTY"] or "").strip()
            by_name[city.upper()].append((state, cnty, lat, lon))
            by_pair.setdefault((city.upper(), state), (lat, lon))
    return by_name, by_pair


# Bare-name city matches against the 30k-row CSV are too noisy — every
# tiny village called "Force" or "Russia" matches. Restrict bare-name
# matching to a curated allowlist of unambiguous major cities.
MAJOR_CITY = {
    "NEW YORK":("New York","NY"),"NEW YORK CITY":("New York","NY"),
    "MANHATTAN":("New York","NY"),"BROOKLYN":("New York","NY"),
    "QUEENS":("New York","NY"),"THE BRONX":("New York","NY"),
    "LOS ANGELES":("Los Angeles","CA"),"CHICAGO":("Chicago","IL"),
    "HOUSTON":("Houston","TX"),"PHOENIX":("Phoenix","AZ"),
    "PHILADELPHIA":("Philadelphia","PA"),"SAN ANTONIO":("San Antonio","TX"),
    "SAN DIEGO":("San Diego","CA"),"DALLAS":("Dallas","TX"),
    "SAN JOSE":("San Jose","CA"),"AUSTIN":("Austin","TX"),
    "JACKSONVILLE":("Jacksonville","FL"),"FORT WORTH":("Fort Worth","TX"),
    "INDIANAPOLIS":("Indianapolis","IN"),"CHARLOTTE":("Charlotte","NC"),
    "SAN FRANCISCO":("San Francisco","CA"),"SEATTLE":("Seattle","WA"),
    "DENVER":("Denver","CO"),"OKLAHOMA CITY":("Oklahoma City","OK"),
    "NASHVILLE":("Nashville","TN"),"EL PASO":("El Paso","TX"),
    "BOSTON":("Boston","MA"),"LAS VEGAS":("Las Vegas","NV"),
    "DETROIT":("Detroit","MI"),"MEMPHIS":("Memphis","TN"),
    "LOUISVILLE":("Louisville","KY"),"BALTIMORE":("Baltimore","MD"),
    "MILWAUKEE":("Milwaukee","WI"),"ALBUQUERQUE":("Albuquerque","NM"),
    "TUCSON":("Tucson","AZ"),"FRESNO":("Fresno","CA"),
    "MESA":("Mesa","AZ"),"SACRAMENTO":("Sacramento","CA"),
    "ATLANTA":("Atlanta","GA"),"KANSAS CITY":("Kansas City","MO"),
    "MIAMI":("Miami","FL"),"TAMPA":("Tampa","FL"),
    "ORLANDO":("Orlando","FL"),"CLEVELAND":("Cleveland","OH"),
    "PITTSBURGH":("Pittsburgh","PA"),"CINCINNATI":("Cincinnati","OH"),
    "ST. LOUIS":("Saint Louis","MO"),"SAINT LOUIS":("Saint Louis","MO"),
    "MINNEAPOLIS":("Minneapolis","MN"),"RALEIGH":("Raleigh","NC"),
    "NEW ORLEANS":("New Orleans","LA"),"OAKLAND":("Oakland","CA"),
    "LONG BEACH":("Long Beach","CA"),"OMAHA":("Omaha","NE"),
    "BAKERSFIELD":("Bakersfield","CA"),"ANCHORAGE":("Anchorage","AK"),
    "MCALLEN":("Mcallen","TX"),"BROWNSVILLE":("Brownsville","TX"),
    "LAREDO":("Laredo","TX"),"YUMA":("Yuma","AZ"),
    "WHITTIER":("Whittier","CA"),"SANTA ANA":("Santa Ana","CA"),
    "COMPTON":("Compton","CA"),"CHULA VISTA":("Chula Vista","CA"),
    "PASADENA":("Pasadena","CA"),"BURBANK":("Burbank","CA"),
    "GLENDALE":("Glendale","CA"),"NEWARK":("Newark","NJ"),
    "JERSEY CITY":("Jersey City","NJ"),"PATERSON":("Paterson","NJ"),
    "MORRISTOWN":("Morristown","NJ"),"ARLINGTON":("Arlington","VA"),
    "RICHMOND":("Richmond","VA"),"ALEXANDRIA":("Alexandria","VA"),
    "CHARLESTON":("Charleston","SC"),"COLUMBUS":("Columbus","OH"),
    "WASHINGTON, D.C.":("Washington","DC"),"WASHINGTON DC":("Washington","DC"),
}


def extract_location(post: dict, by_name, by_pair) -> tuple[str, str] | None:
    sub = (post.get("subreddit") or "").lower()
    if sub in SUBREDDIT_CITY:
        return SUBREDDIT_CITY[sub]
    text = " ".join(filter(None, [post.get("title"), post.get("selftext")]))

    # 1) Explicit "City, ST" or "City, State" patterns.
    for m in re.finditer(r"\b([A-Z][A-Za-z .'-]{1,30})[,]\s*([A-Za-z .]{2,20})\b", text):
        city = m.group(1).strip()
        st_token = m.group(2).strip()
        st = None
        if len(st_token) == 2 and st_token.upper() in STATE_NAMES:
            st = st_token.upper()
        elif st_token.upper() in STATE_NAME_TO_CODE:
            st = STATE_NAME_TO_CODE[st_token.upper()]
        if st and (city.upper(), st) in by_pair:
            return (city, st)

    # 2) Bare-name match limited to MAJOR_CITY. Longer phrases first so
    #    "New York City" wins over "New York", "San Antonio" over "San".
    keys = sorted(MAJOR_CITY.keys(), key=lambda k: -len(k))
    upper = text.upper()
    for key in keys:
        # Word-boundary check by surrounding chars (re.escape so ". " ok).
        pat = re.compile(r"(?<![A-Z])" + re.escape(key) + r"(?![A-Z])")
        if pat.search(upper):
            return MAJOR_CITY[key]
    return None


def main() -> None:
    print("Loading US cities ...")
    by_name, by_pair = load_cities()
    print(f"  {sum(len(v) for v in by_name.values())} city rows; "
          f"{len(by_pair)} unique (city,state) pairs")

    print("Querying Reddit ...")
    posts: dict[str, dict] = {}
    for q in QUERIES:
        results = reddit_search(q)
        print(f"  {q}: {len(results)} posts")
        for p in results:
            posts.setdefault(p["permalink"], p)
        time.sleep(2)  # be polite, unauthenticated endpoint
    print(f"Unique posts: {len(posts)}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    fresh = [p for p in posts.values() if p.get("created_utc")
             and datetime.fromtimestamp(p["created_utc"], tz=timezone.utc) >= cutoff]
    print(f"Within 30d: {len(fresh)}")

    # Group by (city, state).
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    unmatched = 0
    for p in fresh:
        loc = extract_location(p, by_name, by_pair)
        if loc is None:
            unmatched += 1
            continue
        grouped[loc].append(p)
    print(f"Geocoded {sum(len(v) for v in grouped.values())} posts to "
          f"{len(grouped)} city buckets; {unmatched} unmatched.")

    # Reddit volumes are far smaller than FOIA, so use friendlier tiers.
    # Numeric labels (not S/A/B/C/D) so they don't visually collide with
    # the data-center hot-zone tiers that share the same marker style.
    tiers = [
        ("1", 10, "#7a0019"),
        ("2",  5, "#d7263d"),
        ("3",  3, "#f46036"),
        ("4",  2, "#f5a623"),
        ("5",  1, "#9e9e9e"),
    ]

    features = []
    for (city, st), ps in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        latlon = by_pair.get((city.upper(), st))
        if not latlon:
            continue
        lat, lon = latlon
        n = len(ps)
        tier_label, tier_color = "D", "#9e9e9e"
        for label, thresh, color in tiers:
            if n >= thresh:
                tier_label, tier_color = label, color
                break

        deg_per_mi = 1.0 / 69.0
        ring_mi = min(120.0, max(10.0, 10.0 * math.sqrt(n)))
        ring_deg = ring_mi * deg_per_mi
        ring_coords = []
        for k in range(33):
            theta = 2 * math.pi * k / 32
            ring_coords.append([
                lon + ring_deg * math.cos(theta) / math.cos(math.radians(lat)),
                lat + ring_deg * math.sin(theta),
            ])

        examples = []
        for p in ps[:3]:
            examples.append({
                "title": (p.get("title") or "")[:160],
                "subreddit": p.get("subreddit"),
                "permalink": "https://reddit.com" + (p.get("permalink") or ""),
                "score": int(p.get("score") or 0),
            })

        common = {
            "tier": tier_label, "tier_color": tier_color, "n_arrests": n,
            "county": city, "state": STATE_NAMES.get(st, st),
            "label": f"{tier_label}: {n} Reddit post{'' if n==1 else 's'}",
            "examples": examples,
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring_coords]},
            "properties": {**common, "kind": "ring"},
        })
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {**common, "kind": "marker"},
        })

    gj = {
        "type": "FeatureCollection",
        "metadata": {
            "window_start": cutoff.date().isoformat(),
            "window_end": datetime.now(timezone.utc).date().isoformat(),
            "n_total_in_window": sum(len(v) for v in grouped.values()),
            "n_unmatched": unmatched,
            "source": "Reddit search across multiple queries",
        },
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(gj, f)
    print(f"Wrote {OUT} ({OUT.stat().st_size/1024:.1f} KB) "
          f"with {len(features)//2} hot zones")


if __name__ == "__main__":
    main()
