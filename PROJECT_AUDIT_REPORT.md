# Off-grid Solar Digital Twin — Project Audit Report

**Date:** February 1, 2026  
**Scope:** Full codebase review, README alignment, and recommendations for improvement and enhancement.

---

## 1. Executive Summary

The **Off-grid Solar-First Digital Twin (DT)** is a well-scoped prototype for solar-first, grid-independent household energy decision support. It combines a modular digital twin (PV, battery, loads, control), forecast-informed scheduling, deterministic explainability with optional LLM refinement, and a Streamlit dashboard with replay, scheduling visuals, and PDF handouts. The codebase is clean, README and structure match the implementation, and the separation between engine (`src/offgrid_dt/`) and UI (`streamlit_app/`) is clear. This audit summarizes what is in place and recommends concrete improvements and enhancements.

---

## 2. What the Project Is About

- **Purpose:** Advisory decision support for off-grid/solar-first households (e.g. emerging economies, weak or absent grid).
- **Core components:**
  1. **Digital twin:** 15-min time-stepped simulation with PV generation, battery SOC, and task-based loads.
  2. **Controllers:** `naive`, `rule_based`, `static_priority`, `forecast_heuristic` (survivability-first).
  3. **Forecasting:** OpenWeather API (when key is set) or synthetic irradiance template for reproducibility.
  4. **Explainability:** Deterministic reason codes and dominant factors; optional OpenAI rewrite for wording only.
  5. **Streamlit UI:** System config, appliance selection, scenario replay, schedule heatmap, PDF plans (Today + Tomorrow).
- **Outputs:** `*_state.csv`, `*_guidance.jsonl`, PDF handouts; suitable for experiments, KPIs, and user studies.

---

## 3. Current State — What Works Well

### 3.1 Architecture and Structure

- **Engine vs UI:** Engine lives under `src/offgrid_dt/`; Streamlit app imports and calls it. Clear boundary and data contract (state logs, structured records).
- **Modularity:** `dt/` (simulator, battery, load), `forecast/`, `control/`, `xai/`, `metrics/`, `io/` are logically separated.
- **Data contracts:** Pydantic models (`SystemConfig`, `Appliance`, `TaskInstance`, `ControlDecision`, `Guidance`, `StepRecord`) are used consistently.
- **Secrets:** API keys only via Streamlit secrets; template provided; README warns against committing real secrets.

### 3.2 Functionality

- **Simulation:** Closed-loop run with PV, battery update, task serving, inverter/reserve logic, and continuous logging works as described.
- **Controllers:** Four controllers implemented and selectable; forecast heuristic uses horizon and SOC headroom as intended.
- **KPIs:** CLSR, blackout minutes, SAR, solar utilization, battery throughput computed and exposed in UI and logs.
- **Explainability:** Deterministic guidance (risk, reason codes, factors) is always on; OpenAI enhancement is optional and does not change decisions.
- **UI:** Sidebar config (location, PV/battery/inverter, reserve, horizon, appliances), scenario replay, PV/load/SOC plots, schedule heatmap, appliance advisory, CSV/JSONL/PDF downloads.
- **CLI:** `scripts/run_simulation.py` runs multi-controller batch and writes logs for experiments.

### 3.3 Code Quality

- Consistent use of type hints, dataclasses, and Pydantic.
- Docstrings on main APIs (e.g. `simulate`, `update_soc`, `build_plan_pdf`).
- README accurately describes structure, quick start, deployment, KPIs, limitations, and integrity checks.

---

## 4. Issues and Gaps Identified

### 4.1 Bug: PV Forecast Resolution Mismatch (High Impact)

- **Location:** `src/offgrid_dt/dt/simulator.py` + `synthetic_irradiance_forecast` in `forecast/openweather.py`.
- **Issue:** Synthetic forecast returns **one point per hour** (`hours=24*days` → 168 points for 7 days). The simulator uses **15-minute steps** (96 steps/day → 672 steps for 7 days). PV is indexed as `pv_forecast_kw_full[step]`, so:
  - Steps 0–167 use indices 0–167 (first ~1.75 days).
  - Steps 168–671 go out of range and get 0.0 → **no PV for most of a 7-day run** when using synthetic forecast.
