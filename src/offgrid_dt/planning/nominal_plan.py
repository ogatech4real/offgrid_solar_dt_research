"""Nominal planned energy from appliance config and group default runtimes.

Single source of truth for planned demand used in UI cards, matching, and simulator.
Default runtimes: Critical 24 h/day, Flexible 4 h/day, Deferrable 2 h/day.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from offgrid_dt.io.schema import Appliance

# Group default runtimes (hours per day) for nominal planned energy
DEFAULT_HOURS_CRITICAL = 24.0
DEFAULT_HOURS_FLEXIBLE = 4.0
DEFAULT_HOURS_DEFERRABLE = 2.0


@dataclass
class NominalPlanResult:
    """Result of nominal planned energy computation."""
    E_plan_24h_kwh: float
    P_avg_kw: float
    E_plan_12h_kwh: Optional[float] = None  # 24h * (12/24) when requested


def compute_nominal_planned_energy(
    appliances: List[Appliance],
    hours_critical: float = DEFAULT_HOURS_CRITICAL,
    hours_flexible: float = DEFAULT_HOURS_FLEXIBLE,
    hours_deferrable: float = DEFAULT_HOURS_DEFERRABLE,
    include_12h: bool = True,
) -> NominalPlanResult:
    """Compute nominal planned energy and average power from selected appliance config and group default runtimes.

    Critical: hours_critical (default 24) h/day.
    Flexible: hours_flexible (default 4) h/day.
    Deferrable: hours_deferrable (default 2) h/day.

    Returns:
        E_plan_24h_kwh: planned energy for 24h (kWh)
        P_avg_kw: average power over 24h (kW) = E_plan_24h_kwh / 24
        E_plan_12h_kwh: optional planned energy for 12h (E_plan_24h * 12/24)
    """
    hrs_by_cat = {
        "critical": hours_critical,
        "flexible": hours_flexible,
        "deferrable": hours_deferrable,
    }
    E_plan_24h_kwh = 0.0
    for a in appliances:
        p_kw = a.power_w / 1000.0
        hrs = hrs_by_cat.get(a.category, DEFAULT_HOURS_CRITICAL)
        E_plan_24h_kwh += p_kw * hrs

    P_avg_kw = E_plan_24h_kwh / 24.0 if E_plan_24h_kwh else 0.0
    E_plan_12h_kwh = (E_plan_24h_kwh * (12.0 / 24.0)) if include_12h else None
    return NominalPlanResult(
        E_plan_24h_kwh=E_plan_24h_kwh,
        P_avg_kw=P_avg_kw,
        E_plan_12h_kwh=E_plan_12h_kwh,
    )
