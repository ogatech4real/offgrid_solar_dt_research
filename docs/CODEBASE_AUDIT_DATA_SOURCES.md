# Codebase Audit — Data Sources & Orphan Check

**Date:** February 2026  
**Scope:** Trace every displayed output in the Streamlit app to its data source. Confirm all values are **real, live-connected** (no orphan or placeholder-only displays).

**Re-verification:** Full codebase re-audit confirmed (February 2026): all display elements remain correctly wired to their sources; `matching_first_day` is set in simulator (`to_dict()`) and consumed via `res.get("matching_first_day")`; state CSV and guidance JSONL are read by replay step. **Conclusion: no orphan displays; all outputs are real and connected.**

---

## 1. Data Flow Overview

| Source | Produced by | Consumed by |
|--------|-------------|-------------|
| **State CSV** | `RunLogger.flush()` in simulator; each row = one `StepRecord` (timestamp, pv_now_kw, soc_now, load_*, crit_*, kpi_*, served_task_ids, etc.) | UI: `df = pd.read_csv(state_csv)`; `row = df.iloc[step]` for replay step |
| **Guidance JSONL** | Same simulator run; one line per step = `guidance.model_dump()` + timestamp | UI: `gdf = pd.read_json(guidance_jsonl, lines=True)`; `grow = gdf.iloc[step]` |
| **matching_first_day** | `compute_day_ahead_matching(first_day_df, ...)` in simulator after flush; stored as `out["matching_first_day"] = matching.to_dict()` | UI: `matching = res.get("matching_first_day")` or fallback recompute from `df.head(96)` |
| **Current weather** | `OpenWeatherSolarClient.current_weather(lat, lon)` using `st.session_state["latitude"]`, `["longitude"]` | UI: displayed at top of main; `st.session_state["current_weather"]` for PDF |
| **Session state** | User inputs (sidebar + load board + run hours) | UI: config, appliances, replay_step, selected_appliances, qty_map, current_weather |

---

## 2. Display Element ↔ Source (Full Audit)

### 2.1 Sidebar

| Display | Source | Real / Orphan? |
|---------|--------|-----------------|
| Location search, lat/lon, location_name | `st.session_state` (user + OpenWeather geocode) | **Real** — from geocode or manual input |
| PV capacity, battery, inverter | `st.session_state["pv_kw"]`, `["bat_kwh"]`, `["inv_kw"]` | **Real** — user input |
| Auto-run toggle, control strategy, planning days | `st.session_state` | **Real** — user input |
| Run / Demo buttons | Triggers `simulate()` and stores `last_run` | **Real** — drives result block |

### 2.2 Main — Before Run (Always Visible)

| Display | Source | Real / Orphan? |
|---------|--------|-----------------|
| **Current Weather** (status, temp, humidity, cloud, wind) | `weather = client.current_weather(lat_w, lon_w)` with `st.session_state["latitude"]`, `["longitude"]` | **Real** — OpenWeather API for current location; updates when location is set |
| **Load board** (toggles, qty, total load kW) | `st.session_state` load_on_*, qty_*, `appliance_catalog()` | **Real** — user selection; total_load_kw = sum of selected circuit power |
| **Running hours** (Critical/Flexible/Deferrable h/day) | `st.number_input(..., key="run_hrs_*")` | **Real** — user input |
| **Estimated consumption** (24h / 12h kWh, avg kW) | Computed from selected appliances × run_hrs_by_cat; `catalog`, `st.session_state` load_on_*, qty_* | **Real** — formula: sum over selected (power_kw × hrs) |

### 2.3 Main — After Run (Results Block)

