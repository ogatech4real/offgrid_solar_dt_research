# scripts/validate_ukdale.py
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Ensure src/ is importable when running this script without installing the package
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offgrid_dt.control.controllers import (  # noqa: E402
    ForecastAwareHeuristicController,
    NaiveController,
    RuleBasedController,
    StaticPriorityController,
)
from offgrid_dt.dt.simulator import simulate  # noqa: E402
from offgrid_dt.io.schema import SystemConfig, UKDALEConfig  # noqa: E402


def _parse_date(s: str) -> pd.Timestamp:
    # Accept "YYYY-MM-DD" or full ISO timestamps; interpret as UTC if tz-naive.
    ts = pd.to_datetime(s)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _compute_days(start_date: str, end_date: str) -> int:
    s = _parse_date(start_date).normalize()
    e = _parse_date(end_date).normalize()
    # inclusive day count
    return int((e - s).days) + 1


def _reference_utc_for_sim_start(target_day_utc: pd.Timestamp) -> datetime:
    """
    simulate() sets:
        first_planning_date = now_utc.date() + 1
        start = first_planning_date 00:00 UTC
    So to force start == target_day_utc 00:00, set now_utc to previous date.
    """
    prev_day = (target_day_utc.normalize() - pd.Timedelta(days=1)).to_pydatetime()
    return prev_day.replace(tzinfo=timezone.utc) + timedelta(hours=12)  # safe midday


def _daily_metrics_from_state(
    df: pd.DataFrame, timestep_minutes: int, tz: str = "UTC"
) -> pd.DataFrame:
    """
    Compute daily metrics (CLSR, CID, SSR, SU, BT) from state log.
    Assumes columns from StepRecord CSV:
      timestamp, pv_now_kw, load_requested_kw, load_served_kw, crit_requested_kw, crit_served_kw, curtailed_solar_kw, ...
    """
    required = {
        "timestamp",
        "pv_now_kw",
        "load_requested_kw",
        "load_served_kw",
        "crit_requested_kw",
        "crit_served_kw",
        "curtailed_solar_kw",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"State CSV missing columns: {sorted(missing)}")

    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp")

    if tz and tz.upper() != "UTC":
        out["timestamp_local"] = out["timestamp"].dt.tz_convert(tz)
    else:
        out["timestamp_local"] = out["timestamp"]

    dt_h = timestep_minutes / 60.0

    # energies per step
    out["pv_kwh"] = out["pv_now_kw"].astype(float) * dt_h
    out["load_req_kwh"] = out["load_requested_kw"].astype(float) * dt_h
    out["load_served_kwh"] = out["load_served_kw"].astype(float) * dt_h
    out["crit_req_kwh"] = out["crit_requested_kw"].astype(float) * dt_h
    out["crit_served_kwh"] = out["crit_served_kw"].astype(float) * dt_h
    out["curtailed_kwh"] = out["curtailed_solar_kw"].astype(float) * dt_h

    # CID: minutes where critical is not fully served
    out["crit_shortfall"] = (out["crit_served_kw"].astype(float) + 1e-9) < out[
        "crit_requested_kw"
    ].astype(float)

    grp = out.groupby(out["timestamp_local"].dt.date)

    rows: List[Dict[str, float]] = []
    for day, g in grp:
        pv = float(g["pv_kwh"].sum())
        load_req = float(g["load_req_kwh"].sum())
        load_served = float(g["load_served_kwh"].sum())
        crit_req = float(g["crit_req_kwh"].sum())
        crit_served = float(g["crit_served_kwh"].sum())
        curtailed = float(g["curtailed_kwh"].sum())

        clsr = (crit_served / crit_req) if crit_req > 1e-12 else 1.0
        cid_min = float(g["crit_shortfall"].sum() * timestep_minutes)
        ssr = (pv / load_req) if load_req > 1e-12 else np.nan

        # Solar Utilisation (SU): fraction of PV used to serve load (not curtailed).
        # Note: if PV is near zero, SU is undefined; we set NaN.
        su = ((pv - curtailed) / pv) if pv > 1e-12 else np.nan

        rows.append(
            {
                "date": str(day),
                "PV_kWh": pv,
                "LoadReq_kWh": load_req,
                "LoadServed_kWh": load_served,
                "CritReq_kWh": crit_req,
                "CritServed_kWh": crit_served,
                "CLSR": clsr,
                "CID_min": cid_min,
                "SSR": ssr,
                "SU": su,
            }
        )

    return pd.DataFrame(rows)


