# Off-Grid Solar Energy Planner — Project Documentation

**Version:** 0.1.0  
**Last updated:** February 2026  
**Purpose:** Single reference for architecture, modules, data flow, configuration, UI, matching, PDF, tests, deployment, and future upgrades. Nothing is left out for future reference and upgrade.

---

## Table of contents

1. [Overview and purpose](#1-overview-and-purpose)
2. [Architecture](#2-architecture)
3. [Repository layout](#3-repository-layout)
4. [Modules](#4-modules)
5. [Data flow and contracts](#5-data-flow-and-contracts)
6. [Configuration and secrets](#6-configuration-and-secrets)
7. [Streamlit UI](#7-streamlit-ui)
8. [Day-ahead matching and statement list](#8-day-ahead-matching-and-statement-list)
9. [PDF report](#9-pdf-report)
10. [Tests](#10-tests)
11. [Deployment](#11-deployment)
12. [Upgrade and extension guide](#12-upgrade-and-extension-guide)
13. [Related documents](#13-related-documents)

---

## 1. Overview and purpose

### 1.1 What the project is

- **Advisory digital twin** for **day-ahead household energy planning** (next calendar day 00:00–24:00 UTC).
- **Solar source:** NASA POWER (hourly GHI → resampled to 15‑min steps). OpenWeather is used only for **geocoding** and **current weather** display; it is **not** used for irradiance or PV.
- **Control philosophy:** Survivability-first (critical loads first; flexible/deferrable in surplus windows where possible).
- **Output:** Day-ahead outlook (energy margin, surplus/deficit windows, risk), **statement-list appliance advice** (not per-appliance “avoid today” table), per-step recommendation, KPIs, and downloadable CSV/JSONL/PDF.

### 1.2 What it is not

- **Not** a real-time hardware controller (advisory only; user-in-the-loop).
- **Not** tariff or cost optimiser.
- **Not** grid-connected; assumes off-grid or weak-grid.

### 1.3 Audiences

- **Industry:** Prototyping, clear data contracts, path to HIL/live telemetry.
- **Academic:** Reproducible solar (NASA POWER), KPIs, ablation-ready logs, explainable guidance.

---

## 2. Architecture

### 2.1 High-level

```
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit app (streamlit_app/app.py)                            │
│  - Sidebar: location, PV/battery/inverter, run mode, run/demo    │
│  - Main: weather, load board, run → state CSV + guidance JSONL   │
│  - Results: replay, day-ahead outlook, KPIs, recommendation,     │
│             statement-list advice, schedule heatmap, downloads  │
└───────────────────────────┬─────────────────────────────────────┘
                             │ calls simulate(), reads logs,
                             │ format_day_ahead_statements()
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Engine (src/offgrid_dt/)                                        │
│  - dt/simulator.py: time-stepped run, NASA POWER PV, battery,   │
│                     load, controller, RunLogger, matching        │
│  - forecast/: NASA POWER GHI, OpenWeather geocode/weather,      │
│               pv_power (irradiance → kW)                         │
│  - control/: naive, rule_based, static_priority, forecast_heuristic │
│  - matching/: compute_day_ahead_matching, format_day_ahead_statements │
│  - xai/: generate_guidance, optional OpenAI rewrite               │
│  - metrics/: KPITracker (CLSR, blackout, SAR, throughput)         │
│  - io/: schema, logger (state CSV + guidance JSONL), pdf_report   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Security boundary

- **Engine** lives under `src/offgrid_dt/`. No secrets in logs; no PII in OpenAI calls.
- **Secrets** only via Streamlit `.streamlit/secrets.toml` (or env); never committed.
- **UI** is a consumer: calls `simulate()`, reads state CSV and guidance JSONL, uses `matching_first_day` and `format_day_ahead_statements()`.

### 2.3 Key data contracts

| Artifact | Producer | Consumer | Format |
|----------|----------|----------|--------|
| State CSV | RunLogger in simulator | App replay, PDF | One row per step: timestamp, pv_now_kw, soc_now, load_*, crit_*, kpi_*, served_task_ids, etc. |
| Guidance JSONL | Simulator (generate_guidance + optional OpenAI) | App recommendation block | One line per step: risk_level, headline, explanation, reason_codes, timestamp |
| matching_first_day | compute_day_ahead_matching() after flush | App day-ahead block, PDF | Dict: total_solar_kwh, total_demand_kwh, energy_margin_*, surplus_windows, deficit_windows, risk_level, daily_outlook_text, appliance_advisories, timestep_minutes |
| Day-ahead statements | format_day_ahead_statements(matching, …) | App “Appliance advice”, PDF “Appliance advice” | List[str]: total demand, total forecast, capability, flexible/deferrable advice, critical coverage, surplus/deficit windows |

---

## 3. Repository layout

```
offgrid_solar_dt/
  streamlit_app/
    app.py                      # Single Streamlit entry; adds src to path
  src/offgrid_dt/
    __init__.py
    config/                     # (reserved)
    dt/
      simulator.py              # simulate(); NASA POWER PV; RunLogger; matching
      battery.py                # BatteryState, update_soc
      load.py                   # build_daily_tasks, requested_kw_for_step
    forecast/
      nasa_power.py             # fetch_ghi_next_planning_days (NASA POWER GHI)
      openweather.py            # geocode, current_weather, synthetic_irradiance_forecast
      pv_power.py               # irradiance_to_pv_power_kw
    control/
      controllers.py            # get_controllers, BaseController, naive, rule_based, static_priority, forecast_heuristic
    matching/
      day_ahead.py              # compute_day_ahead_matching, format_day_ahead_statements, DayAheadMatchingResult, ApplianceAdvisory
    xai/
      explain.py                # generate_guidance, enhance_explanation_with_openai
    metrics/
      kpis.py                   # KPITracker (CLSR, blackout, SAR, solar util, battery throughput)
    io/
      schema.py                 # SystemConfig, Appliance, TaskInstance, Guidance, StepRecord, etc.
      logger.py                 # RunLogger (state CSV + guidance JSONL)
      pdf_report.py             # build_two_day_plan_pdf_from_logs, build_two_day_plan_pdf
  scripts/
    run_simulation.py           # CLI: --days, --out; runs all controllers, writes logs
  tests/
    conftest.py
    test_battery.py
    test_forecast_resolution.py
    test_nasa_power_parse.py
    test_simulation_smoke.py
  docs/
    PROJECT_DOCUMENTATION.md    # This file
    APP_PURPOSE_AND_ACHIEVEMENTS.md
    CODEBASE_AUDIT_DATA_SOURCES.md
    INTERFACE_MANUSCRIPT_ALIGNMENT.md
    OVERHAUL_ALIGNMENT_AUDIT.md
  .streamlit/
    config.toml                 # Theme (warm colours)
    secrets.template.toml       # Template; never commit secrets.toml
  requirements.txt
  pyproject.toml
  README.md
```

---

## 4. Modules

### 4.1 dt (simulator and physical models)

- **simulator.simulate(cfg, appliances, controller, days=7, …)**  
  - Computes first planning day as next calendar day 00:00 UTC.  
  - Fetches GHI via `fetch_ghi_next_planning_days` (NASA POWER); on failure uses `synthetic_irradiance_forecast`.  
  - Resamples hourly GHI to 15‑min steps via `_resample_to_steps`.  
  - Time loop: PV from irradiance → battery update → load requested → controller decision → served/deferred → guidance (generate_guidance + optional OpenAI) → StepRecord + KPITracker → RunLogger.  
  - After `RunLogger.flush()`, calls `compute_day_ahead_matching(first_day_df, appliances, cfg, …)` and attaches `matching.to_dict()` as `out["matching_first_day"]`.  
  - Returns dict: `state_csv`, `guidance_jsonl`, `start_time`, `matching_first_day`.

- **battery.py** — BatteryState, update_soc (charge/discharge with efficiency, soc_min/soc_max).

- **load.py** — build_daily_tasks (from Appliance list), requested_kw_for_step (per category and total).

### 4.2 forecast

- **nasa_power.py** — `fetch_ghi_next_planning_days(lat, lon, start_date, days)` → hourly GHI (W/m²); used as sole solar source for the run. Parsing and date handling documented in module.

- **openweather.py** — Geocode, current_weather (for UI); synthetic_irradiance_forecast (fallback when NASA POWER unavailable; used inside simulator only when NASA returns no data).

- **pv_power.py** — irradiance_to_pv_power_kw(ghi_wm2, pv_capacity_kw, …) → PV power in kW.

### 4.3 control

- **controllers.py** — get_controllers() returns list of controller instances. BaseController; NaiveController; RuleBasedController; StaticPriorityController; ForecastAwareHeuristicController (forecast_heuristic). Default for UI and manuscript alignment: forecast_heuristic.

### 4.4 matching

- **day_ahead.py**  
  - **compute_day_ahead_matching(state_df, appliances, cfg, inverter_max_kw, timestep_minutes, day_start_ts)**  
    Uses first 96 rows (24h) of state_df. Computes: total_solar_kwh, total_demand_kwh, energy_margin_kwh, energy_margin_type (surplus/tight/deficit), daily_outlook_text, surplus_windows, deficit_windows, critical_fully_protected, risk_level, appliance_advisories (per-appliance status and reason; used internally and for backward compatibility).  
  - **format_day_ahead_statements(matching, has_flexible_or_deferrable=None, timestep_minutes=15)**  
    Returns list of user-facing statements: total demand, total forecast, capability (sustain or not), advice for flexible/deferrable if deficit, critical coverage, surplus/deficit window times. Used by Streamlit “Appliance advice” and PDF “Appliance advice (day-ahead)”.

### 4.5 xai

- **explain.py** — generate_guidance(cfg, ExplanationContext, used_kw, deferred_count) → Guidance (headline, explanation, risk_level, reason_codes, dominant_factors). enhance_explanation_with_openai(api_key, model, guidance, …) optionally rewrites explanation text; does not change decisions.

### 4.6 metrics

- **kpis.py** — KPITracker: snapshot() returns CLSR, Blackout_minutes, SAR, Solar_utilization, Battery_throughput_kwh (cumulative over run).

### 4.7 io

- **schema.py** — SystemConfig, Appliance, TaskInstance, ControlDecision, Guidance, StepRecord; LoadCategory, etc. Pydantic models.

- **logger.py** — RunLogger: append StepRecord (and guidance) per step; flush() writes state CSV and guidance JSONL. Column names must match UI/PDF expectations (e.g. pv_now_kw, kpi_CLSR).

- **pdf_report.py** — build_two_day_plan_pdf_from_logs(state_csv_path, guidance_jsonl_path, title, weather_summary, system_summary_override, matching_result) builds PDF with system summary, KPIs, day-ahead outlook text/risk, **day_ahead_statements** (bullet list), today/tomorrow recommendations and schedules. build_two_day_plan_pdf(…, day_ahead_statements=…) does the actual drawing.

---

## 5. Data flow and contracts

### 5.1 Run flow

1. User sets location, PV, battery, inverter, loads (and quantities), run hours, planning days, control strategy; clicks “Run my plan” or “Try a quick demo”.
2. App builds SystemConfig and appliance list, calls `simulate(cfg, appliances, controller, days, …)`.
3. Simulator: NASA POWER GHI (or synthetic) → resample to steps → for each step: PV, battery, load requested, controller.serve(…) → served/deferred, guidance, KPIs, logger.append(record).
4. Logger.flush() → state CSV, guidance JSONL.
5. compute_day_ahead_matching(first_day_df, appliances, cfg, …) → matching_first_day (dict) attached to result.
6. App stores result in session_state; reads state CSV and guidance JSONL; displays replay, day-ahead outlook, KPIs, recommendation, **format_day_ahead_statements(matching, has_flexible_or_deferrable)**, schedule heatmap, downloads (CSV, JSONL, PDF).

### 5.2 State CSV columns (expected by UI and PDF)

- timestamp, ts (if derived), pv_now_kw, soc_now, load_requested_kw, load_served_kw, crit_requested_kw, crit_served_kw, load_flexible_kw, load_deferrable_kw, served_task_ids, kpi_CLSR, kpi_Blackout_minutes, kpi_SAR, kpi_Solar_utilization, kpi_Battery_throughput_kwh, etc. See RunLogger and schema for full set.

### 5.3 Guidance JSONL fields

- timestamp, risk_level, headline, explanation, reason_codes, dominant_factors (and any optional fields). UI uses risk_level, headline, explanation, reason_codes for the “Recommendation for this time step” block.

### 5.4 matching_first_day (dict) keys

- total_solar_kwh, total_demand_kwh, energy_margin_kwh, energy_margin_type, daily_outlook_text, surplus_windows, deficit_windows, min_power_margin_kw, critical_fully_protected, risk_level, appliance_advisories, timestep_minutes. surplus_windows/deficit_windows are lists of dicts with start_step, end_step, start_ts, end_ts, label.

---

## 6. Configuration and secrets

### 6.1 Streamlit

- **.streamlit/config.toml** — Theme (base, primaryColor, backgroundColor, secondaryBackgroundColor, textColor). Current: warm palette (e.g. primaryColor #c2410c, backgroundColor #faf7f2).
- **.streamlit/secrets.toml** (do not commit) — openweather_api_key, openai_api_key (optional), openai_model (optional, default gpt-4o-mini). Copy from secrets.template.toml.

### 6.2 App defaults (in code)

- DT_MINUTES_DEFAULT = 15.  
- Planning horizon options: 2, 3, 7 days.  
- Default controller: forecast_heuristic.  
- Auto-refresh: 15 minutes when “Auto-refresh every 15 minutes” is on (streamlit-autorefresh).

### 6.3 Running without installing the package

- App and run_simulation.py add `src` to `sys.path` so `offgrid_dt` is importable. For pytest, set `PYTHONPATH=src` (or equivalent) so tests and scripts see the same code.

---

## 7. Streamlit UI

### 7.1 Sections (in order)

- **Header** — “Off-Grid Solar Energy Planner”; subtitle (day-ahead, real solar data, essential loads, solar efficiency).
- **Sidebar** — Your setup: location search (OpenWeather geocode) + lat/lon, PV capacity, battery, inverter; Run mode: auto-refresh toggle, control strategy, planning horizon (days); “Run my plan”, “Try a quick demo (2 days)”.
- **Main (always)** — Current weather at your location (if API key and location set). Your loads: expanders by category (Critical/Flexible/Deferrable), toggles and quantities, total load. Running hours per day. Your estimated consumption (next 24h/12h).
- **Main (after run)** — Explore your plan over time (slider). Your day-ahead outlook: PV chart, Your 24h summary (expected solar, planned demand, energy margin, **day-ahead risk** pill), daily outlook text, surplus/deficit bar chart, expander for surplus/deficit windows. KPI cards. Power available vs load. **Recommendation for this time step** (step risk pill, headline, explanation, reason codes; **step risk** caption). Battery state. Solar forecast from this time step. Household power use chart. **Appliance advice for tomorrow** (statement list from format_day_ahead_statements). Recommended schedule (heatmap). Download your plan (CSV, JSONL, PDF).

### 7.2 Risk clarity

- **Day-ahead risk** — In “Your 24h summary”; from matching_first_day["risk_level"]. Caption: “Day-ahead risk (overall tomorrow)”.
- **Step risk** — In “Recommendation for this time step”; from guidance JSONL for current replay step. Caption: “Step risk — for this moment only. Day-ahead risk is in Your 24h summary above.”

### 7.3 Data source verification

- Every displayed value is traced to a real source (user input, OpenWeather, state CSV, guidance JSONL, matching_first_day, or derived from these). See [CODEBASE_AUDIT_DATA_SOURCES.md](CODEBASE_AUDIT_DATA_SOURCES.md).

---

## 8. Day-ahead matching and statement list

### 8.1 compute_day_ahead_matching

- Input: first 96 rows of state CSV (first planning day), appliances, SystemConfig, inverter_max_kw, timestep_minutes.
- Uses pv_now_kw, load_requested_kw, crit_requested_kw per step. Solar-only comparison (no battery in surplus/deficit).
- Output: DayAheadMatchingResult (total_solar_kwh, total_demand_kwh, energy_margin_*, surplus_windows, deficit_windows, critical_fully_protected, risk_level, appliance_advisories, …). risk_level: high if critical not protected or margin < -0.5; medium if margin < 0 or min_power_margin < -0.5; else low.

### 8.2 format_day_ahead_statements

- Input: matching (dict or DayAheadMatchingResult), has_flexible_or_deferrable (bool or None to infer from appliance_advisories), timestep_minutes.
- Output: List of strings, e.g.:  
  - “Total load demand for the day ahead: X.XX kWh.”  
  - “Total energy forecast for tomorrow: X.XX kWh.”  
  - “If you run your selected loads tomorrow, the system is capable of sustaining them.” / “… may not sustain them — expected shortfall of X.XX kWh.”  
  - If deficit and has_flexible_or_deferrable: “Do not run flexible or deferrable loads tomorrow, or reduce their running hours.”  
  - Critical coverage sentence.  
  - Surplus windows (solar ≥ demand): HH:MM–HH:MM and ….  
  - Deficit windows (demand > solar): HH:MM–HH:MM and ….  
- Used by UI “Appliance advice for tomorrow” and PDF “Appliance advice (day-ahead)” (no per-appliance Status/Reason table).

---

## 9. PDF report

- **build_two_day_plan_pdf_from_logs** reads state CSV and guidance JSONL, infers appliance ids from served_task_ids, builds schedule rows for today and tomorrow, extracts recommendations and KPIs, gets day_ahead_outlook_text and day_ahead_risk from matching_result, and **day_ahead_statements** via format_day_ahead_statements(matching_result, …). Calls build_two_day_plan_pdf(…, day_ahead_statements=…).
- **build_two_day_plan_pdf** draws: title; system summary; key outcomes (KPIs); day-ahead outlook (text + risk); **Appliance advice (day-ahead)** as bullet list from day_ahead_statements; today recommendation; today schedule; tomorrow recommendation; tomorrow schedule; notes (advisory disclaimer).
- PDF does not contain per-appliance Status/Reason table; only the statement list.

---

## 10. Tests

- **test_battery.py** — BatteryState and update_soc (charge/discharge, bounds).
- **test_forecast_resolution.py** — synthetic_irradiance_forecast length and resampling alignment.
- **test_nasa_power_parse.py** — _parse_nasa_power_ghi (NASA response parsing).
- **test_simulation_smoke.py** — simulate() with forecast_heuristic, 2 days; checks state CSV and guidance JSONL exist and have expected structure.
- Run: `PYTHONPATH=src python -m pytest tests -q` (or `pytest` if package is installed). All four tests must pass for a clean verification.

---

## 11. Deployment

### 11.1 Local

- `python -m venv .venv`, activate, `pip install -r requirements.txt`. Copy secrets.template.toml to secrets.toml and set keys. `streamlit run streamlit_app/app.py`.

### 11.2 Streamlit Community Cloud

- Push repo to GitHub. Deploy app pointing to streamlit_app/app.py. Add secrets in dashboard: openweather_api_key, openai_api_key (optional). Ensure requirements.txt includes all dependencies (streamlit, streamlit-autorefresh, numpy, pandas, pydantic, requests, plotly, reportlab, etc.).

### 11.3 CLI batch (reproducible)

- Set PYTHONPATH to include `src`. Run `python scripts/run_simulation.py --days 2 --out logs`. Outputs per controller under logs/run_<controller>/.

---

## 12. Upgrade and extension guide

### 12.1 Adding a new controller

- Implement a class inheriting BaseController in control/controllers.py (name, decide method). Add it to the list returned by get_controllers(). UI and run_simulation.py will pick it up automatically.

### 12.2 Changing solar source

- Simulator currently uses fetch_ghi_next_planning_days (NASA POWER) and falls back to synthetic_irradiance_forecast. To add another source: implement a function returning a time series of GHI (or irradiance) for the planning window; in simulator, call it (e.g. when NASA fails or by config) and pass through _resample_to_steps to match step count. Keep OpenWeather out of the solar path if manuscript alignment is required.

### 12.3 Extending day-ahead matching

- To add new fields to DayAheadMatchingResult: extend day_ahead.py (dataclass and compute_day_ahead_matching), update to_dict(), and any UI/PDF that displays matching. To add new statements: extend format_day_ahead_statements() and keep the same list-of-strings contract for UI and PDF.

### 12.4 Adding UI sections

- Add new st.markdown / st.caption / st.plotly_chart etc. in streamlit_app/app.py. Data must come from res (last_run), state CSV, guidance JSONL, or matching; document in CODEBASE_AUDIT_DATA_SOURCES.md to avoid orphan displays.

### 12.5 Changing theme or copy

- Theme: .streamlit/config.toml and CSS in app.py (_inject_css). Copy: search for the string in app.py (and PDF if applicable) and update.

### 12.6 Integrity checks after changes

- `python -m compileall -q src`  
- `PYTHONPATH=src python -m pytest tests -q`  
- `PYTHONPATH=src python scripts/run_simulation.py --days 2 --out logs_smoke`  
- Manually run Streamlit and run a plan; check day-ahead outlook, statement list, and PDF download.

---

## 13. Related documents

| Document | Purpose |
|----------|---------|
| [README.md](../README.md) | Quick overview, structure, quick start, integrity checks, links to docs. |
| [APP_PURPOSE_AND_ACHIEVEMENTS.md](APP_PURPOSE_AND_ACHIEVEMENTS.md) | What the app does and achieves for industry and academic audiences; data integrity summary. |
| [CODEBASE_AUDIT_DATA_SOURCES.md](CODEBASE_AUDIT_DATA_SOURCES.md) | Trace of every UI display to its data source; confirms no orphan displays. |
| [INTERFACE_MANUSCRIPT_ALIGNMENT.md](INTERFACE_MANUSCRIPT_ALIGNMENT.md) | Interface intent, manuscript–interface contract, handover rules. |
| [OVERHAUL_ALIGNMENT_AUDIT.md](OVERHAUL_ALIGNMENT_AUDIT.md) | Post–NASA POWER and matching feature alignment and recommendations. |

---

*End of project documentation.*
