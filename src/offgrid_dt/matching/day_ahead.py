"""Day-ahead matching: compare expected demand vs expected solar availability.

Three layers:
1. Daily energy feasibility: total demand vs total solar → energy margin (surplus/tight/deficit).
2. Time-resolved power adequacy: surplus windows (solar ≥ demand) and deficit windows (demand > solar).
3. Priority-aware: critical loads fully protected? Flexible/deferrable shift or avoid?

All outputs are day-ahead planning (00:00–24:00), deterministic and explainable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandas as pd

from offgrid_dt.io.schema import Appliance, SystemConfig

# Advisory status per appliance (traceable to surplus/deficit and priority)
ApplianceStatus = Literal["safe_to_run", "run_only_in_recommended_window", "avoid_today"]
EnergyMarginType = Literal["surplus", "tight", "deficit"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass
class TimeWindow:
    """A contiguous time window (e.g. surplus or deficit)."""
    start_step: int
    end_step: int
    start_ts: datetime
    end_ts: datetime
    label: str = ""


@dataclass
class ApplianceAdvisory:
    """Per-appliance day-ahead advisory from matching (traceable to windows and priority)."""
    appliance_id: str
    name: str
    category: Literal["critical", "flexible", "deferrable"]
    status: ApplianceStatus
    recommended_window: Optional[str] = None  # e.g. "08:00–14:00"
    reason: str = ""


@dataclass
class DayAheadMatchingResult:
    """Result of day-ahead demand vs solar matching (first planning day 00:00–24:00)."""
    # Daily energy feasibility
    total_solar_kwh: float
    total_demand_kwh: float
    energy_margin_kwh: float
    energy_margin_type: EnergyMarginType
    daily_outlook_text: str

    # Time-resolved power adequacy
    surplus_windows: List[TimeWindow] = field(default_factory=list)
    deficit_windows: List[TimeWindow] = field(default_factory=list)
    min_power_margin_kw: float = 0.0  # min over steps of (pv - load)

    # Priority-aware
    critical_fully_protected: bool = True
    critical_shortfall_steps: List[int] = field(default_factory=list)
    flexible_deferrable_shortfall_steps: List[int] = field(default_factory=list)

    # Risk and advisories
    risk_level: RiskLevel = "low"
    appliance_advisories: List[ApplianceAdvisory] = field(default_factory=list)

    # Metadata
    day_start_ts: Optional[datetime] = None
    timestep_minutes: int = 15
    steps_per_day: int = 96

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable dict for UI/PDF (datetimes as isoformat)."""
        def _tw_dict(tw: TimeWindow) -> Dict[str, Any]:
            return {
                "start_step": tw.start_step,
                "end_step": tw.end_step,
                "start_ts": tw.start_ts.isoformat() if tw.start_ts else None,
                "end_ts": tw.end_ts.isoformat() if tw.end_ts else None,
                "label": tw.label,
            }
        def _adv_dict(adv: ApplianceAdvisory) -> Dict[str, Any]:
            return {
                "appliance_id": adv.appliance_id,
                "name": adv.name,
                "category": adv.category,
                "status": adv.status,
                "recommended_window": adv.recommended_window,
                "reason": adv.reason,
            }
        return {
            "total_solar_kwh": self.total_solar_kwh,
            "total_demand_kwh": self.total_demand_kwh,
            "energy_margin_kwh": self.energy_margin_kwh,
            "energy_margin_type": self.energy_margin_type,
            "daily_outlook_text": self.daily_outlook_text,
            "surplus_windows": [_tw_dict(tw) for tw in self.surplus_windows],
            "deficit_windows": [_tw_dict(tw) for tw in self.deficit_windows],
            "min_power_margin_kw": self.min_power_margin_kw,
            "critical_fully_protected": self.critical_fully_protected,
            "risk_level": self.risk_level,
            "appliance_advisories": [_adv_dict(a) for a in self.appliance_advisories],
            "timestep_minutes": self.timestep_minutes,
        }


