# Implementation Plan: Expected Solar from Historical GHI (Minimal UI)

**Goal:** Bring “expected solar over the next 24h” to use **real** NASA POWER data by fetching a rolling historical window (e.g. last 7 days), building an hourly mean profile, and using it for the run. **Minimise UI changes:** keep existing wording (“expected”, “next 24h”); only update how the **data source** is shown so users know when it’s real (NASA POWER last 7 days) vs synthetic.

**Out of scope for this plan:** Min/max bounds for survivability/opportunity (mean only for now). No new UI sections, no rewording of “day-ahead” or “expected” beyond the source label.

---

## 1. What will change (summary)

| Layer | What | UI impact |
|-------|------|-----------|
| **forecast/nasa_power.py** | Add: fetch historical window; build 24h mean (and optionally min/max) profile from hourly GHI. | None |
| **dt/simulator.py** | Use historical profile instead of “tomorrow” fetch; produce PV series from mean profile; set `solar_source` to `nasa_power_historical` or `synthetic`. | None |
| **streamlit_app/app.py** | Map `solar_source == "nasa_power_historical"` to a clear label and, if desired, one short caption. | **Minimal:** source label + optional one-line caption only. |
| **io/pdf_report.py** | Use same source value for “Solar source” in PDF (e.g. “NASA POWER (last 7 days)” when applicable). | Same string as UI. |

Existing copy (e.g. “Expected solar over the next 24 hours”, “Your day-ahead outlook”) stays as is. No new widgets, no new sections.

---

## 2. Engine changes (explicit)

### 2.1 `src/offgrid_dt/forecast/nasa_power.py`

**Add (do not remove existing functions):**

1. **`fetch_ghi_historical_window(lat, lon, reference_utc=None, window_days=7, lag_days=7)`**
   - Returns: `List[IrradiancePoint]` for a **past** window.
   - Behaviour:
     - `reference_utc = reference_utc or datetime.now(tz=timezone.utc)`; normalize tz.
     - `end_date = reference_utc.date() - timedelta(days=lag_days)` (e.g. 7 days ago so we stay behind solar latency).
     - `start_date = end_date - timedelta(days=window_days - 1)` (e.g. 7 days of data).
     - Call existing `fetch_ghi_hourly(lat, lon, start_date, end_date, time_standard="UTC")`.
     - Return the list (may be empty if API fails or returns nothing).

2. **`build_hourly_ghi_profile(points: List[IrradiancePoint]) -> tuple`**
   - Input: list of hourly `IrradiancePoint` (ts, ghi_wm2) from the historical window.
   - Output: `(mean_24, min_24, max_24)` where each is a list of 24 floats: index = hour-of-day 0..23.
   - Behaviour:
     - Group points by `ts.hour` (0..23). For each hour `h`, collect all `ghi_wm2` values.
     - `mean_24[h] = mean(values)`; `min_24[h] = min(values)`; `max_24[h] = max(values)`.
     - If a hour has no data, use 0.0 (or interpolate from neighbours); document the choice.
   - For this plan we **use only mean_24** in the simulator; min/max can be stored for future use or ignored for now.

3. **`expected_ghi_profile_from_history(lat, lon, reference_utc=None, window_days=7, lag_days=7)`**
   - Returns: `List[IrradiancePoint]` of length 24 (one per hour 0..23) with **mean** GHI, with placeholder datetimes (e.g. “next day” 00:00..23:00 UTC) so downstream `irradiance_to_pv_power_kw` and resampling work unchanged.
   - Behaviour:
     - Call `fetch_ghi_historical_window(...)`.
     - If empty, return `[]`.
     - Else call `build_hourly_ghi_profile(points)` → get `mean_24`.
     - Build 24 `IrradiancePoint(ts=..., ghi_wm2=mean_24[h])` with ts set to a nominal “planning day” (e.g. first_planning_date at hour h). Caller (simulator) will use these only for the GHI values; timeline is already set by the simulator.

**Keep unchanged:** `fetch_ghi_hourly`, `fetch_ghi_next_planning_days`, `_parse_nasa_power_ghi`. No breaking changes to existing callers.

### 2.2 `src/offgrid_dt/dt/simulator.py`

**Replace only the PV-forecast block** (the `try` that calls `fetch_ghi_next_planning_days`). Do not change time loop, logger, or matching.

1. **Import:** Add `expected_ghi_profile_from_history` from `offgrid_dt.forecast.nasa_power` (or a single helper that does fetch + profile + return 24 points). Keep `fetch_ghi_next_planning_days` import only if still used for fallback; else remove and use only historical path.

