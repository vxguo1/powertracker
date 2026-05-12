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
    baseline_years: int = 3,
    raw_dir: Path | None = None,
) -> pd.DataFrame:
    """For every BA with cached demand, compute mean load over the trailing
    `window_days` ending at `end` vs the mean of the `baseline_years` prior
    trailing-`window_days` windows (analogous periods at t-1y, t-2y, t-3y),
    and the percent change.

    Returns DataFrame[ba, trailing_mw, baseline_mw, growth_pct,
    trailing_hours, baseline_hours]. BAs lacking sufficient coverage
    (<min_coverage of expected hours) in the current OR any of the
    baseline windows are excluded.
    """
    end_ts = pd.Timestamp(end)
    if end_ts.tz is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")
    trailing_start = end_ts - pd.Timedelta(days=window_days)
    expected_hours = window_days * 24
    # Baseline windows: each is `window_days` long, lagged by one extra
    # `window_days` per year. Year-1 baseline ends where the current window
    # starts; year-2 ends one window earlier; year-3 ends two earlier.
    baseline_windows = []
    for k in range(1, baseline_years + 1):
        b_end = end_ts - pd.Timedelta(days=window_days * k)
        b_start = b_end - pd.Timedelta(days=window_days)
        baseline_windows.append((b_start, b_end))

    inventory = list_cached_pulls(raw_dir)
    bas = sorted(inventory[inventory["type"] == "D"]["ba"].unique()) if not inventory.empty else []

    rows = []
    for ba in bas:
        df = load_ba_demand(ba, raw_dir)
        if df.empty:
            continue
        trailing = df[(df["period"] >= trailing_start) & (df["period"] < end_ts)]
        if len(trailing) < expected_hours * min_coverage:
            continue
        baseline_means: list[float] = []
        baseline_hours = 0
        skip = False
        for b_start, b_end in baseline_windows:
            seg = df[(df["period"] >= b_start) & (df["period"] < b_end)]
            if len(seg) < expected_hours * min_coverage:
                skip = True
                break
            baseline_means.append(float(seg["value"].mean()))
            baseline_hours += len(seg)
        if skip:
            continue
        t_mean = float(trailing["value"].mean())
        b_mean = sum(baseline_means) / len(baseline_means)
        if b_mean <= 0:
            continue
        rows.append({
            "ba": ba,
            "trailing_mw": t_mean,
            "baseline_mw": b_mean,
            "growth_pct": (t_mean / b_mean - 1) * 100,
            "trailing_hours": len(trailing),
            "baseline_hours": baseline_hours,
            "baseline_years": baseline_years,
        })
    return pd.DataFrame(rows).sort_values("growth_pct", ascending=False).reset_index(drop=True)
