"""Build the /schedule page + /schedule.ics calendar feed.

Reads data/sites/key_votes.csv (manually curated calendar of zoning votes,
hearings, permit decisions, court rulings, regulator actions, etc. that gate
the data-center campuses we track), joins it against data_centers.csv for
site slugs / state / operator, and emits:

  - app/schedule.html       Public chronological schedule with upcoming +
                            recently-decided sections, with deep links to
                            /site/<slug> for each row.
  - app/schedule.ics        RFC 5545 calendar feed; one VEVENT per row so
                            journalists / researchers can subscribe in
                            Google Calendar / Outlook.

Run after editing data/sites/key_votes.csv:
    python scripts/build_schedule.py
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_locations import slugify  # type: ignore  # noqa: E402

VOTES_CSV = ROOT / "data" / "sites" / "key_votes.csv"
SITES_CSV = ROOT / "data" / "sites" / "data_centers.csv"
APP = ROOT / "app"
HTML_OUT = APP / "schedule.html"
ICS_OUT = APP / "schedule.ics"

ACTION_LABELS = {
    "zoning_vote": "Zoning vote",
    "special_use_permit": "Special-use permit",
    "rezoning": "Rezoning",
    "moratorium_vote": "Moratorium vote",
    "referendum": "Referendum",
    "court_ruling": "Court ruling",
    "regulator_approval": "Regulator approval",
    "permit_hearing": "Permit hearing",
    "tax_abatement": "Tax abatement / performance agreement",
    "legislative_session": "Legislative session",
    "planning_review": "Planning review",
    "public_comment_close": "Public-comment deadline",
    "interconnect_decision": "Grid interconnection",
}

OUTCOME_LABELS = {
    "scheduled": "Scheduled",
    "approved": "Approved",
    "denied": "Denied",
    "tabled": "Tabled",
    "delayed": "Delayed",
    "pending": "Pending",
}


def _load_site_index() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with open(SITES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["name"]] = {
                "slug": slugify(row["name"]),
                "state": row["state"],
                "city": row["city"],
                "operator": row["operator"],
                "status": row["status"],
            }
    return out


def _load_votes() -> list[dict]:
    rows: list[dict] = []
    with open(VOTES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["date_obj"] = datetime.strptime(row["date"], "%Y-%m-%d").date()
            rows.append(row)
    rows.sort(key=lambda r: r["date_obj"])
    return rows


def _event_uid(row: dict) -> str:
    raw = f"{row['date']}|{row['site_name']}|{row['action_type']}|{row['jurisdiction']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16] + "@powertracker.io"


def _fmt_date(d: date) -> str:
    return d.strftime("%b %-d, %Y") if sys.platform != "win32" else d.strftime("%b %#d, %Y")


def _days_label(today: date, d: date) -> tuple[str, str]:
    delta = (d - today).days
    if delta == 0:
        return ("today", "today")
    if delta == 1:
        return ("tomorrow", "soon")
    if delta == -1:
        return ("yesterday", "recent")
    if delta > 0:
        if delta <= 14:
            return (f"in {delta} days", "soon")
        if delta <= 60:
            return (f"in {delta} days", "near")
        return (f"in {delta} days", "later")
    abs_d = -delta
    if abs_d <= 14:
        return (f"{abs_d} days ago", "recent")
    if abs_d <= 60:
        return (f"{abs_d} days ago", "recent")
    return (f"{abs_d} days ago", "old")


def _render_event_card(row: dict, sites: dict, today: date) -> str:
    site_info = sites.get(row["site_name"])
    if site_info:
        site_link = (
            f'<a class="ev-site" href="/site/{site_info["slug"]}">'
            f'{html.escape(row["site_name"])}'
            f' <span class="ev-state">({site_info["state"]})</span>'
            f'</a>'
        )
    else:
        site_link = f'<span class="ev-site ev-site-missing">{html.escape(row["site_name"])}</span>'

    days_text, urgency = _days_label(today, row["date_obj"])
    action_label = ACTION_LABELS.get(row["action_type"], row["action_type"].replace("_", " "))
    outcome = row["outcome"]
    outcome_label = OUTCOME_LABELS.get(outcome, outcome)

    return (
        f'<article class="ev ev-{outcome}" id="ev-{_event_uid(row).split("@")[0]}">'
        f'<div class="ev-date">'
        f'  <time datetime="{row["date"]}">{html.escape(_fmt_date(row["date_obj"]))}</time>'
        f'  <span class="ev-days ev-days-{urgency}">{html.escape(days_text)}</span>'
        f'</div>'
        f'<div class="ev-body">'
        f'  <header class="ev-head">'
        f'    {site_link}'
        f'    <div class="ev-chips">'
        f'      <span class="chip chip-action chip-{row["action_type"]}">{html.escape(action_label)}</span>'
        f'      <span class="chip chip-outcome chip-outcome-{outcome}">{html.escape(outcome_label)}</span>'
        f'    </div>'
        f'  </header>'
        f'  <p class="ev-desc">{html.escape(row["description"])}</p>'
        f'  <footer class="ev-foot">'
        f'    <span class="ev-juris">{html.escape(row["jurisdiction"])} &middot; {html.escape(row["decision_body"])}</span>'
        f'    <a class="ev-source" href="{html.escape(row["source"])}" rel="noopener" target="_blank">source &rsaquo;</a>'
        f'  </footer>'
        f'</div>'
        f'</article>'
    )


def _build_html(rows: list[dict], sites: dict, today: date) -> str:
    upcoming = [r for r in rows if r["date_obj"] >= today]
    recent = [r for r in rows if r["date_obj"] < today]
    recent_sorted = sorted(recent, key=lambda r: r["date_obj"], reverse=True)

    n_upcoming = len(upcoming)
    n_recent = len(recent)
    next_event = upcoming[0] if upcoming else None
    next_event_str = (
        f'{_fmt_date(next_event["date_obj"])} &mdash; {html.escape(next_event["site_name"])}'
        if next_event else "&mdash;"
    )

    # Group upcoming by month for headings.
    upcoming_html_parts: list[str] = []
    last_month = None
    for row in upcoming:
        ym = row["date_obj"].strftime("%B %Y")
        if ym != last_month:
            upcoming_html_parts.append(f'<h3 class="month-head">{ym}</h3>')
            last_month = ym
        upcoming_html_parts.append(_render_event_card(row, sites, today))
    upcoming_html = "\n".join(upcoming_html_parts) or '<p class="empty">No upcoming events scheduled.</p>'

    recent_html_parts: list[str] = []
    last_month = None
    for row in recent_sorted:
        ym = row["date_obj"].strftime("%B %Y")
        if ym != last_month:
            recent_html_parts.append(f'<h3 class="month-head">{ym}</h3>')
            last_month = ym
        recent_html_parts.append(_render_event_card(row, sites, today))
    recent_html = "\n".join(recent_html_parts) or '<p class="empty">No recent events logged.</p>'

    page_title = "Key votes &amp; hearings — US AI data-center approvals | powertracker"
    meta_desc = (
        f"Schedule of upcoming and recent local-government votes, regulator decisions, "
        f"court rulings and permit hearings that gate US AI and hyperscaler data-center "
        f"campuses. {n_upcoming} upcoming, {n_recent} recently decided. "
        f"Subscribe via /schedule.ics."
    )

    today_iso = today.isoformat()

    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "US AI data-center key votes and hearings",
        "description": (
            "Chronological list of upcoming and recent local-government, regulator, and "
            "court actions that gate AI / hyperscaler data-center campuses tracked by "
            "powertracker.io."
        ),
        "url": "https://powertracker.io/schedule",
        "numberOfItems": len(rows),
        "itemListOrder": "https://schema.org/ItemListOrderAscending",
        "itemListElement": [
            {
                "@type": "Event",
                "position": i + 1,
                "name": f"{ACTION_LABELS.get(r['action_type'], r['action_type'])}: {r['site_name']}",
                "startDate": r["date"],
                "eventStatus": (
                    "https://schema.org/EventScheduled" if r["outcome"] == "scheduled"
                    else "https://schema.org/EventRescheduled" if r["outcome"] in {"tabled", "delayed", "pending"}
                    else "https://schema.org/EventScheduled"
                ),
                "eventAttendanceMode": "https://schema.org/MixedEventAttendanceMode",
                "location": {
                    "@type": "Place",
                    "name": r["jurisdiction"],
                    "address": {"@type": "PostalAddress", "addressLocality": r["jurisdiction"], "addressCountry": "US"},
                },
                "description": r["description"],
                "url": r["source"],
            }
            for i, r in enumerate(rows)
        ],
    }

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Key votes &amp; hearings &mdash; US AI data-center approvals | powertracker</title>
<meta name="description" content="{html.escape(meta_desc)}">
<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
<meta name="theme-color" content="#d7263d">

<meta property="og:type" content="article">
<meta property="og:site_name" content="powertracker">
<meta property="og:url" content="https://powertracker.io/schedule">
<meta property="og:title" content="{page_title}">
<meta property="og:description" content="{html.escape(meta_desc)}">
<meta property="og:image" content="https://powertracker.io/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{page_title}">
<meta name="twitter:description" content="{html.escape(meta_desc)}">
<meta name="twitter:image" content="https://powertracker.io/og-image.png">

<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="canonical" href="https://powertracker.io/schedule">
<link rel="alternate" type="text/calendar" title="powertracker key-votes calendar (iCal)" href="/schedule.ics">
<link rel="alternate" type="application/rss+xml" title="powertracker weekly digest" href="/feed.xml">

<script type="application/ld+json">
{json.dumps(item_list, indent=2)}
</script>

<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --text-xs:   0.6875rem;
  --text-sm:   0.8125rem;
  --text-base: 0.9375rem;
  --text-lg:   1.0625rem;
  --text-xl:   1.25rem;
  --text-2xl:  1.75rem;
  --text-3xl:  2.5rem;
  --font-stack: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --c-page:    #f5f5f7;
  --c-surface: #ffffff;
  --c-ink:     #1a1a23;
  --c-ink-muted: #5a5a6e;
  --c-ink-soft:  #8b8b9a;
  --c-border:    #e3e3e8;
  --c-accent:    #d7263d;
  --c-tag:       #eeeef3;
  --shadow-sm: 0 1px 2px rgba(20,20,40,0.06);
  --shadow-md: 0 6px 18px -4px rgba(20,20,40,0.12), 0 2px 6px rgba(20,20,40,0.06);
}}
html, body {{
  font-family: var(--font-stack);
  font-size: var(--text-base);
  line-height: 1.55;
  color: var(--c-ink);
  background: var(--c-page);
  -webkit-font-smoothing: antialiased;
}}
a {{ color: var(--c-accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

.page {{ max-width: 960px; margin: 0 auto; padding: 32px 24px 80px; }}
header.site {{ margin-bottom: 36px; display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; }}
header.site .brand {{ font-size: var(--text-xl); font-weight: 700; letter-spacing: -0.015em; color: var(--c-ink); }}
header.site .tagline {{ font-size: var(--text-sm); color: var(--c-ink-muted); margin-top: 4px; }}
header.site nav a {{ font-size: var(--text-sm); margin-left: 14px; color: var(--c-ink-muted); }}
header.site nav a:hover {{ color: var(--c-accent); }}

.hero {{ margin-bottom: 28px; }}
.hero h1 {{ font-size: clamp(1.75rem, 4vw, 2.4rem); font-weight: 800; letter-spacing: -0.02em; line-height: 1.15; color: var(--c-ink); }}
.hero .lede {{ margin-top: 14px; font-size: var(--text-lg); color: var(--c-ink-muted); max-width: 720px; }}

.summary {{
  background: var(--c-surface); border: 1px solid var(--c-border);
  border-radius: 10px; padding: 16px 20px; box-shadow: var(--shadow-sm);
  margin-bottom: 30px; display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px;
}}
.summary .stat .label {{ font-size: var(--text-xs); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--c-ink-soft); }}
.summary .stat .value {{ font-size: var(--text-xl); font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; color: var(--c-ink); }}
.summary .stat.next .value {{ font-size: var(--text-base); font-weight: 600; line-height: 1.4; }}

.subscribe {{
  background: #fffaf0; border: 1px solid #f4d4a0; border-radius: 10px;
  padding: 14px 18px; margin-bottom: 30px; font-size: var(--text-sm);
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
}}
.subscribe strong {{ color: var(--c-ink); }}
.subscribe a {{ font-weight: 600; }}

.section-head {{ font-size: var(--text-sm); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--c-ink-soft); margin: 28px 0 14px; padding-top: 12px; border-top: 1px solid var(--c-border); }}
.month-head {{ font-size: var(--text-lg); font-weight: 700; color: var(--c-ink); margin: 22px 0 10px; letter-spacing: -0.01em; }}

.ev {{
  display: flex; gap: 18px; background: var(--c-surface);
  border: 1px solid var(--c-border); border-radius: 10px;
  padding: 16px 20px; box-shadow: var(--shadow-sm); margin-bottom: 12px;
  transition: box-shadow 0.15s ease;
}}
.ev:hover {{ box-shadow: var(--shadow-md); }}
.ev:target {{ border-color: var(--c-accent); box-shadow: 0 0 0 2px rgba(215,38,61,0.15), var(--shadow-md); }}

.ev-date {{
  flex: 0 0 100px; min-width: 100px;
  display: flex; flex-direction: column; gap: 4px;
}}
.ev-date time {{ font-weight: 700; font-size: var(--text-sm); font-variant-numeric: tabular-nums; color: var(--c-ink); }}
.ev-days {{ font-size: var(--text-xs); padding: 2px 8px; border-radius: 999px; align-self: flex-start; font-weight: 600; }}
.ev-days-today {{ background: #fde2e6; color: #a8082a; }}
.ev-days-soon  {{ background: #fdf0d8; color: #7a3a10; }}
.ev-days-near  {{ background: #eeeef3; color: var(--c-ink-muted); }}
.ev-days-later {{ background: #eef3ee; color: #44663a; }}
.ev-days-recent {{ background: #eaf3fa; color: #1e4f73; }}
.ev-days-old   {{ background: var(--c-tag); color: var(--c-ink-soft); }}

.ev-body {{ flex: 1; min-width: 0; }}
.ev-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }}
.ev-site {{ font-size: var(--text-base); font-weight: 700; color: var(--c-ink); }}
.ev-site:hover {{ color: var(--c-accent); }}
.ev-site-missing {{ color: var(--c-ink-muted); cursor: default; }}
.ev-state {{ color: var(--c-ink-soft); font-weight: 500; font-size: var(--text-sm); }}

.ev-chips {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.chip {{ font-size: var(--text-xs); font-weight: 600; padding: 3px 9px; border-radius: 999px; white-space: nowrap; }}
.chip-action {{ background: var(--c-tag); color: var(--c-ink-muted); }}
.chip-outcome-scheduled {{ background: #e6e6f5; color: #443d72; }}
.chip-outcome-approved {{ background: #d5ecdb; color: #1b5a30; }}
.chip-outcome-denied {{ background: #fde2e6; color: #a8082a; }}
.chip-outcome-tabled {{ background: #fdf0d8; color: #7a3a10; }}
.chip-outcome-delayed {{ background: #fdf0d8; color: #7a3a10; }}
.chip-outcome-pending {{ background: #eaf3fa; color: #1e4f73; }}

.ev-desc {{ color: var(--c-ink); font-size: var(--text-sm); margin-bottom: 8px; line-height: 1.5; }}
.ev-foot {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; font-size: var(--text-xs); color: var(--c-ink-soft); }}
.ev-juris {{ font-weight: 500; }}
.ev-source {{ font-weight: 600; }}

.empty {{ color: var(--c-ink-soft); font-style: italic; padding: 20px 0; }}

@media (max-width: 640px) {{
  .ev {{ flex-direction: column; gap: 8px; padding: 14px 16px; }}
  .ev-date {{ flex-direction: row; align-items: center; gap: 10px; min-width: 0; }}
}}
</style>
</head>
<body>
<div class="page">
  <header class="site">
    <div>
      <div class="brand"><a href="/" style="color:var(--c-ink)">powertracker</a></div>
      <div class="tagline">US AI &amp; hyperscaler data centers on the grid, in context.</div>
    </div>
    <nav>
      <a href="/">Map</a>
      <a href="/rankings">Rankings</a>
      <a href="/schedule" aria-current="page" style="color:var(--c-accent);font-weight:600">Schedule</a>
      <a href="/weekly">Weekly digest</a>
      <a href="/sources">Sources</a>
    </nav>
  </header>

  <section class="hero">
    <h1>Key votes &amp; hearings</h1>
    <p class="lede">
      Upcoming and recent local-government votes, regulator decisions, court rulings and
      permit hearings that gate the US AI / hyperscaler data-center campuses tracked on
      this site. Maintained by hand; sources cited per row.
    </p>
  </section>

  <section class="summary" aria-label="Schedule at a glance">
    <div class="stat">
      <div class="label">Upcoming</div>
      <div class="value">{n_upcoming}</div>
    </div>
    <div class="stat">
      <div class="label">Decided (last ~6 mo)</div>
      <div class="value">{n_recent}</div>
    </div>
    <div class="stat next">
      <div class="label">Next event</div>
      <div class="value">{next_event_str}</div>
    </div>
  </section>

  <aside class="subscribe">
    <span><strong>Subscribe</strong> in Google Calendar or Outlook so you don't miss a vote.</span>
    <a href="/schedule.ics">Add to calendar (.ics) &rsaquo;</a>
  </aside>

  <h2 class="section-head">Upcoming</h2>
  {upcoming_html}

  <h2 class="section-head">Recently decided</h2>
  {recent_html}

  <footer style="margin-top:48px; padding-top:20px; border-top:1px solid var(--c-border); font-size:var(--text-xs); color:var(--c-ink-soft);">
    Last built {today_iso}. Schedule data is hand-curated from local newspapers,
    county / city / state agendas, regulator dockets and court filings.
    <a href="https://github.com/vxguo1/powertracker/blob/main/data/sites/key_votes.csv">Source CSV</a>.
  </footer>
</div>
</body>
</html>
"""


