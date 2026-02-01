from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from offgrid_dt.io.schema import ControlDecision, SystemConfig, TaskInstance


@dataclass
class ControllerInput:
    step: int
    soc: float
    pv_now_kw: float
    pv_forecast_kw: List[float]
    critical_base_kw: float
    pending_tasks: Dict[str, TaskInstance]
    remaining_steps: Dict[str, int]


class BaseController:
    name: str = "base"

    def decide(self, cfg: SystemConfig, inp: ControllerInput) -> ControlDecision:
        raise NotImplementedError


class NaiveController(BaseController):
    name = "naive"

    def decide(self, cfg: SystemConfig, inp: ControllerInput) -> ControlDecision:
        # Serve everything that's available until SOC hits reserve
        serve = []
        shed = []
        if inp.soc <= cfg.soc_min + 1e-6:
            # protect battery; still attempt critical via direct PV if possible
            shed = list(inp.pending_tasks.keys())
        else:
            serve = [tid for tid, t in inp.pending_tasks.items() if t.earliest_start_step <= inp.step < t.latest_end_step]
        return ControlDecision(charge_kw=0.0, discharge_kw=0.0, served_task_ids=serve, deferred_task_ids=[], shed_task_ids=shed)


class StaticPriorityController(BaseController):
    name = "static_priority"

    def decide(self, cfg: SystemConfig, inp: ControllerInput) -> ControlDecision:
        serve = []
        deferred = []
        shed = []
        # Always allow critical base (handled in simulator). For tasks:
        for tid, t in inp.pending_tasks.items():
            if not (t.earliest_start_step <= inp.step < t.latest_end_step):
                continue
            if t.category == "deferrable":
                # only if SOC comfortably above reserve
                (serve if inp.soc >= cfg.soc_min + 0.10 else deferred).append(tid)
            else:
                # flexible
                (serve if inp.soc >= cfg.soc_min + 0.05 else deferred).append(tid)

        if inp.soc <= cfg.soc_min + 1e-6:
            shed = list(set(deferred))
            deferred = []
        return ControlDecision(0.0, 0.0, serve, deferred, shed)


class RuleBasedController(BaseController):
    name = "rule_based"

    def decide(self, cfg: SystemConfig, inp: ControllerInput) -> ControlDecision:
        # If PV now is strong, allow tasks; otherwise conserve.
        serve = []
        deferred = []
        for tid, t in inp.pending_tasks.items():
            if not (t.earliest_start_step <= inp.step < t.latest_end_step):
                continue
            if inp.pv_now_kw >= inp.critical_base_kw + (t.power_w / 1000.0):
                serve.append(tid)
            else:
                deferred.append(tid)

        # Simple charge/discharge suggestion (simulator respects feasibility)
        charge_kw = max(0.0, inp.pv_now_kw - inp.critical_base_kw)
        discharge_kw = 0.0
        if inp.pv_now_kw < inp.critical_base_kw and inp.soc > cfg.soc_min:
            discharge_kw = min(cfg.inverter_max_kw, inp.critical_base_kw - inp.pv_now_kw)
        return ControlDecision(charge_kw=charge_kw, discharge_kw=discharge_kw, served_task_ids=serve, deferred_task_ids=deferred, shed_task_ids=[])


class ForecastAwareHeuristicController(BaseController):
    name = "forecast_heuristic"

    def decide(self, cfg: SystemConfig, inp: ControllerInput) -> ControlDecision:
        # Policy intent:
        # - Protect reserve when PV forecast is poor
        # - Use PV surplus windows to complete tasks
        # - Prefer must-complete deferrable tasks as window closes
        horizon_avg = sum(inp.pv_forecast_kw[: min(len(inp.pv_forecast_kw), 12)]) / max(1, min(len(inp.pv_forecast_kw), 12))
        pv_outlook_low = horizon_avg < 0.25 * cfg.pv_capacity_kw

        serve = []
        deferred = []

        candidates = [t for t in inp.pending_tasks.values() if t.earliest_start_step <= inp.step < t.latest_end_step]
        # urgency score: closer to deadline + must-complete
        def score(t: TaskInstance) -> Tuple[float, float]:
            slack = max(0, t.latest_end_step - inp.step)
            urgency = 1.0 / max(1.0, float(slack))
            must = 1.0 if t.must_complete else 0.0
            # prefer flexible when PV strong, deferrable when urgent
            return (must + urgency, t.power_w)

        candidates.sort(key=score, reverse=True)

        # Allow task power budget based on PV surplus and SOC headroom
        soc_headroom = max(0.0, inp.soc - cfg.soc_min)
        # conservative if outlook is low
        reserve_factor = 0.5 if pv_outlook_low else 1.0
        allowed_from_battery_kw = reserve_factor * soc_headroom * cfg.battery_capacity_kwh / (cfg.timestep_minutes / 60.0)
        budget_kw = max(0.0, inp.pv_now_kw - inp.critical_base_kw) + min(cfg.inverter_max_kw, allowed_from_battery_kw)

        used_kw = 0.0
        for t in candidates:
            pkw = t.power_w / 1000.0
            if used_kw + pkw <= budget_kw + 1e-9:
                serve.append(t.task_id)
                used_kw += pkw
            else:
                deferred.append(t.task_id)

        # charge/discharge suggestion
        net_surplus_kw = inp.pv_now_kw - (inp.critical_base_kw + used_kw)
        charge_kw = max(0.0, min(cfg.inverter_max_kw, net_surplus_kw))
        discharge_kw = 0.0
        if net_surplus_kw < 0 and inp.soc > cfg.soc_min:
            discharge_kw = min(cfg.inverter_max_kw, abs(net_surplus_kw))

        return ControlDecision(charge_kw=charge_kw, discharge_kw=discharge_kw, served_task_ids=serve, deferred_task_ids=deferred, shed_task_ids=[])


def get_controllers() -> List[BaseController]:
    return [NaiveController(), RuleBasedController(), StaticPriorityController(), ForecastAwareHeuristicController()]