def _save_metric_figures(df_daily: pd.DataFrame, out_dir: Path, prefix: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    for col, fname, xlabel in [
        ("CLSR", f"{prefix}_dist_clsr.png", "CLSR"),
        ("CID_min", f"{prefix}_dist_cid.png", "CID (min)"),
        ("SSR", f"{prefix}_dist_ssr.png", "SSR"),
    ]:
        s = df_daily[col].replace([np.inf, -np.inf], np.nan).dropna()
        plt.figure()
        plt.hist(s.values, bins=20)
        plt.xlabel(xlabel)
        plt.ylabel("Count (days)")
        plt.tight_layout()
        plt.savefig(out_dir / fname, dpi=200)
        plt.close()


def _controllers_from_arg(which: str):
    which = which.strip().lower()
    all_map = {
        "naive": NaiveController(),
        "rule_based": RuleBasedController(),
        "static_priority": StaticPriorityController(),
        "forecast_heuristic": ForecastAwareHeuristicController(),
    }
    if which in ("all", "*"):
        return list(all_map.values())
    if which not in all_map:
        raise ValueError(f"Unknown controller '{which}'. Use one of: all, {list(all_map.keys())}")
    return [all_map[which]]


def main() -> None:
    ap = argparse.ArgumentParser(description="UK-DALE measured-demand validation runner (research mode).")

    # UK-DALE
    ap.add_argument("--ukdale_root", type=str, required=True, help="Path to UK-DALE dataset root.")
    ap.add_argument("--house_id", type=str, default="1", help="UK-DALE house id, e.g. 1, 2, 3...")
    ap.add_argument("--start_date", type=str, required=True, help="ISO date/timestamp (UTC assumed if tz-naive).")
    ap.add_argument("--end_date", type=str, required=True, help="ISO date/timestamp (UTC assumed if tz-naive).")
    ap.add_argument("--resample_minutes", type=int, default=15)
    ap.add_argument("--timezone", type=str, default="Europe/London")
    ap.add_argument("--critical_baseline_kw", type=float, default=0.15)

    # PV/battery system
    ap.add_argument("--location_name", type=str, default="Middlesbrough (UK)")
    ap.add_argument("--lat", type=float, default=54.5742)
    ap.add_argument("--lon", type=float, default=-1.2350)
    ap.add_argument("--pv_kw", type=float, default=3.0)
    ap.add_argument("--pv_eff", type=float, default=0.18)
    ap.add_argument("--bat_kwh", type=float, default=5.0)
    ap.add_argument("--inv_kw", type=float, default=2.5)
    ap.add_argument("--soc_init", type=float, default=0.7)
    ap.add_argument("--soc_min", type=float, default=0.25)
    ap.add_argument("--soc_max", type=float, default=0.95)

    # Run controls
    ap.add_argument("--controller", type=str, default="forecast_heuristic", help="naive|rule_based|static_priority|forecast_heuristic|all")
    ap.add_argument("--out", type=str, default="outputs/validation", help="Output directory.")
    ap.add_argument("--openai_api_key", type=str, default=None)
    ap.add_argument("--openai_model", type=str, default="gpt-4o-mini")

    args = ap.parse_args()

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # Validation horizon -> run days
    n_days = _compute_days(args.start_date, args.end_date)

    ukcfg = UKDALEConfig(
        dataset_root=args.ukdale_root,
        house_id=str(args.house_id),
        start_date=args.start_date,
        end_date=args.end_date,
        resample_minutes=int(args.resample_minutes),
        timezone=args.timezone,
        critical_baseline_kw=float(args.critical_baseline_kw),
    )

    cfg = SystemConfig(
        location_name=args.location_name,
        latitude=float(args.lat),
        longitude=float(args.lon),
        pv_capacity_kw=float(args.pv_kw),
        pv_efficiency=float(args.pv_eff),
        battery_capacity_kwh=float(args.bat_kwh),
        inverter_max_kw=float(args.inv_kw),
        soc_init=float(args.soc_init),
        soc_min=float(args.soc_min),
        soc_max=float(args.soc_max),
        timestep_minutes=int(args.resample_minutes),
        horizon_steps=96,  # keep aligned with manuscript (24h @ 15-min)
        load_source="ukdale",
        ukdale=ukcfg,
    )

    # Force simulator start = validation start date 00:00 UTC
    start_day_utc = _parse_date(args.start_date).normalize()
    reference_utc = _reference_utc_for_sim_start(start_day_utc)

    run_manifest: Dict[str, dict] = {
        "cfg": cfg.model_dump(),
        "ukdale": ukcfg.model_dump(),
        "days": n_days,
        "reference_utc": reference_utc.isoformat(),
    }

    controllers = _controllers_from_arg(args.controller)

    all_daily_frames: List[pd.DataFrame] = []

    for c in controllers:
        run_dir = out_root / f"run_{c.name}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # NOTE: appliances list is unused in ukdale mode; pass empty list.
        result = simulate(
            cfg=cfg,
            appliances=[],
            controller=c,
            days=n_days,
            out_dir=run_dir,
            reference_utc=reference_utc,
            openai_api_key=args.openai_api_key,
            openai_model=args.openai_model,
        )

        run_manifest[c.name] = result

        state_csv = result.get("state_csv")
        if not state_csv:
            raise RuntimeError(f"No state_csv produced for controller={c.name}. Got: {result}")

        df_state = pd.read_csv(state_csv)
        df_daily = _daily_metrics_from_state(df_state, timestep_minutes=cfg.timestep_minutes, tz=args.timezone)
        df_daily["controller"] = c.name
        all_daily_frames.append(df_daily)

        # Save controller daily metrics
        df_daily.to_csv(run_dir / "daily_metrics.csv", index=False)

        # Figures
        fig_dir = run_dir / "figures"
        _save_metric_figures(df_daily, fig_dir, prefix=c.name)

    # Aggregate across controllers (if multiple)
    df_all = pd.concat(all_daily_frames, ignore_index=True) if all_daily_frames else pd.DataFrame()
    df_all.to_csv(out_root / "daily_metrics_all.csv", index=False)

    # Simple overall summary table
    summary = (
        df_all.groupby("controller")[["CLSR", "CID_min", "SSR", "SU"]]
        .agg(["mean", "median", "std", "min", "max"])
        .reset_index()
    )
    summary.to_csv(out_root / "summary_by_controller.csv", index=False)

    # Persist manifest
    with open(out_root / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(run_manifest, f, indent=2)

    print(f"[OK] Validation completed. Outputs in: {out_root}")
    print(f" - daily_metrics_all.csv")
    print(f" - summary_by_controller.csv")
    print(f" - run_manifest.json")
    for c in controllers:
        print(f" - run_{c.name}/daily_metrics.csv and run_{c.name}/figures/*.png")


if __name__ == "__main__":
    main()
