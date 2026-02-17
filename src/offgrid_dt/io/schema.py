from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

LoadCategory = Literal["critical", "flexible", "deferrable"]
LoadSource = Literal["tasks", "ukdale"]


class UKDALEConfig(BaseModel):
    """
    Configuration for measured-load validation using UK-DALE.
    Notes:
    - UK-DALE provides aggregate (whole-home) demand; no appliance disaggregation is required.
    - This config is meant for research_mode / validation runs, typically via CLI.
    """
    dataset_root: str = Field(
        description="Local path to UK-DALE dataset root (keep outside repo / gitignored)."
    )
    house_id: str = Field(default="1", description="UK-DALE house identifier (e.g., '1', '2', ...).")
    channel: str = Field(
        default="mains",
        description="Aggregate channel name (implementation-dependent, e.g., 'mains' or 'mains.dat').",
    )

    start_date: str = Field(
        description="Validation start date in ISO format, e.g., '2014-01-01'."
    )
    end_date: str = Field(
        description="Validation end date in ISO format (inclusive or exclusive per loader), e.g., '2014-01-28'."
    )

    resample_minutes: int = Field(
        default=15, ge=1, le=60, description="Resample interval for aggregate demand."
    )
    timezone: str = Field(
        default="Europe/London",
        description="Timezone for aligning measured demand and reporting (UK default).",
    )

    critical_baseline_kw: float = Field(
        default=0.15,
        ge=0.0,
        description="Fixed critical baseline demand (kW) used to split measured demand into critical + discretionary.",
    )


class ValidationConfig(BaseModel):
    """
    Optional validation controls for research-mode runs.
    Keep this minimal; plotting and report generation can be handled by scripts.
    """
    enabled: bool = Field(default=False)
    output_dir: str = Field(default="outputs/validation")
    save_daily_csv: bool = Field(default=True)
    save_figures: bool = Field(default=True)


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
    # 24h @ 15-min resolution => 96 steps (aligns with manuscript and plots)
    horizon_steps: int = Field(default=96, ge=4, le=288)

    # Demand source selection
    load_source: LoadSource = Field(
        default="tasks",
        description="Demand source: 'tasks' uses appliance/task model; 'ukdale' uses measured aggregate demand.",
    )
    ukdale: Optional[UKDALEConfig] = Field(
        default=None, description="UK-DALE configuration, required when load_source='ukdale'."
    )
    validation: Optional[ValidationConfig] = Field(
        default=None, description="Optional validation controls (research_mode runs)."
    )


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
    served_task_ids: List[str] = Field(default_factory=list)
    deferred_task_ids: List[str] = Field(default_factory=list)
    shed_task_ids: List[str] = Field(default_factory=list)


class Guidance(BaseModel):
    headline: str
    explanation: str
    risk_level: Literal["low", "medium", "high"]
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)
    dominant_factors: Dict[str, float] = Field(default_factory=dict)


class StepRecord(BaseModel):
    timestamp: datetime
    step_index: int

    pv_now_kw: float
    pv_forecast_kw: List[float] = Field(default_factory=list)

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

    kpis_running: Dict[str, float] = Field(default_factory=dict)
