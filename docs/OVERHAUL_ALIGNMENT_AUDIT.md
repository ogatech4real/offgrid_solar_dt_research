# Overhaul Alignment Audit — Post–NASA POWER & Matching Layer

**Date:** February 2026  
**Scope:** Full verification of sidebar and main-body features against the current overhaul (NASA POWER day-ahead solar, matching layer, appliance advisories, advisory framing).  
**Intent:** Identify what is working as expected, what is misaligned, and what needs review. **No code changes** — evaluation and recommendations only for your review.

---

## 1. Overhaul Context (Current State)

The app now has:

- **Solar input:** NASA POWER (GHI for next planning day(s)); OpenWeather only for location + weather display.
- **Simulation timeline:** Starts at 00:00 UTC of the **next** calendar day (first planning day); all PV from NASA or synthetic fallback.
- **Matching layer:** Day-ahead demand vs solar → energy margin (surplus/tight/deficit), surplus/deficit windows, priority-aware (critical protected?), risk level, appliance advisories (safe to run / run in recommended window / avoid today).
- **Framing:** Day-ahead energy planning (00:00–24:00), advisory only, uncertainty and advisory intent stated.

---

## 2. Sidebar — Feature Inventory & Alignment

| # | Feature | Purpose | Working as expected? | Aligned with overhaul? | Notes |
|---|--------|---------|----------------------|------------------------|-------|
| 1 | **Location — Search** | OpenWeather geocoding → lat/lon/label | ✅ Yes | ✅ Yes | Correctly framed: “OpenWeather only for location + weather; solar from NASA POWER.” |
| 2 | **Location — Lat/Lon inputs** | Manual override / no-API use | ✅ Yes | ✅ Yes | Used for NASA POWER and weather when no search. |
| 3 | **Solar + Battery** | PV (kW), battery (kWh), inverter (kW) | ✅ Yes | ✅ Yes | Feed into simulator and matching. |
| 4 | **Run Mode — “Auto-run every 15 minutes”** | Toggle | ⚠️ Partial | ⚠️ See §3.1 | Behaviour is “re-run twin if last run >14 min when app re-executes” — **not** a 15‑min timer. |
| 5 | **Control strategy** | naive / static_priority / rule_based / forecast_heuristic | ✅ Yes | ✅ Yes | Default = forecast_heuristic is correct for manuscript. |
| 6 | **Simulation days** | 2, 3, or 7 days | ✅ Yes | ⚠️ See §3.3 | Works; label/role could be clearer for “day-ahead” (e.g. “Planning horizon (days)”). |
| 7 | **Run digital twin now** | Primary run trigger | ✅ Yes | ✅ Yes | Runs sim + matching; result includes `matching_first_day`. |
| 8 | **Run demo (2 days)** | Quick-start (London, 2 days) | ✅ Yes | ⚠️ See §3.4 | Useful; copy could stress “day-ahead planning demo” not “live” behaviour. |
| 9 | **Caption** | “Solar input: NASA POWER … Location from OpenWeather” | ✅ Yes | ✅ Yes | Correct. |

---

## 3. Deep-Dive: Sidebar Items You Asked About

### 3.1 Auto-run every 15 minutes — Relevant? Retain?

- **Current behaviour:**
  - Toggle stored in `st.session_state["auto_enabled"]`.
  - If True, code calls `getattr(st, "autorefresh", None)`. **`st.autorefresh` is not in core Streamlit** — it comes from the `streamlit-autorefresh` package, which is **not** in `requirements.txt`. So this call is always `None` and **no timer-based refresh runs**.
  - The only “auto” behaviour is later in the main body (lines 299–308): when `auto_enabled` is True and the user has not clicked “Run digital twin now”, the app checks `last_run_time`; if >14 minutes (or no prior run), it sets `run_btn = True` and runs the twin **on that script run**. So auto-run only happens when the app is **re-executed** (e.g. user refreshes the page or navigates back).
- **Manuscript/interface doc (§7):** “The DT auto-runs on a fixed cadence (e.g. 15 min) for realism.”
- **Assessment:**
  - **Relevant:** Yes — the *idea* of periodic day-ahead plan refresh fits “realism” and “day-ahead planning.”
  - **Currently working as a true 15‑min cadence?** No — there is no 15‑min timer unless `streamlit-autorefresh` is added and used.
  - **Recommendation:** Either (1) **retain** the toggle but rename/explain it (e.g. “Auto-run when you return (if last run &gt;14 min)”) and document that true 15‑min cadence would require adding `streamlit-autorefresh` or similar, or (2) add `streamlit-autorefresh` and wire it so that when the toggle is on, the page truly refreshes every 15 min and the existing “if last run &gt;14 min then run” logic then fires. Without (2), the current label “Auto-run every 15 minutes” is **misleading**.

