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
| 11 | NOAA NCEI Climate at a Glance — statewide trailing-12 `tavg` (vs 3-yr baseline) | monthly (T+~10d lag) | monthly | `python scripts/fetch_temperature_yoy.py` | `app/temperature_yoy.geojson` | [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) |
| 12 | NOAA Storm Events Database (outage-driving event counts, state monthly) | monthly | monthly | `python scripts/fetch_outage_uptick.py` | `app/outage_uptick.geojson` | TODO (fold into refresh-cdc.yml) |
| 13 | Curated data-center site list | as we discover sites | manual | edit `data/sites/data_centers.csv` directly | `data/sites/data_centers.csv` → `app/sites.geojson` | n/a (manual) |
| 14 | Data-center hot zones (derived) | follows #13 | re-run when #13 changes | `python scripts/build_hot_zones.py` | `app/hot_zones.geojson` | n/a (derived) |
| 15 | US county polygons | basically static | as-needed | committed | `data/geo/us_counties.geojson` | n/a (static) |
| 16 | US state polygons | basically static | as-needed | committed | `data/geo/us_states.geojson` | n/a (static) |
| 17 | Balancing-authority territory polygons | basically static | as-needed | committed | `data/geo/ba_territories.geojson` | n/a (static) |
| 18 | Utility territory polygons | annually-ish (HIFLD) | annual | committed; re-download from HIFLD when refreshing | `data/geo/utility_territories.geojson` | n/a (static) |
| 19 | US cities geocoding reference (`kelvins/US-Cities-Database`) | basically static | as-needed | `curl https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv` | `data/cache/us_cities.csv` | n/a (static) |
| 20 | Redfin Data Center — county monthly median sale price (3mo rolling vs 3-yr baseline) | monthly | monthly | `python scripts/fetch_realestate_yoy.py` | `data/cache/realestate_yoy.csv` → `app/tiles/realestate.pmtiles` | [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) |
| 21 | EIA power plants (≥ 100 MW, ArcGIS REST) | annual (EIA-860 Sept) | annual | `python scripts/fetch_power_infra.py` | `app/power_plants.geojson` | [refresh-power.yml](../.github/workflows/refresh-power.yml) |
| 22 | OpenStreetMap power substations (≥ 69 kV, via Overpass API) | continuous (OSM edits) | annual | `python scripts/fetch_power_infra.py` | `data/cache/substations.geojson` → `app/tiles/substations.pmtiles` | [refresh-power.yml](../.github/workflows/refresh-power.yml) |
| 23 | EIA electric power transmission lines (ArcGIS REST) | irregular (HIFLD updates) | annual | `python scripts/fetch_power_infra.py` | `data/cache/transmission_lines.geojson` → `app/tiles/transmission_lines.pmtiles` | [refresh-power.yml](../.github/workflows/refresh-power.yml) |

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
- **Cadence**: EIA updates hourly with ~1-day lag. We compute trailing-12-month vs the mean of the 3 prior trailing-12-month windows (anchored at t-12, t-24, t-36 months back).
- **Refresh**: weekly is plenty for a baselined metric.
- **What changes**: the trailing-12 and each of the 3 baseline windows shift as new days come in; each BA needs ≥80% hour coverage in all 4 windows or it falls back to no-data.

### 2. BEA county per-capita GDP

- **Upstream**: Bureau of Economic Analysis CAGDP1/CAGDP2 tables.
- **Module**: [src/powertracker/gdp.py](../src/powertracker/gdp.py)
- **Cadence**: BEA releases county-level real GDP annually, typically December covering through year-1.
- **Refresh**: annual after each release. Currently compares 2024 against the mean of 2021, 2022, 2023.
- **Future**: bump `yoy_per_capita_gdp(2025)` once 2025 lands; the baseline auto-shifts to 2022-2024.

### 3. EIA Form 861 utility retail rates

- **Upstream**: EIA-861 annual utility filings.
- **Module**: [src/powertracker/prices.py](../src/powertracker/prices.py)
- **Cadence**: EIA-861 final release in October each year for the prior year.
- **Refresh**: annual. Currently compares 2024 against the mean of 2021, 2022, 2023.

### 4. Census ACS 5-year median property tax (B25103)

- **Upstream**: `api.census.gov/data/{year}/acs/acs5` (unauthenticated). Variable `B25103_001E`.
- **Script**: [scripts/fetch_property_tax.py](../scripts/fetch_property_tax.py)
- **Cadence**: ACS 5-year releases every December, covering the trailing 5 years.
- **Refresh**: annual (December). Bump `CURRENT_YEAR` in the script when ACS 2025 5-year drops.
- **Algorithm**: compares ACS 2024 against the mean of ACS 2021, 2022, 2023.
- **Caveats**: 5-year windows overlap by 4 years, so the 3 baseline samples are nearly the same population. The "% vs 3yr baseline" reading is attenuated relative to the other layers and should be treated as suggestive only. MOE is large in small counties.

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