| Display | Source | Real / Orphan? |
|---------|--------|-----------------|
| **Replay slider** | `df` from state CSV; `step_max = len(df)-1`; `step` from session_state | **Real** — state CSV length and current step |
| **row**, **now_ts** | `row = df.iloc[step]`, `now_ts = row["ts"]` | **Real** — state CSV row for current replay step |
| **matching** | `res.get("matching_first_day")` (dict from simulator) or `compute_day_ahead_matching(first_day_df, ...)` fallback | **Real** — from run or recomputed from first 96 rows of state CSV |
| **Day-ahead outlook — solar chart (PV kW over 24h)** | `df_day = df.head(steps_24h)`; `pv_kw_24h = df_day["pv_now_kw"]`, `ts_24h = df_day["ts"]` | **Real** — first 24h of state CSV (NASA POWER–derived PV from simulator) |
| **Day-ahead outlook — Summary metrics** (Expected solar 24h, Planned demand 24h, Energy margin, Risk) | `_m(matching, "total_solar_kwh")`, `"total_demand_kwh"`, `"energy_margin_kwh"`, `"risk_level"` | **Real** — from matching (computed from first-day state CSV) |
| **Day-ahead outlook — daily_outlook_text** | `_m(matching, "daily_outlook_text")` | **Real** — from matching |
| **Day-ahead outlook — surplus/deficit bar chart** | `pv_kw_24h`, `load_kw_day = df_day["load_requested_kw"]`; surplus_flag = pv >= load | **Real** — same first-day state CSV; bars match surplus_windows / deficit_windows |
| **Day-ahead outlook — surplus/deficit windows list** | `_m(matching, "surplus_windows")`, `"deficit_windows"` | **Real** — from matching (same logic as bar chart) |
| **Day-ahead outlook — critical_fully_protected warning** | `_m(matching, "critical_fully_protected")` | **Real** — from matching |
| **KPI cards** (Critical reliability %, Blackout min, Solar autonomy %, Battery wear kWh) | `row.get("kpi_CLSR", 0)`, `row.get("kpi_Blackout_minutes", 0)`, `row.get("kpi_SAR", 0)`, `row.get("kpi_Battery_throughput_kwh", 0)` | **Real** — state CSV row; KPIs from `KPITracker.snapshot()` per step (cumulative) |
| **Power available (PV now, PV+battery, Total selected load)** | `row.get("pv_now_kw")`, `row.get("soc_now")`, `soc_min`, `st.session_state["inv_kw"]`; total_selected_kw from appliance_catalog × load_on_* × qty_* | **Real** — state CSV + session state |
| **Recommendation** (risk pill, headline, explanation, reason codes) | `grow = gdf.iloc[step]`; `grow.get("risk_level")`, `"headline"`, `"explanation"`, `"reason_codes"` | **Real** — guidance JSONL row for same step (written by simulator from generate_guidance + optional OpenAI) |
| **Battery state card** (SOC %, Safe/Caution/Risk) | `row.get("soc_now")`, risk from guidance | **Real** — state CSV + guidance |
| **Solar forecast from replay point** (24h/48h chart) | `df["pv_now_kw"].iloc[i0:i1]`, `pd.date_range(now_ts, ...)` | **Real** — state CSV slice from current step |
| **Household Power Use** (Requested/Served/PV lines) | `sub = df.iloc[...]`; `sub["load_requested_kw"]`, `load_served_kw`, `pv_now_kw` | **Real** — state CSV |
| **Appliance advisory table** (by category: Status, Why) | `_m(matching, "appliance_advisories")`; adv_by_name; selected_appliances, qty_map from session_state | **Real** — matching + session state (appliances selected for the run) |
| **Recommended Schedule (Heatmap)** | `one = day_df2[day_df2["day"]==day_match]`; `one.get("served_task_ids")`; parsed to appliance ids | **Real** — state CSV served_task_ids for selected day |
| **Downloads** (CSV, JSONL, PDF) | `state_csv`, `guidance_jsonl` paths from res; `pdf_bytes` from `build_two_day_plan_pdf_from_logs(..., system_summary_override, weather_summary=current_weather, matching_result=matching_for_pdf)` | **Real** — same logs and matching; PDF uses session config + current_weather + matching |

---

## 3. Engine → Logs Contract (Verification)

- **Simulator** builds, per step: `StepRecord(timestamp=..., pv_now_kw=..., soc_now=..., load_requested_kw=..., load_served_kw=..., crit_*=..., decision=..., guidance=..., kpis_running=kpis.snapshot())`.
- **RunLogger.flush()** writes one state row per record; row keys include `pv_now_kw`, `soc_now`, `load_requested_kw`, `load_served_kw`, `crit_requested_kw`, `crit_served_kw`, `served_task_ids`, `risk_level`, `headline`, `explanation`, `reason_codes`, and `kpi_CLSR`, `kpi_Blackout_minutes`, `kpi_SAR`, `kpi_Solar_utilization`, `kpi_Battery_throughput_kwh` (from `r.kpis_running`).
- **KPITracker.snapshot()** returns CLSR, Blackout_minutes, SAR, Solar_utilization, Battery_throughput_kwh — these are cumulative up to that step.
- **UI** reads state CSV and guidance JSONL by replay `step`; all metrics and charts use this row or slices of `df`. No hardcoded or placeholder-only metrics in the results block.

---

## 4. Orphan Check Result

- **No orphan displays found.** Every displayed value in the app is either:
  - **User input** (sidebar, load board, run hours),
  - **Live API** (OpenWeather current weather for location),
  - **Run output** (state CSV, guidance JSONL, matching_first_day), or
  - **Derived from the above** (e.g. total load from selected appliances, estimated consumption from load × run hours, surplus/deficit from first-day state CSV and matching).
- **Captions** that describe “from day-ahead simulation”, “at current replay step”, “regenerated when you run the twin” correctly reflect that KPIs and recommendations are tied to the last run and the selected replay step.

---

## 5. Edge Cases

- **No run yet:** Results block is not rendered (`st.stop()` after “Run the digital twin to see results”). Weather, load board, running hours, and estimated consumption are still shown and are real (location/user input).
- **Matching missing in result:** If `matching_first_day` is absent (e.g. old run), UI recomputes matching from `df.head(steps_per_day_ui)` and current session config so day-ahead outlook and appliance advisories remain real and consistent with the first 24h of the state CSV.
- **OpenWeather key missing:** Weather block shows caption only; no fake data. Solar path uses NASA POWER (or synthetic fallback) and is independent of weather.

---

## 6. Conclusion

All outputs displayed in the app are **real and connected** to live or run-derived data. There are **no orphan or placeholder-only displays** in the current codebase.
