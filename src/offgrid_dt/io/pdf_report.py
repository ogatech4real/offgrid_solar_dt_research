from __future__ import annotations

"""PDF export utilities for the Streamlit prototype.

The goal is *not* to produce a glossy report generator.
It is to create a credible, reproducible "today's plan" artifact suitable for:
  - reviewer screenshots / supplementary material
  - user-study handouts
  - field pilot style guidance
"""

from io import BytesIO
from typing import Dict, List, Optional

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


def build_plan_pdf(
    *,
    title: str,
    system_summary: Dict[str, str],
    kpis: Dict[str, str],
    recommendations: Dict[str, str],
    schedule_rows: List[Dict[str, str]],
    notes: Optional[str] = None,
) -> bytes:
    """Create a single PDF (bytes) for the current run.

    Args:
        title: PDF title shown on the first line.
        system_summary: key/value lines (location, PV, battery, reserve, horizon).
        kpis: key/value KPI lines (CLSR, blackout, SAR, etc.).
        recommendations: headline/explanation/reasons/risk.
        schedule_rows: list of dicts with keys: time_window, appliance, advisory.
        notes: optional footer notes.
    """

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    x0 = 2.0 * cm
    y = h - 2.0 * cm

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0, y, title)
    y -= 0.8 * cm

    # System summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, "System")
    y -= 0.55 * cm
    c.setFont("Helvetica", 10)
    for k, v in system_summary.items():
        c.drawString(x0, y, f"{k}: {v}")
        y -= 0.45 * cm

    y -= 0.25 * cm

    # KPI summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, "Key outcomes")
    y -= 0.55 * cm
    c.setFont("Helvetica", 10)
    for k, v in kpis.items():
        c.drawString(x0, y, f"{k}: {v}")
        y -= 0.45 * cm

    y -= 0.25 * cm

    # Recommendations
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, "Top recommendation")
    y -= 0.55 * cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x0, y, recommendations.get("headline", ""))
    y -= 0.55 * cm

    c.setFont("Helvetica", 10)
    explanation = recommendations.get("explanation", "")
    y = _draw_paragraph(c, x0, y, explanation, max_width=w - 2 * x0, leading=12)
    y -= 0.2 * cm
    c.setFont("Helvetica", 9)
    c.drawString(x0, y, f"Risk: {recommendations.get('risk', '')}  |  Reasons: {recommendations.get('reasons', '')}")
    y -= 0.75 * cm

    # Schedule table
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, "Today’s suggested schedule")
    y -= 0.6 * cm

    col1 = x0
    col2 = x0 + 5.5 * cm
    col3 = x0 + 13.0 * cm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(col1, y, "Time window")
    c.drawString(col2, y, "Appliance")
    c.drawString(col3, y, "Advisory")
    y -= 0.35 * cm
    c.line(x0, y, w - x0, y)
    y -= 0.35 * cm

    c.setFont("Helvetica", 10)
    for r in schedule_rows[:18]:  # keep to one page; this is a handout
        if y < 2.2 * cm:
            c.showPage()
            y = h - 2.0 * cm
            c.setFont("Helvetica-Bold", 12)
            c.drawString(x0, y, "Today’s suggested schedule (cont.)")
            y -= 0.8 * cm
            c.setFont("Helvetica", 10)

        c.drawString(col1, y, str(r.get("time_window", ""))[:22])
        c.drawString(col2, y, str(r.get("appliance", ""))[:40])
        c.drawString(col3, y, str(r.get("advisory", ""))[:18])
        y -= 0.45 * cm

    if notes:
        y -= 0.25 * cm
        c.setFont("Helvetica-Oblique", 9)
        y = _draw_paragraph(c, x0, y, notes, max_width=w - 2 * x0, leading=11)

    c.showPage()
    c.save()
    return buf.getvalue()


