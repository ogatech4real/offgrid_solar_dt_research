from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is importable when running this script without installing the package
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offgrid_dt.control.controllers import get_controllers
from offgrid_dt.dt.simulator import simulate
from offgrid_dt.io.schema import Appliance, SystemConfig, UKDALEConfig


def default_appliances():
    return [
        Appliance(id="light", name="Lighting", category="critical", power_w=100, duration_steps=1, earliest_start_step=0, latest_end_step=96),
        Appliance(id="fan", name="Ceiling fan", category="critical", power_w=75, duration_steps=1, earliest_start_step=0, latest_end_step=96),
        Appliance(id="fridge", name="Refrigerator", category="critical", power_w=150, duration_steps=1, earliest_start_step=0, latest_end_step=96),
        Appliance(id="pump", name="Water pump", category="flexible", power_w=750, duration_steps=4, earliest_start_step=24, latest_end_step=60),
        Appliance(id="wash", name="Washing machine", category="flexible", power_w=600, duration_steps=4, earliest_start_step=28, latest_end_step=72),
        Appliance(id="iron", name="Iron", category="deferrable", power_w=1000, duration_steps=2, earliest_start_step=32, latest_end_step=80),
    ]


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", type=str, default="logs")

    # Research-mode measured demand toggle
    ap.add_argument("--ukdale", action="store_true", help="Use UK-DALE measured demand instead of task-based load")
    ap.add_argument("--ukdale-root", type=str, default=None, help="Path to UK-DALE dataset root")
    ap.add_argument("--house", type=str, default="1", help="UK-DALE house ID")
    ap.add_argument("--start-date", type=str, default=None, help="Validation start date (YYYY-MM-DD)")
    ap.add_argument("--end-date", type=str, default=None, help="Validation end date (YYYY-MM-DD)")
    ap.add_argument("--critical-base-kw", type=float, default=0.15, help="Critical baseline kW for measured split")

    args = ap.parse_args()

    # Base PV-battery configuration
    cfg = SystemConfig(
        location_name="Middlesbrough_UK" if args.ukdale else "Demo",
        latitude=54.5742 if args.ukdale else 28.6139,
        longitude=-1.2348 if args.ukdale else 77.2090,
        pv_capacity_kw=4.0,
        battery_capacity_kwh=7.5,
        inverter_max_kw=2.5,
        soc_init=0.6,
        soc_min=0.25,
    )

    # If measured-demand validation requested
    if args.ukdale:
        if not args.ukdale_root:
            raise ValueError("--ukdale-root must be provided when --ukdale is enabled")
        if not args.start_date or not args.end_date:
            raise ValueError("--start-date and --end-date are required for UK-DALE validation")

        cfg.load_source = "ukdale"
        cfg.ukdale = UKDALEConfig(
            dataset_root=args.ukdale_root,
            house_id=args.house,
            start_date=args.start_date,
            end_date=args.end_date,
            critical_baseline_kw=args.critical_base_kw,
        )

        appliances = []  # Not used in measured mode
    else:
        appliances = default_appliances()

    out_dir = Path(args.out)

    for c in get_controllers():
        paths = simulate(
            cfg,
            appliances,
            controller=c,
            days=args.days,
            out_dir=out_dir / f"run_{c.name}",
        )
        print(c.name, paths)


if __name__ == "__main__":
    main()
