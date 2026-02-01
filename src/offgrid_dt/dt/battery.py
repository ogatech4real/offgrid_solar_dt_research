from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BatteryState:
    soc: float
    throughput_kwh: float = 0.0


def update_soc(
    state: BatteryState,
    charge_kw: float,
    discharge_kw: float,
    timestep_hours: float,
    battery_capacity_kwh: float,
    charge_eff: float,
    discharge_eff: float,
    soc_min: float,
    soc_max: float,
) -> BatteryState:
    """Update battery SOC and throughput.

    Throughput is tracked as |charge| + |discharge| in kWh per step.
    """
    # energy into battery
    e_in_kwh = max(0.0, charge_kw) * timestep_hours * charge_eff
    # energy out of battery
    e_out_kwh = max(0.0, discharge_kw) * timestep_hours / max(1e-9, discharge_eff)

    soc = state.soc + (e_in_kwh - e_out_kwh) / battery_capacity_kwh
    soc = max(soc_min, min(soc_max, soc))

    throughput = state.throughput_kwh + (abs(charge_kw) + abs(discharge_kw)) * timestep_hours
    return BatteryState(soc=soc, throughput_kwh=throughput)
