# Launch post (copy-paste ready)

Three platform variants below. All point at the new prerendered ranking
page at `https://powertracker.io/rankings` so every share carries the
core artifact.

The numbers below are pulled from the May 2026 rebuild (29.1 GW announced
across 80 counties; top 10 = 72%). Re-run `python scripts/build_rankings.py`
and update these numbers before posting if more than a couple weeks have
passed.

---

## Hacker News (Show HN)

**Title** (under 80 chars):
> Show HN: I mapped every public AI data-center site to its county and grid

**Body**:

I've been building powertracker.io to answer a basic question that nobody
seems able to: when a 2 GW AI campus gets announced in a town of 4,000,
what does that actually mean for the people living next to it?

The site is a MapLibre + PMTiles map of 106 known US AI / hyperscaler
data-center campuses, overlaid on the public-data context around each
one: balancing-authority demand (EIA), county GDP (BEA), utility
residential rates (EIA-861), median property tax (Census ACS), home
prices (Redfin), transmission lines and ≥100 MW power plants (EIA),
≥69 kV substations (OSM via Overpass), and county temperature anomalies
(NOAA). Every layer is sourced from a named public feed and refreshed on
a tracked cadence by GitHub Actions.

I just shipped a prerendered ranking that joins them:

  https://powertracker.io/rankings

Top three counties by announced megawatts:

1. **Racine County, WI** — 3.3 GW (Microsoft Fairwater + Mount Pleasant).
   We Energies residential rate is already +11.4% vs the 2021-23
   baseline. County home prices +24.9%.
2. **Laramie County, WY** — 2.6 GW (Crusoe + Meta + Microsoft, all in
   Cheyenne). Black Hills Energy rate +13.3%. Property tax +15.4%.
3. **St. Joseph County, IN** — 2.2 GW (AWS/Anthropic Project Rainier +
   Microsoft Granger). Indiana Michigan Power rate +5.1%, home prices
   +16.8%.

Aggregated: 29.1 GW announced across 80 counties; 72% of all announced
load is concentrated in just the top 10. Most of those 10 are counties
fewer than half the people on this site have heard of.

I'm not making a causal claim that data centers caused those rate or
home-price moves — the page is explicit that these are read-outs of what
the host community has been paying for power and housing in the years
the campus was being planned. The pipeline emits the joined view and
the candidate signals; the research design is up to whoever uses it.

All open source: code, fetchers, weekly refresh workflows, raw caches.
The campus list is a CSV with a source URL per row. PRs welcome — and
correction PRs especially welcome if you live near one of these sites
and we have a number wrong.

  https://github.com/vxguo1/powertracker

Happy to take feedback on data sources we're missing (water draw,
backup-generator runtime, and substation noise complaints are the three
big gaps I want to close next).

---

## Reddit — r/dataisbeautiful

**Title**:
> [OC] The 30 US counties absorbing the AI data-center buildout, ranked by announced gigawatts (29 GW across 80 counties, 72% in the top 10)

**Body**:

Built from a hand-curated list of 106 publicly known AI and hyperscaler
campuses (Stargate, Meta Hyperion, Project Rainier, every Fairwater,
xAI Colossus, the CoreWeave/Crusoe builds, etc.), joined to:

- announced megawatts from press releases / utility filings
- EIA Form 861 residential rate change (2024 vs 2021-23 mean)
- Redfin median sale price change (3-month, vs 3-year baseline)
- Census ACS median property tax change

Top three:

1. **Racine County, WI** — 3.3 GW · We Energies rate +11.4% · home prices +25%
2. **Laramie County, WY** — 2.6 GW (Cheyenne) · Black Hills rate +13.3% · property tax +15%
3. **St. Joseph County, IN** — 2.2 GW (New Carlisle) · home prices +17%

Full ranking + the joined dataset: https://powertracker.io/rankings

Map view (interactive, every site shows its operator, MW, utility, BA,
and surrounding context): https://powertracker.io/

Methodology + sources are linked on the ranking page. Open source at
github.com/vxguo1/powertracker — every campus row carries its source URL.

---

## Reddit — r/energy

**Title**:
> Open map: every announced AI / hyperscaler campus, ranked by county and joined to utility rate change

**Body**:

Posting in case anyone here finds it useful. powertracker.io maps 106
publicly known AI + hyperscaler data-center campuses against EIA hourly
BA demand, EIA-861 utility residential rates, transmission lines,
substations, and power plants ≥ 100 MW. Just added a county ranking
that joins announced MW per county to the utility rate change for the
host utility.

  https://powertracker.io/rankings

A few things that surprised me building it:

- 72% of the 29 GW of announced AI load is concentrated in the top 10
  counties. Plenty of small balancing authorities (Grant County PUD,
  Laramie's slice of WACM, the TVA pocket around Memphis) are looking
  at a doubling of peak demand.
- The utilities that have already raised residential rates the most
  over the last 3 years skew small: Black Hills (+13.3%), We Energies
  (+11.4%), Appalachian Power (+11.6% in WV). These are the same
  utilities signing the biggest new interconnect agreements.
- HIFLD restricted the transmission/substation data in 2022, so the
  substation layer is OSM + Overpass. Coverage of ≥138 kV substations
  in the US is surprisingly good — most local mappers add them.

Open data, open source, weekly auto-refresh. Code:
github.com/vxguo1/powertracker

---

## X / Twitter thread (7 tweets)

**1/**
The AI buildout is going to add 29 gigawatts of new electricity load to
80 US counties.

72% of that load is concentrated in the top 10.

I built powertracker.io to map every announced AI campus to its county,
its grid, and what residents there already pay for power.

[link to /rankings, with OG card]

**2/**
#1: **Racine County, Wisconsin**

3.3 GW of Microsoft Fairwater + Mount Pleasant, all under construction.
We Energies residential electricity rate is already +11.4% vs the 3-year
baseline. County home prices +25%.

Population: 196,000.

**3/**
#2: **Laramie County, Wyoming** (Cheyenne)

2.6 GW across three campuses — Crusoe, Meta, Microsoft. Black Hills
Energy residential rate is +13.3% on a 3-year baseline. Property tax
+15.4%.

Cheyenne metro: 100,000 people.

**4/**
#3: **St. Joseph County, Indiana** (New Carlisle)

Project Rainier (AWS/Anthropic) + Microsoft Granger = 2.2 GW. Indiana
Michigan Power rate +5.1%. Home prices +17%.

The county had ~272,000 residents at last census. They are absorbing
roughly the peak demand of Newark.

**5/**
Three more under-the-radar ones:

- **Mason County, WV** (Point Pleasant) — 2 GW Nscale/Microsoft AI
  factory on Appalachian Power. Rate +11.6%.
- **Nolan County, TX** (Sweetwater) — 2 GW IREN, population 14,000.
- **Milam County, TX** — 1.2 GW Stargate site.

**6/**
None of this is hidden — every site has a public press release. What
hasn't existed is the joined view: who's building what, where, on which
utility's grid, in a county already paying how much more for electricity
and housing.

That's the whole point of the project.

[link to map]

**7/**
Open data, open source, weekly auto-refresh.

Every site in the campus list carries a citation URL. The pipeline
(EIA, BEA, Census, NOAA, CDC, OSM, Redfin) is a Python repo on GitHub.
PRs and corrections welcome.

Especially if you live near one of these sites and we have something
wrong. ⤵

github.com/vxguo1/powertracker
