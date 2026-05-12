# powertracker

Tracking US electricity grid demand around AI data centers.

## What this does

US data centers — especially AI training campuses — are reshaping electricity demand. This project:

1. Catalogs known hyperscaler / AI data center locations
2. Maps each site to its electricity Balancing Authority (BA)
3. Pulls hourly demand from the EIA Hourly Electric Grid Monitor
4. Detects weather-normalized step-changes in load attributable to data center buildouts

## Why BA-level?

The smallest geography with public real-time load data is the **Balancing Authority** (~66 in the US). Sub-utility load is restricted as Critical Energy Infrastructure Information (CEII). So we work at BA resolution and look hardest at small BAs with concentrated buildouts (e.g. Grant County PUD, TVA, Dominion in PJM).

## Data sources

| Source | What | Cadence | License |
|---|---|---|---|
| [EIA Hourly Electric Grid Monitor](https://www.eia.gov/electricity/gridmonitor/) | Hourly demand per BA | Hourly | Public domain |
| [EIA Form 860M](https://www.eia.gov/electricity/data/eia860m/) | Planned generation, often references DC loads | Monthly | Public domain |
| [Baxtel](https://baxtel.com/) / [Data Center Map](https://www.datacentermap.com/) | Site directories | Static | Terms of use |
| [NOAA GHCN](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily) | Weather (HDD/CDD) for normalization | Daily | Public domain |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Get an [EIA API key](https://www.eia.gov/opendata/register.php) (free, instant) and put it in `.env`:

```
EIA_API_KEY=your_key_here
```

## Status

Early scaffolding.
