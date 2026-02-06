# Feasibility: Historical GHI Rolling Window → Expected Profile & Bounds

**Status:** Assessment only — no implementation.  
**Question:** Can we fetch historical hourly GHI (7–14 days), build an expected profile with min/mean/max, distribute it over the next 0–24h, and use it so the graph is real and representative?

---

## 1. Short answer

**Yes — it is achievable both scientifically and technically.** It fits NASA POWER’s data (historical + NRT only), reuses the existing pipeline (GHI → PV → simulator → matching), and gives a clear meaning to mean vs lower vs upper bound. The main requirement is to use a **past** date window and to **label** the product correctly (e.g. “Expected GHI from last 7 days” rather than “tomorrow’s forecast”).

---

## 2. Technical feasibility

### 2.1 Fetching historical GHI (7–14 days)

- NASA POWER hourly API supports a **date range** (start/end). Data are available from 2001 to **Near Real Time**, with **5–7 day latency for solar**.
- So we must request **only past dates** that are already available. For example:
  - End date: `today_utc - 7` (or 8) days so we stay behind the solar latency.
  - Start date: `end_date - 6` for 7 days of data, or `end_date - 13` for 14 days.
- Example: “last 7 days of available solar” = `start = (today - 14)`, `end = (today - 7)` (7 calendar days, all within the valid window).
- The existing `fetch_ghi_hourly(lat, lon, start_date, end_date)` already accepts arbitrary start/end; we only need to call it with this **past** window instead of “tomorrow”. So **fetching is technically straightforward**.

### 2.2 Building expected profile and bounds

- Input: list of hourly `IrradiancePoint` (ts, ghi_wm2) over 7–14 days.
- For each **hour-of-day** `h` (0..23):
  - Collect all GHI values at that hour across the days.
  - Compute **min**, **mean**, **max** (and optionally percentiles, e.g. 10th / 90th).
- Output: three length-24 series: `ghi_mean[h]`, `ghi_min[h]`, `ghi_max[h]`.
- Implementation: group by hour-of-day, then aggregate. No new external dependencies; numpy/pandas or plain Python is enough. **Technically trivial.**

### 2.3 Distributing over “next 0–24h” and feeding the simulator

- The simulator expects a **per-step** PV power series for the planning horizon (e.g. 96 steps for 24h at 15 min).
- **Mapping:** Treat “next 24h” as a **generic** 24-hour day. Hour 0 = 00:00, hour 1 = 01:00, … hour 23 = 23:00. Assign:
  - **Expected (mean):** at hour `h`, use `ghi_mean[h]` → convert to PV power → resample to 15-min (e.g. repeat or interpolate) → this is the main series for the run.
- So the “expected” profile for “the next 24h” is exactly the **recent historical mean by hour-of-day**. We are not dating it to “tomorrow” in the API; we only use it as the shape for the next 24h in the app.
- Existing chain stays the same: GHI series → `irradiance_to_pv_power_kw` → `_resample_to_steps` → `pv_forecast_kw_full` → time loop. So **integration is feasible** with minimal change: a new function that (1) fetches the past window, (2) computes mean/min/max by hour, (3) outputs a 24h GHI series (mean for main run); optionally also outputs min/max series for survivability/opportunity.

### 2.4 Using bounds (survivability vs opportunity)

- **Mean** → main PV series → existing “expected energy” and day-ahead matching (surplus/deficit, risk, statements). This is the “expected” case.
- **Lower bound (min)** → conservative PV series. Can be used to:
  - Run a **second** matching pass (or same logic with min profile) → “survivability” view: e.g. “If solar is at the low end of recent experience, you’d have deficit in these windows.”
- **Upper bound (max)** → optimistic PV series. Can be used for:
  - “Opportunity” view: “If solar is at the high end of recent experience, you’d have surplus in these windows.”
- Implementation options: (a) single run with mean only (simplest); (b) run with mean and store min/max GHI in state or matching for UI (e.g. shaded band on the chart); (c) two extra “shadow” runs with min and max for separate survivability/opportunity messages. All are **technically feasible**; (b) or (c) gives the clearest “survivability vs opportunity” story.

