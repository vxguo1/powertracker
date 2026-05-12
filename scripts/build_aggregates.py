"""Pre-compute the YoY aggregates the Streamlit app needs.

The app loads these tiny CSVs instead of recomputing from raw EIA-930 hourly
demand (~30 MB), EIA-861 ZIPs (~9 MB), or BEA ZIPs (~5 MB). Lets the public
app start fast and avoids needing an EIA API key at runtime.

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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # BA hourly demand: trailing 12mo vs prior 12mo as of today.
    ba = yoy_growth(pd.Timestamp("today").normalize())
    ba_path = OUT_DIR / "ba_demand_yoy.csv"
    ba.to_csv(ba_path, index=False)
    print(f"ba_demand_yoy: {len(ba)} rows -> {ba_path}")

    # Utility residential rates: 2023 vs 2024 from EIA-861.
    rates = yoy_residential(2023, 2024)
    rates_path = OUT_DIR / "utility_rate_yoy.csv"
    rates.to_csv(rates_path, index=False)
    print(f"utility_rate_yoy: {len(rates)} rows -> {rates_path}")

    # County per-capita real GDP: 2023 vs 2024 from BEA.
    gdp = yoy_per_capita_gdp(2023, 2024)
    gdp_path = OUT_DIR / "county_gdp_yoy.csv"
    gdp.to_csv(gdp_path, index=False)
    print(f"county_gdp_yoy: {len(gdp)} rows -> {gdp_path}")


if __name__ == "__main__":
    main()