def _merge_adjacent_windows(step_flags: List[bool], timestamps: List[datetime]) -> List[TimeWindow]:
    """Convert per-step boolean (True = surplus or deficit) into contiguous TimeWindow list."""
    if not step_flags or not timestamps or len(step_flags) != len(timestamps):
        return []
    windows: List[TimeWindow] = []
    in_window = False
    start_step = 0
    for i, flag in enumerate(step_flags):
        if flag and not in_window:
            in_window = True
            start_step = i
        elif not flag and in_window:
            in_window = False
            windows.append(TimeWindow(
                start_step=start_step,
                end_step=i - 1,
                start_ts=timestamps[start_step],
                end_ts=timestamps[i - 1],
            ))
    if in_window:
        windows.append(TimeWindow(
            start_step=start_step,
            end_step=len(step_flags) - 1,
            start_ts=timestamps[start_step],
            end_ts=timestamps[-1],
        ))
    return windows


def _format_window_times(tw: TimeWindow, timestep_minutes: int) -> str:
    """Format time window as HH:MM–HH:MM."""
    start_min = tw.start_step * timestep_minutes
    end_min = (tw.end_step + 1) * timestep_minutes
    sh, sm = divmod(start_min, 60)
    eh, em = divmod(end_min, 60)
    return f"{int(sh):02d}:{int(sm):02d}–{int(eh):02d}:{int(em):02d}"


def compute_day_ahead_matching(
    state_df: pd.DataFrame,
    appliances: List[Appliance],
    cfg: SystemConfig,
    inverter_max_kw: float,
    timestep_minutes: int = 15,
    day_start_ts: Optional[datetime] = None,
) -> DayAheadMatchingResult:
    """Compare expected demand vs expected solar for the first planning day (00:00–24:00).

    Uses per-step pv_now_kw and load_requested_kw from state_df (first 24h).
    Deterministic and explainable; no opaque AI. Battery is not included in
    surplus/deficit (solar-only comparison); UI can note battery may help during deficits.

    Returns DayAheadMatchingResult with daily outlook, surplus/deficit windows,
    priority-aware flags, risk level, and appliance-level advisories.
    """
    steps_per_day = int(24 * 60 / timestep_minutes)
    dt_hours = timestep_minutes / 60.0

    # Use first day only
    day_df = state_df.head(steps_per_day).copy()
    if day_df.empty:
        return _empty_result(timestep_minutes, steps_per_day, day_start_ts)

    day_df["ts"] = pd.to_datetime(day_df["timestamp"], utc=True)
    timestamps = day_df["ts"].tolist()
    pv_kw = day_df["pv_now_kw"].fillna(0.0).to_numpy(dtype=float)
    load_kw = day_df["load_requested_kw"].fillna(0.0).to_numpy(dtype=float)
    crit_kw = day_df["crit_requested_kw"].fillna(0.0).to_numpy(dtype=float)

    # 1) Daily energy feasibility
    total_solar_kwh = float(pv_kw.sum()) * dt_hours
    total_demand_kwh = float(load_kw.sum()) * dt_hours
    energy_margin_kwh = total_solar_kwh - total_demand_kwh

    # Margin type: surplus if margin > 5% of demand, deficit if < -5%, else tight
    if total_demand_kwh <= 0:
        energy_margin_type: EnergyMarginType = "surplus"
    elif energy_margin_kwh > 0.05 * total_demand_kwh:
        energy_margin_type = "surplus"
    elif energy_margin_kwh < -0.05 * total_demand_kwh:
        energy_margin_type = "deficit"
    else:
        energy_margin_type = "tight"

    if energy_margin_type == "surplus":
        daily_outlook_text = "Solar energy is sufficient for the day (expected surplus)."
    elif energy_margin_type == "tight":
        daily_outlook_text = (
            f"Solar and demand are closely matched. Small margin: {energy_margin_kwh:+.2f} kWh. "
            "Consider shifting flexible loads into surplus windows."
        )
    else:
        daily_outlook_text = (
            f"Expected shortfall of {abs(energy_margin_kwh):.2f} kWh. "
            "Prioritise critical loads; run flexible/deferrable only in surplus windows or avoid today."
        )

    # 2) Time-resolved power adequacy: surplus when pv >= load, deficit when load > pv
    power_margin_kw = pv_kw - load_kw
    min_power_margin_kw = float(power_margin_kw.min())
    surplus_step = pv_kw >= load_kw
    deficit_step = load_kw > pv_kw
    surplus_windows = _merge_adjacent_windows(surplus_step.tolist(), timestamps)
    deficit_windows = _merge_adjacent_windows(deficit_step.tolist(), timestamps)
    for tw in surplus_windows:
        tw.label = "surplus"
    for tw in deficit_windows:
        tw.label = "deficit"

    # 3) Priority-aware: critical fully protected when pv >= crit at every step where crit > 0
    critical_fully_protected = True
    critical_shortfall_steps: List[int] = []
    for i in range(len(pv_kw)):
        if crit_kw[i] > 0 and pv_kw[i] < crit_kw[i]:
            critical_fully_protected = False
            critical_shortfall_steps.append(i)
    flexible_deferrable_shortfall_steps = [i for i in range(len(pv_kw)) if deficit_step[i]]

    # 4) Risk level from worst-case margin (energy and power)
    if not critical_fully_protected or energy_margin_kwh < -0.5:
        risk_level: RiskLevel = "high"
    elif energy_margin_kwh < 0 or min_power_margin_kw < -0.5:
        risk_level = "medium"
    else:
        risk_level = "low"

    # 5) Appliance-level advisories (traceable to surplus/deficit and category)
    appliance_advisories = _compute_appliance_advisories(
        appliances=appliances,
        critical_fully_protected=critical_fully_protected,
        surplus_windows=surplus_windows,
        deficit_windows=deficit_windows,
        energy_margin_type=energy_margin_type,
        timestep_minutes=timestep_minutes,
    )

    return DayAheadMatchingResult(
        total_solar_kwh=total_solar_kwh,
        total_demand_kwh=total_demand_kwh,
        energy_margin_kwh=energy_margin_kwh,
        energy_margin_type=energy_margin_type,
        daily_outlook_text=daily_outlook_text,
        surplus_windows=surplus_windows,
        deficit_windows=deficit_windows,
        min_power_margin_kw=min_power_margin_kw,
        critical_fully_protected=critical_fully_protected,
        critical_shortfall_steps=critical_shortfall_steps,
        flexible_deferrable_shortfall_steps=flexible_deferrable_shortfall_steps,
        risk_level=risk_level,
        appliance_advisories=appliance_advisories,
        day_start_ts=day_start_ts or (timestamps[0] if timestamps else None),
        timestep_minutes=timestep_minutes,
        steps_per_day=steps_per_day,
    )


