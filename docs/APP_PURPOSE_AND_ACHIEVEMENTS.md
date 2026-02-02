# Off-Grid Solar Digital Twin — Purpose and Achievements

**Audience:** Industry and academic readers  
**Date:** February 2026  
**Status:** Comprehensive description of what the app does and what it achieves, with verification that all displayed outputs are real and connected to live or run-derived data.

---

## 1. Executive summary

The **Off-Grid Solar Decision Support** application is an **advisory digital twin** for **day-ahead energy planning**. It helps households and small operators (e.g. in weak- or off-grid settings) plan the next 24 hours by:

- Using **physics-based solar data** (NASA POWER GHI) for reproducibility and scientific defensibility.
- Simulating PV, battery, and task-based loads over 15-minute steps.
- Comparing **expected demand** vs **expected solar availability** in a clear **matching layer** (energy margin, surplus/deficit windows, risk, appliance advisories).
- Delivering **explainable recommendations** (risk level, reason codes, per-appliance guidance) and **downloadable plans** (CSV, JSONL, PDF) for operations and research.

The system is **advisory only**: it does not switch loads or inverters. It supports both **industry** prototyping (clear data contracts, deployment path toward hardware-in-the-loop) and **academic** use (reproducible experiments, KPIs, ablation-ready logs).

**Data integrity:** A full codebase audit confirms that **every value shown in the interface is real and connected** — either to user input, live APIs (e.g. OpenWeather for location and current weather), or to the last simulation run (state logs, guidance logs, day-ahead matching result). There are **no orphan or placeholder-only displays**. See [CODEBASE_AUDIT_DATA_SOURCES.md](CODEBASE_AUDIT_DATA_SOURCES.md) for the detailed trace.

---

## 2. What the app is

| Aspect | Description |
|--------|-------------|
| **Role** | Advisory digital twin for **day-ahead** energy planning (next calendar day, 00:00–24:00 UTC). |
| **Solar source** | **NASA POWER** (hourly GHI → resampled to 15-min steps). OpenWeather is used only for **geocoding** and **current weather** context; it is not used for solar irradiance. |
| **Control philosophy** | Survivability-first: critical loads are prioritised; flexible and deferrable loads are scheduled within surplus windows where possible. |
| **Output** | Recommendations, day-ahead outlook (margin, surplus/deficit windows, risk), appliance advisories, KPIs, and downloadable logs/PDF — all **advisory**, not actuation. |

---

## 3. What the app does

### 3.1 Inputs

- **Location:** Search (OpenWeather geocode) or manual lat/lon. Used for NASA POWER and for current weather display.
- **System:** PV capacity (kW), battery capacity (kWh), inverter (kW).
- **Loads:** User selects appliances from a catalog (Critical / Flexible / Deferrable) with quantities and running hours per category. Total load and estimated consumption (12h/24h) are computed from this selection.
- **Planning horizon:** 2, 3, or 7 days (simulation length); **day-ahead matching and main messaging refer to the first planning day** (00:00–24:00).
- **Control strategy:** naive, rule_based, static_priority, or **forecast_heuristic** (default; uses PV forecast and SOC for survivability-first scheduling).

### 3.2 Simulation engine

- **Timeline:** Starts at 00:00 UTC of the **next** calendar day (first planning day). All PV in the run is derived from NASA POWER (or a synthetic fallback if the API is unavailable).
- **Time step:** 15 minutes (96 steps per day).
- **Models:** PV power from irradiance; battery SOC with charge/discharge limits; task-based loads with priority (critical / flexible / deferrable) and optional time windows.
- **Controller:** Decides which tasks to serve each step; emits guidance (risk level, headline, explanation, reason codes). Optional OpenAI layer can rewrite explanations for clarity; decisions remain deterministic.
- **Logging:** Each run produces:
  - **State CSV:** One row per step (timestamp, pv_now_kw, soc_now, load_requested_kw, load_served_kw, critical/flexible/deferrable breakdown, served_task_ids, KPI snapshots).
  - **Guidance JSONL:** One line per step (risk_level, headline, explanation, reason_codes, etc.).

### 3.3 Day-ahead matching layer

After each run, the engine computes a **day-ahead matching result** for the first planning day:

1. **Daily energy feasibility:** Total solar (kWh) vs total demand (kWh) → energy margin (surplus / tight / deficit) and a short daily outlook text.
2. **Time-resolved power adequacy:** Intervals where PV ≥ load (surplus windows) and where load > PV (deficit windows), with start/end times.
3. **Priority-aware:** Whether critical loads are fully protected; which steps have shortfall for flexible/deferrable only.
4. **Risk level:** Low / medium / high from margin and windows.
5. **Appliance advisories:** Per selected appliance — e.g. “safe to run”, “run only in recommended window”, “avoid today” — with reasons tied to surplus/deficit and priority.

This result is stored as `matching_first_day` (dict) in the run output and is shown in the UI and in the PDF report.

### 3.4 User-facing outputs

