from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .openweather import IrradiancePoint


def irradiance_to_pv_power_kw(
    points: List[IrradiancePoint],
    pv_capacity_kw: float,
    pv_efficiency: float = 0.18,
    ref_irradiance_wm2: float = 1000.0,
) -> List[float]:
    out: List[float] = []
    for p in points:
        scale = max(0.0, float(p.ghi_wm2) / ref_irradiance_wm2)
        out.append(pv_capacity_kw * scale * (pv_efficiency / 0.18))
    return out


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
