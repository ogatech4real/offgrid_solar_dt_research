# scripts/validate_ukdale.py
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List

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
    """Accept 'YYYY-MM-DD' or full ISO timestamps; interpret as UTC if tz-naive."""
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
    We choose previous-day midday to avoid edge cases around midnight.
    """
    prev_day_midday = (target_day_utc.normalize() - pd.Timedelta(days=1)).to_pydatetime()
    return prev_day_midday.replace(tzinfo=timezone.utc) + timedelta(hours=12)


def _daily_metrics_from_state(df: pd.DataFrame, timestep_minutes: int, tz: str = "UTC") -> pd.DataFrame:
    """
    Compute daily metrics (CLSR, CID, SSR, SU) from state log.
    Assumes StepRecord CSV columns:
      timestamp, pv_now_kw, load_requested_kw, load_served_kw, crit_requested_kw, crit_served_kw, curtailed_solar_kw
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
    out["pv_kwh"] = pd.to_numeric(out["pv_now_kw"], errors="coerce").astype(float) * dt_h
    out["load_req_kwh"] = pd.to_numeric(out["load_requested_kw"], errors="coerce").astype(float) * dt_h
    out["load_served_kwh"] = pd.to_numeric(out["load_served_kw"], errors="coerce").astype(float) * dt_h
    out["crit_req_kwh"] = pd.to_numeric(out["crit_requested_kw"], errors="coerce").astype(float) * dt_h
    out["crit_served_kwh"] = pd.to_numeric(out["crit_served_kw"], errors="coerce").astype(float) * dt_h
    out["curtailed_kwh"] = pd.to_numeric(out["curtailed_solar_kw"], errors="coerce").astype(float) * dt_h

    # CID: minutes where critical is not fully served
    out["crit_shortfall"] = (
        pd.to_numeric(out["crit_served_kw"], errors="coerce").astype(float) + 1e-9
    ) < pd.to_numeric(out["crit_requested_kw"], errors="coerce").astype(float)

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

        # Solar Utilisation (SU): fraction of PV used to serve load (not curtailed)
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
        s = pd.to_numeric(df_daily[col], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
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


def _ensure_fig_dir(out_root: Path) -> Path:
    fig_dir = out_root / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    return fig_dir


def _pick_representative_days(df_daily: pd.DataFrame) -> Dict[str, str]:
    """
    Pick 3 representative days for the paper: surplus / tight / deficit.
    Uses SSR quantiles (robust, dataset-agnostic).
    """
    d = df_daily.copy()
    d["SSR"] = pd.to_numeric(d["SSR"], errors="coerce")
    d = d.replace([np.inf, -np.inf], np.nan).dropna(subset=["SSR"])
    if d.empty:
        return {}

    targets = {
        "surplus": float(d["SSR"].quantile(0.80)),
        "tight": float(d["SSR"].quantile(0.50)),
        "deficit": float(d["SSR"].quantile(0.20)),
    }

    picked: Dict[str, str] = {}
    for k, t in targets.items():
        idx = (d["SSR"] - t).abs().idxmin()
        picked[k] = str(d.loc[idx, "date"])
    return picked


def _slice_day_state(df_state: pd.DataFrame, date_str: str, tz: str) -> pd.DataFrame:
    """Extract a single local-date slice from the simulator state csv."""
    x = df_state.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    x = x.dropna(subset=["timestamp"]).sort_values("timestamp")

    if tz and tz.upper() != "UTC":
        x["timestamp_local"] = x["timestamp"].dt.tz_convert(tz)
    else:
        x["timestamp_local"] = x["timestamp"]

    target = pd.to_datetime(date_str).date()
    return x[x["timestamp_local"].dt.date == target].copy()


def _make_validation_metrics_placeholder(df_daily: pd.DataFrame, fig_path: Path) -> None:
    """Single figure with distributions of CLSR, CID, SSR (paper placeholder)."""
    d = df_daily.copy()
    for col in ["CLSR", "CID_min", "SSR"]:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.replace([np.inf, -np.inf], np.nan)

    clsr = d["CLSR"].dropna().values
    cid = d["CID_min"].dropna().values
    ssr = d["SSR"].dropna().values

    plt.figure(figsize=(10, 3.2))
    ax1 = plt.subplot(1, 3, 1)
    ax1.hist(clsr, bins=20)
    ax1.set_xlabel("CLSR")
    ax1.set_ylabel("Count (days)")

    ax2 = plt.subplot(1, 3, 2)
    ax2.hist(cid, bins=20)
    ax2.set_xlabel("CID (min)")
    ax2.set_ylabel("Count (days)")

    ax3 = plt.subplot(1, 3, 3)
    ax3.hist(ssr, bins=20)
    ax3.set_xlabel("SSR")
    ax3.set_ylabel("Count (days)")

    plt.tight_layout()
    plt.savefig(fig_path, dpi=250)
    plt.close()


def _make_validation_day_examples_placeholder(
    df_state: pd.DataFrame,
    df_daily: pd.DataFrame,
    tz: str,
    fig_path: Path,
) -> None:
    """
    Single figure with 3 representative days (surplus/tight/deficit).
    Plots PV vs requested vs served load (plus critical req/served).
    """
    reps = _pick_representative_days(df_daily)
    if not reps:
        raise RuntimeError("Could not pick representative days (daily metrics empty).")

    order = [("surplus", reps["surplus"]), ("tight", reps["tight"]), ("deficit", reps["deficit"])]

    plt.figure(figsize=(10, 7.5))

    for i, (label, day) in enumerate(order, start=1):
        day_df = _slice_day_state(df_state, day, tz=tz)
        if day_df.empty:
            continue

        t = day_df["timestamp_local"]
        pv = pd.to_numeric(day_df["pv_now_kw"], errors="coerce")
        req = pd.to_numeric(day_df["load_requested_kw"], errors="coerce")
        served = pd.to_numeric(day_df["load_served_kw"], errors="coerce")
        crit_req = pd.to_numeric(day_df["crit_requested_kw"], errors="coerce")
        crit_served = pd.to_numeric(day_df["crit_served_kw"], errors="coerce")

        ax = plt.subplot(3, 1, i)
        ax.plot(t, pv, label="PV (kW)")
        ax.plot(t, req, label="Requested load (kW)")
        ax.plot(t, served, label="Served load (kW)")
        ax.plot(t, crit_req, label="Critical requested (kW)")
        ax.plot(t, crit_served, label="Critical served (kW)")

        ssr_val = df_daily.loc[df_daily["date"] == day, "SSR"]
        ssr_txt = f"{float(ssr_val.iloc[0]):.2f}" if len(ssr_val) else "n/a"
        ax.set_title(f"{label.capitalize()} day ({day}) — SSR={ssr_txt}")
        ax.set_ylabel("kW")
        ax.grid(True, alpha=0.25)
        if i == 1:
            ax.legend(loc="upper right", ncol=2, fontsize=8)

    plt.tight_layout()
    plt.savefig(fig_path, dpi=250)
    plt.close()


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
    ap.add_argument(
        "--controller",
        type=str,
        default="forecast_heuristic",
        help="naive|rule_based|static_priority|forecast_heuristic|all",
    )
    ap.add_argument("--out", type=str, default="outputs/validation", help="Output directory.")
    ap.add_argument("--openai_api_key", type=str, default=None)
    ap.add_argument("--openai_model", type=str, default="gpt-4o-mini")

    if len(sys.argv) == 1:
    # ----------------------------
    # DEV / PYCHARM DEFAULTS
    # ----------------------------
    class DevArgs:
        ukdale_root = "/absolute/path/to/UKDALE"
        house_id = "1"
        start_date = "2014-01-01"
        end_date = "2014-01-14"
        resample_minutes = 15
        timezone = "Europe/London"
        critical_baseline_kw = 0.15

        location_name = "Middlesbrough (UK)"
        lat = 54.5742
        lon = -1.2350
        pv_kw = 3.0
        pv_eff = 0.18
        bat_kwh = 5.0
        inv_kw = 2.5
        soc_init = 0.7
        soc_min = 0.25
        soc_max = 0.95

        controller = "forecast_heuristic"
        out = "outputs/validation"
        openai_api_key = None
        openai_model = "gpt-4o-mini"

    args = DevArgs()
else:
    args = ap.parse_args()


    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

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
        horizon_steps=96,  # aligned with manuscript (24h @ 15-min)
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

        # appliances list is unused in ukdale mode; pass empty list.
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

        df_daily.to_csv(run_dir / "daily_metrics.csv", index=False)

        fig_dir = run_dir / "figures"
        _save_metric_figures(df_daily, fig_dir, prefix=c.name)

    df_all = pd.concat(all_daily_frames, ignore_index=True) if all_daily_frames else pd.DataFrame()
    df_all.to_csv(out_root / "daily_metrics_all.csv", index=False)

    summary = (
        df_all.groupby("controller")[["CLSR", "CID_min", "SSR", "SU"]]
        .agg(["mean", "median", "std", "min", "max"])
        .reset_index()
    )
    summary.to_csv(out_root / "summary_by_controller.csv", index=False)

    # ----------------------------
    # Journal placeholder figures
    # ----------------------------
    if df_all.empty or "controller" not in df_all.columns:
        raise RuntimeError("No daily metrics produced; cannot generate placeholder figures.")

    fig_root = _ensure_fig_dir(out_root)

    preferred = "forecast_heuristic"
    chosen = preferred if preferred in df_all["controller"].unique() else df_all["controller"].iloc[0]
    df_chosen_daily = df_all[df_all["controller"] == chosen].copy()

    chosen_state_csv = run_manifest.get(chosen, {}).get("state_csv")
    if not chosen_state_csv:
        candidate = out_root / f"run_{chosen}" / "state.csv"
        chosen_state_csv = str(candidate) if candidate.exists() else None

    if not chosen_state_csv:
        raise RuntimeError(f"Could not locate state CSV for controller '{chosen}'.")

    df_chosen_state = pd.read_csv(chosen_state_csv)

    _make_validation_metrics_placeholder(
        df_chosen_daily,
        fig_root / "validation_metrics_placeholder.png",
    )

    _make_validation_day_examples_placeholder(
        df_state=df_chosen_state,
        df_daily=df_chosen_daily,
        tz=args.timezone,
        fig_path=fig_root / "validation_day_examples_placeholder.png",
    )

    print(" - figures/validation_metrics_placeholder.png")
    print(" - figures/validation_day_examples_placeholder.png")

    # Persist manifest
    with open(out_root / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(run_manifest, f, indent=2)

    print(f"[OK] Validation completed. Outputs in: {out_root}")
    print(" - daily_metrics_all.csv")
    print(" - summary_by_controller.csv")
    print(" - run_manifest.json")
    for c in controllers:
        print(f" - run_{c.name}/daily_metrics.csv and run_{c.name}/figures/*.png")


if __name__ == "__main__":
    main()
