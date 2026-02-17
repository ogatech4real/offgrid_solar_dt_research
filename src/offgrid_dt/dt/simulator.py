from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

import numpy as np

from offgrid_dt.control.controllers import BaseController, ControllerInput
from offgrid_dt.dt.battery import BatteryState, update_soc
from offgrid_dt.dt.load import build_daily_tasks, requested_kw_for_step
from offgrid_dt.planning.nominal_plan import compute_nominal_planned_energy
from offgrid_dt.forecast.nasa_power import get_expected_ghi_next_24h
from offgrid_dt.forecast.openweather import synthetic_irradiance_forecast
from offgrid_dt.forecast.pv_power import irradiance_to_pv_power_kw
from offgrid_dt.io.logger import RunLogger
from offgrid_dt.io.schema import Appliance, StepRecord, SystemConfig
from offgrid_dt.matching import compute_day_ahead_matching
from offgrid_dt.metrics.kpis import KPITracker
from offgrid_dt.xai.explain import (
    ExplanationContext,
    enhance_explanation_with_openai,
    generate_guidance,
)


def simulate(
    cfg: SystemConfig,
    appliances: List[Appliance],
    controller: BaseController,
    days: int = 7,
    seed: int = 42,
    openweather_api_key: Optional[str] = None,
    openweather_base_url: str = "https://api.openweathermap.org",
    openai_api_key: Optional[str] = None,
    openai_model: str = "gpt-4o-mini",
    out_dir: Optional[Path] = None,
    reference_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Run closed-loop day-ahead planning simulation and write logs.

    Solar input is from NASA POWER (GHI for the next planning day(s)); OpenWeather
    is not used for irradiance. Simulation timeline starts at 00:00 UTC of the
    first planning day (next calendar day) so that all PV is NASA-derived.

    Supports two demand modes:
    - cfg.load_source == "tasks": task-based household demand (default).
    - cfg.load_source == "ukdale": measured aggregate demand per day (research validation mode).
      This requires a UK-DALE loader module (added in research_mode repo) that provides
      (total_kw_series, crit_kw_series) per day.

    Returns paths to generated log files and start_time.
    """
    rng = np.random.default_rng(seed)
    dt_minutes = cfg.timestep_minutes
    timestep_hours = dt_minutes / 60.0
    steps_per_day = int(round(24 / timestep_hours))
    total_steps = steps_per_day * days

    log = logging.getLogger("offgrid_dt")

    def _resample_to_steps(series: List[float], target_len: int) -> List[float]:
        """Resample a forecast series to match simulator step resolution.

        Handles common cases:
        - hourly series -> 15-min steps (repeat)
        - shorter/longer arbitrary series (linear interpolation)
        """
        if not series:
            return [0.0] * target_len
        if len(series) == target_len:
            return series
        if target_len % len(series) == 0:
            factor = target_len // len(series)
            return [v for v in series for _ in range(factor)]
        x_old = np.linspace(0.0, 1.0, num=len(series))
        x_new = np.linspace(0.0, 1.0, num=target_len)
        y_new = np.interp(x_new, x_old, np.asarray(series, dtype=float))
        return [float(v) for v in y_new]

    # Day-ahead planning: first planning day = next calendar day 00:00–24:00 UTC
    now_utc = reference_utc or datetime.now(tz=timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    first_planning_date = now_utc.date() + timedelta(days=1)
    start = datetime(
        first_planning_date.year,
        first_planning_date.month,
        first_planning_date.day,
        0,
        0,
        0,
        tzinfo=timezone.utc,
    )

    # PV forecast: get_expected_ghi_next_24h tries DOY±3 last year, then yesterday, then synthetic
    pv_forecast_kw_full: List[float] = []
    solar_source: str = "synthetic"
    try:
        irr, solar_source = get_expected_ghi_next_24h(
            lat=cfg.latitude,
            lon=cfg.longitude,
            reference_utc=now_utc,
        )
        if irr:
            irr_multi = irr * days if days > 1 else irr
            pv_forecast_kw_full = irradiance_to_pv_power_kw(
                irr_multi, cfg.pv_capacity_kw, cfg.pv_efficiency
            )
            log.info("Solar source: %s (%d points)", solar_source, len(irr_multi))
    except Exception as e:
        log.warning("NASA POWER GHI failed (%s); using synthetic.", e)

    if not pv_forecast_kw_full:
        irr = synthetic_irradiance_forecast(
            start=start, hours=24 * days, step_minutes=dt_minutes
        )
        pv_forecast_kw_full = irradiance_to_pv_power_kw(
            irr, cfg.pv_capacity_kw, cfg.pv_efficiency
        )
        solar_source = "synthetic"

    # Resample to simulator resolution (e.g. 15-min)
    pv_forecast_kw_full = _resample_to_steps(pv_forecast_kw_full, total_steps)

    # Logger
    out_dir = out_dir or Path("logs") / f"run_{controller.name}"
    logger = RunLogger(out_dir=out_dir)

    battery = BatteryState(soc=cfg.soc_init)
    kpis = KPITracker()

    # Task-mode state
    pending_tasks: Dict[str, Any] = {}
    remaining_steps: Dict[str, int] = {}
    active_task_id: Optional[str] = None
    critical_base_kw: float = 0.0

    # UK-DALE mode state (per-day demand series)
    measured_total_kw_series: List[float] = []
    measured_crit_kw_series: List[float] = []

    def _load_measured_day_series(day_start_utc: datetime) -> None:
        """Populate measured_total_kw_series and measured_crit_kw_series for the given day."""
        nonlocal measured_total_kw_series, measured_crit_kw_series

        if cfg.ukdale is None:
            raise ValueError("cfg.ukdale must be set when cfg.load_source='ukdale'.")

        try:
            # This module is introduced in research_mode repo.
            # It must expose:
            #   load_ukdale_day_profile(cfg.ukdale, day_start_utc, steps_per_day) -> (total_kw, crit_kw)
            from offgrid_dt.data.ukdale_loader import load_ukdale_day_profile  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "UK-DALE demand mode selected but loader is missing. "
                "Add offgrid_dt/data/ukdale_loader.py with load_ukdale_day_profile()."
            ) from e

        total_kw, crit_kw = load_ukdale_day_profile(
            ukdale_cfg=cfg.ukdale,
            day_start_utc=day_start_utc,
            steps_per_day=steps_per_day,
            timestep_minutes=dt_minutes,
        )

        if len(total_kw) != steps_per_day or len(crit_kw) != steps_per_day:
            raise ValueError(
                f"UK-DALE loader returned lengths total={len(total_kw)} crit={len(crit_kw)}; "
                f"expected {steps_per_day}."
            )

        measured_total_kw_series = [float(v) for v in total_kw]
        measured_crit_kw_series = [float(v) for v in crit_kw]

    for step in range(total_steps):
        day_step = step % steps_per_day

        if day_step == 0:
            day_start_utc = start + timedelta(days=step // steps_per_day)

            if cfg.load_source == "ukdale":
                _load_measured_day_series(day_start_utc)
                # No tasks used in measured-demand validation
                pending_tasks = {}
                remaining_steps = {}
                active_task_id = None
                # Keep a representative critical baseline for explainability text
                critical_base_kw = float(
                    np.mean(measured_crit_kw_series) if measured_crit_kw_series else 0.0
                )
            else:
                # tasks mode (default)
                critical_base_kw, tasks = build_daily_tasks(
                    appliances, steps_per_day, rng
                )
                pending_tasks = {t.task_id: t for t in tasks}
                remaining_steps = {t.task_id: t.duration_steps for t in tasks}
                active_task_id = None

        pv_now_kw = pv_forecast_kw_full[step] if step < len(pv_forecast_kw_full) else 0.0

        # Rolling horizon PV forecast
        pv_forecast = pv_forecast_kw_full[step : step + cfg.horizon_steps]
        if len(pv_forecast) < cfg.horizon_steps:
            pv_forecast = pv_forecast + [0.0] * (cfg.horizon_steps - len(pv_forecast))

        if cfg.load_source == "ukdale":
            total_req_kw = measured_total_kw_series[day_step]
            crit_req_kw = measured_crit_kw_series[day_step]
            available_task_ids: List[str] = []
            window_tasks: Dict[str, Any] = {}
        else:
            total_req_kw, crit_req_kw, available_task_ids = requested_kw_for_step(
                critical_base_kw, list(pending_tasks.values()), day_step
            )
            # Controller input uses only tasks that are still pending and in-window
            window_tasks = {
                tid: pending_tasks[tid]
                for tid in available_task_ids
                if tid in pending_tasks
            }

        inp = ControllerInput(
            step=day_step,
            soc=battery.soc,
            pv_now_kw=pv_now_kw,
            pv_forecast_kw=pv_forecast,
            critical_base_kw=critical_base_kw,
            pending_tasks=window_tasks,
            remaining_steps=remaining_steps,
        )

        # Controller still runs (for consistent logging), but in ukdale mode it will have no tasks.
        decision = controller.decide(cfg, inp)

        # Serve critical first (simple feasibility rule)
        crit_served_kw = min(
            crit_req_kw,
            pv_now_kw + (cfg.inverter_max_kw if battery.soc > cfg.soc_min else 0.0),
        )

        # Determine which tasks can be served this step (tasks mode only)
        served_tasks: List[str] = []
        served_task_kw = 0.0

        if cfg.load_source != "ukdale":
            if (
                active_task_id
                and active_task_id in window_tasks
                and remaining_steps.get(active_task_id, 0) > 0
            ):
                forced = window_tasks[active_task_id]
                served_tasks = [active_task_id]
                served_task_kw = forced.power_w / 1000.0
            else:
                active_task_id = None
                for tid in decision.served_task_ids:
                    if tid not in window_tasks:
                        continue
                    t = window_tasks[tid]
                    served_tasks.append(tid)
                    served_task_kw += t.power_w / 1000.0
                    if t.duration_steps > 1:
                        active_task_id = tid
                        break

        # Compute total served load
        if cfg.load_source == "ukdale":
            # After serving critical, attempt to serve remaining measured demand as discretionary (within inverter/battery limits)
            discretionary_req_kw = max(0.0, total_req_kw - crit_req_kw)
            available_supply_kw = pv_now_kw + (cfg.inverter_max_kw if battery.soc > cfg.soc_min else 0.0)
            remaining_supply_kw = max(0.0, available_supply_kw - crit_served_kw)
            discretionary_served_kw = min(discretionary_req_kw, remaining_supply_kw)
            load_served_kw = crit_served_kw + discretionary_served_kw
            served_task_kw = discretionary_served_kw  # for guidance "used_kw"
        else:
            load_served_kw = crit_served_kw + served_task_kw

        # Battery interaction
        net_kw = pv_now_kw - load_served_kw
        charge_kw = max(0.0, min(cfg.inverter_max_kw, net_kw))
        discharge_kw = 0.0
        if net_kw < 0 and battery.soc > cfg.soc_min:
            discharge_kw = min(cfg.inverter_max_kw, abs(net_kw))

        # Update battery
        battery = update_soc(
            battery,
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            timestep_hours=timestep_hours,
            battery_capacity_kwh=cfg.battery_capacity_kwh,
            charge_eff=cfg.charge_eff,
            discharge_eff=cfg.discharge_eff,
            soc_min=cfg.soc_min,
            soc_max=cfg.soc_max,
        )

        curtailed_kw = max(0.0, pv_now_kw - load_served_kw - charge_kw)

        # Mark task progress (tasks mode only)
        if cfg.load_source != "ukdale":
            for tid in served_tasks:
                remaining_steps[tid] = max(0, remaining_steps.get(tid, 0) - 1)
                if remaining_steps[tid] <= 0:
                    pending_tasks.pop(tid, None)
                    if active_task_id == tid:
                        active_task_id = None

        # Explainability
        pv_avg_next2h = sum(pv_forecast[:8]) / 8.0
        guidance = generate_guidance(
            cfg,
            ExplanationContext(
                soc=battery.soc,
                pv_now_kw=pv_now_kw,
                pv_avg_next2h_kw=pv_avg_next2h,
                critical_kw=critical_base_kw if cfg.load_source != "ukdale" else float(np.mean(measured_crit_kw_series)),
            ),
            used_kw=served_task_kw,
            deferred_count=len(decision.deferred_task_ids),
        )
        guidance = enhance_explanation_with_openai(
            openai_api_key, openai_model, guidance, household_context=cfg.location_name
        )

        # KPIs
        kpis.update(
            timestep_hours=timestep_hours,
            crit_req_kw=crit_req_kw,
            crit_served_kw=crit_served_kw,
            total_req_kw=total_req_kw,
            served_kw=load_served_kw,
            pv_now_kw=pv_now_kw,
            curtailed_kw=curtailed_kw,
            throughput_kwh=battery.throughput_kwh,
        )

        rec = StepRecord(
            timestamp=start + timedelta(minutes=dt_minutes * step),
            step_index=step,
            pv_now_kw=pv_now_kw,
            pv_forecast_kw=pv_forecast,
            soc_now=battery.soc,
            soc_min=cfg.soc_min,
            soc_max=cfg.soc_max,
            load_requested_kw=total_req_kw,
            load_served_kw=load_served_kw,
            crit_requested_kw=crit_req_kw,
            crit_served_kw=crit_served_kw,
            curtailed_solar_kw=curtailed_kw,
            decision=decision,
            guidance=guidance,
            kpis_running=kpis.snapshot(),
        )
        logger.append(rec)

    prefix = f"{controller.name}_{days}d"
    out = logger.flush(prefix=prefix)
    if out:
        out["start_time"] = start.isoformat()
        out["solar_source"] = solar_source
        out["load_source"] = getattr(cfg, "load_source", "tasks")

        # Planned energy is meaningful for task-mode. For ukdale, we report measured energy instead.
        try:
            if cfg.load_source == "ukdale":
                # measured demand for first day
                out["planned_energy_kwh"] = float(np.sum(measured_total_kw_series) * timestep_hours)
            else:
                nominal = compute_nominal_planned_energy(appliances, include_12h=False)
                out["planned_energy_kwh"] = nominal.E_plan_24h_kwh
        except Exception as e:
            log.warning("Planned energy computation failed: %s", e)

        # Day-ahead matching: compare expected demand vs solar for first planning day
        try:
            import pandas as pd

            state_path = out.get("state_csv")
            if state_path:
                mdf = pd.read_csv(state_path)
                first_day_df = mdf.head(steps_per_day)
                matching = compute_day_ahead_matching(
                    first_day_df,
                    appliances,
                    cfg,
                    inverter_max_kw=cfg.inverter_max_kw,
                    timestep_minutes=cfg.timestep_minutes,
                    day_start_ts=start,
                )
                out["matching_first_day"] = matching.to_dict()
        except Exception as e:
            log.warning("Day-ahead matching failed: %s", e)

    return out