### 3.2 Control strategy — Default to “forecast” (forecast_heuristic)?

- **Current:** Default is `forecast_heuristic` (via `controller_names.index("forecast_heuristic")` when in list; else 0).
- **Manuscript:** “Forecast-informed survivability-first scheduling.”
- **Assessment:** Defaulting to **forecast_heuristic** is **correct and should be retained**. It is the only controller that explicitly uses PV forecast (horizon average) and SOC for reserve/surplus behaviour and aligns with the manuscript and with NASA POWER day-ahead solar.

### 3.3 Simulation days (2 / 3 / 7) — Still needed? Run demo (2 days)?

- **Current:** Selector “Simulation days (for replay + tomorrow plan)” with options 2, 3, 7. Used as `days` in `simulate()` and for replay/PDF (multi-day log).
- **Overhaul:** Primary product is **day-ahead** (first planning day 00:00–24:00). Matching and main messaging are “next day.”
- **Assessment:**
  - **Still need simulation days?** **Yes.** Reasons: (1) Matching uses **first** day only; replay and PDF still show “today + tomorrow” (or more) for consistency and comparison. (2) Research/reviewer use cases (e.g. 7‑day replay) remain valid. (3) NASA POWER is requested for `days` planning days so the sim has PV for the full run.
  - **Recommendation:** **Retain** the selector. Optionally rename to something like “Planning horizon (days)” or “Days to simulate (replay + plan)” so it’s clear this is “how many days of day-ahead plan/replay” not “real-time control horizon.”
- **Run demo (2 days):** **Retain.** It gives a one-click path to see the full dashboard (including day-ahead outlook, matching, appliance advisories) with London and 2 days. Optional: add a short tooltip/caption that this is a “day-ahead planning demo” so it’s clear we’re not implying live control.

---

## 4. Main Body — Feature Inventory & Alignment

| # | Section | Purpose | Working as expected? | Aligned with overhaul? | Notes |
|---|---------|---------|----------------------|------------------------|-------|
| 1 | **Load — distribution board** | Select appliances (Critical/Flexible/Deferrable), qty, total load | ✅ Yes | ✅ Yes | Advisory only; no physical switching. |
| 2 | **Running hours (per day)** | Critical / Flexible / Deferrable h/day | ✅ Yes | ✅ Yes | Used for estimated consumption (planning). |
| 3 | **Estimated consumption (next 12h / 24h)** | kWh and avg kW from load + run hours | ✅ Yes | ✅ Yes | Framed as “planning — next day 00:00–24:00”. |
| 4 | **Live Replay** | Slider over simulation steps | ✅ Yes | ✅ Yes | Caption states timeline is day-ahead (00:00 next day), NASA POWER. |
| 5 | **Day-ahead outlook (00:00–24:00)** | Matching: daily text, solar/demand/margin, risk, surplus/deficit windows | ✅ Yes | ✅ Yes | Clear daily feasibility; risk from matching. |
| 6 | **Current Weather** | OpenWeather current conditions | ✅ Yes | ✅ Yes | Context only; not used for solar. |
| 7 | **KPI cards** | CLSR, Blackout min, SAR, Battery throughput | ✅ Yes | ✅ Yes | From state CSV; cumulative over replay. |
| 8 | **Power available (inverter) vs load** | PV now, PV+battery, total selected load | ✅ Yes | ✅ Yes | Per replay step. |
| 9 | **Recommendation** | Headline, explanation, risk pill, reason codes; battery state card | ✅ Yes | ⚠️ Minor | Per-step guidance; **risk** here is from **guidance** (step-wise). Day-ahead **risk** is in “Day-ahead outlook.” Two risk concepts (step vs day) both shown — acceptable but could be briefly explained. |
| 10 | **Solar forecast: next 24h (first planning day)** | Chart: PV power + cumulative energy for first 24h | ✅ Yes | ✅ Yes | Explicit “next 24h (first planning day)”, NASA POWER, “forecast, not certainty.” |
| 11 | **Forecast from replay point (24h or 48h)** | Same chart type from current replay step | ✅ Yes | ✅ Yes | Optional horizon; labeled as forecast. |
| 12 | **Household Power Use** | Requested vs served load, solar power (around replay step) | ✅ Yes | ✅ Yes | Good for “forecast → decision → outcome.” |
| 13 | **Appliance advisory (day-ahead)** | Safe to run / Run in recommended window / Avoid today from matching | ✅ Yes | ✅ Yes | Traceable to surplus/deficit and priority; not opaque AI. |
| 14 | **Recommended Schedule (Heatmap)** | Per-day, per-step served tasks | ✅ Yes | ✅ Yes | Log-driven; supports manuscript “digital twin + replay.” |
| 15 | **Downloads** | State CSV, guidance JSONL, PDF (system, weather, day-ahead plan, KPIs, advisory disclaimer) | ✅ Yes | ✅ Yes | PDF receives `matching_result`; day-ahead outlook and appliance advisories included. |

