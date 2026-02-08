import tempfile
from pathlib import Path

import pandas as pd

from offgrid_dt.control.controllers import ForecastAwareHeuristicController
from offgrid_dt.dt.simulator import simulate
from offgrid_dt.io.schema import Appliance, SystemConfig


def test_simulation_runs_and_produces_nonzero_pv():
    cfg = SystemConfig(
        location_name="test",
        latitude=51.5,
        longitude=-0.1,
        pv_capacity_kw=4.0,
        battery_capacity_kwh=7.5,
        inverter_max_kw=3.0,
        soc_init=0.6,
        soc_min=0.25,
        soc_max=0.95,
        timestep_minutes=15,
        horizon_steps=48,
    )
    appliances = [
        Appliance(id="lights", name="Lights", category="critical", power_w=150),
        Appliance(id="fridge", name="Fridge", category="critical", power_w=100),
        Appliance(id="wash", name="Washing", category="flexible", power_w=600, duration_steps=4, earliest_start_step=40, latest_end_step=80),
        Appliance(id="iron", name="Iron", category="deferrable", power_w=1000, duration_steps=2, earliest_start_step=44, latest_end_step=90),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        out = simulate(
            cfg=cfg,
            appliances=appliances,
            controller=ForecastAwareHeuristicController(),
            days=3,
            seed=123,
            openweather_api_key=None,
            out_dir=Path(tmp) / "run",
        )
        state_path = Path(out["state_csv"])
        assert state_path.exists()
        df = pd.read_csv(state_path)
        assert len(df) > 0
        # Synthetic PV should have non-zero points in daytime; ensure not all zeros
        assert df["pv_now_kw"].max() > 0.1
        # Planned daily energy from config (critical 0.25 kW*24h + wash 0.6*4*0.25 + iron 1*2*0.25)
        assert "planned_load_energy_kwh" in out
        assert out["planned_load_energy_kwh"] > 0
        assert out["planned_load_energy_kwh"] < 50  # sanity: not the inflated sum(load_requested_kw)*dt
        # Day-ahead matching uses same planned demand
        matching = out.get("matching_first_day", {})
        if matching:
            assert abs(matching.get("total_demand_kwh", 0) - out["planned_load_energy_kwh"]) < 0.01