- **Impact:** Long runs without OpenWeather key show zero PV after the first ~1.75 days; KPIs and behaviour are wrong.
- **Recommendation:** Either (a) generate synthetic irradiance at 15-min resolution (e.g. 4 points per hour), or (b) in the simulator, map step to hour: `hour_idx = step * dt_minutes // 60` and use `pv_forecast_kw_full[min(hour_idx, len(pv_forecast_kw_full)-1)]`, and similarly expand the rolling `pv_forecast` slice to match horizon in steps.

### 4.2 OpenAI Model Name

- **Location:** `streamlit_app/app.py`, `simulator.py`, `.streamlit/secrets.template.toml`.
- **Issue:** Default model is `gpt-4.1-mini`. If the intent is OpenAI’s small model, the correct name is typically `gpt-4o-mini` or `gpt-4-mini`. `gpt-4.1-mini` may be invalid or institution-specific.
- **Recommendation:** Confirm the correct model id; if using OpenAI API, switch default to a valid name (e.g. `gpt-4o-mini`) and document it.

### 4.3 No Automated Tests

- **Location:** Project root; no `tests/` or `*_test.py` / `test_*.py` found.
- **Issue:** README suggests integrity checks (`compileall`, short `run_simulation.py`), but there are no unit or integration tests. Refactors and fixes (e.g. PV resolution) are not regression-safe.
- **Recommendation:** Add a `tests/` package with:
  - Unit tests for battery `update_soc`, load `requested_kw_for_step` / `build_daily_tasks`, KPI snapshot, deterministic `generate_guidance`.
  - Integration test: short simulation (1–2 days) with synthetic data and one controller; assert non-empty state CSV and basic KPI sanity (e.g. CLSR in [0, 1] where applicable).
  - Optional: parametrized test for PV step indexing once the resolution bug is fixed.

### 4.4 Config Package Unused

- **Location:** `src/offgrid_dt/config/` contains only an empty `__init__.py`.
- **Issue:** No shared config loading (e.g. defaults, validation). Defaults are duplicated (e.g. in schema, app, CLI).
- **Recommendation:** Either remove `config/` if not needed or use it for a single source of defaults (e.g. timestep, horizon, SOC bounds) and import from schema/app/CLI.

### 4.5 Error Handling and Logging

- **Location:** `simulator.py` (forecast try/except), `openweather.py` (multiple endpoints), `explain.py` (OpenAI).
- **Issue:** Exceptions are caught broadly; failures fall back silently (e.g. synthetic forecast, original guidance). No structured logging, so debugging and deployment monitoring are harder.
- **Recommendation:** Use a small logging facade (e.g. `logging`); log at WARNING when falling back to synthetic or when OpenAI enhancement fails; avoid swallowing errors without at least one log line.

### 4.6 Streamlit App Assumes Prior Run

- **Location:** `streamlit_app/app.py` (e.g. after “Run digital twin” block).
- **Issue:** If `last_run` is not set, the app shows an info message and stops. Until the user runs the twin, all main content (replay, heatmap, PDF) is hidden. No sample/demo data for first-time visitors.
- **Recommendation:** Optional “Load sample run” or a short auto-run with default config (e.g. 1 day) so the UI can be explored without configuring and clicking Run first; or clearly document “Run once to see results.”

### 4.7 Dependencies and Packaging

- **Location:** `requirements.txt` vs `pyproject.toml`.
- **Issue:** `requirements.txt` includes `streamlit` and `openai`; `pyproject.toml` lists them as optional (`ui`, `llm`). Installing with `pip install -e .` does not install Streamlit/OpenAI; README quick start uses `pip install -r requirements.txt`. Risk of divergence (e.g. someone installs only the package and the app fails).
- **Recommendation:** Align installation: e.g. in README, “For full app: `pip install -r requirements.txt`” vs “For engine only: `pip install -e .`”. Optionally add a `dev` or `all` extra that pulls `requirements.txt`-equivalent.

