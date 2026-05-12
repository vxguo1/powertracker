"""Fetch hourly demand from EIA for one or more balancing authorities.

Examples:
    python scripts/fetch_demand.py --ba TVA --start 2024-01-01 --end 2024-12-31
    python scripts/fetch_demand.py --ba TVA,ERCO,PJM --start 2024-06-01 --end 2024-06-30
    python scripts/fetch_demand.py --from-sites --start 2024-01-01 --end 2024-12-31
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from powertracker.eia import fetch_demand
from powertracker.sites import bas_in_use

OUT_DIR = REPO_ROOT / "data" / "raw"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ba", help="BA code(s), comma-separated (e.g. TVA,ERCO,PJM)")
    group.add_argument(
        "--from-sites",
        action="store_true",
        help="Fetch every BA referenced in data/sites/data_centers.csv",
    )
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--type", default="D", help="D, NG, TI, or DF (default D)")
    args = parser.parse_args()

    bas = bas_in_use() if args.from_sites else [b.strip() for b in args.ba.split(",")]
    start = f"{args.start}T00"
    end = f"{args.end}T23"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for ba in bas:
        print(f"[{ba}] fetching {args.type} {start} -> {end}...", flush=True)
        df = fetch_demand(ba, start, end, types=(args.type,))
        out = OUT_DIR / f"{ba}_{args.type}_{args.start}_{args.end}.csv"
        df.to_csv(out, index=False)
        print(f"[{ba}] {len(df)} rows -> {out}", flush=True)


if __name__ == "__main__":
    main()