def build_two_day_plan_pdf(
    *,
    title: str,
    system_summary: Dict[str, str],
    kpis: Dict[str, str],
    recommendations_today: Dict[str, str],
    schedule_rows_today: List[Dict[str, str]],
    recommendations_tomorrow: Optional[Dict[str, str]] = None,
    schedule_rows_tomorrow: Optional[List[Dict[str, str]]] = None,
    tomorrow_outlook: Optional[Dict[str, str]] = None,
    notes: Optional[str] = None,
) -> bytes:
    """Create a two-day (Today + Tomorrow) PDF handout.

    This is used to showcase rolling-horizon planning (48h) driven by forecast-informed decisions.
    """

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    x0 = 2.0 * cm
    y = h - 2.0 * cm

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0, y, title)
    y -= 0.8 * cm

    # System summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, "System")
    y -= 0.55 * cm
    c.setFont("Helvetica", 10)
    for k, v in system_summary.items():
        c.drawString(x0, y, f"{k}: {v}")
        y -= 0.45 * cm

    y -= 0.25 * cm

    # KPI summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, "Key outcomes")
    y -= 0.55 * cm
    c.setFont("Helvetica", 10)
    for k, v in kpis.items():
        c.drawString(x0, y, f"{k}: {v}")
        y -= 0.45 * cm

    y -= 0.35 * cm

    # Today recommendation
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, "Today — top recommendation")
    y -= 0.55 * cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x0, y, recommendations_today.get("headline", ""))
    y -= 0.55 * cm
    c.setFont("Helvetica", 10)
    y = _draw_paragraph(c, x0, y, recommendations_today.get("explanation", ""), max_width=w - 2 * x0, leading=12)
    y -= 0.2 * cm
    c.setFont("Helvetica", 9)
    c.drawString(
        x0,
        y,
        f"Risk: {recommendations_today.get('risk','')}  |  Reasons: {recommendations_today.get('reasons','')}",
    )
    y -= 0.6 * cm

    # Today schedule
    y = _draw_schedule_table(
        c,
        x0,
        y,
        w,
        h,
        heading="Today’s suggested schedule",
        rows=schedule_rows_today or [{"time_window": "-", "appliance": "No schedulable tasks", "advisory": "-"}],
    )

    # Tomorrow section (new page for clarity)
    if recommendations_tomorrow is not None or schedule_rows_tomorrow is not None:
        c.showPage()
        y = h - 2.0 * cm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x0, y, "Tomorrow — forecast-based plan")
        y -= 0.7 * cm

        if tomorrow_outlook:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(x0, y, "Tomorrow outlook")
            y -= 0.55 * cm
            c.setFont("Helvetica", 10)
            for k, v in tomorrow_outlook.items():
                c.drawString(x0, y, f"{k}: {v}")
                y -= 0.45 * cm
            y -= 0.2 * cm

        if recommendations_tomorrow:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(x0, y, "Top recommendation")
            y -= 0.55 * cm
            c.setFont("Helvetica-Bold", 11)
            c.drawString(x0, y, recommendations_tomorrow.get("headline", ""))
            y -= 0.55 * cm
            c.setFont("Helvetica", 10)
            y = _draw_paragraph(
                c,
                x0,
                y,
                recommendations_tomorrow.get("explanation", ""),
                max_width=w - 2 * x0,
                leading=12,
            )
            y -= 0.2 * cm
            c.setFont("Helvetica", 9)
            c.drawString(
                x0,
                y,
                f"Risk: {recommendations_tomorrow.get('risk','')}  |  Reasons: {recommendations_tomorrow.get('reasons','')}",
            )
            y -= 0.6 * cm

        y = _draw_schedule_table(
            c,
            x0,
            y,
            w,
            h,
            heading="Tomorrow’s suggested schedule",
            rows=schedule_rows_tomorrow or [{"time_window": "-", "appliance": "No schedulable tasks", "advisory": "-"}],
        )

    if notes:
        if y < 3.0 * cm:
            c.showPage()
            y = h - 2.0 * cm
        y -= 0.25 * cm
        c.setFont("Helvetica-Oblique", 9)
        _draw_paragraph(c, x0, y, notes, max_width=w - 2 * x0, leading=11)

    c.showPage()
    c.save()
    return buf.getvalue()


def _draw_schedule_table(
    c: canvas.Canvas,
    x0: float,
    y: float,
    w: float,
    h: float,
    *,
    heading: str,
    rows: List[Dict[str, str]],
) -> float:
    """Draw a compact schedule table and return updated y (may span pages)."""
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x0, y, heading)
    y -= 0.6 * cm

    col1 = x0
    col2 = x0 + 5.5 * cm
    col3 = x0 + 13.0 * cm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(col1, y, "Time window")
    c.drawString(col2, y, "Appliance")
    c.drawString(col3, y, "Advisory")
    y -= 0.35 * cm
    c.line(x0, y, w - x0, y)
    y -= 0.35 * cm

    c.setFont("Helvetica", 10)
    for r in (rows or [])[:28]:
        if y < 2.2 * cm:
            c.showPage()
            y = h - 2.0 * cm
            c.setFont("Helvetica-Bold", 12)
            c.drawString(x0, y, f"{heading} (cont.)")
            y -= 0.8 * cm
            c.setFont("Helvetica", 10)
        c.drawString(col1, y, str(r.get("time_window", ""))[:22])
        c.drawString(col2, y, str(r.get("appliance", ""))[:40])
        c.drawString(col3, y, str(r.get("advisory", ""))[:18])
        y -= 0.45 * cm

    return y


