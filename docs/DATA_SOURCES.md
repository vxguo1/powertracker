# Data sources

Every external feed we pull, where it lives, how often it changes upstream,
how often we should refresh, and the exact command to do it.

When you add a source, append a row to the table and a section below.
When you add a refresh job, link it from the **Refresh job** column.

## Quick reference

| # | Source | Upstream cadence | Suggested refresh | Fetch command | Output | Refresh job |
|---|--------|------------------|-------------------|---------------|--------|-------------|
| 1 | EIA balancing-authority hourly demand | hourly (T+~1d lag) | weekly | `python scripts/fetch_demand.py --from-sites --start … --end …` + `scripts/build_aggregates.py` | `data/cache/ba_demand_yoy.csv` | [refresh-eia-demand.yml](../.github/workflows/refresh-eia-demand.yml) |
| 2 | BEA county per-capita GDP | annual (Nov–Dec) | annual | drop raw ZIPs in `data/raw/bea/`, then `scripts/build_aggregates.py` | `data/cache/county_gdp_yoy.csv` | TODO (needs fetcher) |
| 3 | EIA Form 861 utility retail prices | annual (Oct release) | annual | drop raw Excel in `data/raw/eia-861/`, then `scripts/build_aggregates.py` | `data/cache/utility_rate_yoy.csv` | TODO (needs fetcher) |
| 4 | Census ACS 5-year B25103 (median property tax) | annual (Dec release) | annual | `python scripts/fetch_property_tax.py` | `data/cache/property_tax_yoy.csv` | [refresh-property-tax.yml](../.github/workflows/refresh-property-tax.yml) |
| 5 | `tonmcg/US_County_Level_Election_Results_08-24` | one-shot per election | every 4y (after election certification) | manual `curl …/2024_US_County_Level_Presidential_Results.csv` | `data/cache/election_2024_county.csv` | n/a |
| 6 | Reddit search — ICE raid reports | continuous | daily | `python scripts/fetch_ice_hotzones_reddit.py` | `app/ice_hotzones.geojson` | [refresh-reddit.yml](../.github/workflows/refresh-reddit.yml) |
| 7 | Reddit search — protest reports | continuous | daily | `python scripts/fetch_protest_hotzones.py` | `app/protest_hotzones.geojson` | [refresh-reddit.yml](../.github/workflows/refresh-reddit.yml) |
| 8 | Deportation Data Project via Big Local News | monthly snapshot, FOIA-lagged | monthly (alt source, currently unused) | `python scripts/fetch_ice_hotzones.py` | `app/ice_hotzones.geojson` | n/a (alt source) |
| 9 | CDC VSRR Provisional Drug Overdose Deaths (`xkb8-kh2a`) — multi-indicator OD uptick | monthly (first few days of month) | monthly | `python scripts/fetch_od_uptick.py` | `app/od_uptick.geojson` | [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) |
| 10 | CDC Mapping Injury, Overdose, and Violence — State (`fpsi-y8tj`, `All_Homicide`) | quarterly-ish refresh, annual + TTM | monthly | `python scripts/fetch_homicide_uptick.py` | `app/homicide_uptick.geojson` | [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) |
| 10b | NOAA NCEI Climate at a Glance — statewide trailing-12 `tavg` | monthly (T+~10d lag) | monthly | `python scripts/fetch_temperature_yoy.py` | `app/temperature_yoy.geojson` | [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) |
| 11 | Curated data-center site list | as we discover sites | manual | edit `data/sites/data_centers.csv` directly | `data/sites/data_centers.csv` → `app/sites.geojson` | n/a (manual) |
| 12 | Data-center hot zones (derived) | follows #11 | re-run when #11 changes | `python scripts/build_hot_zones.py` | `app/hot_zones.geojson` | n/a (derived) |
| 13 | US county polygons | basically static | as-needed | committed | `data/geo/us_counties.geojson` | n/a (static) |
| 14 | US state polygons | basically static | as-needed | committed | `data/geo/us_states.geojson` | n/a (static) |
| 15 | Balancing-authority territory polygons | basically static | as-needed | committed | `data/geo/ba_territories.geojson` | n/a (static) |
| 16 | Utility territory polygons | annually-ish (HIFLD) | annual | committed; re-download from HIFLD when refreshing | `data/geo/utility_territories.geojson` | n/a (static) |
| 17 | US cities geocoding reference (`kelvins/US-Cities-Database`) | basically static | as-needed | `curl https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv` | `data/cache/us_cities.csv` | n/a (static) |

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
- **Refresh**: daily via [refresh-reddit.yml](../.github/workflows/refresh-reddit.yml).
- **Caveats**: Reddit caps search results at ~100 per query; we top out at ~500–800 unique posts/month regardless of true volume. Heavily biased toward areas with active local subs. Crowd-sourced — not an enforcement record.
- **Geocoding deps**: requires `data/cache/us_cities.csv` (entry #17).

### 7. Reddit protest mentions (live)

- **Upstream**: `reddit.com/search.json` (unauthenticated), 11 queries (`"protest in"`, `"rally in"`, `"march on"`, `"demonstration in"`, `"protest erupted"`, plus a few topic-specific phrases).
- **Script**: [scripts/fetch_protest_hotzones.py](../scripts/fetch_protest_hotzones.py)
- **Cadence**: continuous; rolling 30-day window.
- **Refresh**: daily via [refresh-reddit.yml](../.github/workflows/refresh-reddit.yml).
- **Caveats**: "protest" is far more common on Reddit than "ICE raid" — expect bigger denominators and lower geocoding match rates. Same crowd-sourcing biases as #6. Shares the geocoding stack (subreddit map + `City, ST` regex + major-city allowlist) with the ICE crawler.

### 8. Deportation Data Project (via Big Local News)

- **Upstream**: `data.biglocalnews.org/deportation-data/arrests/{ST}_ice_arrests.csv` — DDP's FOIA'd ICE arrests dataset, mirrored as per-state CSVs.
- **Script**: [scripts/fetch_ice_hotzones.py](../scripts/fetch_ice_hotzones.py)
- **Cadence**: BLN updates roughly monthly. Last observed snapshot ends 2025-10-15.
- **Refresh**: monthly check — but only swap into production if it overtakes the Reddit source's freshness. Currently the Reddit feed (#6) is active.
- **Caveats**: FOIA data lags by months; BLN's mirror often older than DDP's dashboard. More accurate than Reddit for what it covers, but stale.

### 9. CDC VSRR Provisional Drug Overdose Deaths — OD uptick (`xkb8-kh2a`)

- **Upstream**: `data.cdc.gov/resource/xkb8-kh2a.json`, all indicators (all-cause, fentanyl, heroin, methadone, semi-synthetic opioids, cocaine, psychostimulants), state monthly trailing-12-month counts.
- **Script**: [scripts/fetch_od_uptick.py](../scripts/fetch_od_uptick.py)
- **Algorithm**: Z per state per drug-class against baseline `[t-72, t-12]` months; persistence over the prior month; final state level = the most severe class that persists.
- **Cadence**: CDC updates this monthly (first week of the month for the prior month's data).
- **Refresh**: monthly via [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) (5th of each month).
- **Caveats**: rolling-12 data is auto-correlated, so the baseline must be far in the past to avoid overlap — that's why the window starts at `t-72`. Suppressed cells (low-quality footnotes) are filtered out.

### 10. CDC Homicide rate — state TTM (`fpsi-y8tj`, `All_Homicide`)

- **Upstream**: `data.cdc.gov/resource/fpsi-y8tj.json?intent=All_Homicide`, state annual rates per 100k for 2019–2024 plus a TTM (trailing-twelve-months) row.
- **Script**: [scripts/fetch_homicide_uptick.py](../scripts/fetch_homicide_uptick.py)
- **Algorithm**: `z = (TTM_rate - mean(2019..2023)) / stdev(2019..2023)`. No persistence check — TTM and 2024 share 11 months so they aren't independent.
- **Cadence**: CDC refreshes this dataset roughly quarterly; the TTM window slides forward each release.
- **Refresh**: monthly via [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) (re-runs cheap; data only changes when CDC posts a new TTM).
- **Caveats**: 5-year baseline is small — stdev estimates are noisy and small-state Z-scores (Wyoming, the Dakotas) move on a handful of incidents. The spec was weekly; CDC publishes annually. Suppressed cells return as `-999` and are dropped.

### 10b. NOAA Climate at a Glance — state temperature YoY

- **Upstream**: `www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/statewide/time-series/{STATE_ID}/tavg/12/{ENDING_MONTH}/{Y0-Y1}.csv` (unauthenticated, one CSV per state).
- **Script**: [scripts/fetch_temperature_yoy.py](../scripts/fetch_temperature_yoy.py)
- **Algorithm**: Δ°F = (latest trailing-12 mean) − (one year prior trailing-12 mean). Also emits % YoY for the tooltip but the Fahrenheit zero is arbitrary so display the Δ°F as the headline.
- **Cadence**: NOAA publishes the prior month within ~10 days; we re-pull monthly along with the CDC uptick layers.
- **Refresh**: monthly via [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml).
- **Coverage**: NOAA's CONUS divisional series uses state IDs 1-48 (alphabetical) + 50 (Alaska). **Hawaii is not in this series** and renders as no-data.

### 11. Data-center site list (manual / curated)

- **File**: [data/sites/data_centers.csv](../data/sites/data_centers.csv)
- **Cadence**: ad-hoc. Update when you learn about a new hyperscaler announcement.
- **Refresh**: manual edits. After editing, run `python scripts/build_tiles.py` to regenerate `app/sites.geojson`.

### 12. Data-center hot zones (derived)

- **Script**: [scripts/build_hot_zones.py](../scripts/build_hot_zones.py)
- **Cadence**: re-run whenever #11 changes.
- **Output**: [app/hot_zones.geojson](../app/hot_zones.geojson)

### 13–16. Geo polygons (static)

- [data/geo/us_counties.geojson](../data/geo/us_counties.geojson), [data/geo/us_states.geojson](../data/geo/us_states.geojson), [ba_territories.geojson](../data/geo/ba_territories.geojson), [utility_territories.geojson](../data/geo/utility_territories.geojson).
- US Census TIGER (counties), `PublicaMundi/MappingAPI` (states), HIFLD (BA / utility). Re-download from source on the rare occasion boundaries shift (mostly utility territories on multi-year cadence).

### 17. US cities geocoding (`kelvins/US-Cities-Database`)

- **Upstream**: [GitHub raw CSV](https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv)
- **File**: [data/cache/us_cities.csv](../data/cache/us_cities.csv)
- **Cadence**: basically static. ~30k US cities with lat/lon and county.
- **Refresh**: as-needed (years).

---

## Refresh workflows

Four scheduled GitHub Actions live under `.github/workflows/`:

| Workflow | Cron | Covers | Behavior |
|----------|------|--------|----------|
| [refresh-reddit.yml](../.github/workflows/refresh-reddit.yml) | `0 6 * * *` (daily 06:00 UTC) | ICE raid reports + protest reports | Runs `fetch_ice_hotzones_reddit.py` and `fetch_protest_hotzones.py`, commits only if geojson changed, deploys |
| [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) | `0 6 5 * *` (5th @ 06:00 UTC) | OD uptick + homicide uptick + temperature YoY | Runs `fetch_od_uptick.py`, `fetch_homicide_uptick.py`, `fetch_temperature_yoy.py`; commits if changed, deploys |
| [refresh-eia-demand.yml](../.github/workflows/refresh-eia-demand.yml) | `0 7 * * 1` (Mon @ 07:00 UTC) | EIA hourly demand → BA YoY → `ba.pmtiles` | Pulls 24 months of hourly demand, recomputes YoY, rebuilds tiles via Docker, deploys |
| [refresh-property-tax.yml](../.github/workflows/refresh-property-tax.yml) | `0 7 15 1 *` (Jan 15 @ 07:00 UTC) | ACS property tax → `property_tax.pmtiles` | Refetches Census API, rebuilds tiles via Docker, deploys |

All workflows require the following **GitHub Secrets** (Settings →
Secrets and variables → Actions):

| Secret | Used by | What it is |
|--------|---------|------------|
| `CLOUDFLARE_API_TOKEN` | all four | Workers Scripts: Edit, scoped to the powertracker account |
| `CLOUDFLARE_ACCOUNT_ID` | all four | The `d8e8518b7870983e964bdd183fc718b6` account id |
| `EIA_API_KEY` | refresh-eia-demand | Free key from [eia.gov/opendata/register](https://www.eia.gov/opendata/register.php) |

All commits use the repo's built-in `GITHUB_TOKEN`. Concurrency groups
prevent overlapping runs of the same workflow.

### Workflow pattern

Every refresh workflow follows the same skeleton:
1. Check out the repo (`actions/checkout@v4`).
2. Set up Python (`actions/setup-python@v5`).
3. Install minimal pip deps for the scripts that will run.
4. Run the fetch script(s) — they write to `app/` or `data/cache/`.
5. If the source feeds into a PMTiles layer, run `scripts/build_tiles.py`
   (Docker is pre-installed on the runner; the tippecanoe + go-pmtiles
   images pull on first use).
6. `git diff --cached --quiet`-gate a commit so we don't push empty
   refreshes.
7. Set up Node (`actions/setup-node@v4`) and run `npx wrangler deploy`.

### Still manual

| # | Source | What's missing |
|---|--------|----------------|
| 2 | BEA county GDP | Needs a `scripts/fetch_bea_gdp.py` that downloads the CAGDP1 + CAINC1 ZIPs from `apps.bea.gov/regional/zip/`. Once that exists, wire it into a `refresh-bea.yml` or fold it into `refresh-property-tax.yml`. |
| 3 | EIA-861 utility prices | Needs a `scripts/fetch_eia861.py` that downloads `eia861<year>.zip` from `eia.gov/electricity/data/eia861/zip/` and extracts the `Sales_Ult_Cust_<year>.xlsx` sheet. |
| 5 | Election results | One-shot per cycle; no need to schedule. |
| 11 | Data-center site list | Manual edits to a CSV — no automation possible. |
| 12 | Hot zones (derived) | Re-run after #11 changes; trivial to add a workflow that watches the CSV path, deferred until #11 churns. |
| 13–17 | Geo / cities | Effectively static. |

Drop a `scripts/fetch_*.py` for the missing fetchers and a
`refresh-*.yml` workflow follows the same skeleton as the existing
four.
