# Off-Grid Solar Energy Planner

An **advisory digital twin** for **day-ahead household energy planning** in off-grid or weak-grid settings. It uses **NASA POWER** solar data, simulates PV–battery–load over 15‑minute steps, and delivers clear day-ahead outlook, statement-list advice, and downloadable plans (CSV, JSONL, PDF).

---

## What you get

- **Day-ahead planning (00:00–24:00)** — Expected solar vs your selected load; surplus/deficit windows; risk and capability statements.
- **NASA POWER solar** — Physics-based GHI for reproducibility; OpenWeather only for location and current weather.
- **Streamlit dashboard** — Warm UI, replay over time, KPIs, recommendation per step, appliance advice as a **statement list** (not per-appliance “avoid today” table).
- **Pluggable controllers** — `naive`, `rule_based`, `static_priority`, **`forecast_heuristic`** (default).
- **Logs and PDF** — State CSV, guidance JSONL, and a two-day PDF plan for handouts and review.

**Advisory only** — no automatic switching; user stays in control. Suitable for **academic** evaluation (KPIs, ablation, reproducible solar) and **industry** prototyping (clear contracts, path to HIL/live telemetry).

---

## Repository structure

```
offgrid_solar_dt/
  streamlit_app/
    app.py                    # Streamlit UI (adds src/ to path, runs simulate + matching)
  src/offgrid_dt/
    dt/                       # Simulator + physical models
      simulator.py            # Time-stepped run; NASA POWER PV; matching_first_day
      battery.py, load.py
    forecast/
      nasa_power.py           # NASA POWER GHI for next planning day(s)
      openweather.py         # Geocoding + current weather only
      pv_power.py            # Irradiance → PV power
    control/
      controllers.py         # naive, rule_based, static_priority, forecast_heuristic
    matching/
      day_ahead.py            # compute_day_ahead_matching, format_day_ahead_statements
    xai/
      explain.py             # Deterministic guidance + optional OpenAI rewrite
    metrics/
      kpis.py                # CLSR, blackout, SAR, battery throughput
    io/
      schema.py, logger.py, pdf_report.py
  scripts/
    run_simulation.py        # CLI batch run (all controllers, writes logs)
  tests/
    test_*.py                # Battery, forecast resolution, NASA parse, simulation smoke
  docs/                      # Full project documentation (see below)
  .streamlit/
    config.toml              # Theme (warm colours); secrets.template.toml
  requirements.txt, pyproject.toml
```

**Security:** Engine under `src/offgrid_dt/`; secrets via Streamlit secrets only; no secrets in logs.

---

## Quick start

### 1. Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Secrets (optional)

Copy `.streamlit/secrets.template.toml` to `.streamlit/secrets.toml`:

- `openweather_api_key` — geocoding and current weather.
- `openai_api_key` (optional) — clearer explanation wording; decisions stay deterministic.

### 3. Run the app

```bash
streamlit run streamlit_app/app.py
```

Use **Run my plan** or **Try a quick demo (2 days)** to see the day-ahead outlook and statement-list advice.

### 4. CLI batch (reproducible runs)

From repo root, set `PYTHONPATH` so `src` is importable, then run:

- **Windows PowerShell:** `$env:PYTHONPATH = "src"; python scripts/run_simulation.py --days 2 --out logs`
- **Unix / Bash:** `export PYTHONPATH=src && python scripts/run_simulation.py --days 2 --out logs`

Outputs: `logs/run_<controller>/<controller>_2d_state.csv`, `*_guidance.jsonl`, and matching in the returned dict.

---

## Integrity checks

```bash
python -m compileall -q src
# Set PYTHONPATH first (Windows: $env:PYTHONPATH = "src"; Unix: export PYTHONPATH=src)
python -m pytest tests -q
python scripts/run_simulation.py --days 2 --out logs_smoke
```

---

## Documentation

| Document | Purpose |
|---------|--------|
| [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) | **Full project reference** — architecture, modules, data flow, config, UI, matching, PDF, tests, deployment, upgrade. |
| [docs/APP_PURPOSE_AND_ACHIEVEMENTS.md](docs/APP_PURPOSE_AND_ACHIEVEMENTS.md) | What the app does and achieves (industry & academic). |
| [docs/CODEBASE_AUDIT_DATA_SOURCES.md](docs/CODEBASE_AUDIT_DATA_SOURCES.md) | Trace of every UI display to its data source (no orphan displays). |
| [docs/INTERFACE_MANUSCRIPT_ALIGNMENT.md](docs/INTERFACE_MANUSCRIPT_ALIGNMENT.md) | Interface intent and handover rules. |
| [docs/OVERHAUL_ALIGNMENT_AUDIT.md](docs/OVERHAUL_ALIGNMENT_AUDIT.md) | Post–NASA POWER and matching feature alignment. |

---

## KPIs

- **Critical Load Supply Ratio (CLSR)** — How consistently essentials are powered.
- **Blackout time** — Minutes of unserved critical load.
- **Solar Autonomy Ratio (SAR)** — Share of demand met by solar.
- **Battery throughput** — Charge/discharge (wear proxy).

---

## Limitations

- Solar from NASA POWER (or synthetic fallback if API unavailable); accuracy depends on location and conditions.
- Battery ageing is a throughput proxy only.
- Loads are task-based (scheduling); not full appliance transient physics.

---

## License

MIT (adjust if your institution requires).
