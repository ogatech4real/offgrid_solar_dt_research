from offgrid_dt.dt.battery import BatteryState, update_soc
from offgrid_dt.io.schema import SystemConfig


def test_update_soc_bounds_and_direction():
    cfg = SystemConfig(
        pv_capacity_kw=4.0,
        battery_capacity_kwh=7.5,
        inverter_max_kw=3.0,
        soc_init=0.5,
        soc_min=0.25,
        soc_max=0.95,
    )

    # Charge should increase SOC (bounded)
    b = BatteryState(soc=0.5)
    b2 = update_soc(
        state=b,
        charge_kw=2.0,
        discharge_kw=0.0,
        timestep_hours=0.25,
        battery_capacity_kwh=cfg.battery_capacity_kwh,
        charge_eff=cfg.charge_eff,
        discharge_eff=cfg.discharge_eff,
        soc_min=cfg.soc_min,
        soc_max=cfg.soc_max,
    )
    assert b2.soc > b.soc
    assert cfg.soc_min <= b2.soc <= cfg.soc_max

    # Discharge should decrease SOC (bounded)
    b = BatteryState(soc=0.5)
    b2 = update_soc(
        state=b,
        charge_kw=0.0,
        discharge_kw=2.0,
        timestep_hours=0.25,
        battery_capacity_kwh=cfg.battery_capacity_kwh,
        charge_eff=cfg.charge_eff,
        discharge_eff=cfg.discharge_eff,
        soc_min=cfg.soc_min,
        soc_max=cfg.soc_max,
    )
    assert b2.soc < b.soc
    assert cfg.soc_min <= b2.soc <= cfg.soc_max
