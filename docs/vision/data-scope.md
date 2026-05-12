# Data Scope and Source Inventory

This document catalogs the public data sources powertracker depends on, the geography and cadence each operates at, and the specific research question each dimension is meant to answer. Every source listed here is either already in the pipeline, planned for the next phase, or flagged as a gap that requires advocacy or FOIA work.

## Source matrix

| Dimension | Primary source | Cadence | Native geography | License | Status |
|---|---|---|---|---|---|
| Hourly grid demand and generation | EIA Hourly Electric Grid Monitor (v2 API) | Hourly | Balancing Authority (~66 US) | Public domain | In pipeline |
| Planned generation additions | EIA Form 860M | Monthly | Plant | Public domain | Planned |
| Retail sales and revenue | EIA Form 861 | Annual | Utility | Public domain | Planned |
| Large-load tariff filings | State PUC dockets, FERC eLibrary | Event-driven | Utility | Public, retrieval varies | Manual ingest |
| Data center site registry | Baxtel, Data Center Map, press releases, SEC filings, manual curation | Continuous | Site (lat, lon) | Mixed, see per-row source | Seed list shipped |
| Weather (heating and cooling degree days) | NOAA GHCN Daily | Daily | Station | Public domain | Planned |
| Property values | FHFA HPI, county assessor open data, ATTOM (commercial fallback) | Quarterly to annual | County to parcel | Mixed | Planned |
| Life expectancy | CDC NCHS, USALEEP | Annual, multi-year rolling | Census tract | Public domain | Planned |
| Social vulnerability | CDC/ATSDR Social Vulnerability Index | Biennial | Census tract | Public domain | Planned |
| Demographics and income | ACS 5-year estimates | Annual rolling | Tract, block group | Public domain | Planned |
| Air quality | EPA AQS, PurpleAir (community-grade) | Hourly | Station | Public domain (EPA), CC-BY (PurpleAir) | Planned |
| Water draw | USGS NWIS, voluntary corporate ESG disclosures | Variable | Watershed, site | Public domain (USGS) | Gap, partial |
| Backup generator inventory and runtime | State air permit filings, county records | Annual or event | Site | Public, retrieval varies | Gap, manual |
| Noise complaints | County 311 systems, FOIA requests | Continuous to FOIA | Address | Public, jurisdiction-dependent | Gap |
| Construction permits | Local jurisdiction open data portals | Continuous | Parcel | Mixed | Planned |
| Property tax abatements and PILOTs | State and local economic development agencies | Event-driven | Project | Public, retrieval varies | Manual ingest |

## Core research questions

Each question maps to a subset of the dimensions above. The point of the project is to make these questions answerable from a single joined dataset rather than from a half-dozen agency portals.

### 1. The load attribution question

How much of the post-2022 demand growth in a given balancing authority is attributable to data center colocations rather than broader electrification, weather, or economic activity?

Inputs: hourly grid demand, planned generation additions, NOAA degree days, site registry with online_year and announced_mw.

Method sketch: weather-normalize hourly demand, segment by pre and post commissioning windows for each known site, attribute residual step-change with uncertainty bounds.

### 2. The cost-shift question

When a hyperscaler signs a special large-load tariff or behind-the-meter arrangement, what portion of the utility's fixed costs gets recovered from residential and small commercial ratepayers?

Inputs: PUC tariff filings, EIA Form 861, utility rate case orders.

Method sketch: extract negotiated rate structures from dockets, compare to standard tariff schedules, model residual cost recovery by customer class.

### 3. The local economy question

What happens to property values, tax base, and median household income within concentric radii (1mi, 5mi, 10mi) of a new campus, before and after commissioning?

Inputs: site registry, FHFA HPI, county assessor parcel data, ACS 5-year, property tax abatement records.

Method sketch: difference-in-differences with matched control counties (same state, similar baseline economy, no large data center).

### 4. The health and longevity question

Is there a measurable change in respiratory hospitalization rates, low-birth-weight prevalence, or life expectancy in census tracts that host or border large diesel-backed campuses?

Inputs: site registry, EPA AQS, CDC NCHS small-area life expectancy, state hospital discharge data where available.

Method sketch: tract-level pre/post comparison with matched controls. This is the dimension where causal claims are hardest. The project will publish the joined data and the candidate signals. Causal inference is a downstream research question, not a project deliverable.

### 5. The equity question

Are AI and hyperscaler sites disproportionately located in census tracts already scoring high on the CDC Social Vulnerability Index, controlling for the practical siting requirements (transmission access, fiber, land cost)?

Inputs: site registry, CDC SVI, transmission line shapefiles, fiber backbone maps.

Method sketch: compare SVI distribution at site tracts to SVI distribution at counterfactual tracts that satisfy the practical siting criteria.

## What is explicitly out of scope (for now)

The project will not chase these in the first 18 months. Listing them here so contributors do not duplicate effort or expect coverage that is not coming.

- International data centers. The legal regime and data availability differ enough to warrant a separate project.
- Retail customer-level load. This data is restricted by every utility we have looked at, and aggregating it would be a multi-year regulatory campaign.
- GPU-level workload attribution. Whether a campus is training a frontier model or serving inference is not observable from the load shape and is not what we are trying to measure.
- Carbon intensity attribution at the corporate level. Several existing projects (Electricity Maps, WattTime, corporate sustainability disclosures) do this well. We will link to them, not duplicate them.

## Update cadence and reproducibility commitments

- The site registry is updated continuously as announcements land. Each row carries a source URL and a date-added field.
- Hourly load is refetched on a configurable schedule (default: weekly catch-up).
- Joined community-overlay snapshots are released quarterly, tagged with the source vintages used.
- Every transform in the pipeline is implemented in version-controlled Python. Every published number can be regenerated from raw inputs by running a single script.

## Known data quality risks

- EIA respondent reporting is occasionally revised retroactively. The pipeline stores raw fetches and tracks revisions.
- The site registry depends on press releases, which routinely overstate announced megawatts and understate timelines. Each row should be read as "as disclosed," not "as built."
- Census tract boundaries change between decennial censuses. Joins across the 2010 and 2020 boundary revisions require a crosswalk that is not yet implemented.
- Property and health data have meaningful lag (12 to 36 months for some sources). Real-time community impact stories will run ahead of the dataset's ability to confirm them.
