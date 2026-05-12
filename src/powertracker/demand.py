"""Load and aggregate cached EIA hourly demand pulls.

Raw CSVs land in `data/raw/<BA>_D_<start>_<end>.csv` from
`scripts/fetch_demand.py`. This module reads them back and computes
period aggregates.
"""

from pathlib import Path
import re

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"

_FNAME_RE = re.compile(r"^(?P<ba>[A-Z0-9]+)_(?P<type>[A-Z]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$")


def list_cached_pulls(raw_dir: Path | None = None) -> pd.DataFrame:
    """Inventory of cached pulls: one row per BA/type/range CSV on disk."""
    raw = raw_dir or RAW_DIR
    rows = []
    for f in raw.glob("*.csv"):
        m = _FNAME_RE.match(f.name)
        if not m:
            continue
        rows.append({"ba": m["ba"], "type": m["type"], "start": m["start"], "end": m["end"], "path": f})
    return pd.DataFrame(rows)


def load_ba_demand(ba: str, raw_dir: Path | None = None) -> pd.DataFrame:
    """Load all cached demand pulls for a single BA and concatenate them,
    deduping on `period`. Returns columns [period, value] sorted by period.
    The widest cached range wins; if multiple pulls cover the same period,
    the value from the most recent pull (by end date) is kept.
    """
    inventory = list_cached_pulls(raw_dir)
    if inventory.empty:
        return pd.DataFrame(columns=["period", "value"])
    matches = inventory[(inventory["ba"] == ba) & (inventory["type"] == "D")]
    matches = matches.sort_values("end")
    if matches.empty:
        return pd.DataFrame(columns=["period", "value"])

    frames = []
    for _, row in matches.iterrows():
        df = pd.read_csv(row["path"], parse_dates=["period"])
        frames.append(df[["period", "value"]])
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset="period", keep="last").sort_values("period").reset_index(drop=True)
    return out


def yoy_growth(
    end: pd.Timestamp | str,
    window_days: int = 365,
    min_coverage: float = 0.8,
    raw_dir: Path | None = None,
) -> pd.DataFrame:
    """For every BA with cached demand, compute mean load over the trailing
    `window_days` ending at `end` vs the prior matched window, and the
    percent change.

    Returns DataFrame[ba, trailing_mw, prior_mw, growth_pct, trailing_hours,
    prior_hours]. BAs without enough data in either window (<min_coverage of
    expected hours) are excluded.
    """
    end_ts = pd.Timestamp(end)
    if end_ts.tz is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")
    trailing_start = end_ts - pd.Timedelta(days=window_days)
    prior_end = trailing_start
    prior_start = prior_end - pd.Timedelta(days=window_days)
    expected_hours = window_days * 24

    inventory = list_cached_pulls(raw_dir)
    bas = sorted(inventory[inventory["type"] == "D"]["ba"].unique()) if not inventory.empty else []

    rows = []
    for ba in bas:
        df = load_ba_demand(ba, raw_dir)
        if df.empty:
            continue
        trailing = df[(df["period"] >= trailing_start) & (df["period"] < end_ts)]
        prior = df[(df["period"] >= prior_start) & (df["period"] < prior_end)]
        if (
            len(trailing) < expected_hours * min_coverage
            or len(prior) < expected_hours * min_coverage
        ):
            continue
        t_mean = float(trailing["value"].mean())
        p_mean = float(prior["value"].mean())
        if p_mean <= 0:
            continue
        rows.append({
            "ba": ba,
            "trailing_mw": t_mean,
            "prior_mw": p_mean,
            "growth_pct": (t_mean / p_mean - 1) * 100,
            "trailing_hours": len(trailing),
            "prior_hours": len(prior),
        })
    return pd.DataFrame(rows).sort_values("growth_pct", ascending=False).reset_index(drop=True)
