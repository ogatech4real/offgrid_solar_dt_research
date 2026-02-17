# src/offgrid_dt/validation/configs.py  (optional)
from __future__ import annotations

from pydantic import BaseModel, Field


class UKDALEValidationRun(BaseModel):
    """
    Optional helper config for CLI validation. This is not required,
    but it keeps validate_ukdale.py clean and repeatable.
    """
    ukdale_root: str = Field(..., description="UK-DALE dataset root")
    house_id: str = Field(default="1")
    start_date: str = Field(..., description="ISO date, e.g. 2014-01-01")
    end_date: str = Field(..., description="ISO date, e.g. 2014-01-28")
    resample_minutes: int = Field(default=15, ge=1, le=60)
    timezone: str = Field(default="Europe/London")
    critical_baseline_kw: float = Field(default=0.15, ge=0.0)

    out_dir: str = Field(default="results/validation/ukdale")