def _draw_paragraph(c: canvas.Canvas, x: float, y: float, text: str, *, max_width: float, leading: int = 12) -> float:
    """Draw wrapped text and return the updated y."""
    if not text:
        return y
    words = text.split()
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, "Helvetica", 10) <= max_width:
            line = test
        else:
            c.drawString(x, y, line)
            y -= leading * 0.035 * cm * (leading / 12)  # normalize a bit
            line = w
    if line:
        c.drawString(x, y, line)
        y -= leading * 0.035 * cm * (leading / 12)
    return y


def schedule_from_state_csv(
    df: pd.DataFrame,
    *,
    appliance_id_to_name: Dict[str, str],
    day_index: int = 0,
    timestep_minutes: int = 15,
) -> List[Dict[str, str]]:
    """Build a simple, human-readable schedule summary from served_task_ids.

    This produces time windows where a given appliance/task was served.
    It is intentionally simple and deterministic.
    """
    if df.empty:
        return []

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp")
    df["day"] = df["timestamp"].dt.floor("D")
    days = sorted(df["day"].unique())
    if not days:
        return []
    day_index = max(0, min(day_index, len(days) - 1))
    d0 = days[day_index]
    day_df = df[df["day"] == d0].reset_index(drop=True)
    if day_df.empty:
        return []

    def _parse_ids(s: str) -> List[str]:
        if not isinstance(s, str) or not s.strip():
            return []
        return [x for x in s.split(";") if x]

    # Map served tasks per step to appliance ids
    served_appl_per_step: List[List[str]] = []
    for s in day_df.get("served_task_ids", "").astype(str).tolist():
        ids = _parse_ids(s)
        appl_ids = []
        for tid in ids:
            appl_id = tid.split("_")[0]
            if appl_id:
                appl_ids.append(appl_id)
        served_appl_per_step.append(appl_ids)

    # For each appliance, merge consecutive served steps
    schedule_rows: List[Dict[str, str]] = []
    unique_appliances = sorted({a for step_ids in served_appl_per_step for a in step_ids})
    for appl in unique_appliances:
        idxs = [i for i, ids in enumerate(served_appl_per_step) if appl in ids]
        if not idxs:
            continue
        # merge consecutive
        start = prev = idxs[0]
        for i in idxs[1:]:
            if i == prev + 1:
                prev = i
                continue
            schedule_rows.append(_window_row(d0, start, prev, timestep_minutes, appliance_id_to_name.get(appl, appl)))
            start = prev = i
        schedule_rows.append(_window_row(d0, start, prev, timestep_minutes, appliance_id_to_name.get(appl, appl)))

    # Sort by time
    schedule_rows.sort(key=lambda r: r.get("time_window", ""))
    return schedule_rows


def _window_row(day, start_step: int, end_step: int, timestep_minutes: int, appliance_name: str) -> Dict[str, str]:
    start_min = start_step * timestep_minutes
    end_min = (end_step + 1) * timestep_minutes
    start_h, start_m = divmod(start_min, 60)
    end_h, end_m = divmod(end_min, 60)
    tw = f"{int(start_h):02d}:{int(start_m):02d}–{int(end_h):02d}:{int(end_m):02d}"
    return {"time_window": tw, "appliance": appliance_name, "advisory": "Run"}