---

## 3. Scientific validity and limitations

### 3.1 What the construction represents

- **Mean profile:** “Average hourly GHI over the last 7–14 days at this location.” Used as the **expected** GHI for the next 24h.
- **Min / max (or percentiles):** “Worst and best hourly GHI in that window.” They are **not** forecast uncertainty intervals; they are **observed spread** in recent history.

So we are **not** claiming “tomorrow’s forecast with confidence intervals.” We are claiming “expected and range of recent experience, applied to the next 24h.” That is a standard, defensible use of recent climatology / persistence for energy planning when no forecast is available.

### 3.2 When it is scientifically reasonable

- **Season and regime:** If the next 24h are in the same season and similar weather regime as the last 7–14 days, the recent mean is a plausible “expected” day. For many off-grid use cases (e.g. tropical or dry seasons), a 7–14 day window is often representative.
- **Labelling:** As long as the UI and docs state clearly that the profile is “from recent 7–14 days of NASA POWER data” and “expected” is “average of that window,” the approach is **scientifically honest** and publishable.

### 3.3 Limitations (to document and accept)

- **No weather forecast:** A sudden storm or clear-up tomorrow will not be in the profile; the mean is “typical recent day,” not “tomorrow’s forecast.”
- **Window length:** 7 days gives more weight to recent weather; 14 days smooths more but may mix different regimes. Both are acceptable; 7–14 is a reasonable range.
- **Latency:** We must use a window that ends at least ~7 days in the past so NASA POWER has solar data. So “recent” is “recent available,” not “yesterday.”
- **Bounds:** Min/max are **observed** bounds in the window, not probabilistic forecast intervals. They still usefully separate “conservative” vs “optimistic” for planning.

---

## 4. Making the graph “real and representing”

- **Real:** The time series is built from **real** NASA POWER GHI at the user’s (lat, lon), over a **real** past window. So the curve is location- and history-specific, not a fixed synthetic curve.
- **Representing:** The curve represents “expected GHI for the next 24h **as inferred from recent 7–14 days**.” It will **vary** when the user changes location or when the rolling window moves (e.g. different 7 days), so the graph is no longer the same every time.
- Optional: show a **band** (e.g. min–max or 10th–90th percentile) around the mean curve so “expected” and “range of recent experience” are visible at a glance.

---

## 5. Summary table

| Aspect | Feasible? | Notes |
|--------|-----------|--------|
| Fetch 7–14 days historical GHI from NASA POWER | Yes | Use past window (e.g. end = today−7, length 7–14 days). Existing `fetch_ghi_hourly` supports it. |
| Build hourly mean / min / max profile | Yes | Group by hour-of-day; aggregate. Simple and no new deps. |
| Map profile to “next 24h” and run simulator | Yes | Mean profile → 24h GHI → PV → resample to 15-min → same as current pipeline. |
| Use mean for “expected,” lower for “survivability,” upper for “opportunity” | Yes | Mean for main run; min/max for extra runs or for display (band / separate metrics). |
| Scientifically defensible | Yes | If framed as “expected from recent history” and labelled clearly; limitations documented. |
| Graph real and representative | Yes | Real GHI, location-specific, varies with window and location. |

---

## 6. Recommendation

The approach is **achievable and sound** both technically and scientifically. Next step, when you decide to implement, would be:

1. Add a function to fetch a **past** GHI window (e.g. 7 days ending at today−7).
2. Add a function to compute **hour-of-day** mean, min, and max from that window.
3. Use the **mean** profile as the 24h GHI input to the existing simulator path (replacing “tomorrow” fetch).
4. Optionally attach **min/max** (or percentiles) to the run output and use them in the UI (e.g. band on chart, or survivability/opportunity statements).
5. Set **solar_source** to a new label (e.g. `"nasa_power_historical"`) and show it on the chart so users know the data source.

No code has been changed in this assessment.
