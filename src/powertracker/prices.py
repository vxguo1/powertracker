"""Load and aggregate utility-level retail electricity rates from EIA-861.

EIA-861's `Sales_Ult_Cust_<year>.xlsx` (sheet "States") is the raw form data
the EIA OpenData API summarises to state level. We parse it directly so we
can keep utility-level granularity.

Each utility may appear in multiple rows (one per state served, one per
"Part" segment — A=bundled, B/C/D=unbundled). We sum revenue and sales
within (utility_id, state) and derive residential price = revenue / sales.
"""

from pathlib import Path
import zipfile

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EIA861_DIR = REPO_ROOT / "data" / "raw" / "eia861"

_HEADER_ROW = 2  # Row index in the raw sheet that holds true column names.


def _read_sales_ult_cust(year: int) -> pd.DataFrame:
    """Parse `Sales_Ult_Cust_<year>.xlsx` from the cached EIA-861 zip."""
    zpath = EIA861_DIR / f"f861{year}.zip"
    if not zpath.exists():
        raise FileNotFoundError(f"EIA-861 zip not cached for {year}: {zpath}")
    with zipfile.ZipFile(zpath) as z:
        with z.open(f"Sales_Ult_Cust_{year}.xlsx") as f:
            raw = pd.read_excel(f, sheet_name="States", header=None)

    # The sheet has three header rows:
    #   row 0: sector group (RESIDENTIAL / COMMERCIAL / ...) for cols 9-23
    #          and "Utility Characteristics" for the leading columns
    #   row 1: field name (Revenues / Sales / Customers) for cols 9-23
    #   row 2: leaf header (column name for cols 0-8, unit for cols 9-23)
    # We use row 2 for the first 9 cols and row 0 + row 1 for the financials.
    group = raw.iloc[0].ffill()
    field = raw.iloc[1]
    header = raw.iloc[_HEADER_ROW]
    cols = []
    for g, fld, h in zip(group, field, header):
        g_s = "" if pd.isna(g) else str(g).strip()
        is_characteristic = g_s in ("", "Utility Characteristics", "nan")
        if is_characteristic:
            cols.append(str(h).strip())
        else:
            cols.append(f"{g_s}_{str(fld).strip()}")
    df = raw.iloc[_HEADER_ROW + 1:].copy()
    df.columns = cols
    df = df.reset_index(drop=True)

    # Coerce numerics. EIA uses "." as a missing-value sentinel.
    for c in df.columns:
        if c.endswith(("_Revenues", "_Sales", "_Customers")):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Utility Number"] = pd.to_numeric(df["Utility Number"], errors="coerce").astype("Int64")
    df["Data Year"] = pd.to_numeric(df["Data Year"], errors="coerce").astype("Int64")
    return df


def residential_rates_by_utility(year: int) -> pd.DataFrame:
    """One row per (utility_id, state) with residential revenue, sales, and
    derived price in cents/kWh. Utilities with zero or missing residential
    sales are excluded.
    """
    df = _read_sales_ult_cust(year)
    grouped = (
        df.groupby(["Utility Number", "Utility Name", "State", "Ownership"], dropna=False)
        .agg(
            revenue_kdollars=("RESIDENTIAL_Revenues", "sum"),
            sales_mwh=("RESIDENTIAL_Sales", "sum"),
            customers=("RESIDENTIAL_Customers", "sum"),
        )
        .reset_index()
        .rename(columns={
            "Utility Number": "utility_id",
            "Utility Name": "utility_name",
            "State": "state",
            "Ownership": "ownership",
        })
    )
    grouped = grouped[grouped["sales_mwh"] > 0].copy()
    # cents/kWh = (revenue in $1000s) / (sales in MWh) * 100
    grouped["price_cents_per_kwh"] = (
        grouped["revenue_kdollars"] / grouped["sales_mwh"] * 100
    )
    grouped["year"] = year
    return grouped.reset_index(drop=True)


def yoy_residential(prior_year: int = 2023, recent_year: int = 2024) -> pd.DataFrame:
    """For every (utility_id, state) present in both years, return the YoY
    percent change in residential cents/kWh.
    """
    p = residential_rates_by_utility(prior_year)
    r = residential_rates_by_utility(recent_year)
    merged = p.merge(
        r,
        on=["utility_id", "state"],
        suffixes=(f"_{prior_year}", f"_{recent_year}"),
        how="inner",
    )
    merged["price_change_pct"] = (
        merged[f"price_cents_per_kwh_{recent_year}"]
        / merged[f"price_cents_per_kwh_{prior_year}"]
        - 1
    ) * 100
    return merged[[
        "utility_id",
        f"utility_name_{recent_year}",
        "state",
        f"ownership_{recent_year}",
        f"price_cents_per_kwh_{prior_year}",
        f"price_cents_per_kwh_{recent_year}",
        "price_change_pct",
        f"customers_{recent_year}",
        f"sales_mwh_{recent_year}",
    ]].rename(columns={
        f"utility_name_{recent_year}": "utility_name",
        f"ownership_{recent_year}": "ownership",
        f"price_cents_per_kwh_{prior_year}": f"price_{prior_year}",
        f"price_cents_per_kwh_{recent_year}": f"price_{recent_year}",
        f"customers_{recent_year}": "customers",
        f"sales_mwh_{recent_year}": "sales_mwh",
    })
