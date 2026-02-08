"""Tests for planned daily energy (config-based, not sum(load_requested_kw)*dt)."""

from offgrid_dt.dt.load import compute_planned_daily_energy_kwh
from offgrid_dt.io.schema import Appliance


def test_compute_planned_daily_energy_kwh_critical_only():
    day_steps = 96
    dt_h = 0.25
    appliances = [
        Appliance(id="lights", name="Lights", category="critical", power_w=100),
        Appliance(id="fridge", name="Fridge", category="critical", power_w=150),
    ]
    E = compute_planned_daily_energy_kwh(appliances, day_steps, dt_h)
    # 0.25 kW * 96 * 0.25 = 6 kWh
    assert abs(E - 6.0) < 0.01


def test_compute_planned_daily_energy_kwh_with_flexible_and_deferrable():
    day_steps = 96
    dt_h = 0.25
    appliances = [
        Appliance(id="lights", name="Lights", category="critical", power_w=100),
        Appliance(id="wash", name="Washing", category="flexible", power_w=600, duration_steps=4),
        Appliance(id="iron", name="Iron", category="deferrable", power_w=1000, duration_steps=2, daily_quota_steps=0),
    ]
    E = compute_planned_daily_energy_kwh(appliances, day_steps, dt_h)
    # critical: 0.1 * 96 * 0.25 = 2.4 kWh
    # wash: 0.6 * 4 * 0.25 = 0.6 kWh
    # iron: 1.0 * 2 * 0.25 = 0.5 kWh
    # total = 3.5 kWh
    assert abs(E - 3.5) < 0.01


def test_compute_planned_daily_energy_kwh_deferrable_quota():
    day_steps = 96
    dt_h = 0.25
    appliances = [
        Appliance(id="ev", name="EV", category="deferrable", power_w=3000, daily_quota_steps=16),
    ]
    E = compute_planned_daily_energy_kwh(appliances, day_steps, dt_h)
    # 3 kW * 16 steps * 0.25 h = 12 kWh
    assert abs(E - 12.0) < 0.01
