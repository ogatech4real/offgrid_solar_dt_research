from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

import numpy as np

from offgrid_dt.control.controllers import BaseController, ControllerInput
from offgrid_dt.dt.battery import BatteryState, update_soc
from offgrid_dt.dt.load import build_daily_tasks, requested_kw_for_step
from offgrid_dt.forecast.openweather import OpenWeatherSolarClient, synthetic_irradiance_forecast
from offgrid_dt.forecast.pv_power import irradiance_to_pv_power_kw
from offgrid_dt.io.logger import RunLogger
from offgrid_dt.io.schema import Appliance, StepRecord, SystemConfig
from offgrid_dt.metrics.kpis import KPITracker
from offgrid_dt.xai.explain import ExplanationContext, enhance_explanation_with_openai, generate_guidance


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
) -> Dict[str, str]:
    """Run closed-loop simulation and write logs.

    Returns paths to generated log files.
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
        # generic linear interpolation
        x_old = np.linspace(0.0, 1.0, num=len(series))
        x_new = np.linspace(0.0, 1.0, num=target_len)
        y_new = np.interp(x_new, x_old, np.asarray(series, dtype=float))
        return [float(v) for v in y_new]

    # PV forecast source
    start = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    pv_forecast_kw_full: List[float] = []
    try:
        if openweather_api_key:
            client = OpenWeatherSolarClient(openweather_api_key, base_url=openweather_base_url)
            irr = client.fetch_irradiance_forecast(cfg.latitude, cfg.longitude, hours=24 * days)
        else:
            irr = synthetic_irradiance_forecast(start=start, hours=24 * days, step_minutes=dt_minutes)
        pv_forecast_kw_full = irradiance_to_pv_power_kw(irr, cfg.pv_capacity_kw, cfg.pv_efficiency)
    except Exception:
        log.warning("PV forecast fetch failed; falling back to synthetic irradiance.")
        irr = synthetic_irradiance_forecast(start=start, hours=24 * days, step_minutes=dt_minutes)
        pv_forecast_kw_full = irradiance_to_pv_power_kw(irr, cfg.pv_capacity_kw, cfg.pv_efficiency)

    # Ensure forecast aligns to simulator resolution
    pv_forecast_kw_full = _resample_to_steps(pv_forecast_kw_full, total_steps)

    # Logger
    out_dir = out_dir or Path("logs") / f"run_{controller.name}"
    logger = RunLogger(out_dir=out_dir)

    battery = BatteryState(soc=cfg.soc_init)
    kpis = KPITracker()

    # Build tasks day-by-day
    pending: Dict[str, Appliance] = {}
    pending_tasks: Dict[str, Any] = {}
    remaining_steps: Dict[str, int] = {}

    # Track which tasks are currently running (for multi-step duration)
    active_task_id: Optional[str] = None

    for step in range(total_steps):
        day_step = step % steps_per_day
        if day_step == 0:
            critical_base_kw, tasks = build_daily_tasks(appliances, steps_per_day, rng)
            pending_tasks = {t.task_id: t for t in tasks}
            remaining_steps = {t.task_id: t.duration_steps for t in tasks}
            active_task_id = None

        pv_now_kw = pv_forecast_kw_full[step] if step < len(pv_forecast_kw_full) else 0.0
        # Rolling horizon PV forecast
        pv_forecast = pv_forecast_kw_full[step : step + cfg.horizon_steps]
        if len(pv_forecast) < cfg.horizon_steps:
            pv_forecast = pv_forecast + [0.0] * (cfg.horizon_steps - len(pv_forecast))

        total_req_kw, crit_req_kw, available_task_ids = requested_kw_for_step(critical_base_kw, list(pending_tasks.values()), day_step)

        # Controller input uses only tasks that are still pending and in-window
        window_tasks = {tid: pending_tasks[tid] for tid in available_task_ids if tid in pending_tasks}
        inp = ControllerInput(
            step=day_step,
            soc=battery.soc,
            pv_now_kw=pv_now_kw,
            pv_forecast_kw=pv_forecast,
            critical_base_kw=critical_base_kw,
            pending_tasks=window_tasks,
            remaining_steps=remaining_steps,
        )
        decision = controller.decide(cfg, inp)

        # Enforce inverter/power feasibility with a simple power balance
        # Serve critical first
        crit_served_kw = min(crit_req_kw, pv_now_kw + (cfg.inverter_max_kw if battery.soc > cfg.soc_min else 0.0))

        # Determine which tasks can be served this step
        served_tasks = []
        served_task_kw = 0.0

        # If a multi-step task is active, force-continue it if possible
        if active_task_id and active_task_id in window_tasks and remaining_steps.get(active_task_id, 0) > 0:
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
                # only allow one concurrent multi-step task in this simple MVP
                if t.duration_steps > 1:
                    active_task_id = tid
                    break

        # Compute total served load
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

        # Curtailment: any surplus after max charging
        curtailed_kw = max(0.0, pv_now_kw - load_served_kw - charge_kw)

        # Mark task progress
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
            ExplanationContext(soc=battery.soc, pv_now_kw=pv_now_kw, pv_avg_next2h_kw=pv_avg_next2h, critical_kw=critical_base_kw),
            used_kw=served_task_kw,
            deferred_count=len(decision.deferred_task_ids),
        )
        guidance = enhance_explanation_with_openai(openai_api_key, openai_model, guidance, household_context=cfg.location_name)

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
    return logger.flush(prefix=prefix)
