"""Pre-compute the YoY aggregates the Streamlit app needs.

The app loads these tiny CSVs instead of recomputing from raw EIA-930 hourly
demand (~30 MB), EIA-861 ZIPs (~9 MB), or BEA ZIPs (~5 MB). Lets the public
app start fast and avoids needing an EIA API key at runtime.

Each component (demand / prices / gdp) is independent. A component skips with
a warning if its raw data isn't cached. This lets workflows that only refresh
one source run this script without needing the other sources' raw data
present. The dedicated fetchers `fetch_bea_gdp.py` and `fetch_eia861.py` also
write the prices/gdp caches directly and are the recommended path for those
two layers.

Run after refreshing any of the raw data, then commit the resulting CSVs
under `data/cache/`.
"""

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from powertracker.demand import yoy_growth
from powertracker.gdp import yoy_per_capita_gdp
from powertracker.prices import yoy_residential

OUT_DIR = REPO_ROOT / "data" / "cache"


def _try(label: str, fn) -> None:
    try:
        fn()
    except FileNotFoundError as e:
        print(f"{label}: skipped (raw data not cached: {e})")
    except Exception as e:
        print(f"{label}: skipped ({type(e).__name__}: {e})")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def _demand():
        ba = yoy_growth(pd.Timestamp("today").normalize())
        ba_path = OUT_DIR / "ba_demand_yoy.csv"
        ba.to_csv(ba_path, index=False)
        print(f"ba_demand_yoy: {len(ba)} rows -> {ba_path}")

    def _prices():
        rates = yoy_residential(2024)
        rates_path = OUT_DIR / "utility_rate_yoy.csv"
        rates.to_csv(rates_path, index=False)
        print(f"utility_rate_yoy: {len(rates)} rows -> {rates_path}")

    def _gdp():
        gdp = yoy_per_capita_gdp(2024)
        gdp_path = OUT_DIR / "county_gdp_yoy.csv"
        gdp.to_csv(gdp_path, index=False)
        print(f"county_gdp_yoy: {len(gdp)} rows -> {gdp_path}")

    _try("ba_demand_yoy", _demand)
    _try("utility_rate_yoy", _prices)
    _try("county_gdp_yoy", _gdp)


if __name__ == "__main__":
    main()
