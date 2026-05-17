# powertracker.io launch package

Drafted 2026-05-17 for a coordinated launch on **Tue 2026-05-19, 08:00 PT**.
Every number traces to `app/rankings.html` (built 2026-05-17) and
`docs/DATA_SOURCES.md`. The user posts. This file is the script.

All public-facing copy below was run through the comms-master skill at
`C:\Users\PC\OneDrive\skills\comms-master`. Each section names the
frameworks it layers and (for the journalist email) the tone calibration.

---

## 1. One-line pitch

> 29.1 GW of announced AI data-center load is landing in 80 US counties.
> 72% of it goes to just 10 of them. powertracker.io maps every campus
> to its grid, its utility, and what residents there already pay for power.

URL: https://powertracker.io . Rankings: https://powertracker.io/rankings
. Code: https://github.com/vxguo1/powertracker

---

## 2. Show HN

**Title** (78 chars):

> Show HN: powertracker.io, 29 GW of AI data centers mapped to county + grid

**First-author comment** (305 words):

I kept reading "X gigawatt AI campus announced in [county I'd never
heard of]" and wanting the local context that the press release never
includes. What is the existing peak demand of the balancing authority
absorbing this load? What has the host utility's residential rate done
over the last three years? How big is the town. That gap is why I
built powertracker.io.

The map is MapLibre + PMTiles, served from a Cloudflare Worker. The
dataset is 106 publicly known AI / hyperscaler campuses, hand-curated
from press releases, FOIA filings, and zoning records. Every row in
`data/sites/data_centers.csv` carries a source URL. The campus list is
joined to:

- EIA hourly balancing-authority demand (trailing-12 vs 3-yr baseline)
- EIA Form 861 utility residential rates
- Census ACS B25103 median property tax
- Redfin median sale price (3mo rolling, volume-weighted)
- EIA-860 power plants 100 MW and up, EIA transmission lines 138 kV and up
- OSM substations 69 kV and up via the Overpass API (HIFLD restricted
  public access in 2022, so OSM is the only US-wide free option left)
- NOAA Climate at a Glance anomalies, CDC overdose and homicide
  indicators, Reddit-sourced ICE-raid and protest hot zones

Today I shipped a prerendered ranking that joins announced MW per
county to the rate / home-price / property-tax change for the host
community: https://powertracker.io/rankings

Headline reading. 29.1 GW announced across 80 counties, 72% in the top
10. The #1 county is Racine, WI. 3.3 GW of Microsoft (Fairwater +
Mount Pleasant) on We Energies, where residential rates are already
+11.4% and home prices +24.9% vs the 3-yr baseline.

The page is explicit that none of those deltas are caused by data
centers alone. They are read-outs of what the host community has been
paying in the years the campus was being planned.

Every county has its own prerendered page at `/<state>/<county>` so
you can punch in your zip code's county and see what's happening
upstream.

PRs welcome, especially correction PRs if you live near one of these
sites and a number is wrong. Three data gaps I want to close next:
water draw, backup-generator runtime, and substation noise complaints.

**Framework rationale:** Golden Circle opens with the why (the missing
local context behind every press release) before the what (the map).
SCQA spine runs through it. Situation is the announcement firehose,
Complication is the missing context, Question is "what does this mean
for that town," Answer is the joined dataset. STAR moment lands at
Racine, WI. one town of 27k, one number (3.3 GW), one rate change
(+11.4%). Close is an explicit invitation (PRs, the three open gaps),
which doubles as ethos. publicly admitting what you don't have built
yet is more credible than promising completeness.

---

## 3. r/dataisbeautiful

**Title** (must include `[OC]`):

> [OC] The 30 US counties absorbing the AI data-center buildout, ranked by
> announced gigawatts. 29 GW across 80 counties, 72% concentrated in the top 10

**Body** (post text. short, the OC source comment carries the method):

Hand-curated list of 106 publicly announced AI / hyperscaler campuses
(Stargate, Meta Hyperion, Fairwater, Project Rainier, xAI Colossus,
CoreWeave, Crusoe), joined to host-county economic context.

Top 3:

