"""CLI wrapper around `powertracker.mapbuild` that writes the layered
folium map to `data/maps/data_centers.html`.

By default this recomputes YoY aggregates from raw EIA/BEA data. Pass
`--cache` to read pre-computed aggregates from `data/cache/`, which is
what the hosted Streamlit app uses.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from powertracker.mapbuild import build_folium_map, load_data  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "maps"
OUT_FILE = OUT_DIR / "data_centers.html"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cache",
        action="store_true",
        help="read pre-computed aggregates from data/cache/ (default: recompute from raw)",
    )
    args = p.parse_args()

    data = load_data(use_cache=args.cache)
    m, summary = build_folium_map(data)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    m.save(str(OUT_FILE))
    print(
        f"wrote {OUT_FILE} "
        f"({summary['n_sites']} sites, {len(summary['zones'])} clusters, "
        f"{sum(1 for z in summary['zones'] if not (z['tier']=='D' and z['sites']<3))} zones drawn, "
        f"{summary['n_ba']} BAs colored, {summary['n_util']} utilities colored, "
        f"{summary['n_gdp']} counties colored)"
    )

    summary["zones"].sort(key=lambda c: (-c["total_mw"], -c["sites"]))
    print("\ntop hot zones:")
    print(f"  {'tier':<5}{'label':<28}{'sites':>6}{'  stated_mw':>14}")
    for c in summary["zones"][:15]:
        print(f"  {c['tier']:<5}{c['label']:<28}{c['sites']:>6}{c['total_mw']:>14,}")

    if not data.ba_yoy.empty:
        print("\nBA YoY demand growth (trailing 12mo vs prior 12mo):")
        print(f"  {'ba':<6}{'growth':>8}  {'trailing_mw':>12}  {'prior_mw':>12}")
        for _, r in data.ba_yoy.sort_values("growth_pct", ascending=False).iterrows():
            print(f"  {r.ba:<6}{r.growth_pct:>+7.2f}%  {r.trailing_mw:>12,.0f}  {r.prior_mw:>12,.0f}")


if __name__ == "__main__":
    main()