- **Current weather:** OpenWeather current conditions at the chosen location (context only).
- **Load board:** Selected appliances, quantities, total load (kW), running hours, and **estimated consumption** (12h/24h kWh and average kW) for planning.
- **After a run:**
  - **Replay slider:** Scrub through any timestep; all downstream metrics and charts update from the state and guidance logs for that step.
  - **Day-ahead outlook (00:00–24:00):** PV curve, summary metrics (expected solar, planned demand, energy margin, risk), advisory text, surplus/deficit bar chart, surplus/deficit window list, and critical-load protection note.
  - **KPI cards:** Critical Load Supply Ratio (CLSR), Blackout minutes, Solar Autonomy Ratio (SAR), Battery throughput (wear proxy).
  - **Power available:** PV now, PV + battery (inverter limit), vs total selected load at the current replay step.
  - **Recommendation:** Risk pill, headline, explanation, reason codes (from guidance JSONL for the current step).
  - **Battery state:** SOC and safe/caution/risk from guidance.
  - **Solar forecast from replay point:** PV power (and optional cumulative energy) for the next 24h/48h from state CSV.
  - **Household power use:** Requested vs served load and PV over a short window.
  - **Appliance advisory table:** By category; status and reason from the day-ahead matching result.
  - **Recommended schedule (heatmap):** From served_task_ids in the state CSV for the selected day.
  - **Downloads:** State CSV, guidance JSONL, and a **two-day plan PDF** (system summary, weather, matching summary, appliance advisories, and optional KPI/replay context).

---

## 4. What it achieves for industry

| Goal | How the app supports it |
|------|--------------------------|
| **Operational planning** | Day-ahead view of expected solar vs demand; surplus/deficit windows and risk level help plan when to run flexible/deferrable loads (e.g. washing, EV charging). |
| **Risk visibility** | Single day-ahead risk (from matching) and per-step risk (from guidance); appliance-level “safe / run in window / avoid” advisories. |
| **Reproducibility** | Same location and inputs yield the same NASA POWER–driven run; logs (CSV, JSONL) can be replayed and shared. |
| **Clear data contracts** | Engine and UI communicate via state CSV, guidance JSONL, and matching dict; no hidden or duplicate logic in the UI. |
| **Deployment path** | Advisory by default (user-in-the-loop). Moving to live operation is an incremental step: keep the same decision engine, replace or augment the simulator with live telemetry, and add actuators gated by safety rules. |
| **Security and maintainability** | Engine lives under `src/offgrid_dt/`; secrets only in Streamlit secrets; no secrets in logs. |

---

## 5. What it achieves for academia

| Goal | How the app supports it |
|------|--------------------------|
| **Reproducible solar input** | **NASA POWER** provides hourly GHI for any lat/lon; same request → same series. No proprietary or unrepeatable solar forecast in the core path. |
| **Physics-based, defensible methodology** | PV is derived from irradiance (NASA POWER GHI); battery and load models are explicit and time-stepped; matching is deterministic and traceable to the same state logs. |
| **Labelling and transparency** | UI and PDF state that solar is from NASA POWER, that the product is day-ahead planning, and that outcomes are advisory and uncertain (forecast, not certainty). |
| **Structured KPIs** | CLSR, blackout duration, SAR, solar utilization, battery throughput (and flexible satisfaction) map directly to survivability and comfort; they are computed per step and aggregated in logs. |
| **Ablation and comparison** | Multiple controllers (naive, rule_based, static_priority, forecast_heuristic); CLI batch runs produce one log set per controller for the same scenario; logs are suitable for figures and tables. |
| **Explainability** | Deterministic reason codes and dominant factors; optional LLM refinement for wording only; appliance advisories tied to surplus/deficit and priority. |
| **User studies and handouts** | PDF plan (today + tomorrow, matching summary, appliance advisories) and replay allow consistent stimuli for experiments and reviewer appendices. |

---

## 6. Technical summary

- **Solar:** NASA POWER GHI (hourly) → resampled to 15-min steps; simulation starts at 00:00 UTC of the first planning day.
- **Matching:** First-day state CSV (96 steps) + config → `DayAheadMatchingResult` (energy margin, surplus/deficit windows, risk, appliance advisories); stored as dict in run output and used by UI and PDF.
- **Display integrity:** Every UI element is traced to a real source (session state, OpenWeather current weather, state CSV, guidance JSONL, or matching result); see [CODEBASE_AUDIT_DATA_SOURCES.md](CODEBASE_AUDIT_DATA_SOURCES.md). No orphan or placeholder-only displays.
- **Optional automation:** With “Auto-run” enabled, the app can refresh every 15 minutes and re-run the twin if the last run was more than 14 minutes ago; behaviour is documented in the UI.

---

## 7. References within the repo

- [CODEBASE_AUDIT_DATA_SOURCES.md](CODEBASE_AUDIT_DATA_SOURCES.md) — Full trace of every display to its data source; confirms all outputs are real and connected.
- [INTERFACE_MANUSCRIPT_ALIGNMENT.md](INTERFACE_MANUSCRIPT_ALIGNMENT.md) — Interface intent, visual representation, and architectural boundaries for the advisory digital twin.
- [OVERHAUL_ALIGNMENT_AUDIT.md](OVERHAUL_ALIGNMENT_AUDIT.md) — Post–NASA POWER and matching-layer feature alignment and recommendations.
- [README.md](../README.md) — Quick start, repository structure, KPIs, forecasting approach, and deployment notes.
