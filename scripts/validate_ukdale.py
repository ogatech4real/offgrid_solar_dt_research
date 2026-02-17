# scripts/validate_ukdale.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is importable when running this script without installing the package
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offgrid_dt.control.controllers import ForecastAwareHeuristicController
from offgrid_dt.dt.simulator import simulate
from offgrid_dt.io.schema import SystemConfig
from offgrid_dt.validation.metrics_summary import compute_daily_metrics_from_state_csv, save_metrics_and_plots


def main() -> None:
    ap = argparse.ArgumentParser(description="Measured-demand validation using UK-DALE (research_mode).")
    ap.add_argument("--ukdale-root", required=True, type=str)
    ap.add_argument("--house-id", default="1", type=str)
    ap.add_argument("--start-date", required=True, type=str)  # schema: start_date
    ap.add_argument("--end-date", required=True, type=str)    # schema: end_date
    ap.add_argument("--resample-minutes", default=15, type=int)
    ap.add_argument("--timezone", default="Europe/London", type=str)
    ap.add_argument("--critical-baseline-kw", default=0.15, type=float)

    ap.add_argument("--lat", default=54.5742, type=float)
    ap.add_argument("--lon", default=-1.2348, type=float)

    ap.add_argument("--pv-kw", default=3.0, type=float)
    ap.add_argument("--bat-kwh", default=5.0, type=float)
    ap.add_argument("--inv-kw", default=2.5, type=float)

    ap.add_argument("--soc-init", default=0.7, type=float)
    ap.add_argument("--soc-min", default=0.25, type=float)
    ap.add_argument("--soc-max", default=0.95, type=float)

    ap.add_argument("--days", default=7, type=int, help="Temporary cap; you can later infer days from date window.")
    ap.add_argument("--out", default="results/validation/ukdale", type=str)
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = SystemConfig(
        location_name=f"UK-DALE house_{args.house_id}",
        latitude=float(args.lat),
        longitude=float(args.lon),
        pv_capacity_kw=float(args.pv_kw),
        battery_capacity_kwh=float(args.bat_kwh),
        inverter_max_kw=float(args.inv_kw),
        soc_init=float(args.soc_init),
        soc_min=float(args.soc_min),
        soc_max=float(args.soc_max),
        timestep_minutes=int(args.resample_minutes),
        horizon_steps=96,
        load_source="ukdale",
        ukdale={
            "dataset_root": str(Path(args.ukdale_root).expanduser().resolve()),
            "house_id": str(args.house_id),
            "channel": "mains",
            "start_date": args.start_date,
            "end_date": args.end_date,
            "resample_minutes": int(args.resample_minutes),
            "timezone": args.timezone,
            "critical_baseline_kw": float(args.critical_baseline_kw),
        },
        validation={"enabled": True, "output_dir": str(out_dir), "save_daily_csv": True, "save_figures": True},
    )

    controller = ForecastAwareHeuristicController()

    # For now: run limited days; later you can compute exact days from start/end dates and run them all.
    run_out = simulate(
        cfg=cfg,
        appliances=[],
        controller=controller,
        days=int(args.days),
        out_dir=out_dir / f"run_{controller.name}",
    )

    state_csv = run_out.get("state_csv")
    if not state_csv:
        raise RuntimeError(f"simulate() did not return state_csv. Got: {run_out}")

    metrics_df = compute_daily_metrics_from_state_csv(Path(state_csv))
    artifacts = save_metrics_and_plots(metrics_df, out_dir=out_dir)

    print("UK-DALE validation complete.")
    print("state_csv:", state_csv)
    print("metrics_csv:", artifacts["metrics_csv"])


if __name__ == "__main__":
    main()
