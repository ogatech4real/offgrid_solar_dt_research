# Off-Grid Solar Digital Twin — Interface–Manuscript Alignment & Development Handover

**Project:** Solar-First Off-Grid Household Energy Decision Support  
**Audience:** Academic reviewers, practitioners, non-technical household users  
**Status:** Production-grade prototype aligned with manuscript  
**Role of Cursor / developers:** Improve UI/UX, polish visuals, refactor code safely — **without changing system intent or control logic**.

---

## 1. What This Application Is (Non-Negotiable)

This application is an **advisory digital twin**, not a live controller.

**It exists to:**

- Demonstrate a solar-first, grid-independent household energy management framework
- Support decision guidance under energy uncertainty
- Prioritize critical load survivability, solar utilization, and battery sustainability
- Translate system intelligence into plain-language, explainable guidance

**It does not:**

- Automatically control hardware
- Perform tariff or cost optimization
- Assume grid availability
- Hide decisions behind opaque AI

**All interface changes must preserve this framing.**

---

## 2. Manuscript–Interface Contract (Must Stay Aligned)

The manuscript claims the following. The interface exists only to make these claims **visible and understandable**.

### 2.1 Core Claims in the Paper

- Solar-first, off-grid operation
- Forecast-informed survivability-first scheduling
- Critical load protection
- Battery lifecycle awareness (throughput proxy)
- Explainable, user-facing decision support
- Advisory (human-in-the-loop) operation
- Digital twin + log-driven replay

### 2.2 Interface Must Visually Support These Claims

| Manuscript Claim | Interface Responsibility |
|------------------|--------------------------|
| Energy autonomy | Show PV generation vs demand |
| Survivability | Show SOC, reserve protection, blackout avoidance |
| Forecast awareness | Show 24–48h PV forecast |
| Explainability | Show why actions are recommended |
| Human-centric | Use plain language, not equations |
| Digital twin | Replay time, scenarios, logs |
| Advisory mode | No automatic ON/OFF control |

---

## 3. What the Interface Is Meant to Achieve

### 3.1 For Non-Technical Users

**Answer:** “What should I run now and when?”

**Show:**

- Weather & sun conditions in familiar terms
- Battery safety status
- Clear recommendations (Run / Delay / Avoid)
- Confidence-building explanations

### 3.2 For Technical / Academic Reviewers

**Make visible:**

- Forecast → decision → outcome chain
- Time-stepped digital twin behaviour
- KPIs (reliability, autonomy, sustainability)
- Reproducible replay and downloadable evidence

---

## 4. Fixed Architectural Boundaries (Do Not Break)

### 4.1 Engine vs Interface Separation

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **Engine** | `src/offgrid_dt/` | Digital twin logic, controllers, forecast handling, explainability logic, KPI computation |
| **Interface** | `streamlit_app/` | Configuration UI, visualization, replay controls, PDF/downloads |

- The UI **consumes** logs and engine outputs.
- The UI **does not** implement control logic.

---

## 5. What the Interface Should Show (Authoritative List)

### 5.1 System Awareness (Human-Readable)

- Weather status based on selected location (e.g. Partly Cloudy)
- Solar irradiance
- Sun intensity (low / medium / high)
- Temperature
- Humidity
- Cloud cover
- Wind speed

*These are contextual cues, not control inputs.*

### 5.2 Energy State

- Battery SOC with reserve zone
- “Safe / Caution / Risk” state
- Instantaneous PV power (kW)
- Cumulative PV energy (kWh) over 24–48h

### 5.3 Forecast Visualization (Required)

- Smooth graph:
  - PV Power (kW) vs time
  - Cumulative Energy (kWh) vs time
- Horizon: 24h or 48h
- **Forecast clearly labeled as forecast, not certainty**

### 5.4 Load & Appliance Interaction

- Appliance list with:
  - Name
  - Category (Critical / Flexible / Deferrable)
  - Quantity
  - Status: Allowed / Delay / Avoid
- Visual cues:
  - Green = safe to run
  - Red = avoid now
- **No physical switching implied**

### 5.5 Explainable Guidance (Core)

Each recommendation must include:

- **Headline** (one sentence)
- **Reason** (plain language)
- **Dominant factors** (SOC, PV forecast, reserve)
- **Risk level** (low / medium / high)

*LLMs may rephrase, never decide.*

---

## 6. What Must NOT Be Added (Scope Guardrails)

**Do not:**

- Add cost, tariff, or grid optimization
- Introduce opaque AI decision-making
- Remove deterministic explainability
- Expose low-level tuning (SOC limits, horizons) to general users
- Replace log-driven replay with black-box live logic

---

## 7. Auto-Run & Replay Philosophy

- The DT auto-runs on a fixed cadence (e.g. 15 min) for realism.
- Replay slider allows:
  - Inspecting past and future steps
  - Visualizing decision consistency
- **Logs remain the source of truth.**

This supports:

- Academic reproducibility
- User studies
- Debugging
- Reviewer confidence

---

## 8. Downloads & Evidence

Downloads are **evidence artifacts**, not marketing material.

**PDFs should include:**

- System configuration summary
- Weather context
- Today’s plan
- Tomorrow’s forecast-based plan
- Key KPIs
- Advisory disclaimer

CSV/JSONL remain available for analysis.

---

## 9. How Cursor / Developers Should Improve the App (Allowed)

**You may:**

- Improve layout, spacing, colors, typography
- Improve clarity of labels and descriptions
- Add better charts, gauges, cards
- Reduce cognitive load
- Improve responsiveness
- Refactor UI code for cleanliness

**You must preserve:**

- Data contracts
- Meaning of metrics
- Advisory framing
- Engine logic

---

## 10. One-Sentence North Star

> **“This interface exists to make a solar-first, off-grid energy digital twin understandable, trustworthy, and actionable for households — while remaining scientifically defensible and reproducible.”**

---

## 11. Developer Checklist for UI Changes

Use this when changing anything under `streamlit_app/` or docs/UI behaviour:

- [ ] **Intent:** Does the change preserve “advisory digital twin” framing? (No automatic hardware control, no tariff/cost optimization, no opaque AI.)
- [ ] **Engine boundary:** Is all control/forecast/KPI logic still only in `src/offgrid_dt/`? (UI only consumes logs and engine outputs.)
- [ ] **Manuscript alignment:** Does the UI still clearly support: energy autonomy, survivability, forecast awareness, explainability, human-centric language, replay, advisory mode?
- [ ] **Explainability:** Are headline, reason, dominant factors, and risk level still shown for each recommendation? (LLM may rephrase text only.)
- [ ] **Evidence:** Are downloads (PDF, CSV, JSONL) still treated as evidence artifacts with system summary, weather context, today/tomorrow plan, KPIs, and advisory disclaimer?
- [ ] **Labels:** Is “forecast” labeled as forecast (not certainty)? Are appliance statuses clearly Allowed / Delay / Avoid with green/red cues and no implied physical switching?
- [ ] **Data contracts:** Have you avoided changing the meaning or names of metrics and log columns consumed by the UI (or updated both logger and UI together)?

If any checkbox would be unchecked, revise the change or get explicit approval before proceeding.
