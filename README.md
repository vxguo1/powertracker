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
pip install -e .
```

Get an [EIA API key](https://www.eia.gov/opendata/register.php) (free, instant) and put it in `.env`:

```
EIA_API_KEY=your_key_here
```

## Run the map

Three options, smallest to largest:

**1. Static HTML (one file, no server):**
```powershell
python scripts\build_map.py --cache
# writes data\maps\data_centers.html; open it directly
```

**2. MapLibre + PMTiles app (zoom-aware vector tiles, what gets deployed):**
```powershell
# regenerate tiles after data refresh (needs Docker)
python scripts\build_tiles.py
# serve locally
cd app && python -m http.server 8000
# open http://localhost:8000
```

**3. Streamlit app (interactive filters + leaderboards):**
```powershell
streamlit run app.py
# open http://localhost:8501
```

## Deploy

The MapLibre app under `app/` is fully static (HTML + PMTiles + GeoJSON).

**Cloudflare Pages (recommended)**
1. Push the repo to GitHub.
2. https://dash.cloudflare.com -> Pages -> "Connect to Git" -> pick this repo.
3. Set **build output directory** to `app`. Leave the build command blank.
4. Deploy. You get a `*.pages.dev` URL on Cloudflare's CDN.

**GitHub Pages**
1. Rename `app/` to `docs/` (or set up a GitHub Actions workflow that
   publishes `app/` to the `gh-pages` branch).
2. Repo Settings -> Pages -> source = `main`, folder = `/docs`.
3. URL is `<user>.github.io/<repo>/`.

**Streamlit Cloud** (for the Streamlit variant)
1. Push to GitHub.
2. https://share.streamlit.io -> point at the repo with `app.py` as entrypoint.
3. Reads pre-computed `data/cache/*.csv` + `data/geo/*.geojson`. No API key needed.

To refresh data after a new EIA release:

```powershell
# (Re-)fetch raw data — needs EIA_API_KEY in .env
python scripts\fetch_demand.py --from-sites --start 2023-01-01 --end <today>
# EIA-861 + BEA zips download themselves on first call to prices.py / gdp.py
python scripts\build_aggregates.py
# Commit the updated data\cache\*.csv and push.
```

## SEO / discoverability

The deployed `app/` directory ships with a holistic SEO baseline:

| File | Purpose |
|---|---|
| `app/index.html` `<head>` | Title, description, canonical, robots, theme-color, Open Graph + Twitter cards, JSON-LD (`WebSite` + `Organization` + `WebApplication` + `Dataset`), preconnect hints |
| `app/index.html` `<body>` | `.sr-only` semantic `<section>` describing every layer category + a `<noscript>` fallback panel; gives crawlers and JS-disabled clients real text to index |
| `app/sources.html` `<head>` | Per-page title, description, canonical, OG/Twitter, JSON-LD (`WebPage` + `BreadcrumbList`) |
| `app/og-image.png` | 1200x630 social-share card; regenerate with `python scripts/build_og_image.py` |
| `app/robots.txt` | Allows all crawlers (including AI training crawlers - the project is open data), points at the sitemap |
| `app/sitemap.xml` | Lists `/` and `/sources` |
| `worker.js` | Sends `X-Robots-Tag: noindex, nofollow` on `.pmtiles` responses so binary tiles don't pollute `site:powertracker.io` results |

Validate the structured data after any edit:

```
python -c "import json,re,pathlib; [print(p, json.loads(re.search(r'application/ld\\+json\">\\s*(.*?)\\s*</script>', pathlib.Path(p).read_text(encoding='utf-8'), re.DOTALL).group(1)) and 'ok') for p in ['app/index.html','app/sources.html']]"
```

Or paste the page source into Google's Rich Results Test (`search.google.com/test/rich-results`).

## LLM reach (GEO / answer-engine optimization)

Distinct from search-engine SEO: getting the site cited by ChatGPT,
Claude, Perplexity, Gemini, Google AI Overviews and Bing Copilot.

| File | Purpose |
|---|---|
| `app/robots.txt` | Explicit `Allow: /` blocks for ~25 named AI crawlers (CCBot, GPTBot, ClaudeBot, Google-Extended, PerplexityBot, Applebot-Extended, Meta-ExternalAgent, Amazonbot, Bytespider, etc.). Common Crawl - the basis of most open LLM training corpora - is listed first. |
| `app/llms.txt` | [Answer.AI llms.txt](https://llmstxt.org/) proposed standard. Short markdown index of the site - primary pages, citable facts, upstream sources. |
| `app/llms-full.txt` | Long-form citable corpus. Self-contained markdown an LLM can ingest to answer questions about the site without crawling further. |
| `index.html` `FAQPage` JSON-LD | Nine Q&A pairs covering "what is powertracker.io", how many sites, top states, BA methodology, data sources, refresh cadence, license, and maintainer. LLMs preferentially cite pages with explicit Q&A. |
| `index.html` `.sr-only` "Key facts" block | Off-screen but indexed stat block with concrete, citable numbers (site count, top states, top operators, total announced MW). Retrieval-friendly self-contained chunk. |
| `<link rel="alternate" type="text/markdown">` in `<head>` | HTML-side discovery hint pointing at `/llms.txt` and `/llms-full.txt`. |

After any change to the site list or layer set, regenerate the key
facts in `app/llms.txt`, `app/llms-full.txt`, the `FAQPage` JSON-LD,
and the `.sr-only` "Key facts" block. They should all agree.

The aggregate stats can be re-derived with:

```
python -c "import json,pathlib; s=json.loads(pathlib.Path('app/sites.geojson').read_text(encoding='utf-8'))['features']; print(len(s), 'sites,', len({f['properties'].get('state') for f in s}), 'states')"
```

## Status

Early scaffolding.