def _empty_result(
    timestep_minutes: int,
    steps_per_day: int,
    day_start_ts: Optional[datetime],
) -> DayAheadMatchingResult:
    return DayAheadMatchingResult(
        total_solar_kwh=0.0,
        total_demand_kwh=0.0,
        energy_margin_kwh=0.0,
        energy_margin_type="tight",
        daily_outlook_text="No data for first planning day. Run the digital twin to generate a day-ahead outlook.",
        min_power_margin_kw=0.0,
        critical_fully_protected=True,
        risk_level="medium",
        appliance_advisories=[],
        day_start_ts=day_start_ts,
        timestep_minutes=timestep_minutes,
        steps_per_day=steps_per_day,
    )


def _compute_appliance_advisories(
    appliances: List[Appliance],
    critical_fully_protected: bool,
    surplus_windows: List[TimeWindow],
    deficit_windows: List[TimeWindow],
    energy_margin_type: EnergyMarginType,
    timestep_minutes: int,
) -> List[ApplianceAdvisory]:
    """Derive appliance status from surplus/deficit windows, load category, and duration.

    Each advisory is unique and verifiable: uses actual surplus/deficit times from the
    day-ahead solar vs demand comparison, and appliance duration_steps to recommend
    windows long enough for each load.
    """
    advisories: List[ApplianceAdvisory] = []
    surplus_coverage_ratio = _surplus_coverage_ratio(surplus_windows, timestep_minutes)
    has_surplus_windows = len(surplus_windows) > 0
    deficit_times_str = _format_windows_list(deficit_windows, timestep_minutes) if deficit_windows else ""

    for a in appliances:
        power_kw = float(a.power_w) / 1000.0
        duration_steps = max(1, getattr(a, "duration_steps", 1))

        if a.category == "critical":
            if critical_fully_protected:
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category="critical",
                    status="safe_to_run",
                    reason=f"Your {a.name} ({power_kw:.2f} kW) is covered by expected solar all day.",
                ))
            else:
                shortfall_phrase = (
                    f"Shortfall expected {deficit_times_str}. "
                    if deficit_times_str
                    else "Expected solar may not cover essentials in some windows. "
                )
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category="critical",
                    status="avoid_today",
                    reason=f"{shortfall_phrase}Keep {a.name} on and avoid adding load then.",
                ))
            continue

        # Flexible / deferrable: use surplus windows that fit this appliance's duration
        if not has_surplus_windows or energy_margin_type == "deficit":
            if deficit_windows:
                def_times = _format_windows_list(deficit_windows, timestep_minutes)
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category=a.category,
                    status="avoid_today",
                    reason=(
                        f"Tomorrow demand exceeds solar in {def_times}. "
                        f"Avoid running {a.name} ({power_kw:.2f} kW) then; run in surplus windows if any."
                    ),
                ))
            else:
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category=a.category,
                    status="avoid_today",
                    reason=f"No surplus windows tomorrow; avoid non-essential use of {a.name}.",
                ))
            continue

        best_tw, fallback_tw = _best_surplus_window_for_duration(
            surplus_windows, duration_steps, timestep_minutes
        )
        chosen_tw = best_tw or fallback_tw
        recommended_window_str = (
            _format_window_times(chosen_tw, timestep_minutes) if chosen_tw else ""
        )

        if best_tw:
            # A surplus window is long enough for this appliance
            if surplus_coverage_ratio >= 0.5:
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category=a.category,
                    status="safe_to_run",
                    recommended_window=recommended_window_str,
                    reason=(
                        f"Run {a.name} between {recommended_window_str} — "
                        f"solar exceeds your load then ({power_kw:.2f} kW)."
                    ),
                ))
            else:
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category=a.category,
                    status="run_only_in_recommended_window",
                    recommended_window=recommended_window_str,
                    reason=(
                        f"Run {a.name} only between {recommended_window_str} — "
                        f"solar covers your load ({power_kw:.2f} kW) in that window."
                    ),
                ))
        else:
            # No window long enough; recommend longest surplus as fallback
            if fallback_tw:
                fallback_str = _format_window_times(fallback_tw, timestep_minutes)
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category=a.category,
                    status="run_only_in_recommended_window",
                    recommended_window=fallback_str,
                    reason=(
                        f"{a.name} needs {duration_steps * timestep_minutes // 60}h continuous surplus; "
                        f"longest surplus is {fallback_str}. Run there if needed ({power_kw:.2f} kW)."
                    ),
                ))
            else:
                advisories.append(ApplianceAdvisory(
                    appliance_id=a.id,
                    name=a.name,
                    category=a.category,
                    status="avoid_today",
                    reason=f"No surplus window long enough for {a.name} ({power_kw:.2f} kW) tomorrow.",
                ))
    return advisories


