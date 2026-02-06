# Troubleshooting: Why Real NASA POWER GHI Is Not Used (Synthetic Data Always)

**Date:** February 2026  
**Issue:** The solar graph is always the same; live GHI from NASA POWER does not appear to be used; the app feels unrealistic.  
**Scope:** Deep investigation only — no code changes. Root cause and recommendations.

---

## 1. Summary of findings

**Root cause:** The app requests GHI for **tomorrow** (and the next N days). NASA POWER does **not** provide future or forecast data. It only provides **historical and near real-time (NRT)** data, with **5–7 day latency for solar parameters**. So every request is for dates that the API does not have → the API returns no usable data or an error → the simulator always falls back to **synthetic** irradiance. The synthetic curve is a **fixed bell shape** (same every run), which is why the graph looks the same.

---

## 2. Data flow (what the code does)

### 2.1 How the simulator gets PV data

1. **Simulator** (`dt/simulator.py`) decides the “first planning day”:
   - `first_planning_date = now_utc.date() + timedelta(days=1)`  
   → **always tomorrow** (UTC).

2. It calls:
   - `fetch_ghi_next_planning_days(lat, lon, days, reference_utc=now_utc)`.

3. **fetch_ghi_next_planning_days** (`forecast/nasa_power.py`):
   - `today = reference_utc.date()`
   - `first_planning_day = today + timedelta(days=1)` → **tomorrow**
   - `last_planning_day = today + timedelta(days=days)` → tomorrow + (days-1)
   - Calls `fetch_ghi_hourly(lat, lon, start_dt, end_date)` with **start = tomorrow 00:00 UTC**, **end = last planning day**.

4. **fetch_ghi_hourly**:
   - Builds request: `start=YYYYMMDD`, `end=YYYYMMDD` (e.g. tomorrow’s date).
   - `GET https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=ALLSKY_SFC_SW_DWN&community=RE&latitude=...&longitude=...&start=20260204&end=20260205&format=JSON&time-standard=UTC`
   - Parses response with `_parse_nasa_power_ghi(data)`.

5. If `irr` is empty or an exception occurs, the simulator uses **synthetic_irradiance_forecast(...)** instead.

So from the code’s perspective, **every run asks NASA POWER for tomorrow (and possibly the next days)**. There is no path in the current design where “today” or “yesterday” is requested for the main planning horizon.

---

## 3. NASA POWER API constraints (official behaviour)

From NASA POWER documentation and FAQs:

