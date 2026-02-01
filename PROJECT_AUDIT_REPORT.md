# Off-grid Solar Digital Twin — Project Audit Report (Revised)

**Date:** February 1, 2026 (revised after manual folder updates)  
**Scope:** Full codebase re-audit aligned with docs/INTERFACE_MANUSCRIPT_ALIGNMENT.md (handover document); production-readiness pass completed.

---

## 1. Executive Summary

The **Off-grid Solar-First Digital Twin (DT)** remains a well-scoped prototype for solar-first, grid-independent household energy decision support. Since the previous audit, several improvements have been made: **PV forecast resolution is fixed**, **automated tests exist**, **OpenAI model default is corrected**, **simulator uses structured logging**, and the **Streamlit app has a “Run demo” path and a refactored PDF-from-logs API**. A production-readiness pass (handover alignment) is complete: **openweather orphan fixed** (current_weather on OpenWeatherSolarClient), **PDF-from-logs schema aligned** (kpi_*, pv_now_kw, system_summary_override, timestamp in guidance, advisory disclaimer), **app data contracts fixed** (column names, get_controllers, day_choice, Safe/Caution/Risk, Allowed/Delay/Avoid, simulate(cfg=cfg)). Remaining: **pytest not in pyproject.toml** optional deps, **config package** unused.

---

## 2. What the Project Is About

- **Purpose:** Advisory decision support for off-grid/solar-first households (e.g. emerging economies, weak or absent grid).
- **Core components:**
  1. **Digital twin:** 15-min time-stepped simulation with PV, battery SOC, and task-based loads.
  2. **Controllers:** `naive`, `rule_based`, `static_priority`, `forecast_heuristic` (survivability-first).
  3. **Forecasting:** OpenWeather API (when key is set) or synthetic irradiance at configurable step resolution.
  4. **Explainability:** Deterministic reason codes and dominant factors; optional OpenAI rewrite for wording only.
  5. **Streamlit UI:** System config, appliance catalog, scenario replay, schedule heatmap, PDF plans (including build-two-day-from-logs).
- **Outputs:** `*_state.csv`, `*_guidance.jsonl`, PDF handouts; suitable for experiments, KPIs, and user studies.

---

## 3. Current State — What Works Well

### 3.1 Architecture and Structure

- **Engine vs UI:** Engine under `src/offgrid_dt/`; Streamlit app imports and calls it. Clear boundary.
- **Modularity:** `dt/`, `forecast/`, `control/`, `xai/`, `metrics/`, `io/` are logically separated.
- **Data contracts:** Pydantic models used consistently; state CSV and guidance JSONL are the main artifacts.

### 3.2 Fixes and Additions Since Last Audit

| Item | Status |
|------|--------|
| **PV forecast resolution** | **Fixed.** `synthetic_irradiance_forecast` now accepts `step_minutes` (e.g. 15); simulator calls it with `dt_minutes` and uses `_resample_to_steps()` so any forecast length (e.g. hourly from OpenWeather) is aligned to `total_steps`. Multi-day runs have correct PV for every step. |
| **OpenAI model name** | **Fixed.** Default is `gpt-4o-mini` everywhere (README, secrets template, app, simulator). |
| **Automated tests** | **Added.** `tests/conftest.py`, `test_battery.py`, `test_forecast_resolution.py`, `test_simulation_smoke.py`. Battery bounds, synthetic 15-min resolution, and 3-day simulation with non-zero PV are covered. |
| **Structured logging** | **Added.** Simulator uses `logging.getLogger("offgrid_dt")` and logs a warning when falling back to synthetic irradiance. |
| **Typing** | **Fixed.** `simulator.py` uses `Dict[str, Any]` (from `typing`) instead of `any`. |
| **First-run UX** | **Improved.** App has a “Run demo (2 days)” button that sets London and triggers a run so users can explore the dashboard without manual config. |
| **README** | **Updated.** Integrity checks include `pytest -q`; openai_model default documented. |

### 3.3 Test Suite

- **conftest.py:** Ensures `src/` is on `sys.path` when running tests without an editable install.
- **test_battery.py:** `update_soc` charge/discharge direction and SOC bounds (soc_min/soc_max).
- **test_forecast_resolution.py:** Synthetic irradiance with `step_minutes=15` yields `48*4` points and monotonic timestamps.
- **test_simulation_smoke.py:** 3-day simulation with `ForecastAwareHeuristicController`, synthetic forecast; asserts state CSV exists, non-empty, and `pv_now_kw.max() > 0.1`.

### 3.4 Simulator and Forecast

