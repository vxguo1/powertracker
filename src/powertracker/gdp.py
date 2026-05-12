"""County GDP and per-capita GDP from BEA Regional Economic Accounts.

Sources cached under `data/raw/bea/`:
  - CAGDP1: county GDP (real chained 2017 dollars, nominal current dollars)
  - CAINC1: county personal income + population

Both are downloadable as a single all-states CSV inside each ZIP. The
GeoFIPS column has surrounding double quotes that we strip on load.
"""

from pathlib import Path
import zipfile

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BEA_DIR = REPO_ROOT / "data" / "raw" / "bea"

# Suppressed/missing markers used in BEA CSVs.
_NA_MARKERS = {"(NA)", "(D)", "(L)", "(NM)", "..."}


def _clean_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace(list(_NA_MARKERS), pd.NA), errors="coerce")


def _load(table: str, csv_name: str) -> pd.DataFrame:
    z = zipfile.ZipFile(BEA_DIR / f"{table}.zip")
    with z.open(csv_name) as f:
        df = pd.read_csv(f, encoding="latin-1", low_memory=False)
    df["fips"] = df["GeoFIPS"].astype(str).str.strip().str.strip('"')
    return df


def county_gdp(year: int = 2024, dollars: str = "current") -> pd.DataFrame:
    """County GDP for a given year.

    Args:
        year: 4-digit year present in the CAGDP1 file.
        dollars: "current" (nominal $, LineCode 3) or "real" (chained 2017 $, LineCode 1).

    Returns:
        DataFrame[fips, geoname, gdp_kdollars]
    """
    if dollars not in ("current", "real"):
        raise ValueError("dollars must be 'current' or 'real'")
    df = _load("CAGDP1", "CAGDP1__ALL_AREAS_2001_2024.csv")
    line = 3 if dollars == "current" else 1
    sub = df[df["LineCode"] == line].copy()
    sub["gdp_kdollars"] = _clean_numeric(sub[str(year)])
    # Exclude non-county aggregates (state totals like "01000", US "00000",
    # metro divisions, regions). County FIPS is 5 digits with non-zero last 3.
    sub = sub[sub["fips"].str.len() == 5]
    sub = sub[~sub["fips"].str.endswith("000")]
    return sub[["fips", "GeoName", "gdp_kdollars"]].rename(columns={"GeoName": "geoname"}).reset_index(drop=True)


def county_population(year: int = 2024) -> pd.DataFrame:
    df = _load("CAINC1", "CAINC1__ALL_AREAS_1969_2024.csv")
    sub = df[df["LineCode"] == 2].copy()
    sub["population"] = _clean_numeric(sub[str(year)])
    sub = sub[sub["fips"].str.len() == 5]
    sub = sub[~sub["fips"].str.endswith("000")]
    return sub[["fips", "GeoName", "population"]].rename(columns={"GeoName": "geoname"}).reset_index(drop=True)


def per_capita_gdp(year: int = 2024, dollars: str = "current") -> pd.DataFrame:
    """Per-capita GDP (gdp_kdollars * 1000 / population).

    Returns:
        DataFrame[fips, geoname, gdp_kdollars, population, gdp_per_capita]
    """
    gdp = county_gdp(year, dollars=dollars)
    pop = county_population(year)
    out = gdp.merge(pop[["fips", "population"]], on="fips", how="inner")
    out["gdp_per_capita"] = out["gdp_kdollars"] * 1000.0 / out["population"]
    return out.dropna(subset=["gdp_per_capita"]).reset_index(drop=True)


def yoy_per_capita_gdp(prior_year: int = 2023, recent_year: int = 2024) -> pd.DataFrame:
    """YoY % change in per-capita real GDP (chained 2017 dollars).

    Inflation-stripped so the % is comparable to the demand and rate YoY
    layers. Population denominator is per-year (uses each year's BEA
    population estimate).

    Returns:
        DataFrame[fips, geoname, gdp_per_capita_<prior>, gdp_per_capita_<recent>,
                  growth_pct, population_<recent>]
    """
    p = per_capita_gdp(prior_year, dollars="real")
    r = per_capita_gdp(recent_year, dollars="real")
    merged = p.merge(
        r[["fips", "gdp_per_capita", "population"]],
        on="fips",
        suffixes=(f"_{prior_year}", f"_{recent_year}"),
    )
    merged["growth_pct"] = (
        merged[f"gdp_per_capita_{recent_year}"] / merged[f"gdp_per_capita_{prior_year}"] - 1
    ) * 100
    return merged[[
        "fips",
        "geoname",
        f"gdp_per_capita_{prior_year}",
        f"gdp_per_capita_{recent_year}",
        "growth_pct",
        f"population_{recent_year}",
    ]].dropna(subset=["growth_pct"]).reset_index(drop=True)