### 11. NOAA Climate at a Glance — state temperature vs 3-yr baseline

- **Upstream**: `www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/statewide/time-series/{STATE_ID}/tavg/12/{ENDING_MONTH}/{Y0-Y1}.csv` (unauthenticated, one CSV per state).
- **Script**: [scripts/fetch_temperature_yoy.py](../scripts/fetch_temperature_yoy.py)
- **Algorithm**: Δ°F = (latest trailing-12 mean) − mean(prior 3 trailing-12 means at the same ending-month, t-12 / t-24 / t-36 months back). Also emits % vs baseline for the tooltip but the Fahrenheit zero is arbitrary so display Δ°F as the headline. Fetcher pulls 6 years of monthly anchors so 4 valid endpoints are virtually guaranteed.
- **Cadence**: NOAA publishes the prior month within ~10 days; we re-pull monthly along with the CDC uptick layers.
- **Refresh**: monthly via [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml).
- **Coverage**: NOAA's CONUS divisional series uses state IDs 1-48 (alphabetical) + 50 (Alaska). **Hawaii is not in this series** and renders as no-data.

### 12. NOAA Storm Events - power outage uptick proxy

- **Upstream**: `ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/` - per-year `StormEvents_details-ftp_v1.0_dYYYY_cYYYYMMDD.csv.gz`.
- **Script**: [scripts/fetch_outage_uptick.py](../scripts/fetch_outage_uptick.py)
- **Algorithm**: For each state, count outage-driving events (Thunderstorm Wind, Tornado, Ice Storm, Hurricane, High Wind, Winter Storm, Wildfire, Lightning, Flash Flood, ...) per month, then form a trailing-12-month sum. `Z = (current - mean) / stdev` against months `[t-72, t-12]`. Persistence: prior month must also exceed the same threshold band.
- **Cadence**: NOAA NCEI re-publishes monthly with roughly 1-2 months of data-entry lag.
- **Refresh**: monthly. Cached gzip files keyed on the NOAA `c-date` so a republished year refetches automatically. To wire to CI, fold into [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) (same cadence as temperature).
- **Caveats**: this is a **weather-event proxy, not measured customer-out counts**. The original spec called for DOE OE-417 customer-out data, but `oe.netl.doe.gov` no longer resolves and the OE-417 dataset has no equivalent free public endpoint. Oak Ridge EAGLE-I requires registration. A state can score high if storm activity was unusual even if grids held up. The map legend names this substitution.

### 13. Data-center site list (manual / curated)

- **File**: [data/sites/data_centers.csv](../data/sites/data_centers.csv)
- **Cadence**: ad-hoc. Update when you learn about a new hyperscaler announcement.
- **Refresh**: manual edits. After editing, run `python scripts/build_tiles.py` to regenerate `app/sites.geojson`.

### 14. Data-center hot zones (derived)

- **Script**: [scripts/build_hot_zones.py](../scripts/build_hot_zones.py)
- **Cadence**: re-run whenever #13 changes.
- **Output**: [app/hot_zones.geojson](../app/hot_zones.geojson)

### 15-18. Geo polygons (static)

- [data/geo/us_counties.geojson](../data/geo/us_counties.geojson), [data/geo/us_states.geojson](../data/geo/us_states.geojson), [ba_territories.geojson](../data/geo/ba_territories.geojson), [utility_territories.geojson](../data/geo/utility_territories.geojson).
- US Census TIGER (counties), `PublicaMundi/MappingAPI` (states), HIFLD (BA / utility). Re-download from source on the rare occasion boundaries shift (mostly utility territories on multi-year cadence).

### 19. US cities geocoding (`kelvins/US-Cities-Database`)

- **Upstream**: [GitHub raw CSV](https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv)
- **File**: [data/cache/us_cities.csv](../data/cache/us_cities.csv)
- **Cadence**: basically static. ~30k US cities with lat/lon and county.
- **Refresh**: as-needed (years).

### 20. Redfin Data Center - county median closing price vs 3-yr baseline