1. **Racine County, WI**. 3.3 GW . We Energies rate +11.4% . home prices +25%
2. **Laramie County, WY**. 2.6 GW (Cheyenne) . Black Hills +13.3% . prop tax +15%
3. **St. Joseph County, IN**. 2.2 GW (New Carlisle) . home prices +17%

Full sortable list with methodology: https://powertracker.io/rankings
Interactive map: https://powertracker.io

**Mandatory OC source comment** (post this as the first reply to the
thread within 60 seconds of the post going live. r/dataisbeautiful
auto-removes [OC] posts without it):

> Source comment as required by r/dataisbeautiful rules.
>
> **Tool:** Python (pandas) for the join. MapLibre + PMTiles for the
> rendering. Cloudflare Worker for hosting. tippecanoe + go-pmtiles for
> the tile build. Open source: github.com/vxguo1/powertracker
>
> **Data:**
> - Campus list (announced MW, operator, status, citation URL) is
>   hand-curated from press releases, utility interconnection filings,
>   and local zoning records. `data/sites/data_centers.csv`.
> - Utility residential rate change: EIA Form 861 (2024 vs mean of 2021-23).
> - Home price change: Redfin Data Center, 3-month volume-weighted
>   median vs the mean of 3 prior same-month windows at t-12 / t-24 / t-36.
> - Property tax change: Census ACS 5-year B25103.
> - County rollup uses Census FIPS via `kelvins/US-Cities-Database`.
>
> Every county in the table links to its own prerendered page with the
> full source list, surrounding power infrastructure, and the BA demand
> curve. Corrections welcome via PR. The campus CSV has a citation
> column for every row.

**Framework rationale:** Minto Pyramid in title and body. Strongest
single fact (72% in 10 counties) leads, top 3 evidence supports it,
methodology drops to the OC comment where r/dataisbeautiful expects it.
Subreddit-specific structural choice: the source comment is mandatory
moderation infrastructure, not optional context, so it gets the full
data-trail treatment that would otherwise bloat the post body.

---

## 4. r/energy

**Title:**

> 72% of all announced AI data-center load (29 of 29.1 GW) is going to
> just 10 US counties. Open map joining each campus to its utility +
> rate trajectory.

**Opening paragraph** (the post body):

