"""EIA Hourly Electric Grid Monitor client.

Docs: https://www.eia.gov/opendata/browser/electricity/rto/region-data
"""

import os
import time
from typing import Iterable

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

EIA_REGION_DATA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
PAGE_SIZE = 5000


def _api_key() -> str:
    key = os.environ.get("EIA_API_KEY")
    if not key:
        raise RuntimeError(
            "EIA_API_KEY not set. Register at https://www.eia.gov/opendata/register.php "
            "and add it to .env"
        )
    return key


def fetch_demand(
    respondent: str,
    start: str,
    end: str,
    types: Iterable[str] = ("D",),
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch hourly grid data for a single balancing authority.

    Args:
        respondent: BA code, e.g. "ERCO", "TVA", "PJM".
        start, end: ISO timestamps with hour, e.g. "2024-01-01T00".
        types: any of D (demand), NG (net generation), TI (total interchange),
               DF (day-ahead demand forecast).
        api_key: defaults to EIA_API_KEY env var.

    Returns:
        DataFrame[period (UTC tz-aware), respondent, type, value (MWh)].
    """
    key = api_key or _api_key()
    rows: list[dict] = []
    offset = 0

    while True:
        params: dict[str, object] = {
            "api_key": key,
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": respondent,
            "start": start,
            "end": end,
            "offset": offset,
            "length": PAGE_SIZE,
        }
        for i, t in enumerate(types):
            params[f"facets[type][{i}]"] = t

        resp = requests.get(EIA_REGION_DATA_URL, params=params, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"EIA API error: {body['error']}")

        batch = body["response"].get("data", [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.2)

    if not rows:
        return pd.DataFrame(columns=["period", "respondent", "type", "value"])

    df = pd.DataFrame(rows)
    df["period"] = pd.to_datetime(df["period"], utc=True, format="%Y-%m-%dT%H")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return (
        df[["period", "respondent", "type", "value"]]
        .sort_values(["respondent", "type", "period"])
        .reset_index(drop=True)
    )