- **Upstream**: `https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/county_market_tracker.tsv000.gz`. Gzipped TSV, ~225 MB. One row per (county, property_type, month) going back to ~2012. We filter to `PROPERTY_TYPE == "All Residential"`.
- **Script**: [scripts/fetch_realestate_yoy.py](../scripts/fetch_realestate_yoy.py)
- **Algorithm**: For each county, collapse the monthly `MEDIAN_SALE_PRICE` series to a trailing-3-month volume-weighted mean (weight = `HOMES_SOLD`). The baseline is the simple mean of three such 3-month means anchored at t-12, t-24, and t-36 months back from the latest anchor. % change = (current 3mo mean − baseline) / baseline × 100. Counties with < **30 sales** in the current 3mo window OR in any of the 3 baseline 3mo windows are dropped to no-data — single-month medians in thin markets are dominated by which specific houses sold, not by price-level change.
- **Cadence**: Redfin refreshes the bulk file approximately weekly, but our baselined signal only moves materially month over month.
- **Refresh**: monthly via [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml). Fetcher writes the CSV; `scripts/build_tiles.py` rebuilds `app/tiles/realestate.pmtiles`.
- **FIPS resolution**: Redfin uses its own region IDs and labels counties as `"Foo County, ST"` / `"Foo Parish, LA"` / `"Foo Census Area, AK"`. The fetcher expands the Census GeoJSON LSAD abbreviations (`CA` -> `Census Area`, `Muno` -> `Municipality`, `Cty&Bor` -> `City and Borough`, etc.) and normalizes `&` -> `and` plus diacritics to bridge "King & Queen County" / "King and Queen County" and "Dona Ana" / "Doña Ana".
- **Caveats**: median sale price (not list price) so it reflects actual closings. The 3-month rolling absorbs most low-volume noise, but a handful of mid-population counties with a luxury-tail can still swing >+/- 30% over a 3-year span; treat extremes as suggestive, not definitive. **Not seasonally adjusted** — each baseline window matches the current window's calendar months, which neutralizes seasonality for the headline number but the underlying levels are not. The 3-year baseline tightens around long-run county price level rather than a single year, so the headline % shrinks vs the old 1-year YoY for steadily-rising markets and grows for newly-accelerating ones. Coverage drops modestly vs the 1-year version because a county must clear the 30-sales floor in **four** 3mo windows (current + 3 baseline) instead of two.

### 21. EIA power plants (≥ 100 MW)

- **Upstream**: EIA-hosted ArcGIS Online feature service `Power_Plants_in_the_US/FeatureServer/0` (org `FiaPA4ga0iQKduv3`). This is the public-map mirror of EIA Form 860 generator data.
- **Script**: [scripts/fetch_power_infra.py](../scripts/fetch_power_infra.py)
- **Filter**: `Total_MW >= 100` (~2,500 of ~12,000 total plants). Below 100 MW the map gets unreadable and the load impact relative to a hyperscaler campus is rounding error.
- **Fields kept**: plant code, name, operator, sector, city/county/state, primary fuel, tech description, installed MW, total MW.
- **Cadence**: EIA-860 final annual data drops in early September each year for the prior year.
- **Refresh**: annual on October 1 via [refresh-power.yml](../.github/workflows/refresh-power.yml).
- **Caveats**: marker color is `PrimSource`; some plants are mixed-fuel and the secondary fuel columns (`Bat_MW`, `Bio_MW`, `Coal_MW`, etc.) are dropped to keep the tooltip terse. Plants with only "planned" status are filtered out by the upstream service.

### 22. OpenStreetMap power substations (≥ 69 kV)

- **Upstream**: OpenStreetMap via the public Overpass API (`overpass-api.de/api/interpreter`). Query targets `power=substation` features with a numeric `voltage` tag, chunked into 4 CONUS quadrants to stay within Overpass server limits.
- **Script**: [scripts/fetch_power_infra.py](../scripts/fetch_power_infra.py)
- **Filter**: `max(voltage) >= 69 kV` (~47k substations US-wide). The OSM `voltage` tag is stored in volts and can be semicolon-separated (`"345000;138000"`); the fetcher splits, normalizes to kV, and takes the max.
- **Fields kept**: name, operator, city, state, OSM substation type (transmission/distribution/etc.), status, min/max voltage, OSM ID.
- **Cadence**: OSM is continuously edited by volunteers and utilities; substations are mapped fairly comprehensively in the US (especially the HV/EHV ones — local mappers tend to add them).
- **Refresh**: annual via [refresh-power.yml](../.github/workflows/refresh-power.yml). Re-running pulls the current state of OSM.
- **Output**: ~14 MB raw geojson → `data/cache/substations.geojson` → `build_tiles.py` packs into `app/tiles/substations.pmtiles` (a few MB compressed).
- **Why not HIFLD**: HIFLD was the canonical source until 2022 when DHS restricted public access. The Rutgers academic mirror that still exists only covers the Northeast US (~5k substations in 13 states). OSM is the most reliable free option with US-wide coverage, at the cost of accepting volunteer-mapped data quality.
- **Caveats**: voltage tags may be missing or malformed for newer/poorly-mapped substations — those get filtered out. Substation names from OSM are often a `ref` (numeric ID) rather than a friendly name. Coverage of <138 kV substations is somewhat sparse in rural areas vs the (now-gone) HIFLD authoritative count. Be polite to Overpass: the fetcher sleeps 2s between quadrant queries and runs only once a year.

