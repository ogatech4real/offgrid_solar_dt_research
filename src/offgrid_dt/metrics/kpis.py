from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KPITracker:
    crit_requested_kwh: float = 0.0
    crit_served_kwh: float = 0.0
    total_requested_kwh: float = 0.0
    solar_used_kwh: float = 0.0
    solar_generated_kwh: float = 0.0
    solar_curtailed_kwh: float = 0.0
    blackout_minutes: int = 0
    throughput_kwh: float = 0.0

    def update(
        self,
        timestep_hours: float,
        crit_req_kw: float,
        crit_served_kw: float,
        total_req_kw: float,
        served_kw: float,
        pv_now_kw: float,
        curtailed_kw: float,
        throughput_kwh: float,
    ) -> None:
        self.crit_requested_kwh += crit_req_kw * timestep_hours
        self.crit_served_kwh += crit_served_kw * timestep_hours
        self.total_requested_kwh += total_req_kw * timestep_hours
        self.solar_generated_kwh += pv_now_kw * timestep_hours
        self.solar_curtailed_kwh += curtailed_kw * timestep_hours
        self.solar_used_kwh += max(0.0, pv_now_kw - curtailed_kw) * timestep_hours
        if crit_served_kw + 1e-9 < crit_req_kw:
            self.blackout_minutes += int(round(timestep_hours * 60))
        self.throughput_kwh = throughput_kwh

    def snapshot(self) -> dict:
        clsr = self.crit_served_kwh / max(1e-9, self.crit_requested_kwh)
        sar = self.solar_used_kwh / max(1e-9, self.total_requested_kwh)
        solar_util = 1.0 - (self.solar_curtailed_kwh / max(1e-9, self.solar_generated_kwh))
        return {
            "CLSR": float(clsr),
            "Blackout_minutes": float(self.blackout_minutes),
            "SAR": float(sar),
            "Solar_utilization": float(solar_util),
            "Battery_throughput_kwh": float(self.throughput_kwh),
        }
