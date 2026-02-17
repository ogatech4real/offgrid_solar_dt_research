# src/offgrid_dt/data/ukdale_loader.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from offgrid_dt.io.schema import UKDALEConfig


def _read_labels(labels_path: Path) -> Dict[int, str]:
    """
    UK-DALE labels.dat format typically: "<channel_id> <label>"
    Example: "1 mains", "2 mains", "3 kettle"
    """
    labels: Dict[int, str] = {}
    if not labels_path.exists():
        return labels

    for raw in labels_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
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
    UK-DALE channel file format: "<epoch_seconds> <power_watts>" (space-separated)
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
    idx = pd.to_datetime(df["ts"], unit="s", utc=True)
    s = pd.Series(df["power_w"].astype(float).values, index=idx, name=path.stem)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def _resolve_house_dir(cfg: UKDALEConfig) -> Path:
    root = Path(cfg.dataset_root).expanduser().resolve()
    house_id = str(cfg.house_id).strip()
    house_dir = root / f"house_{house_id}"
    if not house_dir.exists():
        raise FileNotFoundError(f"UK-DALE house folder not found: {house_dir}")
    return house_dir


def load_ukdale_aggregate_kw(cfg: UKDALEConfig) -> pd.Series:
    """
    Load measured aggregate demand (kW) from UK-DALE for one house,
    resampled to cfg.resample_minutes.

    Output index: UTC tz-aware timestamps.
    """
    house_dir = _resolve_house_dir(cfg)
    labels = _read_labels(house_dir / "labels.dat")

    # Identify mains channels (commonly 1 & 2). UK-DALE often has two "mains".
    mains_channels = [ch for ch, lab in labels.items() if lab == "mains"]

    # Fallback logic if labels missing or channel name differs
    if not mains_channels:
        fallback = []
        if (house_dir / "channel_1.dat").exists():
            fallback.append(1)
        if (house_dir / "channel_2.dat").exists():
            fallback.append(2)
        mains_channels = fallback if fallback else [1]

    mains_series: List[pd.Series] = []
    for ch in mains_channels:
        mains_series.append(_read_channel_dat(house_dir / f"channel_{ch}.dat"))

    agg_w = pd.concat(mains_series, axis=1).sum(axis=1)
    agg_w.name = "mains_w"

    # Slice window (treat cfg.start_date/end_date as UTC dates unless user provided time)
    start_ts = pd.to_datetime(cfg.start_date, utc=True)
    end_ts = pd.to_datetime(cfg.end_date, utc=True)

    # Include full end day if user provided a date-only string
    # (pragmatic: end at 23:59:59 of that day)
    if len(cfg.end_date.strip()) <= 10:  # "YYYY-MM-DD"
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    agg_w = agg_w.loc[start_ts:end_ts]

    # Resample to fixed grid
    rule = f"{int(cfg.resample_minutes)}min"
    agg_w = agg_w.resample(rule).mean()

    # Fill short gaps (<= 1 hour for 15-min) to avoid dropping days due to minor missingness
    limit_steps = max(1, int(round(60 / cfg.resample_minutes)))
    agg_w = agg_w.interpolate(limit=limit_steps, limit_direction="both")

    return (agg_w / 1000.0).rename("mains_kw")


def split_into_days(series_kw: pd.Series, tz: str = "UTC") -> List[pd.Series]:
    """
    Split a UTC series into per-day slices, returning each day as tz-aligned series.
    """
    if series_kw.empty:
        return []
    s = series_kw.dropna().copy()
    if s.empty:
        return []

    # Align to a reporting timezone if desired (Europe/London typical)
    if tz and tz.upper() != "UTC":
        s = s.tz_convert(tz)

    out: List[pd.Series] = []
    for _, g in s.groupby(s.index.date):
        out.append(g.sort_index())
    return out


def align_day_to_full_steps(
    day_series_kw: pd.Series,
    timestep_minutes: int,
    tz: str,
) -> Tuple[pd.DatetimeIndex, List[float]]:
    """
    Create a full-day time grid at timestep_minutes and align measured data onto it.
    Conservative fill: forward-fill then back-fill.
    """
    if day_series_kw.empty:
        raise ValueError("Empty day_series_kw")

    # day start in local tz, then convert to UTC for simulation indexing consistency
    day_local_start = pd.Timestamp(day_series_kw.index[0].date(), tz=tz)
    steps_per_day = int(round(24 * 60 / timestep_minutes))
    full_local = pd.date_range(day_local_start, periods=steps_per_day, freq=f"{timestep_minutes}min", tz=tz)

    aligned = day_series_kw.reindex(full_local).ffill().bfill()
    return full_local, [float(v) for v in aligned.values]

# ------------------------------------------------------------
# Wrapper expected by simulator (research mode integration)
# ------------------------------------------------------------

from datetime import datetime
from typing import List, Tuple

def load_ukdale_day_profile(
    ukdale_cfg: UKDALEConfig,
    day_start_utc: datetime,
    steps_per_day: int,
    timestep_minutes: int,
) -> Tuple[List[float], List[float]]:
    """
    Adapter for simulator research mode.

    Returns:
        total_kw: measured whole-home demand aligned to fixed 24h grid
        crit_kw:  fixed critical baseline split per step

    Notes:
        - Uses UKDALEConfig.start_date/end_date window.
        - Day selection is done in reporting timezone (default Europe/London).
        - Simulator operates in UTC; demand slicing is done in local tz
          then aligned to fixed timestep grid.
    """

    # Load full validation window once
    series_kw = load_ukdale_aggregate_kw(ukdale_cfg)

    if series_kw.empty:
        raise ValueError("UK-DALE aggregate series is empty after slicing window.")

    # Convert to reporting timezone for day slicing
    tz = ukdale_cfg.timezone or "Europe/London"
    s_local = series_kw.tz_convert(tz)

    # Determine target local date corresponding to simulator UTC day
    target_local_date = (
        pd.Timestamp(day_start_utc, tz="UTC")
        .tz_convert(tz)
        .date()
    )

    # Extract matching day
    day_series = s_local[s_local.index.date == target_local_date]

    if day_series.empty:
        raise ValueError(
            f"No UK-DALE data found for local day {target_local_date}"
        )

    # Align to full fixed grid
    _, total_kw = align_day_to_full_steps(
        day_series_kw=day_series,
        timestep_minutes=timestep_minutes,
        tz=tz,
    )

    if len(total_kw) != steps_per_day:
        # Defensive guard (should not happen with align_day_to_full_steps)
        total_kw = total_kw[:steps_per_day]
        if len(total_kw) < steps_per_day:
            total_kw += [0.0] * (steps_per_day - len(total_kw))

    # Split into critical + discretionary using fixed baseline
    crit_base = float(ukdale_cfg.critical_baseline_kw)
    crit_kw = [min(v, crit_base) for v in total_kw]

    return total_kw, crit_kw
