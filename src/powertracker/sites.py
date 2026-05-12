"""Load the data center site list."""

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SITES_CSV = REPO_ROOT / "data" / "sites" / "data_centers.csv"


def load_sites(path: Path | None = None) -> pd.DataFrame:
    """Load the data center site CSV as a DataFrame."""
    return pd.read_csv(path or DEFAULT_SITES_CSV)


def bas_in_use(path: Path | None = None) -> list[str]:
    """Return the unique balancing authority codes referenced by the site list."""
    return sorted(load_sites(path)["ba_code"].dropna().unique().tolist())