- **Synthetic forecast:** `synthetic_irradiance_forecast(start, hours, step_minutes=60, ...)` now produces one point per step (e.g. 96 points per day for 15-min steps). Docstring explains simulator resolution.
- **Resampling:** `_resample_to_steps(series, target_len)` handles length mismatch (repeat or linear interpolation), so OpenWeather hourly data is safely aligned to 15-min steps.
- **Fallback:** On forecast failure, simulator logs a warning and uses synthetic with correct step resolution.

### 3.5 App and PDF

- **App:** Refactored session state (e.g. `loc_query`, `latitude`, `longitude`, `sim_days`), appliance catalog as `list[Appliance]`, “Run demo (2 days)” button, and import of `build_two_day_plan_pdf_from_logs`.
- **PDF:** New helper `build_two_day_plan_pdf_from_logs(state_csv_path, guidance_jsonl_path, title, weather_summary)` builds the two-day plan from log files and supports optional weather summary. Original `build_plan_pdf`, `build_two_day_plan_pdf`, and `schedule_from_state_csv` remain in `pdf_report.py`.

---

## 4. Issues and Gaps Identified (Current)

### 4.1 Orphaned / Dead Code in openweather.py (Medium)

- **Location:** `src/offgrid_dt/forecast/openweather.py`, lines 132–166.
- **Issue:** After `synthetic_irradiance_forecast` (which ends with `return points` at line 129), there is an indented `def current_weather(self, lat, lon, units="metric")`. It is **inside** the function (after the return), so it is **unreachable**. It looks like a method intended for `OpenWeatherSolarClient` that was pasted in the wrong place.
- **Impact:** Dead code; `current_weather` is never callable. If the app or PDF uses “current weather” (e.g. for weather_summary), it would need to be implemented elsewhere or this method moved into the class.
- **Recommendation:** Move `current_weather` into `OpenWeatherSolarClient` (correct indentation and `self`), or remove it if not needed. If the UI passes `weather_summary` from somewhere else, document the source and remove the orphan.

### 4.2 PDF-from-logs Schema Mismatch (High)

- **Location:** `src/offgrid_dt/io/pdf_report.py` — `build_two_day_plan_pdf_from_logs`.
- **Issue:** The function expects state CSV columns and guidance JSONL shape that do not match what the logger actually writes.

  **State CSV:** Logger writes (see `io/logger.py` and sample `logs_smoke2/.../forecast_heuristic_2d_state.csv`):
  - No `location_name`, `pv_capacity_kw`, `battery_capacity_kwh`, `inverter_max_kw`, `timestep_minutes`, or `pv_kw`.
  - KPIs as `kpi_CLSR`, `kpi_Blackout_minutes`, `kpi_SAR`, `kpi_Solar_utilization`, `kpi_Battery_throughput_kwh`.

  **PDF builder expects:**
  - `first.get("location_name")`, `pv_capacity_kw`, `battery_capacity_kwh`, `inverter_max_kw` → all absent, so system summary shows 0 or blank.
  - `last.get("clsr_running")`, `blackout_minutes_running`, `sar_running`, `solar_util_running`, `throughput_kwh_running` → none exist; actual columns are `kpi_CLSR`, etc. So KPI block shows 0.
  - `timestep_minutes` from CSV → absent; fallback 15 is used in one place but `pv_kw` is used for tomorrow outlook; CSV has `pv_now_kw`, not `pv_kw`.

- **Impact:** Downloaded PDF from “Downloads and raw logs” shows empty/zero system summary and zero KPIs; tomorrow outlook may also be wrong if it relies on `pv_kw`.
- **Recommendation:** Either (a) extend the logger to write system config and timestep (and optionally a row-level `pv_kw` alias or use `pv_now_kw` in PDF), and add columns `clsr_running`, `blackout_minutes_running`, etc., **or** (b) change `build_two_day_plan_pdf_from_logs` to read the current CSV/JSONL schema: use `kpi_CLSR`, `kpi_Blackout_minutes`, `kpi_SAR`, `kpi_Solar_utilization`, `kpi_Battery_throughput_kwh`, and `pv_now_kw`, and accept system summary from config passed in or leave as “From run” if not in CSV. Align guidance JSONL usage: logger writes only `r.guidance.model_dump()` (no timestamp); if PDF needs per-day guidance, either add timestamp to guidance JSONL or derive day from state CSV row index.

### 4.3 Guidance JSONL Without Timestamp (Medium)