| Fact | Source |
|------|--------|
| Hourly data is available from **2001/01/01 to Near Real Time (NRT)**. | [Hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/) |
| **No future forecast.** The API only serves historical and NRT data. | Multiple docs and web summaries. |
| **Solar parameters have 5–7 day latency.** NRT for solar means data is typically available only up to about **5–7 days before “today”**. | [Data FAQs – Latency](https://power.larc.nasa.gov/docs/faqs/data/) |
| Requesting dates **outside the valid range (e.g. future)** can result in **422 validation errors** or **empty/no data**. | API behaviour and troubleshooting (e.g. Stack Overflow 422). |

So:

- **“Tomorrow”** is **always** outside the valid range (future).
- Even **“today”** is often outside the valid range for **solar**, because of the 5–7 day latency.

Therefore, for the current app design (requesting tomorrow’s GHI), NASA POWER will **never** be able to return real solar data for the requested dates. The only outcome is: no data or error → fallback to synthetic.

---

## 4. Why the graph always looks the same

When the fallback is used, the simulator calls:

- `synthetic_irradiance_forecast(start=start, hours=24*days, step_minutes=dt_minutes)`  
  with a fixed `peak_ghi_wm2=850.0` (default).

That function:

- Uses a **deterministic bell curve** between 06:00 and 18:00 (UTC).
- Same formula every time: `ghi = peak_ghi_wm2 * (4 * x * (1 - x))` with `x = (hour - 6) / 12`.
- No location, no weather, no season.

So every run that uses synthetic produces the **same shape** and similar magnitude. That matches the observation that “the graph has been the same” and that “live GHI are not captured”.

---

## 5. Possible failure points (in order of likelihood)

1. **Date range (primary)**  
   - Requested range is **tomorrow → tomorrow+(days-1)**.  
   - NASA POWER has no data for those dates (future / beyond NRT).  
   - Result: empty `properties.parameter.ALLSKY_SFC_SW_DWN` or 422 → `irr` empty or exception → synthetic.

2. **API returns 200 but empty structure**  
   - For invalid/future dates, the API might return HTTP 200 with a JSON that has no hourly GHI (e.g. empty object or different structure).  
   - `_parse_nasa_power_ghi` would then return `[]` → `if irr:` is False → synthetic.

3. **API returns 422 for future dates**  
   - `r.raise_for_status()` raises → exception in simulator → `except` branch → synthetic.  
   - So even with 422, the app “works” but always on synthetic.

4. **Network / timeouts**  
   - Any request failure (timeout, DNS, etc.) also leads to exception → synthetic.  
   - Would not explain “always the same” by itself; would be intermittent unless the environment always blocks or times out.

5. **Parameter/community**  
   - We use `ALLSKY_SFC_SW_DWN` and `community=RE`. These are valid for the Renewable Energy community.  
   - If the request were for **valid past dates**, this would work. So parameter/community are unlikely the root cause; the date range is.

---

## 6. How to confirm in your environment

Without changing app logic, you can verify behaviour as follows:

1. **Check logs when running a simulation**  
   - If you see: `"Using NASA POWER GHI for day-ahead PV forecast (N points)"` → NASA returned data (only possible if something in the request or server behaviour is different from “tomorrow”).  
   - If you see: `"NASA POWER returned no GHI points for YYYYMMDD–YYYYMMDD"` → API returned 200 but no GHI (e.g. future dates).  
   - If you see: `"NASA POWER fetch failed (...); falling back to synthetic irradiance"` → Exception (e.g. 422, timeout, or parse error).

2. **Call the API by hand with the same dates the app would use**  
   - Compute “tomorrow” in UTC and call:  
     `https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=ALLSKY_SFC_SW_DWN&community=RE&longitude=<lon>&latitude=<lat>&start=<tomorrow_YYYYMMDD>&end=<tomorrow_YYYYMMDD>&format=JSON&time-standard=UTC`  
   - Then try the same with a **past** date (e.g. today minus 7 days).  
   - Compare: for “tomorrow” you should get empty or 422; for “today minus 7” you should get hourly GHI in the response.

3. **Check the UI “Source” label**  
   - After a run, the chart and caption show “Source: NASA POWER” or “Source: Synthetic (demo)”.  
   - If it always shows “Synthetic (demo)”, that confirms the simulator never received usable NASA data for the requested dates.

---

## 7. Recommendations (what can be done)

### Option A: Use the latest available NASA POWER window (real GHI, but “recent past” not “tomorrow”)

- **Idea:** Request GHI for the **most recent period that NASA POWER actually has** for solar (e.g. “today minus 7 days” through “today minus 6 days”, or the latest single day available), instead of “tomorrow”.
- **Pros:** You get **real** GHI from NASA POWER, so the graph reflects real data and varies by location and date.  
- **Cons:** The planning horizon is no longer “tomorrow” but “a recent past day”. You’d need to relabel the UI (e.g. “Solar from latest available day (NASA POWER)” and use that day as a proxy for “typical” or “recent” conditions rather than a true forecast.

### Option B: Keep “day-ahead” semantics and add a real forecast source

- **Idea:** Keep requesting “tomorrow” for planning, but get **tomorrow’s** GHI from a source that **does** provide forecasts (e.g. OpenWeather One Call, Solcast, or another solar forecast API).
- **Pros:** Real forecast for the actual planning day; graph can change daily and by location.  
- **Cons:** Requires integrating (and possibly subscribing to) another API; may not be free or open like NASA POWER.

### Option C: Hybrid (NASA when available, synthetic otherwise)

- **Idea:** First try NASA POWER for a **valid** range (e.g. latest available day: today minus 7 days). If that succeeds, use it (and label it as “latest available NASA POWER day”). If it fails, fall back to synthetic and label “Synthetic (demo)”.
- **Pros:** Real data when the API responds; no future-date request.  
- **Cons:** “Day-ahead” in the UI would need to be reframed (e.g. “Planning based on latest available solar day” or similar).

### Option D: Keep current design but make the limitation explicit

- **Idea:** Do not change the data source. Keep requesting “tomorrow” (so NASA never has data) and using synthetic. Improve UI and docs to state clearly: “Solar curve is synthetic (demo) because NASA POWER does not provide future forecasts; use for layout and behaviour only.”
- **Pros:** No API or logic change; clear expectations.  
- **Cons:** Graph remains non-realistic and always the same.

---

## 8. Conclusion

- **Why real GHI is not used:** The app asks NASA POWER for **tomorrow’s** (and following days’) GHI. NASA POWER only has **historical + NRT** data with **5–7 day latency for solar**, and **no future forecasts**. So the requested dates never have data → response empty or error → synthetic used every time.
- **Why the graph looks the same:** The fallback is a **fixed synthetic bell curve**; it does not depend on location or date, so the graph is the same every run.
- **What can be done:** Either request **past** dates within NASA POWER’s valid range (Options A or C), or add a **forecast** source for tomorrow (Option B), or keep synthetic and document the limitation (Option D). No code was changed in this investigation; the above are recommendations for when you decide to implement a fix.
