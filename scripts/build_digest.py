"""Weekly digest builder.

Diffs the current snapshot of the project against the previous one and emits
a human-readable digest entry. The entry covers:

  - **New campuses** added to data/sites/data_centers.csv since last run.
  - **Biggest movers** in YoY layers (utility rate, home price, property tax)
    by absolute change in the per-period %.

Outputs:
  - app/weekly/index.html           Rolling page with the latest 26 entries.
  - app/feed.xml                    RSS 2.0 feed of the same entries.
  - data/cache/digest_snapshot.json Latest snapshot for next-run comparison.
  - data/cache/digest_history.json  Accumulated digest entries.

Run after data refreshes:
    python scripts/build_digest.py
"""

from __future__ import annotations

import csv
import html
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_rankings import (  # type: ignore  # noqa: E402
    SITES_CSV,
    UTILITY_RATE,
    REALESTATE,
    PROPERTY_TAX,
    STATE_ABBR_TO_NAME,
    load_fips_pct,
    load_utility_rates,
)
from build_locations import slugify, county_slug  # type: ignore  # noqa: E402

APP = ROOT / "app"
WEEKLY_DIR = APP / "weekly"
SNAPSHOT_PATH = ROOT / "data" / "cache" / "digest_snapshot.json"
HISTORY_PATH = ROOT / "data" / "cache" / "digest_history.json"
FEED_PATH = APP / "feed.xml"

MAX_HISTORY = 26
TOP_MOVERS = 5


def site_key(name: str, city: str, state: str) -> str:
    return f"{name}|{city}|{state}"