---

## 5. Cross-Cutting Checks

### 5.1 Two “risk” concepts

- **Step-wise risk** (Recommendation block): from guidance JSONL per step (explainability layer).
- **Day-ahead risk** (Day-ahead outlook): from matching (surplus/deficit, critical protection, energy margin).
- Both are low/medium/high and consistent with manuscript. No bug; optional improvement: one short line in the Recommendation area, e.g. “Day-ahead risk (above) summarizes the full day; this risk is for the current replay step.”

### 5.2 Manuscript checklist (from INTERFACE_MANUSCRIPT_ALIGNMENT.md §11)

- **Intent:** Advisory digital twin, no automatic hardware control, no tariff/cost, no opaque AI → ✅ Preserved.
- **Engine boundary:** Control/forecast/KPI/matching in `src/offgrid_dt/`; UI consumes logs and outputs → ✅ Preserved.
- **Manuscript alignment:** Energy autonomy, survivability, forecast awareness, explainability, human-centric, replay, advisory → ✅ Supported.
- **Explainability:** Headline, reason, dominant factors, risk per recommendation → ✅ Present.
- **Evidence:** PDF with system summary, weather, today/tomorrow plan, KPIs, advisory disclaimer → ✅ Plus day-ahead outlook and appliance advisories.
- **Labels:** “Forecast” as forecast; appliance statuses Allowed/Delay/Avoid (now Safe / Run in window / Avoid today) with green/red cues; no physical switching → ✅ Aligned.
- **Data contracts:** Metrics and log columns used by UI match logger/simulator → ✅ No change needed.

---

## 6. Summary Table

| Area | Working as expected | Aligned with overhaul | Action |
|------|--------------------|------------------------|--------|
| **Sidebar — Location, Solar+Battery, Control strategy, Run buttons** | Yes | Yes | None. Default forecast_heuristic: keep. |
| **Sidebar — Auto-run every 15 min** | Partial (no real 15‑min timer) | Toggle retained in doc; label misleading | Clarify label and/or add streamlit-autorefresh. |
| **Sidebar — Simulation days** | Yes | Yes (optional label tweak) | Retain; optionally rename for “planning horizon.” |
| **Sidebar — Run demo (2 days)** | Yes | Yes | Retain; optionally frame as “day-ahead planning demo.” |
| **Main — Load, consumption, replay, day-ahead outlook, weather, KPIs, power vs load** | Yes | Yes | None. |
| **Main — Recommendation** | Yes | Yes | Optional: one line distinguishing step risk vs day-ahead risk. |
| **Main — Solar charts, Household Power Use, Appliance advisory, Schedule, Downloads** | Yes | Yes | None. |

---

## 7. Recommendations (For Your Decision)

1. **Auto-run:**  
   - **Retain** the toggle (manuscript supports “fixed cadence”).  
   - **Fix** the implementation or the label:  
     - Either add `streamlit-autorefresh` (or equivalent) so “Auto-run every 15 minutes” really triggers a refresh every 15 min and the existing “run if last run >14 min” logic runs,  
     - Or change the label to something like “Auto-run when you return (if last run &gt;14 min)” and add a short caption so users are not misled.

2. **Control strategy default:**  
   - **Keep** default = `forecast_heuristic`. No change.

3. **Simulation days:**  
   - **Keep** the selector (2, 3, 7).  
   - **Optional:** Rename to “Planning horizon (days)” or “Days to simulate (replay + plan)” for day-ahead clarity.

4. **Run demo (2 days):**  
   - **Keep** it.  
   - **Optional:** Tooltip or caption: “Day-ahead planning demo — explore the dashboard with default location and 2 days.”

5. **Main body:**  
   - No structural changes needed.  
   - **Optional:** One sentence near the Recommendation block to distinguish “day-ahead risk” (above) from “current step risk” (here).

Once you’ve reviewed this audit, we can decide which of these options to implement and in what order.
