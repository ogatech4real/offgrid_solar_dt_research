# src/offgrid_dt/validation/metrics_summary.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class DailyMetrics:
    date: str
    clsr: float
    cid_minutes: float
    ssr: float
    solar_utilisation: float
    battery_throughput_kwh: Optional[float] = None


def _infer_dt_minutes(df: pd.DataFrame) -> int:
    # prefer explicit config column if present; else infer from timestamps
    if "timestep_minutes" in df.columns:
        try:
            return int(df["timestep_minutes"].iloc[0])
        except Exception:
            pass
    if "timestamp" not in df.columns or len(df) < 2:
        return 15
    ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").dropna()
    if len(ts) < 2:
        return 15
    delta = (ts.iloc[1] - ts.iloc[0]).total_seconds() / 60.0
    return int(round(delta)) if delta > 0 else 15


def _get_col(df: pd.DataFrame, candidates: Tuple[str, ...]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def compute_daily_metrics_from_state_csv(state_csv: Path) -> pd.DataFrame:
    """
    Expects the simulator state CSV (RunLogger output).
    Computes daily CLSR, CID, SSR, Solar Utilisation (SU), and Battery Throughput when available.

    Robust to slightly different column names.
    """
    df = pd.read_csv(state_csv)
    if "timestamp" not in df.columns:
        raise ValueError(f"state_csv missing 'timestamp' column: {state_csv}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df["date"] = df["timestamp"].dt.date.astype(str)

    dt_min = _infer_dt_minutes(df)
    dt_h = dt_min / 60.0

    col_crit_req = _get_col(df, ("crit_requested_kw", "critical_requested_kw"))
    col_crit_srv = _get_col(df, ("crit_served_kw", "critical_served_kw"))
    col_load_req = _get_col(df, ("load_requested_kw", "total_requested_kw"))
    col_load_srv = _get_col(df, ("load_served_kw", "total_served_kw"))
    col_pv = _get_col(df, ("pv_now_kw", "pv_kw"))
    col_curtailed = _get_col(df, ("curtailed_solar_kw", "curtailed_kw"))
    # battery throughput might be logged as a running KPI or explicit column
    col_bt = _get_col(df, ("battery_throughput_kwh", "throughput_kwh"))

    required = [col_crit_req, col_crit_srv, col_load_req, col_load_srv, col_pv]
    if any(c is None for c in required):
        raise ValueError(
            f"state_csv missing required columns. "
            f"Need crit_req/crit_serv/load_req/load_serv/pv. Found columns: {list(df.columns)}"
        )

    out_rows = []
    for d, g in df.groupby("date"):
        crit_req_e = (g[col_crit_req].astype(float).clip(lower=0.0) * dt_h).sum()
        crit_srv_e = (g[col_crit_srv].astype(float).clip(lower=0.0) * dt_h).sum()

        # CLSR
        clsr = float(crit_srv_e / crit_req_e) if crit_req_e > 1e-9 else 1.0

        # CID: time steps where critical not fully served
        cid_steps = (g[col_crit_srv].astype(float) + 1e-9) < g[col_crit_req].astype(float)
        cid_minutes = float(cid_steps.sum() * dt_min)

        # SSR (intrinsic adequacy): PV energy / requested energy
        pv_e = (g[col_pv].astype(float).clip(lower=0.0) * dt_h).sum()
        load_req_e = (g[col_load_req].astype(float).clip(lower=0.0) * dt_h).sum()
        ssr = float(pv_e / load_req_e) if load_req_e > 1e-9 else 0.0

        # Solar utilisation: energy served directly from PV / PV energy
        # Approximation: served_from_pv = min(pv_now, load_served) each step
        served_from_pv_e = (g[[col_pv, col_load_srv]].astype(float).min(axis=1).clip(lower=0.0) * dt_h).sum()
        su = float(served_from_pv_e / pv_e) if pv_e > 1e-9 else 0.0

        bt = None
        if col_bt:
            try:
                # if it's running total in each row, take last value for that day
                bt = float(g[col_bt].astype(float).iloc[-1])
            except Exception:
                bt = None

        out_rows.append(
            DailyMetrics(
                date=d,
                clsr=clsr,
                cid_minutes=cid_minutes,
                ssr=ssr,
                solar_utilisation=su,
                battery_throughput_kwh=bt,
            ).__dict__
        )

    return pd.DataFrame(out_rows).sort_values("date")


def save_metrics_and_basic_plots(metrics_df: pd.DataFrame, out_dir: Path) -> Dict[str, str]:
    """
    Saves metrics CSV and basic matplotlib plots to out_dir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "ukdale_validation_daily_metrics.csv"
    metrics_df.to_csv(csv_path, index=False)

    # plots (matplotlib only)
    import matplotlib.pyplot as plt  # local import by design

    paths: Dict[str, str] = {"metrics_csv": str(csv_path)}

    # CLSR
    plt.figure()
    plt.plot(pd.to_datetime(metrics_df["date"]), metrics_df["clsr"])
    plt.xlabel("Date")
    plt.ylabel("CLSR")
    plt.tight_layout()
    p = out_dir / "clsr_timeseries.png"
    plt.savefig(p, dpi=200)
    plt.close()
    paths["clsr_plot"] = str(p)

    # CID
    plt.figure()
    plt.plot(pd.to_datetime(metrics_df["date"]), metrics_df["cid_minutes"])
    plt.xlabel("Date")
    plt.ylabel("CID (minutes)")
    plt.tight_layout()
    p = out_dir / "cid_timeseries.png"
    plt.savefig(p, dpi=200)
    plt.close()
    paths["cid_plot"] = str(p)

    # SSR
    plt.figure()
    plt.plot(pd.to_datetime(metrics_df["date"]), metrics_df["ssr"])
    plt.xlabel("Date")
    plt.ylabel("SSR")
    plt.tight_layout()
    p = out_dir / "ssr_timeseries.png"
    plt.savefig(p, dpi=200)
    plt.close()
    paths["ssr_plot"] = str(p)

    return paths
