# src/offgrid_dt/validation/metrics_summary.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd


def _infer_dt_minutes(df: pd.DataFrame) -> int:
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
    Computes daily metrics from RunLogger state CSV:
      - CLSR
      - CID (minutes)
      - SSR
      - SU (solar utilisation, proxy)
      - battery throughput if logged (optional)
    """
    df = pd.read_csv(state_csv)
    if "timestamp" not in df.columns:
        raise ValueError(f"state_csv missing 'timestamp': {state_csv}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df["date"] = df["timestamp"].dt.date.astype(str)

    dt_min = _infer_dt_minutes(df)
    dt_h = dt_min / 60.0

    col_crit_req = _get_col(df, ("crit_requested_kw",))
    col_crit_srv = _get_col(df, ("crit_served_kw",))
    col_load_req = _get_col(df, ("load_requested_kw",))
    col_load_srv = _get_col(df, ("load_served_kw",))
    col_pv = _get_col(df, ("pv_now_kw",))
    col_bt = _get_col(df, ("throughput_kwh", "battery_throughput_kwh"))

    required = [col_crit_req, col_crit_srv, col_load_req, col_load_srv, col_pv]
    if any(c is None for c in required):
        raise ValueError(
            "Missing required columns in state CSV. "
            f"Need crit_requested_kw, crit_served_kw, load_requested_kw, load_served_kw, pv_now_kw. "
            f"Found: {list(df.columns)}"
        )

    rows = []
    for d, g in df.groupby("date"):
        crit_req_e = (g[col_crit_req].astype(float).clip(lower=0.0) * dt_h).sum()
        crit_srv_e = (g[col_crit_srv].astype(float).clip(lower=0.0) * dt_h).sum()
        clsr = float(crit_srv_e / crit_req_e) if crit_req_e > 1e-9 else 1.0

        cid_steps = (g[col_crit_srv].astype(float) + 1e-9) < g[col_crit_req].astype(float)
        cid_minutes = float(cid_steps.sum() * dt_min)

        pv_e = (g[col_pv].astype(float).clip(lower=0.0) * dt_h).sum()
        load_req_e = (g[col_load_req].astype(float).clip(lower=0.0) * dt_h).sum()
        ssr = float(pv_e / load_req_e) if load_req_e > 1e-9 else 0.0

        served_from_pv_e = (g[[col_pv, col_load_srv]].astype(float).min(axis=1).clip(lower=0.0) * dt_h).sum()
        su = float(served_from_pv_e / pv_e) if pv_e > 1e-9 else 0.0

        bt = None
        if col_bt:
            try:
                bt = float(g[col_bt].astype(float).iloc[-1])
            except Exception:
                bt = None

        rows.append(
            {
                "date": d,
                "clsr": clsr,
                "cid_minutes": cid_minutes,
                "ssr": ssr,
                "solar_utilisation": su,
                "battery_throughput_kwh": bt,
            }
        )

    return pd.DataFrame(rows).sort_values("date")


def save_metrics_and_plots(metrics_df: pd.DataFrame, out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_csv = out_dir / "ukdale_validation_daily_metrics.csv"
    metrics_df.to_csv(metrics_csv, index=False)

    import matplotlib.pyplot as plt

    artifacts: Dict[str, str] = {"metrics_csv": str(metrics_csv)}

    for col, fname, ylabel in [
        ("clsr", "clsr_timeseries.png", "CLSR"),
        ("cid_minutes", "cid_timeseries.png", "CID (minutes)"),
        ("ssr", "ssr_timeseries.png", "SSR"),
        ("solar_utilisation", "su_timeseries.png", "Solar utilisation (proxy)"),
    ]:
        plt.figure()
        plt.plot(pd.to_datetime(metrics_df["date"]), metrics_df[col])
        plt.xlabel("Date")
        plt.ylabel(ylabel)
        plt.tight_layout()
        p = out_dir / fname
        plt.savefig(p, dpi=200)
        plt.close()
        artifacts[col] = str(p)

    return artifacts