2. **Logic (explicit steps):**
   - Set `solar_source = "synthetic"`.
   - Try:
     - Call `expected_ghi_profile_from_history(lat=cfg.latitude, lon=cfg.longitude, reference_utc=now_utc, window_days=7, lag_days=7)`.
     - If result is non-empty (24 points):
       - For a **multi-day** run (`days` > 1): replicate the 24-point profile for each day (e.g. 24 * days points) so that the same “expected day” shape repeats.
       - Convert to PV power: `pv_forecast_kw_full = irradiance_to_pv_power_kw(irr, cfg.pv_capacity_kw, cfg.pv_efficiency)`.
       - Resample to step count: `pv_forecast_kw_full = _resample_to_steps(pv_forecast_kw_full, total_steps)`.
       - Set `solar_source = "nasa_power_historical"`.
       - Log: e.g. "Using NASA POWER historical GHI (last 7 days) for expected solar profile."
     - If result is empty or exception: keep existing fallback (synthetic), log warning as today.
   - Ensure `out["solar_source"]` is set to `solar_source` (already done in current code).

3. **Leave unchanged:** `start` (first planning day 00:00 UTC), `total_steps`, `_resample_to_steps`, rest of simulator.

---

## 3. UI changes (minimal and explicit)

### 3.1 `streamlit_app/app.py`

**Only two small edits:**

1. **Source label (chart annotation + caption)**  
   Locate where `solar_source` and `source_label` are set (e.g. after `res.get("solar_source")`).  
   - Current: `source_label = "NASA POWER" if solar_source == "nasa_power" else "Synthetic (demo)"`.  
   - Change to:
     - If `solar_source == "nasa_power_historical"`: `source_label = "NASA POWER (last 7 days)"`.
     - Else if `solar_source == "nasa_power"`: `source_label = "NASA POWER"` (keep for any future use).
     - Else: `source_label = "Synthetic (demo)"`.
   - No change to the chart title (“Expected solar over the next 24 hours”) or to the annotation text beyond using this `source_label`.
   - Caption under the chart: keep current line “Solar data for this run: **{source_label}**.” Optionally add a single line only when `solar_source == "nasa_power_historical"`: e.g. “Expected profile from recent 7 days at your location.” (One line; no new section.)

2. **No other UI changes:** Do not add new sections, change “day-ahead”, “expected”, or other wording. Do not add min/max band or survivability/opportunity UI in this plan.

### 3.2 `src/offgrid_dt/io/pdf_report.py`

**Single point:** Where the PDF system summary or “Solar source” string is set (e.g. in `build_two_day_plan_pdf_from_logs` or the dict passed in), ensure that when `solar_source == "nasa_power_historical"` the displayed string is **"NASA POWER (last 7 days)"** (or the same as the UI label). If the PDF currently takes this from the run result, the simulator will already return `solar_source = "nasa_power_historical"`; the app builds `system_summary_override` and may pass a “Solar source” key — in that case, when building that dict (in the app), set “Solar source” to the same label as in the UI when `res.get("solar_source") == "nasa_power_historical"`. So: one conditional string in the place that builds the PDF system summary.

---

## 4. What will not change

- **Wording:** “Expected solar over the next 24 hours”, “Your day-ahead outlook (00:00–24:00)”, “Expected solar”, “Your planned demand”, “Energy margin”, “Appliance advice for tomorrow”, etc. All remain as they are.
- **Structure:** No new sidebar controls, no new expanders, no new charts. Only the **value** behind the chart (real GHI-based when NASA historical works) and the **source label/caption** change.
- **Matching / statements:** They keep using the same state CSV and matching result; the only difference is that the state CSV will now be filled with PV from the historical mean profile when NASA POWER data is available.
- **Fallback:** If NASA POWER historical fetch fails or returns no points, behaviour stays as today: synthetic profile and `solar_source = "synthetic"`, with existing caption.

---

## 5. Order of implementation (when you implement)

1. **nasa_power.py:** Add `fetch_ghi_historical_window`, `build_hourly_ghi_profile`, `expected_ghi_profile_from_history`. Add/update tests if needed (e.g. parse + profile build from fixed list).
2. **simulator.py:** Switch PV block to use `expected_ghi_profile_from_history`, replicate for multi-day, convert to PV, resample; set `solar_source` to `nasa_power_historical` or `synthetic`.
3. **app.py:** Extend source label branch for `nasa_power_historical`; optionally add one caption line.
4. **pdf_report / app:** Ensure PDF “Solar source” string reflects `nasa_power_historical` with the same label.

---

## 6. Result for the user

- When NASA POWER historical data is available: the “Expected solar over the next 24 hours” chart and all downstream metrics (expected kWh, surplus/deficit, risk, statements) will be based on **real** GHI from the **last 7 days** at the user’s location, and the chart will **vary** by location and over time as the window moves.
- The UI will still say “expected” and “next 24h”; the only explicit change is the **source** line: “NASA POWER (last 7 days)” instead of “Synthetic (demo)” when real data is used, with an optional one-line caption that it’s from recent 7 days at their location.
- No overclaim: we do not say “tomorrow’s forecast”; we say “expected” and “from last 7 days,” which matches the implementation.

This is the full explicit plan with minimal UI impact before any code is written.