def load_sites() -> list[dict]:
    out = []
    with open(SITES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                mw = float(row["announced_mw"]) if row["announced_mw"] else 0.0
            except ValueError:
                mw = 0.0
            out.append({
                "name": row["name"],
                "operator": row["operator"],
                "city": row["city"],
                "state": row["state"],
                "utility": row["utility"],
                "announced_mw": mw,
                "status": row["status"],
                "online_year": row["online_year"],
                "source": row["source"],
            })
    return out


def load_utility_id_map() -> dict[tuple[str, str], str]:
    """{(utility_name, state): utility_name pretty}. Used to label movers."""
    out: dict[tuple[str, str], str] = {}
    with open(UTILITY_RATE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[(row["utility_name"].strip(), row["state"])] = row["utility_name"].strip()
    return out


def fips_to_county_name() -> dict[str, str]:
    """{fips: 'Foo County, ST'}. Cached from property_tax (already has the name)."""
    out: dict[str, str] = {}
    with open(PROPERTY_TAX, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["fips"]] = row["name"]
    return out


def load_snapshot() -> dict:
    if SNAPSHOT_PATH.exists():
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return {}


def save_snapshot(snap: dict) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")


def load_history() -> list[dict]:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return []


def save_history(history: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2), encoding="utf-8")


def build_entry() -> dict:
    """Compute this run's digest entry against the previous snapshot."""
    prev = load_snapshot()
    today = datetime.now(timezone.utc).date().isoformat()

    sites = load_sites()
    rate_rows = []
    with open(UTILITY_RATE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rate_rows.append({
                    "utility_id": row["utility_id"],
                    "utility_name": row["utility_name"].strip(),
                    "state": row["state"],
                    "pct": float(row["price_change_pct"]),
                    "customers": float(row["customers"] or 0),
                })
            except (ValueError, KeyError):
                continue
    homes = load_fips_pct(REALESTATE, "growth_pct")
    taxes = load_fips_pct(PROPERTY_TAX, "growth_pct")
    fips_names = fips_to_county_name()

    # NEW campuses since last snapshot.
    prev_sites = prev.get("sites", {})
    new_campuses = []
    for s in sites:
        if site_key(s["name"], s["city"], s["state"]) not in prev_sites:
            new_campuses.append(s)

    # On a first-ever run, every site looks "new" - which is misleading.
    # Suppress the new-campus list on the kickoff digest.
    is_kickoff = not prev

    # Rate movers (filter to high-customer-count utilities so the list isn't
    # dominated by tiny co-ops with noisy values; >= 50k customers).
    prev_rates = prev.get("rates", {})
    rate_movers = []
    for r in rate_rows:
        if r["customers"] < 50_000:
            continue
        key = f"{r['utility_id']}|{r['state']}"
        prev_val = prev_rates.get(key)
        if prev_val is None:
            continue
        delta = r["pct"] - prev_val
        rate_movers.append({
            "utility_name": r["utility_name"],
            "state": r["state"],
            "now": r["pct"],
            "prev": prev_val,
            "delta": delta,
        })
    rate_movers.sort(key=lambda x: -abs(x["delta"]))
    rate_movers = rate_movers[:TOP_MOVERS]

    # Home-price movers.
    prev_homes = prev.get("homes", {})
    home_movers = []
    for fips, v in homes.items():
        prev_val = prev_homes.get(fips)
        if prev_val is None:
            continue
        delta = v - prev_val
        home_movers.append({
            "fips": fips,
            "county": fips_names.get(fips, fips),
            "now": v,
            "prev": prev_val,
            "delta": delta,
        })
    home_movers.sort(key=lambda x: -abs(x["delta"]))
    home_movers = home_movers[:TOP_MOVERS]

    # Property-tax movers (same shape).
    prev_taxes = prev.get("taxes", {})
    tax_movers = []
    for fips, v in taxes.items():
        prev_val = prev_taxes.get(fips)
        if prev_val is None:
            continue
        delta = v - prev_val
        tax_movers.append({
            "fips": fips,
            "county": fips_names.get(fips, fips),
            "now": v,
            "prev": prev_val,
            "delta": delta,
        })
    tax_movers.sort(key=lambda x: -abs(x["delta"]))
    tax_movers = tax_movers[:TOP_MOVERS]

    entry = {
        "date": today,
        "kickoff": is_kickoff,
        "new_campuses": [] if is_kickoff else new_campuses,
        "rate_movers": rate_movers,
        "home_movers": home_movers,
        "tax_movers": tax_movers,
        "stats": {
            "total_campuses": len(sites),
            "total_announced_mw": sum(s["announced_mw"] for s in sites),
            "utility_rate_rows": len(rate_rows),
            "home_price_rows": len(homes),
            "property_tax_rows": len(taxes),
        },
    }

    new_snap = {
        "date": today,
        "sites": {
            site_key(s["name"], s["city"], s["state"]): {
                "operator": s["operator"],
                "mw": s["announced_mw"],
                "status": s["status"],
            }
            for s in sites
        },
        "rates": {
            f"{r['utility_id']}|{r['state']}": r["pct"]
            for r in rate_rows
        },
        "homes": dict(homes),
        "taxes": dict(taxes),
    }
    save_snapshot(new_snap)
    return entry


def fmt_pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def fmt_delta(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}pp"


def render_entry_html(e: dict) -> str:
    parts: list[str] = []

    parts.append(f'<article class="entry" id="{e["date"]}">')
    parts.append(f'<header><h2>{e["date"]}</h2>')
    if e.get("kickoff"):
        parts.append(
            '<p class="kickoff">First digest. The diff layers '
            "(new campuses, rate movers, price movers) will activate from the "
            "next refresh onward; this entry records the baseline state.</p>"
        )
    parts.append("</header>")

    # New campuses.
    if e["new_campuses"]:
        parts.append('<section><h3>New campuses</h3><ul class="list">')
        for s in e["new_campuses"]:
            slug = slugify(s["name"])
            mw_str = (
                f" &mdash; <strong>{int(round(s['announced_mw']))} MW</strong>"
                if s["announced_mw"] > 0 else ""
            )
            state_name = STATE_ABBR_TO_NAME.get(s["state"], s["state"])
            parts.append(
                f'<li><a href="/site/{slug}"><strong>{html.escape(s["name"])}</strong></a>'
                f' &middot; {html.escape(s["operator"])}'
                f' &middot; <span class="muted">{html.escape(s["city"])}, {state_name}</span>'
                f"{mw_str}</li>"
            )
        parts.append("</ul></section>")

    # Rate movers.
    if e["rate_movers"]:
        parts.append('<section><h3>Biggest utility-rate movers</h3><ul class="list">')
        for r in e["rate_movers"]:
            parts.append(
                f'<li><strong>{html.escape(r["utility_name"])}</strong> '
                f'<span class="muted">({r["state"]})</span> '
                f'&mdash; now <strong>{fmt_pct(r["now"])}</strong> '
                f'(was {fmt_pct(r["prev"])}, <strong>{fmt_delta(r["delta"])}</strong>)'
                f"</li>"
            )
        parts.append("</ul></section>")

    # Home-price movers.
    if e["home_movers"]:
        parts.append('<section><h3>Biggest home-price movers</h3><ul class="list">')
        for m in e["home_movers"]:
            parts.append(
                f'<li><strong>{html.escape(m["county"])}</strong> '
                f'&mdash; now <strong>{fmt_pct(m["now"])}</strong> '
                f'(was {fmt_pct(m["prev"])}, <strong>{fmt_delta(m["delta"])}</strong>)'
                f"</li>"
            )
        parts.append("</ul></section>")

    # Property-tax movers.
    if e["tax_movers"]:
        parts.append('<section><h3>Biggest property-tax movers</h3><ul class="list">')
        for m in e["tax_movers"]:
            parts.append(
                f'<li><strong>{html.escape(m["county"])}</strong> '
                f'&mdash; now <strong>{fmt_pct(m["now"])}</strong> '
                f'(was {fmt_pct(m["prev"])}, <strong>{fmt_delta(m["delta"])}</strong>)'
                f"</li>"
            )
        parts.append("</ul></section>")

    # Stats footer.
    s = e["stats"]
    parts.append(
        '<footer class="entry-foot">'
        f'<span class="muted">Snapshot stats:</span> '
        f"{s['total_campuses']} campuses tracked &middot; "
        f"{s['total_announced_mw'] / 1000:.1f} GW announced &middot; "
        f"{s['utility_rate_rows']} utility rows &middot; "
        f"{s['home_price_rows']} county home-price rows"
        "</footer>"
    )
    parts.append("</article>")
    return "\n".join(parts)


def render_weekly_page(history: list[dict]) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries_html = "\n".join(render_entry_html(e) for e in history)

    desc = (
        "Weekly digest of new AI data-center campus announcements and "
        "the biggest movers in utility residential rates, home prices, and "
        "property taxes across US counties hosting data-center load."
    )
    feed_link = '<link rel="alternate" type="application/rss+xml" title="powertracker weekly" href="/feed.xml">'

    html_out = WEEKLY_TEMPLATE.format(
        today=today,
        desc=html.escape(desc),
        feed_link=feed_link,
        entries=entries_html,
        feed_url="https://powertracker.io/feed.xml",
    )
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    (WEEKLY_DIR / "index.html").write_text(html_out, encoding="utf-8")


def render_rss_feed(history: list[dict]) -> None:
    now = datetime.now(timezone.utc)
    items_xml = []
    for e in history:
        # Treat date as UTC midnight for pubDate.
        try:
            d = datetime.fromisoformat(e["date"]).replace(tzinfo=timezone.utc)
        except ValueError:
            d = now
        title = f"powertracker · {e['date']}"
        if e["new_campuses"]:
            title += f" · {len(e['new_campuses'])} new campus"
            if len(e["new_campuses"]) != 1:
                title += "es"
        if e["rate_movers"]:
            title += f" · {len(e['rate_movers'])} rate movers"
        # Plaintext body of the digest, line by line.
        body_lines = []
        if e.get("kickoff"):
            body_lines.append("First digest - baseline snapshot.")
        if e["new_campuses"]:
            body_lines.append("New campuses:")
            for s in e["new_campuses"]:
                mw = f" - {int(round(s['announced_mw']))} MW" if s["announced_mw"] > 0 else ""
                body_lines.append(f"  - {s['name']} ({s['operator']}, {s['city']}, {s['state']}){mw}")
        if e["rate_movers"]:
            body_lines.append("Rate movers:")
            for r in e["rate_movers"]:
                body_lines.append(
                    f"  - {r['utility_name']} ({r['state']}): "
                    f"{fmt_pct(r['now'])} (was {fmt_pct(r['prev'])}, {fmt_delta(r['delta'])})"
                )
        if e["home_movers"]:
            body_lines.append("Home-price movers:")
            for m in e["home_movers"]:
                body_lines.append(
                    f"  - {m['county']}: {fmt_pct(m['now'])} "
                    f"(was {fmt_pct(m['prev'])}, {fmt_delta(m['delta'])})"
                )
        if e["tax_movers"]:
            body_lines.append("Property-tax movers:")
            for m in e["tax_movers"]:
                body_lines.append(
                    f"  - {m['county']}: {fmt_pct(m['now'])} "
                    f"(was {fmt_pct(m['prev'])}, {fmt_delta(m['delta'])})"
                )
        body = "\n".join(body_lines).strip() or "No changes detected this run."
        guid = f"https://powertracker.io/weekly#{e['date']}"
        items_xml.append(
            "  <item>\n"
            f"    <title>{html.escape(title)}</title>\n"
            f"    <link>{guid}</link>\n"
            f"    <guid isPermaLink=\"true\">{guid}</guid>\n"
            f"    <pubDate>{format_datetime(d)}</pubDate>\n"
            f"    <description><![CDATA[<pre>{html.escape(body)}</pre>]]></description>\n"
            "  </item>"
        )

    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        "  <title>powertracker · weekly</title>\n"
        "  <link>https://powertracker.io/weekly</link>\n"
        "  <description>Weekly diff of US AI / hyperscaler data-center "
        "campuses and the grid + economic context around them.</description>\n"
        '  <atom:link href="https://powertracker.io/feed.xml" rel="self" '
        'type="application/rss+xml"/>\n'
        "  <language>en-us</language>\n"
        f"  <lastBuildDate>{format_datetime(now)}</lastBuildDate>\n"
        + "\n".join(items_xml)
        + "\n</channel>\n</rss>\n"
    )
    FEED_PATH.write_text(rss, encoding="utf-8")


WEEKLY_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weekly digest - powertracker</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="https://powertracker.io/weekly">
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
  <meta name="theme-color" content="#d7263d">
  <meta name="author" content="powertracker">

  <meta property="og:type" content="article">
  <meta property="og:site_name" content="powertracker">
  <meta property="og:url" content="https://powertracker.io/weekly">
  <meta property="og:title" content="Weekly digest - powertracker">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="https://powertracker.io/og-image.png">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="Weekly digest - powertracker">
  <meta name="twitter:description" content="{desc}">
  <meta name="twitter:image" content="https://powertracker.io/og-image.png">

  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  {feed_link}
  <link rel="sitemap" type="application/xml" href="/sitemap.xml">

  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --c-page:#f5f5f7;--c-surface:#fff;--c-ink:#1a1a23;--c-ink-muted:#5a5a6e;
      --c-ink-soft:#8b8b9a;--c-border:#e3e3e8;--c-accent:#d7263d;
      --font:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
      --shadow-sm:0 1px 2px rgba(20,20,40,.06);
    }}
    html,body{{font-family:var(--font);font-size:15px;line-height:1.55;color:var(--c-ink);background:var(--c-page);-webkit-font-smoothing:antialiased}}
    a{{color:var(--c-accent);text-decoration:none}}a:hover{{text-decoration:underline}}
    .page{{max-width:840px;margin:0 auto;padding:32px 24px 80px}}
    header.site{{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
    header.site .brand{{font-size:18px;font-weight:700;letter-spacing:-.015em}}
    header.site .tagline{{font-size:13px;color:var(--c-ink-muted);margin-top:2px}}
    nav a{{font-size:13px;margin-left:14px}}
    .lede{{margin-bottom:32px}}
    .lede h1{{font-size:clamp(1.75rem,4vw,2.5rem);font-weight:800;letter-spacing:-.02em;line-height:1.15;color:var(--c-ink)}}
    .lede p{{margin-top:12px;font-size:17px;color:var(--c-ink-muted);max-width:680px}}
    .lede .subscribe{{margin-top:14px;display:inline-flex;align-items:center;gap:10px;font-size:13px;color:var(--c-ink-muted)}}
    .lede .subscribe code{{background:#eeeef3;padding:2px 8px;border-radius:4px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--c-ink)}}
    article.entry{{background:var(--c-surface);border:1px solid var(--c-border);border-radius:10px;padding:24px 26px;margin-bottom:18px;box-shadow:var(--shadow-sm)}}
    article.entry header h2{{font-size:24px;font-weight:800;color:var(--c-accent);letter-spacing:-.01em;font-variant-numeric:tabular-nums}}
    article.entry .kickoff{{margin-top:8px;font-size:13px;color:var(--c-ink-muted);font-style:italic}}
    article.entry section{{margin-top:18px}}
    article.entry h3{{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--c-ink-soft);margin-bottom:8px}}
    article.entry ul.list{{list-style:none;padding:0}}
    article.entry ul.list li{{padding:8px 0;border-bottom:1px solid var(--c-border);font-size:14px;line-height:1.6}}
    article.entry ul.list li:last-child{{border-bottom:none}}
    article.entry .muted{{color:var(--c-ink-soft)}}
    article.entry footer.entry-foot{{margin-top:18px;padding-top:14px;border-top:1px solid var(--c-border);font-size:12px;color:var(--c-ink-soft)}}
    footer.foot{{margin-top:40px;padding-top:16px;border-top:1px solid var(--c-border);font-size:12px;color:var(--c-ink-soft);line-height:1.7}}
    footer.foot a{{color:var(--c-ink-muted)}}footer.foot a:hover{{color:var(--c-accent)}}
  </style>
</head>
<body>
<div class="page">
  <header class="site">
    <div>
      <div class="brand">powertracker &middot; weekly</div>
      <div class="tagline">What moved in the AI data-center buildout this week.</div>
    </div>
    <nav>
      <a href="/">map</a>
      <a href="/rankings">rankings</a>
      <a href="/schedule">schedule</a>
      <a href="/sources">sources</a>
    </nav>
  </header>

  <section class="lede">
    <h1>Weekly digest</h1>
    <p>
      Each entry below is the diff between two consecutive data refreshes:
      new campuses added to the registry, and the biggest movers in utility
      residential rates and county home prices. Subscribe by feed reader.
    </p>
    <div class="subscribe">
      <span>Subscribe:</span>
      <a href="{feed_url}"><code>{feed_url}</code></a>
    </div>
  </section>

  {entries}

  <footer class="foot">
    Generated {today} by <code>scripts/build_digest.py</code>. Every entry
    above is reproducible from the cached CSVs in
    <a href="https://github.com/vxguo1/powertracker" target="_blank" rel="noopener">github.com/vxguo1/powertracker</a>.
    See <a href="/sources">all sources</a> for refresh cadences.
  </footer>
</div>
</body>
</html>
"""


def main() -> None:
    entry = build_entry()
    history = load_history()
    history.insert(0, entry)
    history = history[:MAX_HISTORY]
    save_history(history)

    render_weekly_page(history)
    render_rss_feed(history)

    n_new = len(entry["new_campuses"])
    n_rate = len(entry["rate_movers"])
    n_home = len(entry["home_movers"])
    n_tax = len(entry["tax_movers"])
    suffix = " (kickoff)" if entry["kickoff"] else ""
    print(
        f"digest {entry['date']}{suffix}: "
        f"{n_new} new campus, {n_rate} rate movers, "
        f"{n_home} home movers, {n_tax} tax movers"
    )
    print(f"wrote {WEEKLY_DIR / 'index.html'}")
    print(f"wrote {FEED_PATH}")


if __name__ == "__main__":
    main()