### 23. Electric power transmission lines

- **Upstream**: EIA-hosted ArcGIS Online feature service `US_Electric_Power_Transmission_Lines/FeatureServer/0` (same org as #21). Sourced originally from HIFLD; EIA republishes.
- **Script**: [scripts/fetch_power_infra.py](../scripts/fetch_power_infra.py)
- **Filter**: none — the full ~94,600 line segments. Tippecanoe drops the densest features per tile when needed (`--drop-densest-as-needed`) so we don't pre-filter by voltage. Voltage class shows in the tile via the `voltage_kv` attribute, and the MapLibre style scales line width by voltage so EHV (≥345 kV) corridors visually dominate.
- **Fields kept**: type, status, owner, numeric voltage (kV), voltage class, the two end substations (SUB_1, SUB_2).
- **Cadence**: HIFLD-irregular (see #22).
- **Refresh**: annual via [refresh-power.yml](../.github/workflows/refresh-power.yml). After `fetch_power_infra.py` writes the cache, `scripts/build_tiles.py` packs it into `app/tiles/transmission_lines.pmtiles` (raw geojson is ~130 MB; PMTiles is ~10-30 MB).
- **Caveats**: HIFLD uses `-999999` to mean "voltage unknown" — the fetcher coalesces that to null so the tooltip and color scale render cleanly. INFERRED == "Y" means the line's exact path was reconstructed from endpoints (true of many distribution-tier lines); status is a separate column.

---

## Refresh workflows

Five scheduled GitHub Actions live under `.github/workflows/`:

| Workflow | Cron | Covers | Behavior |
|----------|------|--------|----------|
| [refresh-reddit.yml](../.github/workflows/refresh-reddit.yml) | `0 6 * * *` (daily 06:00 UTC) | ICE raid reports + protest reports | Runs `fetch_ice_hotzones_reddit.py` and `fetch_protest_hotzones.py`, commits only if geojson changed, deploys |
| [refresh-cdc.yml](../.github/workflows/refresh-cdc.yml) | `0 6 5 * *` (5th @ 06:00 UTC) | OD uptick + homicide uptick + temperature YoY + Redfin closing price YoY | Runs `fetch_od_uptick.py`, `fetch_homicide_uptick.py`, `fetch_temperature_yoy.py`, `fetch_realestate_yoy.py`; commits if changed, deploys |
| [refresh-eia-demand.yml](../.github/workflows/refresh-eia-demand.yml) | `0 7 * * 1` (Mon @ 07:00 UTC) | EIA hourly demand → BA YoY → `ba.pmtiles` | Pulls 24 months of hourly demand, recomputes YoY, rebuilds tiles via Docker, deploys |
| [refresh-property-tax.yml](../.github/workflows/refresh-property-tax.yml) | `0 7 15 1 *` (Jan 15 @ 07:00 UTC) | ACS property tax → `property_tax.pmtiles` | Refetches Census API, rebuilds tiles via Docker, deploys |
| [refresh-power.yml](../.github/workflows/refresh-power.yml) | `0 7 1 10 *` (Oct 1 @ 07:00 UTC) | Power plants + substations + transmission lines (#21-23) | Paginates the three ArcGIS REST endpoints, writes geojson, rebuilds `transmission_lines.pmtiles`, deploys |

All workflows require the following **GitHub Secrets** (Settings →
Secrets and variables → Actions):

| Secret | Used by | What it is |
|--------|---------|------------|
| `CLOUDFLARE_API_TOKEN` | all five | Workers Scripts: Edit, scoped to the powertracker account |
| `CLOUDFLARE_ACCOUNT_ID` | all five | The `d8e8518b7870983e964bdd183fc718b6` account id |
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
| 12 | NOAA outage uptick | Fetcher exists. Fold it into `refresh-cdc.yml` (same monthly cadence as the temperature fetcher already in that workflow). |
| 13 | Data-center site list | Manual edits to a CSV — no automation possible. |
| 14 | Hot zones (derived) | Re-run after #13 changes; trivial to add a workflow that watches the CSV path, deferred until #13 churns. |
| 15-19 | Geo / cities | Effectively static. |

Drop a `scripts/fetch_*.py` for the missing fetchers and a
`refresh-*.yml` workflow follows the same skeleton as the existing
four.
