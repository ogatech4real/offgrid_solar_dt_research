from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal

from pydantic import BaseModel, Field

LoadCategory = Literal["critical", "flexible", "deferrable"]


class SystemConfig(BaseModel):
    location_name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0

    pv_capacity_kw: float = Field(gt=0, description="PV peak capacity (kW)")
    pv_efficiency: float = Field(default=0.18, ge=0.05, le=0.30)

    battery_capacity_kwh: float = Field(gt=0)
    inverter_max_kw: float = Field(gt=0)

    soc_init: float = Field(default=0.7, ge=0.0, le=1.0)
    soc_min: float = Field(default=0.25, ge=0.0, le=1.0)
    soc_max: float = Field(default=0.95, ge=0.0, le=1.0)

    charge_eff: float = Field(default=0.95, ge=0.7, le=1.0)
    discharge_eff: float = Field(default=0.95, ge=0.7, le=1.0)

    timestep_minutes: int = Field(default=15, ge=1, le=60)
    horizon_steps: int = Field(default=48, ge=4, le=288)


class Appliance(BaseModel):
    id: str
    name: str
    category: LoadCategory
    power_w: float = Field(gt=0)

    duration_steps: int = Field(default=1, ge=1)
    earliest_start_step: int = Field(default=0, ge=0)
    latest_end_step: int = Field(default=96, ge=1)

    daily_quota_steps: int = Field(default=0, ge=0)


class TaskInstance(BaseModel):
    task_id: str
    appliance_id: str
    name: str
    category: LoadCategory
    power_w: float
    duration_steps: int
    earliest_start_step: int
    latest_end_step: int
    must_complete: bool = False


class ControlDecision(BaseModel):
    charge_kw: float = 0.0
    discharge_kw: float = 0.0
    served_task_ids: List[str] = []
    deferred_task_ids: List[str] = []
    shed_task_ids: List[str] = []


class Guidance(BaseModel):
    headline: str
    explanation: str
    risk_level: Literal["low", "medium", "high"]
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    reason_codes: List[str] = []
    dominant_factors: Dict[str, float] = {}


class StepRecord(BaseModel):
    timestamp: datetime
    step_index: int

    pv_now_kw: float
    pv_forecast_kw: List[float]

    soc_now: float
    soc_min: float
    soc_max: float

    load_requested_kw: float
    load_served_kw: float
    crit_requested_kw: float
    crit_served_kw: float

    curtailed_solar_kw: float

    decision: ControlDecision
    guidance: Guidance

    kpis_running: Dict[str, float] = {}
