# Why we're building powertracker

## The thing nobody can see

A 2-gigawatt data center is rising in Rayville, Louisiana, a town of about 3,700 people. The press release calls it transformative investment. The local paper runs a stock photo. The county commission approves the tax abatement. And then everyone moves on.

Nobody can tell you what this campus will draw on a hot Tuesday in July, how much of that draw the rest of Entergy Louisiana's customers will subsidize through fixed-cost recovery, whether home values within a five-mile radius will move, whether the diesel backup fleet will change the air the elementary school breathes, or whether life expectancy in the tract that hosts the substation will diverge from the tract that does not.

These are not exotic questions. They are the first questions any resident would ask if they knew to ask them. The answers are not secret. They are scattered, unjoined, and frequently buried inside agency portals that were not built for cross-cutting research.

## What this project does about it

Powertracker is a public record. It pulls together what is already public, joins it to the physical infrastructure that triggered the change, and publishes the joined view openly so that anyone can audit, fork, or extend it.

Three things have to be true at once.

**It has to be honest about resolution.** Hourly load data stops at the balancing authority because anything finer is treated as Critical Energy Infrastructure Information. Property records are county-level in some states and parcel-level in others. Life expectancy is tract-level. We meet each source at its real resolution. We do not invent precision the data does not support.

**It has to be honest about causation.** A step-change in PJM's load coincident with a Loudoun County commissioning is suggestive, not conclusive. Property values inside a five-mile radius can move because of a new highway, a school rezoning, or the data center. The pipeline emits the joined data and the candidate signals. It does not pretend to settle questions that need a research design.

**It has to be honest about what it does not yet measure.** Water draw, backup generator runtime, substation noise complaints, and worker exposure are mostly outside the public dataset today. The project documents these gaps explicitly so that future contributors and FOIA campaigns know where to push.

## Why now

Three forces are converging.

The first is scale. The publicly announced capacity on just three of our 19 seed sites already exceeds 4 gigawatts. Industry analysts now project that data center load could account for nearly all incremental US electricity demand growth through 2030. This is not a niche story anymore. It is the dominant story of the next decade of the American grid.

The second is concentration. AI training campuses cluster where land is cheap, power is abundant, and oversight is thin. Many of the largest are landing in small balancing authorities, in counties that lack the staff to negotiate with a counterparty whose lawyers bill more in an hour than the planning department's annual budget.

The third is opacity. The information asymmetry between the hyperscaler and the host community is, today, almost total. Utilities sign nondisclosure agreements as a condition of large-load interconnection. Site selection consultants treat the search itself as confidential. Local officials sign tax abatements based on numbers they cannot independently verify.

A public record cannot fix the asymmetry. But it can make the asymmetry visible.

## What we believe

We believe the AI buildout is going to happen. We are not trying to stop it. We are trying to make sure that when historians look back at how the United States rebuilt its electrical infrastructure in the 2020s, the record of who paid, who benefited, and what changed in the host communities is in the open and not in a consultant's slide deck.

We believe public data, joined carefully, is more powerful than commissioned reports. A commissioned report is read once. A public dataset is queried for a decade.

We believe in citing every row. Every site in our registry carries a source URL. Every transform in our pipeline is reproducible from raw inputs. If a number is wrong, anyone can find where it came from and submit a correction.

## What we are asking

If you are a researcher, fork the repo and challenge the methodology. If you are a journalist, use the dataset for a story and tell us what was missing. If you live near one of these sites, tell us what your community already knows that we have not yet captured. If you work for a utility or a hyperscaler and you want to disclose more than you currently do, the schema is open.

The first version of the joined dataset will not be complete. The second version will be less incomplete. The tenth version, with enough hands on it, can be the canonical public record of what the AI infrastructure boom did to the places that hosted it.

That is the work.