def build_two_day_plan_pdf_from_logs(
    *,
    state_csv_path: str,
    guidance_jsonl_path: str,
    title: str = "Solar-first Household Plan (Today + Tomorrow)",
    weather_summary: Optional[Dict[str, object]] = None,
) -> bytes:
    """Convenience wrapper: build a two-day PDF from the standard DT logs.

    Keeps the UI simple and ensures the downloadable artifact is consistent with the replay logs.
    """
    df = pd.read_csv(state_csv_path)
    if df.empty:
        return build_two_day_plan_pdf(
            title=title,
            system_summary={},
            kpis={},
            recommendations_today={"headline": "No data", "explanation": "Run the digital twin to generate a plan."},
            schedule_rows_today=[],
            notes="No simulation data was available to generate a plan.",
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    gdf = pd.read_json(guidance_jsonl_path, lines=True)
    if not gdf.empty:
        gdf["timestamp"] = pd.to_datetime(gdf["timestamp"], utc=True)
        gdf = gdf.sort_values("timestamp").reset_index(drop=True)

    # System summary (simple, non-technical)
    first = df.iloc[0]
    system_summary = {
        "Location": str(first.get("location_name", "")) or "Configured location",
        "PV capacity": f"{float(first.get('pv_capacity_kw', 0.0)):.1f} kW",
        "Battery": f"{float(first.get('battery_capacity_kwh', 0.0)):.1f} kWh",
        "Inverter limit": f"{float(first.get('inverter_max_kw', 0.0)):.1f} kW",
    }

    if weather_summary:
        desc = str(weather_summary.get("description", "")).title()
        t = weather_summary.get("temperature_c", None)
        h = weather_summary.get("humidity_pct", None)
        c = weather_summary.get("cloud_cover_pct", None)
        w = weather_summary.get("wind_speed_mps", None)
        system_summary["Weather now"] = desc or "—"
        if t is not None:
            system_summary["Temperature"] = f"{float(t):.1f} °C"
        if h is not None:
            system_summary["Humidity"] = f"{float(h):.0f} %"
        if c is not None:
            system_summary["Cloud cover"] = f"{float(c):.0f} %"
        if w is not None:
            system_summary["Wind"] = f"{float(w):.1f} m/s"

    # KPI snapshot: use last row as cumulative view
    last = df.iloc[-1]
    kpis = {
        "Critical reliability (CLSR)": f"{100*float(last.get('clsr_running', 0.0)):.1f} %",
        "Blackout time (critical)": f"{float(last.get('blackout_minutes_running', 0.0)):.0f} minutes",
        "Solar autonomy (SAR)": f"{100*float(last.get('sar_running', 0.0)):.1f} %",
        "Solar utilization": f"{100*float(last.get('solar_util_running', 0.0)):.1f} %",
        "Battery wear proxy": f"{float(last.get('throughput_kwh_running', 0.0)):.2f} kWh throughput",
    }

    # Appliance id -> name mapping inferred from served_task_ids (best-effort)
    def _infer_ids(series: pd.Series) -> Dict[str, str]:
        ids = set()
        for s in series.astype(str).tolist():
            if not s or s == "nan":
                continue
            for tid in str(s).split(";"):
                if tid:
                    ids.add(tid.split("_")[0])
        return {i: i.replace("-", " ").title() for i in sorted(ids)}

    appliance_id_to_name = _infer_ids(df.get("served_task_ids", pd.Series(dtype=str)))

    # Recommendations (today & tomorrow): first entry per day
    recommendations_today = {"headline": "No recommendation", "explanation": "Guidance log not available."}
    recommendations_tomorrow = None

    if not gdf.empty:
        gdf["day"] = gdf["timestamp"].dt.floor("D")
        days = sorted(gdf["day"].unique())
        if days:
            g0 = gdf[gdf["day"] == days[0]].iloc[0]
            recommendations_today = {
                "headline": str(g0.get("headline", "")),
                "explanation": str(g0.get("explanation", "")),
                "risk": str(g0.get("risk_level", "")),
            }
            if len(days) > 1:
                g1 = gdf[gdf["day"] == days[1]].iloc[0]
                recommendations_tomorrow = {
                    "headline": str(g1.get("headline", "")),
                    "explanation": str(g1.get("explanation", "")),
                    "risk": str(g1.get("risk_level", "")),
                }

    # Schedules
    schedule_rows_today = schedule_from_state_csv(df, appliance_id_to_name=appliance_id_to_name, day_index=0, timestep_minutes=int(df.get("timestep_minutes", pd.Series([15])).iloc[0] if "timestep_minutes" in df.columns else 15))
    schedule_rows_tomorrow = None
    tomorrow_outlook = None

    if df["timestamp"].dt.floor("D").nunique() > 1:
        schedule_rows_tomorrow = schedule_from_state_csv(df, appliance_id_to_name=appliance_id_to_name, day_index=1, timestep_minutes=int(df.get("timestep_minutes", pd.Series([15])).iloc[0] if "timestep_minutes" in df.columns else 15))

        # Simple tomorrow outlook: expected solar energy (kWh) and typical risk indicator
        # Compute from pv_kw over day 2
        df2 = df.copy()
        df2["day"] = df2["timestamp"].dt.floor("D")
        days = sorted(df2["day"].unique())
        if len(days) > 1:
            d1 = days[1]
            day_df = df2[df2["day"] == d1]
            dt_hours = (int(df.get("timestep_minutes", pd.Series([15])).iloc[0]) / 60.0) if "timestep_minutes" in df.columns else 0.25
            pv_kwh = float(day_df["pv_kw"].astype(float).sum() * dt_hours)
            load_kwh = float(day_df["load_requested_kw"].astype(float).sum() * dt_hours)
            tomorrow_outlook = {
                "Expected solar energy": f"{pv_kwh:.1f} kWh",
                "Expected demand": f"{load_kwh:.1f} kWh",
            }

    return build_two_day_plan_pdf(
        title=title,
        system_summary=system_summary,
        kpis=kpis,
        recommendations_today=recommendations_today,
        schedule_rows_today=schedule_rows_today,
        recommendations_tomorrow=recommendations_tomorrow,
        schedule_rows_tomorrow=schedule_rows_tomorrow,
        tomorrow_outlook=tomorrow_outlook,
        notes="Plans are advisory and will update as conditions change.",
    )
