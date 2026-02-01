# Off-grid Solar-First Digital Twin (DT) + Explainable Decision Support

This repository implements a **solar-first, grid-independent household energy decision-support system** designed for emerging-economy operating conditions (weak/absent grid). It combines:

1) a **modular digital twin** (PV generation, battery SOC, household loads, and control loop),
2) a **forecast-informed controller** (survivability-first scheduling),
3) an **explainable advisory layer** (deterministic reason codes + optional LLM refinement), and
4) a **Streamlit dashboard** that communicates recommended actions with replay, scheduling visuals, and PDF handouts for user studies and peer review.

The project is intentionally structured to serve **both academic** evaluation (reproducible experiments, KPIs, ablation-ready logs) and **industry** prototyping (clear data contracts, security hygiene, deployment pathway toward HIL/IoT control).

---

## What you get (production-grade prototype)

### Digital Twin engine (backend)
- Time-stepped simulation (default **15 min**) with PV, battery, and task-based loads.
- Pluggable controllers:
  - `naive` (no intelligence)
  - `rule_based` (simple inverter-like logic)
  - `static_priority` (priorities + SOC thresholds)
  - `forecast_heuristic` (forecast-informed survivability-first scheduling)
- Continuous logging to:
  - `*_state.csv` (state + decisions + metrics per timestep)
  - `*_guidance.jsonl` (headline, explanation, reason codes, dominant factors)

### Streamlit advisory interface (frontend)
- **Sidebar system configuration** including location (OpenWeather geocoding), PV/battery/inverter, and reserve settings.
- **Dynamic appliance selection** (multiselect + quantities) with optional per-appliance overrides.
- **Scenario replay**: time scrubber to review any timestep and see decisions + explanations update.
- **Schedule timeline heatmap** for recommended task execution windows.
- **Downloadable PDF plan** for **Today + Tomorrow** (48h rolling-horizon view), suitable for reviewer appendices and user-study handouts.
- Explainability-first presentation:
  - risk indicator (low/medium/high)
  - reason codes + dominant factors
  - appliance advisory (green/amber/red)

---

## Repository structure

```
offgrid_solar_dt/
  streamlit_app/                 # UI layer (imports engine from src/)
    app.py
  src/offgrid_dt/                # Engine layer
    dt/                          # Simulator + physical models
      simulator.py
      battery.py
      load.py
    forecast/                     # Forecast acquisition + PV conversion
      openweather.py
      pv_power.py
    control/                      # Controllers (baselines + forecast heuristic)
      controllers.py
    xai/                          # Deterministic explanations + optional LLM refinement
      explain.py
    metrics/                      # KPI computation
      kpis.py
    io/                           # Schemas, logging, PDF report generation
      schema.py
      logger.py
      pdf_report.py
  scripts/
    run_simulation.py             # CLI batch runner (writes logs)
  .streamlit/
    config.toml
    secrets.template.toml         # NEVER commit real secrets
  requirements.txt
  pyproject.toml
```

**Security boundary:** the engine lives under `src/offgrid_dt/`. The UI is a consumer that calls engine functions and reads log outputs. Secrets are only accessed via Streamlit secrets and are not written to logs.

**Interface–manuscript alignment:** For UI/UX work, advisory framing, and what the interface must (and must not) do, see [docs/INTERFACE_MANUSCRIPT_ALIGNMENT.md](docs/INTERFACE_MANUSCRIPT_ALIGNMENT.md). This document is the single source of truth for interface development and handover.

---

## Quick start (local)

### 1) Install
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2) Configure secrets (optional but recommended)
Copy the template and fill keys:
```bash
cp .streamlit/secrets.template.toml .streamlit/secrets.toml
```

In `secrets.toml`:
- `openweather_api_key` enables geocoding + forecast calls.
- `openai_api_key` enables LLM-enhanced explanation rewriting (deterministic XAI remains the source of truth).
 - `openai_model` (optional) defaults to `gpt-4o-mini`.

### 3) Run the app
```bash
streamlit run streamlit_app/app.py
```

---

## Streamlit Community Cloud deployment

1) Push this repo to GitHub.
2) Deploy on Streamlit Cloud.
3) Add secrets in the Streamlit UI:
   - `openweather_api_key = "..."`
   - `openai_api_key = "..."` (optional)

---

## Reproducible experiments (CLI)

Run a multi-controller batch simulation and write logs:
```bash
python scripts/run_simulation.py --days 7 --out logs
```

Outputs are written to:
```
logs/
  run_naive/
    naive_7d_state.csv
    naive_7d_guidance.jsonl
  run_forecast_heuristic/
    forecast_heuristic_7d_state.csv
    forecast_heuristic_7d_guidance.jsonl
  ...
```

These logs are directly reusable for:
- paper figures
- KPI tables
- scenario playback in the UI
- user-study stimuli

---

## KPIs (maps cleanly to the manuscript)

The engine computes the following (per timestep and aggregated):
- **Critical Load Supply Ratio (CLSR)**
- **Blackout duration** (minutes/hours for critical load shortfall)
- **Solar Autonomy Ratio (SAR)**
- **Solar utilization** (curtailment proxy)
- **Battery throughput / cycling proxy** (ageing proxy)
- **Flexible task satisfaction** (comfort proxy)

The intent is survivability-first operation:
**critical loads dominate**, then solar utilization, then battery protection.

---

## Forecasting approach (pragmatic, review-safe)

The system supports OpenWeather-driven inputs when keys and product access are available. Where API limits or endpoint availability constrain solar forecasting, the engine falls back to a **synthetic irradiance template** so:
- the demo remains fully runnable,
- experiments stay reproducible,
- the controller behaviour remains testable.

For publication, clearly label the forecast source used in each run (OpenWeather vs template) and report sensitivity when appropriate.

---

## Explainability model (deterministic-first + optional OpenAI enhancement)

### Deterministic XAI (always on)
The controller emits:
- `risk_level` (low/medium/high)
- `reason_codes` (e.g., `LOW_SOC`, `PV_SURPLUS_WINDOW`, `PROTECT_RESERVE`)
- `dominant_factors` (SOC, PV outlook, reserve thresholds)

### Optional OpenAI enhancement (stylistic refinement)
If an `openai_api_key` is provided, the app can **rewrite** the deterministic explanation into clearer language. This does **not** change decisions and should be treated as a communication layer only.

---

## How this supports HIL / industry deployment

This prototype is **advisory** by default (user-in-the-loop). A realistic deployment pathway is:
1) Keep the decision engine identical.
2) Replace or augment the simulator with live telemetry (SOC, PV power, load sensing).
3) Add an actuator interface (smart plugs/relays/inverter API) gated by safety rules.

Because the UI and engine are separated and communicate via a stable data contract (state logs / structured records), moving from replay to live mode is an incremental engineering step.

---

## Integrity checks (what to run if you change code)

```bash
python -m compileall -q src
python scripts/run_simulation.py --days 2 --out logs_smoke
pytest -q
```

---

## Limitations (be explicit in the manuscript)

- Forecast accuracy depends on endpoint availability and local microclimate; the template fallback is for reproducibility.
- Battery ageing is represented as a throughput/cycling proxy in this prototype.
- Loads are represented as **task-based** abstractions (suitable for scheduling; not appliance transient physics).

---

## License

MIT (adjust if your institution requires a different license).
