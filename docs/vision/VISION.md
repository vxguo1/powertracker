# Powertracker: Vision Brief

**One sentence.** Build the first open, community-resolution dataset that tracks how the AI data center buildout is reshaping electricity demand, local economies, and resident outcomes across the United States.

## The situation

Between 2022 and 2026, US hyperscalers and AI labs announced more than 50 GW of new data center capacity. The 19 sites in our seed list alone account for over 4 GW of publicly disclosed nameplate load, and most sites in that list have not published a number at all. EIA, NERC, and several utilities now project that data center load will be the single largest source of grid demand growth this decade.

## The complication

The public record stops where the impact begins.

1. **Grid data stops at the Balancing Authority.** PJM spans 13 states. Nobody outside the utility can see how much of a county's load is one campus.
2. **Site-level power, water, and emissions data are voluntary.** Most of it is never published.
3. **Local impact data exists, but in silos.** Property records, mortality tables, ACS demographics, air quality, and noise complaints all sit in separate systems. None of them are joined to the infrastructure that triggered the change.

The result: residents, regulators, and journalists cannot answer a basic question. What does this campus cost the people who live next to it?

## The answer

Powertracker assembles the answer from public sources, at the smallest geography each source permits, on a refresh cadence the data supports.

**Three pillars.**

1. **Load.** Hourly demand per Balancing Authority from the EIA Hourly Electric Grid Monitor, weather-normalized with NOAA GHCN, with step-change detection tuned for data center commissioning windows.
2. **Site ledger.** A continuously curated registry of US AI and hyperscaler sites with location, operator, announced megawatts, utility, balancing authority, and status. Open CSV, citation per row.
3. **Community overlay.** County and census-tract joins for property value (FHFA HPI, county assessor data), life expectancy (CDC NCHS, USALEEP), and social vulnerability (CDC SVI, ACS 5-year). Each dimension carries a clearly stated research question, not a predetermined narrative.

## What we ship

- A reproducible Python pipeline (already scaffolded) for ingesting EIA, NOAA, and site data.
- A versioned, public site registry that any researcher can fork or contribute to.
- Quarterly snapshots of the joined dataset, released under a permissive license.
- A short, opinionated methodology document for each derived metric, so every number in the dataset can be traced to the source and the transform.

## Who this is for

- **Journalists and researchers** investigating the local impact of specific buildouts.
- **Regulators and PUC staff** who need a comparable cross-utility baseline.
- **Residents and local advocates** who deserve a clear picture of what is being built near them.
- **Developers and operators** who want a credible public benchmark for their own siting and disclosure decisions.

## What success looks like in 18 months

A reporter in Memphis, a city councilor in Rayville, a doctoral student at UT Austin, and an oversight analyst at FERC can all answer the same question from the same dataset: how is this campus changing my community, and how does that compare to the others.

If they can, we have done the job.
