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
from offgrid_dt.io.schema import Appliance, SystemConfig  # assumes you added load_source + ukdale config fields
from offgrid_dt.validation.metrics_summary import compute_daily_metrics_from_state_csv, save_metrics_and_basic_plots


def main() -> None:
    ap = argparse.ArgumentParser(description="UK-DALE measured-demand validation runner (research_mode).")
    ap.add_argument("--ukdale-root", required=True, type=str, help="Path to UK-DALE dataset root")
    ap.add_argument("--house", required=True, type=int, help="House id, e.g. 1")
    ap.add_argument("--start", type=str, default=None, help="ISO start date/time (UTC), e.g. 2013-01-01")
    ap.add_argument("--end", type=str, default=None, help="ISO end date/time (UTC)")
    ap.add_argument("--timestep", type=int, default=15, help="Timestep minutes (must match your simulator)")
    ap.add_argument("--critical-kw", type=float, default=0.20, help="Fixed critical baseline kW")
    ap.add_argument("--lat", type=float, default=54.5742, help="Latitude for PV profile (default UK)")
    ap.add_argument("--lon", type=float, default=-1.2348, help="Longitude for PV profile (default UK)")
    ap.add_argument("--pv-kw", type=float, default=3.0)
    ap.add_argument("--bat-kwh", type=float, default=5.0)
    ap.add_argument("--inv-kw", type=float, default=2.5)
    ap.add_argument("--soc-init", type=float, default=0.7)
    ap.add_argument("--soc-min", type=float, default=0.25)
    ap.add_argument("--out", type=str, default=str(Path("results") / "validation" / "ukdale"))
    ap.add_argument("--days", type=int, default=None, help="Optional explicit number of days to simulate")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # IMPORTANT:
    # - appliances list can be empty for measured-demand mode
    # - simulator should branch on cfg.load_source == "ukdale"
    appliances: list[Appliance] = []

    # This assumes you added these to SystemConfig in your updated schema.py:
    #   load_source: Literal["tasks","ukdale"]
    #   ukdale: UKDALEConfig (with dataset_root, house_id, start, end, critical_baseline_kw, etc.)
    cfg = SystemConfig(
        location_name=f"UK-DALE house_{args.house}",
        latitude=float(args.lat),
        longitude=float(args.lon),
        pv_capacity_kw=float(args.pv_kw),
        battery_capacity_kwh=float(args.bat_kwh),
        inverter_max_kw=float(args.inv_kw),
        soc_init=float(args.soc_init),
        soc_min=float(args.soc_min),
        soc_max=0.95,
        timestep_minutes=int(args.timestep),
        # --- research mode switches (must exist in your SystemConfig)
        load_source="ukdale",
        ukdale={
            "dataset_root": str(Path(args.ukdale_root).resolve()),
            "house_id": int(args.house),
            "start": args.start,
            "end": args.end,
            "target_timestep_minutes": int(args.timestep),
            "critical_baseline_kw": float(args.critical_kw),
        },
    )

    controller = ForecastAwareHeuristicController()

    # days: if not provided, let simulator infer from ukdale date window (your implementation),
    # otherwise override (useful for quick tests).
    sim_days = args.days if args.days is not None else 7

    run_out = simulate(
        cfg=cfg,
        appliances=appliances,
        controller=controller,
        days=sim_days,
        out_dir=out_dir / f"run_{controller.name}",
    )

    state_csv = run_out.get("state_csv")
    if not state_csv:
        raise RuntimeError(f"No state_csv returned from simulate(): {run_out}")

    metrics_df = compute_daily_metrics_from_state_csv(Path(state_csv))
    artifacts = save_metrics_and_basic_plots(metrics_df, out_dir=out_dir)

    print("UK-DALE validation complete.")
    print("Run outputs:", run_out)
    print("Artifacts:", artifacts)


if __name__ == "__main__":
    main()