def _ics_escape(s: str) -> str:
    # RFC 5545 text escaping: backslash, semicolon, comma, newline.
    return (
        s.replace("\\", "\\\\")
         .replace(";", "\\;")
         .replace(",", "\\,")
         .replace("\n", "\\n")
    )


def _ics_fold(line: str) -> str:
    # RFC 5545 line-folding at 75 octets; UTF-8 simple version.
    out = []
    while len(line.encode("utf-8")) > 75:
        # cut at 73 chars to leave room for CRLF + leading space
        chunk = line[:73]
        out.append(chunk)
        line = " " + line[73:]
    out.append(line)
    return "\r\n".join(out)


def _build_ics(rows: list[dict], sites: dict, now: datetime) -> str:
    dtstamp = now.strftime("%Y%m%dT%H%M%SZ")
    preamble = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//powertracker.io//Key Votes Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:powertracker - AI data-center key votes",
        "X-WR-CALDESC:Upcoming and recent US local-government votes\\, regulator decisions\\, court rulings and permit hearings that gate AI / hyperscaler data-center campuses tracked by powertracker.io",
        "X-WR-TIMEZONE:UTC",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
    ]
    lines: list[str] = [_ics_fold(l) for l in preamble]
    for row in rows:
        d = row["date_obj"]
        dnext = d + timedelta(days=1)
        action_label = ACTION_LABELS.get(row["action_type"], row["action_type"])
        outcome_label = OUTCOME_LABELS.get(row["outcome"], row["outcome"])
        site_info = sites.get(row["site_name"])
        site_url = (
            f"https://powertracker.io/site/{site_info['slug']}"
            if site_info else "https://powertracker.io/schedule"
        )
        summary = f"[powertracker] {action_label} - {row['site_name']} ({row['jurisdiction']})"
        description = (
            f"{row['description']}\n\n"
            f"Site: {row['site_name']}\n"
            f"Decision body: {row['decision_body']}\n"
            f"Action: {action_label}\n"
            f"Outcome: {outcome_label}\n"
            f"Source: {row['source']}\n"
            f"Powertracker site page: {site_url}"
        )
        for raw_line in [
            "BEGIN:VEVENT",
            f"UID:{_event_uid(row)}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{dnext.strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description)}",
            f"LOCATION:{_ics_escape(row['jurisdiction'])}",
            f"URL:{row['source']}",
            f"CATEGORIES:{_ics_escape(action_label)},{_ics_escape(outcome_label)}",
            f"STATUS:{'CONFIRMED' if row['outcome'] == 'scheduled' else 'TENTATIVE' if row['outcome'] in ('tabled','delayed','pending') else 'CONFIRMED'}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]:
            lines.append(_ics_fold(raw_line))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main() -> None:
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    rows = _load_votes()
    sites = _load_site_index()

    html_out = _build_html(rows, sites, today)
    HTML_OUT.write_text(html_out, encoding="utf-8")
    print(f"wrote {HTML_OUT} ({HTML_OUT.stat().st_size/1024:.1f} KB, {len(rows)} events)")

    ics_out = _build_ics(rows, sites, now)
    ICS_OUT.write_bytes(ics_out.encode("utf-8"))
    print(f"wrote {ICS_OUT} ({ICS_OUT.stat().st_size/1024:.1f} KB)")

    missing = sorted({r["site_name"] for r in rows} - set(sites.keys()))
    if missing:
        print(f"warning: {len(missing)} event(s) reference site names not in data_centers.csv:")
        for n in missing:
            print(f"  - {n!r}")


if __name__ == "__main__":
    main()
