# Data sources

Every external feed we pull, where it lives, how often it changes upstream,
how often we should refresh, and the exact command to do it.

When you add a source, append a row to the table and a section below.
When you add a refresh job, link it from the **Refresh job** column.

## Quick reference

| # | Source | Upstream cadence | Suggested refresh | Fetch command | Output | Refresh job |
|---|--------|------------------|-------------------|---------------|--------|-------------|
| 1 | EIA balancing-authority hourly demand | hourly (T+~1d lag) | weekly | `python scripts/fetch_demand.py` | `data/cache/ba_demand_yoy.csv` | TODO |
| 2 | BEA county per-capita GDP | annual (Nov–Dec) | annual | (computed in `src/powertracker/gdp.py` via `yoy_per_capita_gdp(2023, 2024)`) | `data/cache/county_gdp_yoy.csv` | TODO |
| 3 | EIA Form 861 utility retail prices | annual (Oct release) | annual | (computed in `src/powertracker/prices.py`) | `data/cache/utility_rate_yoy.csv` | TODO |
| 4 | Census ACS 5-year B25103 (median property tax) | annual (Dec release) | annual | `python scripts/fetch_property_tax.py` | `data/cache/property_tax_yoy.csv` | TODO |
| 5 | `tonmcg/US_County_Level_Election_Results_08-24` | one-shot per election | every 4y (after election certification) | manual `curl …/2024_US_County_Level_Presidential_Results.csv` | `data/cache/election_2024_county.csv` | n/a |
| 6 | Reddit search — ICE raid reports | continuous | **weekly** (or daily once budgeted) | `python scripts/fetch_ice_hotzones_reddit.py` | `app/ice_hotzones.geojson` | TODO |
| 7 | Deportation Data Project via Big Local News | monthly snapshot, FOIA-lagged | monthly (unused while #6 is active) | `python scripts/fetch_ice_hotzones.py` | `app/ice_hotzones.geojson` | n/a (alt source) |
| 8 | Curated data-center site list | as we discover sites | manual | edit `data/sites/data_centers.csv` directly | `data/sites/data_centers.csv` → `app/sites.geojson` | n/a (manual) |
| 9 | Data-center hot zones (derived) | follows #8 | re-run when #8 changes | `python scripts/build_hot_zones.py` | `app/hot_zones.geojson` | n/a (derived) |
| 10 | US county polygons | basically static | as-needed | committed | `data/geo/us_counties.geojson` | n/a (static) |
| 11 | Balancing-authority territory polygons | basically static | as-needed | committed | `data/geo/ba_territories.geojson` | n/a (static) |
| 12 | Utility territory polygons | annually-ish (HIFLD) | annual | committed; re-download from HIFLD when refreshing | `data/geo/utility_territories.geojson` | n/a (static) |
| 13 | US cities geocoding reference (`kelvins/US-Cities-Database`) | basically static | as-needed | `curl https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv` | `data/cache/us_cities.csv` | n/a (static) |

After any **cached CSV** change (rows 1–7), tiles need rebuilding:
```
python scripts/build_tiles.py    # ba/utility/county/election/property_tax pmtiles
python scripts/build_hot_zones.py # data-center hot zones
```
Then `npx wrangler deploy`.

The Reddit job (#6) writes directly to `app/ice_hotzones.geojson` and doesn't
need `build_tiles.py`. Just deploy.

---

## Detailed entries

### 1. EIA balancing-authority hourly demand

- **Upstream**: EIA Open Data API, demand series by balancing authority.
- **Module**: [src/powertracker/demand.py](../src/powertracker/demand.py), [src/powertracker/eia.py](../src/powertracker/eia.py)
- **Auth**: requires `EIA_API_KEY` env var (`.env`).
- **Cadence**: EIA updates hourly with ~1-day lag. We compute trailing-12-month vs prior-12-month YoY.
- **Refresh**: weekly is plenty for a YoY metric.
- **What changes**: rolling 12-month aggregates shift as new days come in.

### 2. BEA county per-capita GDP

- **Upstream**: Bureau of Economic Analysis CAGDP1/CAGDP2 tables.
- **Module**: [src/powertracker/gdp.py](../src/powertracker/gdp.py)
- **Cadence**: BEA releases county-level real GDP annually, typically December covering through year-1.
- **Refresh**: annual after each release. Currently joins 2023→2024.
- **Future**: bump the year arguments in `yoy_per_capita_gdp(2024, 2025)` once 2025 lands.

### 3. EIA Form 861 utility retail rates

- **Upstream**: EIA-861 annual utility filings.
- **Module**: [src/powertracker/prices.py](../src/powertracker/prices.py)
- **Cadence**: EIA-861 final release in October each year for the prior year.
- **Refresh**: annual. Currently joins 2023→2024.

### 4. Census ACS 5-year median property tax (B25103)

- **Upstream**: `api.census.gov/data/{year}/acs/acs5` (unauthenticated). Variable `B25103_001E`.
- **Script**: [scripts/fetch_property_tax.py](../scripts/fetch_property_tax.py)
- **Cadence**: ACS 5-year releases every December, covering the trailing 5 years.
- **Refresh**: annual (December). Bump the years in the script when ACS 2025 5-year drops.
- **Caveats**: 5-year windows overlap by 4 years, so "YoY" is really a 1-year window shift. MOE is large in small counties.

### 5. 2024 county-level presidential election results

- **Upstream**: [`tonmcg/US_County_Level_Election_Results_08-24`](https://github.com/tonmcg/US_County_Level_Election_Results_08-24) (community-maintained, sourced from AP/Politico).
- **Fetched once with**: `curl -sL https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master/2024_US_County_Level_Presidential_Results.csv -o data/cache/election_2024_county.csv`
- **Cadence**: snapshot per election; certification adjustments trickle in for a few months after election day.
- **Refresh**: every 4 years; one extra refetch the spring after the election in case of late corrections.

### 6. Reddit ICE raid mentions (live)

- **Upstream**: `reddit.com/search.json` (unauthenticated), 8 queries (`"ICE raid"`, `"ICE arrest"`, etc.).
- **Script**: [scripts/fetch_ice_hotzones_reddit.py](../scripts/fetch_ice_hotzones_reddit.py)
- **Cadence**: continuous; we read a 30-day window of the firehose.
- **Refresh**: **weekly minimum**, daily if we want fresher hot zones.
- **Caveats**: Reddit caps search results at ~100 per query; we top out at ~500–800 unique posts/month regardless of true volume. Heavily biased toward areas with active local subs. Crowd-sourced — not an enforcement record.
- **Geocoding deps**: requires `data/cache/us_cities.csv` (entry #13).

### 7. Deportation Data Project (via Big Local News)

- **Upstream**: `data.biglocalnews.org/deportation-data/arrests/{ST}_ice_arrests.csv` — DDP's FOIA'd ICE arrests dataset, mirrored as per-state CSVs.
- **Script**: [scripts/fetch_ice_hotzones.py](../scripts/fetch_ice_hotzones.py)
- **Cadence**: BLN updates roughly monthly. Last observed snapshot ends 2025-10-15.
- **Refresh**: monthly check — but only swap into production if it overtakes the Reddit source's freshness. Currently the Reddit feed (#6) is active.
- **Caveats**: FOIA data lags by months; BLN's mirror often older than DDP's dashboard. More accurate than Reddit for what it covers, but stale.

### 8. Data-center site list (manual / curated)

- **File**: [data/sites/data_centers.csv](../data/sites/data_centers.csv)
- **Cadence**: ad-hoc. Update when you learn about a new hyperscaler announcement.
- **Refresh**: manual edits. After editing, run `python scripts/build_tiles.py` to regenerate `app/sites.geojson`.

### 9. Data-center hot zones (derived)

- **Script**: [scripts/build_hot_zones.py](../scripts/build_hot_zones.py)
- **Cadence**: re-run whenever #8 changes.
- **Output**: [app/hot_zones.geojson](../app/hot_zones.geojson)

### 10–12. Geo polygons (static)

- [data/geo/us_counties.geojson](../data/geo/us_counties.geojson), [ba_territories.geojson](../data/geo/ba_territories.geojson), [utility_territories.geojson](../data/geo/utility_territories.geojson).
- US Census TIGER (counties) and HIFLD (BA / utility). Re-download from source on the rare occasion boundaries shift (mostly utility territories on multi-year cadence).

### 13. US cities geocoding (`kelvins/US-Cities-Database`)

- **Upstream**: [GitHub raw CSV](https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv)
- **File**: [data/cache/us_cities.csv](../data/cache/us_cities.csv)
- **Cadence**: basically static. ~30k US cities with lat/lon and county.
- **Refresh**: as-needed (years).

---

## Building refresh jobs

When wiring scheduled refreshes, the natural pattern is:

```
.github/workflows/refresh-{source}.yml   # cron, runs fetch + tile build + wrangler deploy
```

Each workflow should:
1. Check out the repo.
2. Set up Python + (for tile builds) Docker.
3. Run the fetch script.
4. Run `build_tiles.py` if the source feeds into a PMTiles layer.
5. Commit & push the regenerated artifacts.
6. `npx wrangler deploy` with `CLOUDFLARE_API_TOKEN` from secrets.

Sensitive: the Cloudflare token must come from GitHub Secrets, not the repo.
Currently nothing is automated — every entry above is **manual** until we wire
the workflows.
