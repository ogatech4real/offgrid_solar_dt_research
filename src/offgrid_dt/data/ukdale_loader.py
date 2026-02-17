# src/offgrid_dt/data/ukdale_loader.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class UKDALELoadSpec:
    """
    Minimal spec for pulling aggregate (mains) demand from UK-DALE.

    Expected UK-DALE structure:
      <root>/
        house_1/
          labels.dat
          channel_1.dat
          channel_2.dat
          ...
    labels.dat lines typically: "<channel_id> <label>"
    Aggregate mains are usually label "mains" (often two channels, summed).
    """
    dataset_root: Path
    house_id: int
    start: Optional[str] = None  # ISO date/time string, e.g. "2013-01-01"
    end: Optional[str] = None    # ISO date/time string
    target_timestep_minutes: int = 15
    timezone: str = "UTC"        # UK-DALE timestamps are epoch seconds (UTC-like)


def _read_labels(labels_path: Path) -> Dict[int, str]:
    labels: Dict[int, str] = {}
    if not labels_path.exists():
        return labels
    for raw in labels_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        # "1 mains" / "2 kettle" etc.
        parts = raw.split()
        if len(parts) < 2:
            continue
        try:
            ch = int(parts[0])
        except ValueError:
            continue
        label = " ".join(parts[1:]).strip().lower()
        labels[ch] = label
    return labels


def _read_channel_dat(path: Path) -> pd.Series:
    """
    UK-DALE channel files are space-separated: "<epoch_seconds> <power_watts>"
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing channel file: {path}")
    df = pd.read_csv(
        path,
        sep=r"\s+",
        header=None,
        names=["ts", "power_w"],
        engine="python",
    )
    # epoch seconds
    idx = pd.to_datetime(df["ts"], unit="s", utc=True)
    s = pd.Series(df["power_w"].astype(float).values, index=idx, name=path.stem)
    # remove duplicates, keep last
    s = s[~s.index.duplicated(keep="last")]
    return s.sort_index()


def load_ukdale_aggregate_kw(spec: UKDALELoadSpec) -> pd.Series:
    """
    Returns a timezone-aware (UTC) pandas Series of aggregate demand in kW,
    resampled to target_timestep_minutes using mean.
    """
    house_dir = spec.dataset_root / f"house_{spec.house_id}"
    if not house_dir.exists():
        raise FileNotFoundError(f"House folder not found: {house_dir}")

    labels = _read_labels(house_dir / "labels.dat")

    # pick mains channels (often 1 and 2); fallback to channel_1 if labels missing
    mains_channels = [ch for ch, lab in labels.items() if lab == "mains"]
    if not mains_channels:
        # pragmatic fallback: try channels 1 and 2 if present, else channel_1 only
        candidates = []
        if (house_dir / "channel_1.dat").exists():
            candidates.append(1)
        if (house_dir / "channel_2.dat").exists():
            candidates.append(2)
        mains_channels = candidates if candidates else [1]

    mains_series: List[pd.Series] = []
    for ch in mains_channels:
        s = _read_channel_dat(house_dir / f"channel_{ch}.dat")
        mains_series.append(s)

    agg_w = pd.concat(mains_series, axis=1).sum(axis=1)
    agg_w.name = "mains_w"

    # optional slicing
    if spec.start:
        agg_w = agg_w.loc[pd.to_datetime(spec.start, utc=True) :]
    if spec.end:
        agg_w = agg_w.loc[: pd.to_datetime(spec.end, utc=True)]

    # resample to fixed step; UK-DALE is irregular
    rule = f"{int(spec.target_timestep_minutes)}min"
    agg_w = agg_w.resample(rule).mean()

    # fill small gaps; keep large gaps as NaN and later handle upstream if needed
    agg_w = agg_w.interpolate(limit=4, limit_direction="both")  # up to 1h at 15-min
    agg_kw = (agg_w / 1000.0).rename("mains_kw")
    return agg_kw


def slice_series_to_days(series_kw: pd.Series) -> List[pd.Series]:
    """
    Splits a UTC-indexed series into a list of per-day series (00:00-24:00 UTC).
    Each item retains the original frequency (e.g. 15min) and index timestamps.
    """
    if series_kw.empty:
        return []
    s = series_kw.dropna()
    if s.empty:
        return []
    days: List[pd.Series] = []
    for date, grp in s.groupby(s.index.date):
        grp = grp.sort_index()
        days.append(grp)
    return days


def ensure_full_day_steps(
    day_series_kw: pd.Series,
    timestep_minutes: int,
    day_start_utc: Optional[pd.Timestamp] = None,
) -> Tuple[pd.DatetimeIndex, List[float]]:
    """
    Builds a full-day index at the given timestep and aligns measured data onto it.
    Missing steps are forward-filled then back-filled (conservative for demand).
    """
    if day_series_kw.empty:
        raise ValueError("Empty day_series_kw")

    ts0 = day_start_utc or pd.Timestamp(day_series_kw.index[0].date(), tz="UTC")
    steps_per_day = int(round(24 * 60 / timestep_minutes))
    full_index = pd.date_range(ts0, periods=steps_per_day, freq=f"{timestep_minutes}min", tz="UTC")

    aligned = day_series_kw.reindex(full_index)
    # conservative fill: if missing, assume last known demand (ffill), then bfill start
    aligned = aligned.ffill().bfill()
    return full_index, [float(v) for v in aligned.values]