- **Location:** `src/offgrid_dt/io/logger.py` (writes guidance); `pdf_report.build_two_day_plan_pdf_from_logs` (reads guidance).
- **Issue:** Logger writes `json.dumps(r.guidance.model_dump(), ...)` per line. `Guidance` has no `timestamp` field, so guidance JSONL lines do not contain timestamp. PDF code does `gdf["timestamp"] = pd.to_datetime(gdf["timestamp"], utc=True)` and then `gdf["day"] = gdf["timestamp"].dt.floor("D")`, so `timestamp` and `day` will be missing/NaT and day-based splits for “today” vs “tomorrow” recommendations are broken.
- **Recommendation:** Either (a) add `timestamp` to each guidance JSONL line in the logger (e.g. include `r.timestamp.isoformat()` in the dict written per line), and ensure PDF uses it, or (b) in PDF, align guidance to state CSV by row index (e.g. same number of lines as state rows) and derive day from state CSV timestamps.

### 5.2 pytest in pyproject.toml (Low)

- **Location:** `pyproject.toml` vs `requirements.txt`.
- **Issue:** `requirements.txt` includes `pytest>=8.0`, and README says to run `pytest -q`. `pyproject.toml` does not list pytest in `dependencies` or `[project.optional-dependencies]` (e.g. `dev`). Editable installs with `pip install -e .` will not get pytest.
- **Recommendation:** Add a `dev` optional extra, e.g. `dev = ["pytest>=8.0"]`, and in README mention “For tests: `pip install -e '.[dev]'` or use `requirements.txt`.” Alternatively add pytest to main dependencies in pyproject if the project expects tests to always be runnable.

### 5.3 Config Package Still Unused (Low)

- **Location:** `src/offgrid_dt/config/` — only empty `__init__.py`.
- **Recommendation:** Remove the package or use it for shared defaults/validation to avoid duplication between schema, app, and CLI.

### 5.4 Run Simulation Script vs Logger Schema (Low)

- **Location:** `scripts/run_simulation.py` passes `out_dir=out_dir / f"run_{c.name}"`; `simulate()` returns paths. Logger does not write system config or timestep into the state CSV. So any consumer (e.g. PDF-from-logs) that expects those columns must be updated or the logger extended.
- **Recommendation:** Align with the PDF-from-logs fix (either extend logger or adapt PDF to current schema).

---

## 5. Recommendations Summary

### 5.1 High Priority

1. **Fix PDF-from-logs schema (4.2, 4.3):** Make `build_two_day_plan_pdf_from_logs` use the actual state CSV column names (`kpi_*`, `pv_now_kw`) and either add `timestamp` to guidance JSONL or derive day from state CSV when splitting today/tomorrow recommendations.
2. **Resolve openweather orphan (4.1):** Move `current_weather` into `OpenWeatherSolarClient` or remove it, and ensure any `weather_summary` in the app is populated from a callable API.

### 5.2 Medium / Low Priority

3. **pytest in pyproject (4.4):** Add `dev = ["pytest>=8.0"]` (or similar) and document how to install dev deps.
4. **Config package (4.5):** Remove or use for shared defaults.
5. **Documentation:** In README or a short “Log format” section, document the state CSV and guidance JSONL schema (column names, one line per step for JSONL, optional timestamp) so PDF and future tools stay aligned.

---

## 7. Integrity Checks (Current vs Suggested)

- **Current (README):**
  ```bash
  python -m compileall -q src
  python scripts/run_simulation.py --days 2 --out logs_smoke
  pytest -q
  ```
- **Suggested:** Ensure pytest is installed (e.g. `pip install -r requirements.txt` or `pip install -e '.[dev]'`). After fixing PDF-from-logs, consider a small test that builds a two-day PDF from a fixture CSV/JSONL and checks for non-zero KPI strings.

---

## 7. Summary Table (Revised)

| Area | Status | Notes |
|------|--------|--------|
| Architecture | Good | Engine/UI split; modular packages; Pydantic contracts |
| Simulation core | Good | PV resolution fixed; resampling; logging on fallback |
| Controllers | Good | Four controllers; forecast heuristic as intended |
| Forecasting | Good | Synthetic 15-min; OpenWeather hourly resampled in simulator |
| Explainability | Good | Deterministic + optional LLM; model default gpt-4o-mini |
| Tests | Good | Battery, forecast resolution, simulation smoke; pytest in requirements.txt |
| UI | Good | Demo button; refactored app; PDF-from-logs API present |
| PDF from logs | Good | kpi_*, pv_now_kw, system_summary_override, advisory disclaimer, reasons |
| openweather.py | Good | current_weather on OpenWeatherSolarClient; orphan removed |
| Documentation | Good | README updated; pytest in integrity checks |
| Packaging | Minor | pytest not in pyproject.toml optional deps |

---

This audit reflects the repository state after the production-readiness pass aligned with the handover document. The interface supports the manuscript claims and evidence artifacts (PDF, CSV, JSONL) with correct schema and advisory framing.“download PDF from logs” 