### 4.8 Minor / Consistency

- **NaiveController:** In `controllers.py`, `shed` is used uninitialized if the `else` branch is taken (logically it is always set, but a static linter may complain). Initializing `shed = []` before the if/else would make it explicit.
- **Typing:** `simulator.py` uses `Dict[str, any]` for `pending_tasks`; `any` should be `Any` (from `typing`) for consistency and correctness.
- **PDF report:** `schedule_from_state_csv` and heatmap both parse `served_task_ids` with the same `;`-separated, `task_id` prefix convention; this is consistent but could be a shared helper to avoid drift.

---

## 5. Recommendations for Improvement and Enhancement

### 5.1 High Priority

1. **Fix PV forecast resolution** (see 4.1): Resolve hourly-vs-step indexing so multi-day runs with synthetic (and, if applicable, OpenWeather) forecast have correct PV for every step.
2. **Add tests** (see 4.3): At least battery, load, KPI, and one short end-to-end simulation; add to CI if the project is on GitHub.
3. **Verify OpenAI model name** (see 4.2): Use a valid model id and document it.

### 5.2 Medium Priority

4. **Structured logging** (see 4.5): Single module or function that uses `logging`; use it in simulator, forecast, and XAI for fallbacks and errors.
5. **First-run UX** (see 4.6): Sample run or one-click “Demo run” so the dashboard is usable without a prior manual run.
6. **Install/docs alignment** (see 4.7): Clarify in README when to use `requirements.txt` vs `pip install -e .` and, if desired, add an extra that includes UI/LLM.

### 5.3 Lower Priority / Enhancements

7. **Config package** (see 4.4): Either remove or use for shared defaults and validation.
8. **Minor code cleanups** (see 4.8): Initialize `shed` in NaiveController; replace `any` with `Any`; consider a shared parser for `served_task_ids`.
9. **OpenWeather:** Document which OpenWeather product/endpoint is required for solar forecast and any rate limits; optional retry/backoff (e.g. tenacity) is already in deps.
10. **Accessibility and i18n:** If targeting field pilots or diverse users, consider basic accessibility (labels, contrast) and later a simple i18n path for strings (e.g. reason codes, headlines).
11. **HIL/live path:** README already describes moving from replay to live telemetry and actuators; keep the data contract stable and consider a small “live adapter” interface (e.g. abstract data source) for future swap.

---

## 6. Integrity Checks (Current vs Suggested)

- **Current (README):**  
  `python -m compileall -q src`  
  `python scripts/run_simulation.py --days 2 --out logs_smoke`

- **Suggested addition:**  
  After adding tests:  
  `pytest tests/ -v`  
  (or `python -m pytest tests/ -v`).

---

## 7. Summary Table

| Area              | Status        | Notes                                                                 |
|-------------------|---------------|-----------------------------------------------------------------------|
| Architecture      | Good          | Clear engine/UI split; modular packages; Pydantic contracts           |
| Simulation core   | Good          | Logic correct; PV resolution bug with synthetic forecast             |
| Controllers       | Good          | Four controllers; forecast heuristic aligned with survivability      |
| Forecasting       | Adequate      | OpenWeather + synthetic; resolution mismatch with 15-min steps        |
| Explainability    | Good          | Deterministic + optional LLM; decisions unchanged by LLM              |
| UI                | Good          | Feature-complete; first-run experience could be improved              |
| Logging / PDF     | Good          | State CSV, guidance JSONL, PDF handouts as described                   |
| Tests             | Missing       | No automated tests                                                    |
| Documentation     | Good          | README matches implementation and limitations                         |
| Security          | Good          | Secrets via Streamlit; no keys in logs                                |
| Deployment        | Documented    | Streamlit Cloud steps in README                                       |

---

This audit reflects the codebase and README as of the audit date. Addressing the high-priority items (PV resolution, tests, model name) will significantly improve correctness and maintainability; the rest can be scheduled according to roadmap and resources.
