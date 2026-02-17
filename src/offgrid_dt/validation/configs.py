# src/offgrid_dt/validation/configs.py  (optional)
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class UKDALEValidationConfig(BaseModel):
    """
    Optional convenience config for validation runs.

    If you already placed UK-DALE config in SystemConfig (schema.py), you can skip this,
    but this file keeps your validation CLI clean and repeatable.
    """
    dataset_root: Path = Field(..., description="Path to UK-DALE root folder")
    house_id: int = Field(..., ge=1, description="UK-DALE house number, e.g. 1")
    start: Optional[str] = Field(default=None, description="ISO start datetime/date (UTC)")
    end: Optional[str] = Field(default=None, description="ISO end datetime/date (UTC)")
    timestep_minutes: int = Field(default=15, ge=1, le=60)

    critical_baseline_kw: float = Field(default=0.20, ge=0.0, description="Fixed critical baseline kW")
    out_dir: Path = Field(default=Path("results") / "validation" / "ukdale")

    # if you want location-specific PV, pass lat/lon here (UK is typical)
    latitude: float = Field(default=54.5742)   # Middlesbrough-ish default
    longitude: float = Field(default=-1.2348)

    pv_capacity_kw: float = Field(default=3.0, gt=0)
    battery_capacity_kwh: float = Field(default=5.0, gt=0)
    inverter_max_kw: float = Field(default=2.5, gt=0)

    soc_init: float = Field(default=0.7, ge=0.0, le=1.0)
    soc_min: float = Field(default=0.25, ge=0.0, le=1.0)
    soc_max: float = Field(default=0.95, ge=0.0, le=1.0)