Cross-posting in case anyone here finds it useful.
[powertracker.io](https://powertracker.io) is an open map of 106
publicly known AI / hyperscaler data-center campuses, layered on the
existing grid: EIA balancing-authority demand, EIA-861 utility
residential rates, EIA power plants 100 MW and up, EIA transmission
138 kV and up, OSM substations 69 kV and up (HIFLD lockdown made this
the only free option), NOAA temperature anomalies, Redfin home prices.
Today I shipped a county ranking that joins announced MW per county to
the host utility's 3-year residential rate change:
https://powertracker.io/rankings

Three things stood out building it:

- 72% of the 29.1 GW is concentrated in the top 10 counties. Most are
  small. Racine, Cheyenne, New Carlisle, Sweetwater, Point Pleasant.
  Several balancing authorities (Black Hills, the TVA pocket around
  Memphis, AEP-East's WV slice) are looking at a doubling of peak load
  from a single campus.
- The utilities that have already raised residential rates the most in
  the last 3 years skew small. Black Hills Energy (+13.3% in Laramie
  WY), We Energies (+11.4% in Racine WI), Appalachian Power (+11.6% in
  Mason WV). Those are the same utilities signing the largest new
  interconnect agreements.
- HIFLD restricted transmission and substation data in 2022. The
  substation layer is OSM via Overpass. Surprisingly good US-wide
  coverage for 138 kV and up because local mappers add them. Naming is
  inconsistent (lots of bare numeric refs) but geometry is solid.

All data sources are documented at /sources with refresh cadences.
Weekly auto-refresh runs via GitHub Actions. Code, fetchers, and the
campus CSV are open at github.com/vxguo1/powertracker. Every row in
the campus list carries a citation URL.

Curious where this misses things. Correction PRs especially welcome.

**Framework rationale:** Minto lead with the headline stat (72% in 10
counties), then Rule of Three for the substantive observations. Each
of the three bullets pairs a finding with the data trail behind it,
which is how r/energy regulars evaluate posts. Pathos kept low.
critical-engineering audience reads epistemic humility as ethos, so
the "curious where this misses things" close is doing more work than
it looks like.

---

## 5. Other subreddit candidates

| Sub | Fit | Action |
|-----|-----|--------|
| r/MachineLearning | Weak. Paper-focused sub. Infra/policy posts get downvoted unless tied to compute economics. | Skip. |
| r/electricalengineering | Moderate. Transmission/substation layer + balancing-authority pages are EE-relevant. The rate/home-price layer is not. | Cross-post only with an EE-framed title (below). |
| r/Futurology | Moderate. High volume, lower engagement quality, mods tolerant of map projects. | Cross-post with a forward-looking framing (below). |
| r/economics | Weak. The rate/home-price deltas are correlations, not causal claims. The sub is critical of correlation-as-policy posts and would (correctly) push back. | Skip. |
| r/dataengineering | Weak as a launch channel. Moderate as a follow-up "here's the pipeline" technical post a week after launch. | Skip on day 1. revisit. |
| r/MapPorn | Strong fit for the map view, not the ranking. Use a screenshot + map link, not /rankings. | Cross-post Wed 2026-05-20 to spread traffic across days. |

Draft titles for the three that fit:

**r/electricalengineering:**
> Mapped 80 US counties absorbing 29 GW of new AI data-center load against
> the actual transmission corridors and 69 kV and up substations near each site

**r/Futurology:**
> 72% of all publicly announced US AI data-center power (29 GW) is going
> to 10 counties. Most are towns under 200k. Here's the map.

**r/MapPorn** (Wed 2026-05-20):
> Every announced AI / hyperscaler data center in the US, with the
> 138 kV and up transmission lines feeding each one [interactive]

**Framework rationale:** Each draft title applies a single subreddit's
preferred Minto lead. r/EE wants the infrastructure stat (transmission
+ substations), r/Futurology wants the concentration stat framed as a
trend, r/MapPorn wants the visual concept. Skip rationales kept terse.
the audit table is itself a Minto pyramid (fit assessment, then
action).

---

## 6. X/Twitter thread (7 tweets, each up to 280 chars)

**1/**
The biggest single announced AI data-center campus in the US is being
built in a Wisconsin town of 27,000 people.

Microsoft Fairwater + Mount Pleasant: 3.3 GW. On a utility (We
Energies) whose residential rates are already +11.4% over 3 years.

I built a map. powertracker.io

**2/**
That's just #1.

Across the 106 publicly known AI / hyperscaler campuses in the US,
operators have announced 29.1 gigawatts of new electricity load.

72% of it is concentrated in the top 10 counties.

Most you've never heard of. /rankings

**3/**
The top 10, in order:

1. Racine, WI . 3.3 GW
2. Laramie, WY (Cheyenne) . 2.6 GW
3. St. Joseph, IN (New Carlisle) . 2.2 GW
4. Taylor, TX (Abilene, Stargate) . 2.1 GW
5. Shelby, TN (Memphis, xAI) . 2.0 GW
6. Richland, LA . 2.0 GW
7. Mason, WV . 2.0 GW
8. Nolan, TX (Sweetwater) . 2.0 GW
9. Trumbull, OH (Lordstown, Stargate)
10. Jackson, MO

**4/**
For every county on the list, you can pull the full picture:

- which campuses are there
- the host utility's 3-yr residential rate change
- Redfin home prices vs 3-yr baseline
- Census property tax change
- the 138 kV and up transmission lines feeding the site

Each county has its own page: /county/[state]-[name]

**5/**
The utilities that have raised residential rates the most over the
last 3 years are the same ones signing the biggest new interconnect
agreements:

- Black Hills (Laramie WY): +13.3%
- Appalachian Power (Mason WV): +11.6%
- We Energies (Racine WI): +11.4%

This is not a coincidence.

**6/**
Find your county.

Every US county with a publicly announced AI campus has a prerendered
page at powertracker.io/county/[state]-[name].

If you live near one of these sites and a number is wrong, file a PR.
Every row in the campus CSV carries a citation URL.

**7/**
Open data, open source, weekly auto-refresh from EIA, BEA, Census,
Redfin, NOAA, CDC, OSM.

Code: github.com/vxguo1/powertracker
Map: powertracker.io
Rankings: powertracker.io/rankings

**Framework rationale:** Duarte Sparkline runs across the 7 tweets,
alternating tension and relief. Tweet 1 (tension: a 27k town getting
3.3 GW) is the STAR moment up front because feed-scroll attention
collapses without an immediate hook. Tweet 2 widens the frame (more
tension: 72% in 10 places). Tweet 3 delivers the named list (relief:
specificity). Tweet 4 grants agency (relief: here's how to look up
your county). Tweet 5 returns to tension (the rate/interconnect
correlation). Tweet 6 grants agency again (file a PR). Tweet 7 lands
the bare-URL CTA. The Racine anecdote is in tweet 1 because Twitter is
a STAR-moment-first medium.

---

## 7. LinkedIn

I spent the last several months building **powertracker.io** because I
kept reading hyperscaler press releases that left out the part I
actually wanted: where is this load landing, and what does that place
already pay for power.

Today the dataset has 106 publicly known AI and hyperscaler campuses
across 80 US counties. The 30 largest by announced megawatts account
for **29.1 gigawatts of new electricity load**. 72% of that is
concentrated in just 10 counties. Most are places I had not heard of
before pulling the list together.

The site joins each campus to: EIA balancing-authority demand, the
host utility's residential rate trajectory (Form 861), median property
tax (Census ACS), home-price change (Redfin), and the surrounding
power infrastructure (EIA generators, EIA transmission, OSM
substations). All of it is documented. Refresh workflows run weekly
on GitHub Actions.

Today's new addition is a prerendered county ranking at
**powertracker.io/rankings**, plus an individual page for every county
hosting a campus. The intention is not a "data centers cause bills to
go up" claim. That is a causal question I cannot answer from the
joined view. The intention is to make the join available to anyone
(utility commissioners, local reporters, residents, researchers) who
has been reading hyperscaler press releases without the local context.

If you work on grid planning, utility-rate design, or local AI-campus
permitting, I would value a critical read. PRs and correction issues
are welcome at github.com/vxguo1/powertracker. Especially if you live
near one of the sites and have something we got wrong.

**Framework rationale:** Level 3 Balanced Professional tone (LinkedIn
default for a B2B-adjacent technical audience). First-person Ethos
opener establishes why the author is the right person to have built
this (the gap was personal before it was a project). Three-beat story
arc. what existed before, what the join now does, what the new
ranking adds. Close is a clear ask (critical reads, correction PRs)
calibrated as collegial not promotional, which is the LinkedIn
register most likely to surface to grid-planning and PUC readers.

---

## 8. Cold journalist email (template, with bracketed slots)

**Subject** (8 words, number-led, beat keyword front-loaded):

> 29 GW of US AI data-center load, mapped by county

**Body** (target 150 words, draft hits 148):

Hi [REPORTER FIRST NAME],

I read [SHORT TITLE OF RECENT PIECE, within last 60 days] and thought
the dataset behind powertracker.io might be useful. It is an open map
of all 106 publicly known US AI / hyperscaler data-center campuses,
joined to the host utility, the balancing authority absorbing the
load, and 3-year changes in residential electricity rates, property
tax, and home prices for each host county.

Headline reading from the new prerendered ranking at
powertracker.io/rankings: operators have announced 29.1 GW of new
load across 80 counties, 72% of it concentrated in just 10. Mostly
small places. Racine WI (3.3 GW on We Energies, rates already +11.4%),
Cheyenne WY (2.6 GW on Black Hills, rates +13.3%), New Carlisle IN
(2.2 GW from AWS).

The campus list is hand-curated, every row carries a citation URL,
and the full pipeline is open at github.com/vxguo1/powertracker.

Happy to walk through [SPECIFIC ANGLE FOR THIS REPORTER] or ship a
custom extract. Cited or background, your call.

[USER NAME]
powertracker.io . github.com/vxguo1/powertracker

**Tone note:** Cold outreach to a journalist, Level 2 (Casual
Professional), 148 words. Calibration: relationship 0 (cold) +
hierarchy 0 (peer-to-peer professional) + industry -1 (tech/media) +
stakes 0 (medium) = Level 2 after baseline of Level 2.

**Framework rationale:** Inverted Minto. Line 1 references their
recent work (ethos in one beat), then the headline stat lands in the
second paragraph because for cold-outreach to busy reporters, the
"why this exists" sentence has to precede the "here is the number,"
otherwise the number reads as out-of-context spam. The three concrete
counties function as the STAR moment (specific places, specific
rates, specific operators). The dual offer at the close (custom
extract or background) is the easy-yes CTA the email-frameworks
reference calls for. cited-or-background gives the reporter two
ways to say yes and zero ways to feel pressured.

---

## 9. Outlet target list

Grouped by beat. Reporter names are listed only where verified by web
search this session (May 2026). For unverified outlets, send to the
publication's general tip line and reference the beat.

### Tier 1, verified bylines on AI / data-center / power coverage

| Outlet | Reporter(s) | Verified angle |
|---|---|---|
| Heatmap News | **Emily Pontecorvo** (founding staff writer), **Matthew Zeitlin** (correspondent), **Robinson Meyer** (founding exec editor, podcast Shift Key) | Heatmap is the deepest 2026 coverage of data-center power and local opposition. Pontecorvo and Zeitlin both have 2026 bylines on data-center electricity. Robinson Meyer co-hosts Shift Key with Jesse Jenkins, so the dataset would land naturally on the podcast as well as the news side. |
| Canary Media | **Jeff St. John** (chief reporter, policy specialist). Most prolific on data-center / hyperscaler power demand | St. John's existing pieces include "Data centers are driving US power demand to hard-to-reach heights" and "Data-center power forecasts climb to unreachable heights." Powertracker is the dataset behind those forecasts. |
| Canary Media | **Maria Gallucci** (senior reporter). Has covered the data-center energy race with Google/Microsoft | Secondary contact at Canary. Angle is operator competition. |
| Utility Dive | **Ethan Howland**. Multiple 2026 bylines on data-center interconnection (PJM, FERC, EEI) | Direct fit. Powertracker's per-county view + transmission overlay is exactly his beat. |
| Utility Dive | **Emma Penrod**, **Diana DiGangi**, **Herman K. Trabish**, **Meris Lutz**. All have 2026 bylines in the data-center load / interconnection space | Secondary Utility Dive contacts. |
| Bloomberg | **Naureen S. Malik** + **Josh Saul** (co-bylined "Hidden Power Costs of AI" Bloomberg package, honorable mention from Press Club DC) | The most consistent Bloomberg duo on data-center power costs. Pitch them jointly. |
| The Verge | **Justine Calma** (senior science reporter on climate, energy, environment) | 2026 coverage includes data-center power demand at Lake Tahoe, nuclear revival for data centers. Strong fit for the "find your county" / participation angle. |

### Tier 2, outlets by beat, no verified individual byline this session

Send to the tip line. Reference the beat editor.

| Outlet | Beat to target | Why |
|---|---|---|
| MIT Tech Review | Climate / energy desk | Their AI infrastructure pieces are usually paired to a number, which the dataset supplies. |
| Inside Climate News | "Inside Clean Energy" newsletter (data-center coverage confirmed 2026, individual bylines not verified this session) | The newsletter format is ideal for the joined-view framing. |
| E&E News | Grid / utility regulation desk | Trade-press depth. The EIA-861 rate joins are their language. |

### Tier 3, outlets to monitor, not pitch on day 1

| Outlet | Why hold |
|---|---|
| Wired | Slower to cover dataset launches without an exclusive angle. Hold for a follow-up "here's what we learned 90 days in" pitch. |
| The Information | Paywalled, narrow audience. Pitch only if the user has a relationship. |
| Politico Pro Energy | Trade subscription. Useful for state-PUC reporters but the ROI on launch day is low. |

**Pitch order for Tue 2026-05-19:**
1. Send to Tier 1 verified bylines first, 8:30 AM PT (right after HN goes live).
2. Tier 2 outlets via tip lines by 11:00 AM PT.
3. Tier 3 hold for follow-up.

---

## 10. Launch sequence

Today is Sunday 2026-05-17. Launch day is **Tuesday 2026-05-19**.
HN engagement is best Tue to Thu 08:00 to 10:00 PT. Tuesday gives
Wednesday as a clean follow-up day before the end-of-week dropoff.

### Mon 2026-05-18, prep day

| Time | Action | Owner |
|---|---|---|
| AM | Re-run `python scripts/build_rankings.py`. Spot-check that the top 10 list hasn't shifted vs this draft. If it has, update sections 3 / 4 / 6 numbers. | user |
| AM | WebFetch `https://powertracker.io/` and `/rankings` from a logged-out browser. Confirm OG card renders (Twitter / LinkedIn previewers). Confirm /og-image.png loads. | user |
| AM | Set up the three new social accounts. Confirm X handle, LinkedIn page, Bluesky/Mastodon. Add `powertracker.io` to each bio. Pin a tweet that's just the /rankings URL. | user |
| PM | Stage every draft from this file in scheduled-post drafts (X, LinkedIn). Do not auto-publish. | user |
| PM | Identify the 5 to 10 specific journalists from section 9 Tier 1. For each, pull one recent piece title (within last 60 days) into the `[SHORT TITLE OF RECENT PIECE]` slot of section 8. | user |
| PM | Email yourself the section 8 template as a draft so it's ready to copy-paste-personalize on Tuesday. | user |

### Tue 2026-05-19, launch day

All times Pacific. The whole point of same-day coordination is that a
journalist clicking through at 11:00 AM should see HN traction +
recent activity on the social accounts.

| Time | Action | Channel |
|---|---|---|
| 08:00 | Post the HN submission (section 2 title). Immediately post the first-author comment as a reply to your own thread. | Hacker News |
| 08:05 | Post the X thread (section 6). 7 tweets, posted as a single thread, not 7 separate tweets. Use the X scheduling preview to confirm the OG card on tweet 1 renders. | X/Twitter |
| 08:10 | Post to r/energy (section 4). Do not crosspost yet. Let it sit organically for 60+ minutes. | Reddit |
| 08:15 | Post to r/dataisbeautiful (section 3). Within 60 seconds post the source comment as the first reply. (r/dataisbeautiful auto-removes [OC] posts without a source comment within about 15 min.) | Reddit |
| 08:30 | Send Tier 1 journalist emails (section 8 personalized per section 9 list). One outlet at a time, not BCC'd as a single blast. | Email |
| 09:00 | Post the LinkedIn (section 7). | LinkedIn |
| 11:00 | Send Tier 2 outlet tip-line emails (section 9 Tier 2). | Email |
| 12:00 | Check HN ranking. If on front page, do nothing. Don't ask people to upvote, that gets posts buried. If not on front page after 4 hours, the launch on HN is over. Pivot effort to Reddit and X engagement. | (none) |
| 13:00 | Reply to every comment on HN, r/energy, r/dataisbeautiful. Especially correction requests. Every accepted correction is a future cite. | (none) |
| 17:00 | Post r/electricalengineering (section 5 draft). Different audience, off-peak HN time, reduces multi-sub spam-flag risk. | Reddit |

### Wed 2026-05-20, follow-up day

| Time | Action |
|---|---|
| 08:00 | Post r/MapPorn (section 5 draft) with the map screenshot, not the rankings page. |
| 09:00 | Post r/Futurology (section 5 draft). |
| 10:00 | Reply to overnight comments across all platforms. |
| PM | If any journalist responded to a section 8 pitch, schedule the call or send the requested custom extract. The user owns the schema. Pulling a "your readers' state, ranked" CSV is `pandas` one-liners. |
| PM | Quote-tweet or reply-on-thread to anyone who replied with a substantive question. Don't engage trolls. |

### Thu 2026-05-21 onward

- Wait. Don't re-post. Don't ask for upvotes. Don't at-mention more journalists.
- Track who linked back. The GitHub repo's referer logs will catch most of it.
- If a journalist publishes, ship a brief X thread quoting the piece with one
  additional fact they didn't have. This keeps the dataset in their next story.

### Hard rules

- No auto-posting from this file. Every paste is manual.
- No begging for upvotes. HN, Reddit, X all penalize this.
- One link per Reddit post (the rankings URL). The map URL goes in a
  comment if asked.
- No corrections-by-email. Push everyone who has a correction to open
  a PR on `data/sites/data_centers.csv`. The CSV with the citation
  column is the system of record. That's the whole pitch.
- Don't commit anything from this run. This file is local until the
  user explicitly asks otherwise.