def _surplus_coverage_ratio(surplus_windows: List[TimeWindow], timestep_minutes: int) -> float:
    """Fraction of 96 steps (24h @ 15min) covered by surplus windows."""
    if not surplus_windows:
        return 0.0
    total_steps = 0
    for tw in surplus_windows:
        total_steps += tw.end_step - tw.start_step + 1
    return total_steps / 96.0


def _first_surplus_window_str(surplus_windows: List[TimeWindow], timestep_minutes: int) -> str:
    """First surplus window as HH:MM–HH:MM for display."""
    if not surplus_windows:
        return ""
    return _format_window_times(surplus_windows[0], timestep_minutes)


def _format_windows_list(windows: List[TimeWindow], timestep_minutes: int) -> str:
    """Format multiple windows as '08:00–10:00 and 12:00–14:00'."""
    if not windows:
        return ""
    return " and ".join(_format_window_times(tw, timestep_minutes) for tw in windows)


def _window_length_steps(tw: TimeWindow) -> int:
    """Number of steps in the window (inclusive)."""
    return tw.end_step - tw.start_step + 1


def _best_surplus_window_for_duration(
    surplus_windows: List[TimeWindow],
    duration_steps: int,
    timestep_minutes: int,
) -> Tuple[Optional[TimeWindow], Optional[TimeWindow]]:
    """Find first surplus window that fits duration_steps; fallback = longest surplus window."""
    if not surplus_windows:
        return None, None
    # First that fits
    for tw in surplus_windows:
        if _window_length_steps(tw) >= duration_steps:
            return tw, None
    # Fallback: longest window
    longest = max(surplus_windows, key=_window_length_steps)
    return None, longest
