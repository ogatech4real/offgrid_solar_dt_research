"""Tests for nominal planned energy (single source of truth: Critical 24h, Flexible 4h, Deferrable 2h)."""

from offgrid_dt.io.schema import Appliance
from offgrid_dt.planning.nominal_plan import (
    DEFAULT_HOURS_CRITICAL,
    DEFAULT_HOURS_DEFERRABLE,
    DEFAULT_HOURS_FLEXIBLE,
    compute_nominal_planned_energy,
)


def test_nominal_critical_only():
    appliances = [
        Appliance(id="lights", name="Lights", category="critical", power_w=100),
        Appliance(id="fridge", name="Fridge", category="critical", power_w=150),
    ]
    r = compute_nominal_planned_energy(appliances)
    # 0.25 kW * 24 h = 6 kWh
    assert abs(r.E_plan_24h_kwh - 6.0) < 0.01
    assert abs(r.P_avg_kw - 0.25) < 0.01
    assert r.E_plan_12h_kwh is not None and abs(r.E_plan_12h_kwh - 3.0) < 0.01


def test_nominal_flexible_and_deferrable_defaults():
    appliances = [
        Appliance(id="lights", name="Lights", category="critical", power_w=100),
        Appliance(id="wash", name="Washing", category="flexible", power_w=600),
        Appliance(id="iron", name="Iron", category="deferrable", power_w=1000),
    ]
    r = compute_nominal_planned_energy(appliances)
    # critical: 0.1 * 24 = 2.4
    # flexible: 0.6 * 4 = 2.4
    # deferrable: 1.0 * 2 = 2.0
    # total = 6.8 kWh
    assert abs(r.E_plan_24h_kwh - 6.8) < 0.01
    assert abs(r.P_avg_kw - (6.8 / 24.0)) < 0.01


def test_nominal_default_runtimes():
    assert DEFAULT_HOURS_CRITICAL == 24.0
    assert DEFAULT_HOURS_FLEXIBLE == 4.0
    assert DEFAULT_HOURS_DEFERRABLE == 2.0
