
import sys
from pathlib import Path
from datetime import datetime, timedelta
import math

# Ensure src/ is importable when running Streamlit without installing the package
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from offgrid_dt.control.controllers import get_controllers
from offgrid_dt.dt.simulator import simulate
from offgrid_dt.forecast.openweather import OpenWeatherSolarClient
from offgrid_dt.io.schema import Appliance, SystemConfig
from offgrid_dt.io.pdf_report import build_two_day_plan_pdf_from_logs

st.set_page_config(page_title="Off-grid Solar DT", layout="wide")

DT_MINUTES_DEFAULT = 15
AUTO_REFRESH_MS = 15 * 60 * 1000  # 15 minutes

# ---------------------------- UI styling ----------------------------

def _inject_css() -> None:
    st.markdown(
        """
        <style>
          .app-title {font-size: 2.0rem; font-weight: 750; margin-bottom: 0.25rem;}
          .app-sub {opacity: 0.85; margin-top: 0;}
          .card {border: 1px solid rgba(49, 51, 63, 0.18); border-radius: 16px; padding: 14px 16px; background: rgba(255,255,255,0.02);}
          .kpi {font-size: 1.35rem; font-weight: 700;}
          .muted {opacity: 0.78;}
          .pill {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.85rem; border: 1px solid rgba(49, 51, 63, 0.25);}
          .pill.low {background: rgba(34,197,94,0.12); border-color: rgba(34,197,94,0.35);}
          .pill.med {background: rgba(234,179,8,0.14); border-color: rgba(234,179,8,0.35);}
          .pill.high {background: rgba(239,68,68,0.12); border-color: rgba(239,68,68,0.35);}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _risk_pill(risk: str) -> str:
    r = (risk or "").lower()
    if r in ("low", "medium", "high"):
        cls = {"low":"low", "medium":"med", "high":"high"}[r]
        return f'<span class="pill {cls}">Risk: {risk.title()}</span>'
    return '<span class="pill">Risk: Unknown</span>'

# ---------------------------- Appliance catalog ----------------------------

def appliance_catalog() -> list[Appliance]:
    # Typical appliances + publishable defaults; user can quantity-adjust.
    return [
        Appliance(id="light", name="Lighting", category="critical", power_w=60, duration_steps=1),
        Appliance(id="fan", name="Ceiling Fan", category="critical", power_w=70, duration_steps=1),
        Appliance(id="fridge", name="Refrigerator", category="critical", power_w=150, duration_steps=1),
        Appliance(id="phone", name="Phone Charging", category="critical", power_w=15, duration_steps=1),
        Appliance(id="router", name="Wi‑Fi Router", category="critical", power_w=12, duration_steps=1),

        Appliance(id="tv", name="Television", category="flexible", power_w=120, duration_steps=4, earliest_start_step=60, latest_end_step=92),
        Appliance(id="laptop", name="Laptop", category="flexible", power_w=65, duration_steps=4, earliest_start_step=20, latest_end_step=92),

        Appliance(id="washing", name="Washing Machine (cycle)", category="deferrable", power_w=500, duration_steps=8, earliest_start_step=32, latest_end_step=80, daily_quota_steps=8),
        Appliance(id="iron", name="Ironing", category="deferrable", power_w=1000, duration_steps=4, earliest_start_step=36, latest_end_step=84, daily_quota_steps=4),
        Appliance(id="pump", name="Water Pump", category="deferrable", power_w=750, duration_steps=4, earliest_start_step=28, latest_end_step=88, daily_quota_steps=4),

        Appliance(id="microwave", name="Microwave", category="flexible", power_w=1200, duration_steps=1, earliest_start_step=20, latest_end_step=92),
        Appliance(id="ac", name="Small Air Conditioner", category="flexible", power_w=1200, duration_steps=8, earliest_start_step=56, latest_end_step=92),
    ]

def category_badge(cat: str) -> str:
    c = (cat or "").lower()
    if c == "critical":
        return "Critical"
    if c == "flexible":
        return "Flexible"
    return "Deferrable"

# ---------------------------- OpenWeather helpers ----------------------------

def get_openweather_client() -> OpenWeatherSolarClient | None:
    key = st.secrets.get("openweather_api_key", "")
    if not key:
        return None
    return OpenWeatherSolarClient(api_key=key)

def weather_icon_url(icon: str) -> str:
    if not icon:
        return ""
    return f"https://openweathermap.org/img/wn/{icon}@2x.png"

# ---------------------------- Plotting ----------------------------

def plot_power_and_energy(ts: pd.DatetimeIndex, pv_kw: np.ndarray, dt_minutes: int) -> go.Figure:
    dt_hours = dt_minutes / 60.0
    cum_kwh = np.cumsum(pv_kw) * dt_hours

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(x=ts, y=pv_kw, mode="lines", line_shape="spline", name="PV Power (kW)"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=ts, y=cum_kwh, mode="lines", line_shape="spline", name="Cumulative PV Energy (kWh)"),
        secondary_y=True,
    )
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
    fig.update_yaxes(title_text="kW", secondary_y=False)
    fig.update_yaxes(title_text="kWh", secondary_y=True)
    return fig

# ---------------------------- App ----------------------------

_inject_css()

st.markdown('<div class="app-title">Off-grid Solar Decision Support</div>', unsafe_allow_html=True)
st.markdown('<p class="app-sub">Forecast-informed, survivability-first guidance for solar + battery households (advisory mode).</p>', unsafe_allow_html=True)

# Optional auto-refresh (every 15 minutes)
auto_enabled = st.session_state.get("auto_enabled", False)
if auto_enabled:
    st_autorefresh = getattr(st, "autorefresh", None)
    if st_autorefresh:
        st_autorefresh(interval=AUTO_REFRESH_MS, key="dt_autorefresh")

client = get_openweather_client()

# ---------------------------- Sidebar: smart configuration ----------------------------
with st.sidebar:
    st.header("System Configuration")
    st.caption("Set your system once; the assistant generates a daily plan automatically.")

    # Location: search -> geocode -> auto-fill
    st.subheader("Location")
    loc_query = st.text_input("Search location", value=st.session_state.get("loc_query", ""))
    st.session_state["loc_query"] = loc_query

    lat = st.session_state.get("latitude", 0.0)
    lon = st.session_state.get("longitude", 0.0)
    loc_label = st.session_state.get("location_name", "")

    if client and loc_query:
        try:
            candidates = client.geocode(loc_query, limit=5)
        except Exception:
            candidates = []
        if candidates:
            labels = []
            for c in candidates:
                state = c.get("state", "")
                labels.append(f'{c.get("name","")}{" ("+state+")" if state else ""}, {c.get("country","")}'.strip())
            idx = st.selectbox("Select match", list(range(len(labels))), format_func=lambda i: labels[i])
            chosen = candidates[idx]
            lat = float(chosen.get("lat", 0.0))
            lon = float(chosen.get("lon", 0.0))
            loc_label = labels[idx]
            st.session_state["latitude"] = lat
            st.session_state["longitude"] = lon
            st.session_state["location_name"] = loc_label
    else:
        st.caption("Tip: add OpenWeather key in Streamlit Secrets to enable location search.")

    cols = st.columns(2)
    lat = cols[0].number_input("Latitude", value=float(lat), format="%.6f")
    lon = cols[1].number_input("Longitude", value=float(lon), format="%.6f")
    st.session_state["latitude"] = lat
    st.session_state["longitude"] = lon
    if not loc_label:
        loc_label = f"{lat:.4f}, {lon:.4f}"
        st.session_state["location_name"] = loc_label

    # System capacity
    st.subheader("Solar + Battery")
    pv_kw = st.number_input("PV capacity (kW)", min_value=0.5, max_value=30.0, value=float(st.session_state.get("pv_kw", 3.0)), step=0.1)
    bat_kwh = st.number_input("Battery capacity (kWh)", min_value=0.5, max_value=50.0, value=float(st.session_state.get("bat_kwh", 5.0)), step=0.1)
    inv_kw = st.number_input("Inverter max (kW)", min_value=0.3, max_value=30.0, value=float(st.session_state.get("inv_kw", 2.5)), step=0.1)
    st.session_state["pv_kw"] = pv_kw
    st.session_state["bat_kwh"] = bat_kwh
    st.session_state["inv_kw"] = inv_kw

    # Appliance selection (dynamic dropdown + quantity)
    st.subheader("Appliance Control")
    catalog = appliance_catalog()
    name_to_obj = {a.name: a for a in catalog}

    default_selected = st.session_state.get("selected_appliances", [a.name for a in catalog if a.category == "critical"])
    selected_names = st.multiselect("Select appliances in your home", options=list(name_to_obj.keys()), default=default_selected)
    st.session_state["selected_appliances"] = selected_names

    qty_map = st.session_state.get("qty_map", {})
    # show quantity inputs for selected
    for n in selected_names:
        a = name_to_obj[n]
        cols = st.columns([6, 2, 2])
        cols[0].write(f"**{a.name}** · {category_badge(a.category)} · {int(a.power_w)} W")
        qty = cols[1].number_input("Qty", min_value=1, max_value=10, value=int(qty_map.get(a.id, 1)), key=f"qty_{a.id}")
        qty_map[a.id] = qty
        # quick indicator column
        cols[2].write("")
    st.session_state["qty_map"] = qty_map

    # Run modes
    st.subheader("Run Mode")
    auto_enabled = st.toggle("Auto-run every 15 minutes", value=auto_enabled)
    st.session_state["auto_enabled"] = auto_enabled

    controller_names = list(get_controllers().keys())
    controller_name = st.selectbox("Control strategy", controller_names, index=controller_names.index(st.session_state.get("controller_name", "forecast_heuristic")) if "forecast_heuristic" in controller_names else 0)
    st.session_state["controller_name"] = controller_name

    days = st.selectbox("Simulation days (for replay + tomorrow plan)", [2, 3, 7], index=0)
    st.session_state["sim_days"] = days

    run_btn = st.button("Run digital twin now", type="primary")
    demo_btn = st.button("Run demo (2 days)", help="Quick-start run with defaults to explore the dashboard.")
    if demo_btn:
        st.session_state["loc_query"] = st.session_state.get("loc_query", "London")
        st.session_state["latitude"] = st.session_state.get("latitude", 51.5074)
        st.session_state["longitude"] = st.session_state.get("longitude", -0.1278)
        st.session_state["location_name"] = st.session_state.get("location_name", "London, GB")
        run_btn = True
        st.session_state["sim_days"] = 2

# Auto-run trigger on autorefresh
if st.session_state.get("auto_enabled", False) and not run_btn:
    # Run if last run older than ~14 minutes
    last_run_time = st.session_state.get("last_run_time")
    if isinstance(last_run_time, datetime):
        if datetime.utcnow() - last_run_time > timedelta(minutes=14):
            run_btn = True
    else:
        # no prior run yet, do one
        run_btn = True

# ---------------------------- Build config + run simulation ----------------------------
def _build_appliances(selected_names: list[str], qty_map: dict) -> list[Appliance]:
    catalog = appliance_catalog()
    name_to_obj = {a.name: a for a in catalog}
    out: list[Appliance] = []
    for n in selected_names:
        base = name_to_obj[n]
        q = int(qty_map.get(base.id, 1))
        # represent quantity by scaling power
        out.append(Appliance(**{**base.model_dump(), "power_w": float(base.power_w) * q}))
    return out

if run_btn:
    cfg = SystemConfig(
        location_name=st.session_state.get("location_name", ""),
        latitude=float(st.session_state.get("latitude", 0.0)),
        longitude=float(st.session_state.get("longitude", 0.0)),
        pv_capacity_kw=float(st.session_state.get("pv_kw", 3.0)),
        battery_capacity_kwh=float(st.session_state.get("bat_kwh", 5.0)),
        inverter_max_kw=float(st.session_state.get("inv_kw", 2.5)),
        # SOC settings are auto (defaults in schema)
        timestep_minutes=DT_MINUTES_DEFAULT,
        horizon_steps=48,  # controller horizon (12 hours @15min), stable default
    )
    appliances = _build_appliances(st.session_state.get("selected_appliances", []), st.session_state.get("qty_map", {}))

    api_key = st.secrets.get("openweather_api_key", "")
    openai_key = st.secrets.get("openai_api_key", "")
    openai_model = st.secrets.get("openai_model", "gpt-4o-mini")

    controller = get_controllers()[st.session_state.get("controller_name")]

    with st.spinner("Running digital twin…"):
        result = simulate(
            config=cfg,
            appliances=appliances,
            controller=controller,
            days=int(st.session_state.get("sim_days", 2)),
            openweather_api_key=api_key,
            openai_api_key=openai_key,
            openai_model=openai_model,
        )

    st.session_state["last_run"] = result
    st.session_state["last_run_time"] = datetime.utcnow()

# ---------------------------- Load result ----------------------------
res = st.session_state.get("last_run")
if not res:
    st.info("Run the digital twin to see results. Use **Run demo (2 days)** if you want a quick start.")
    st.stop()

state_csv = res["state_csv"]
guidance_jsonl = res["guidance_jsonl"]
t0 = pd.to_datetime(res["start_time"])

df = pd.read_csv(state_csv)
df["ts"] = pd.to_datetime(df["timestamp"])

# Replay control
st.markdown("### Live Replay")
step_max = max(0, len(df) - 1)
default_step = int(st.session_state.get("replay_step", min(step_max, 0)))
step = st.slider("Replay time", min_value=0, max_value=step_max, value=default_step, help="Scrub through the simulation timeline.")
st.session_state["replay_step"] = step

row = df.iloc[step]
now_ts = pd.to_datetime(row["ts"])

# Weather snapshot
weather = None
if client:
    try:
        weather = client.current_weather(float(st.session_state["latitude"]), float(st.session_state["longitude"]))
    except Exception:
        weather = None

# KPI summary cards (more meaningful language)
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown('<div class="card"><div class="muted">Critical power reliability</div>'
                f'<div class="kpi">{100*float(row.get("clsr_running",0)):.1f}%</div>'
                '<div class="muted">How consistently essentials stay powered</div></div>', unsafe_allow_html=True)
with col2:
    st.markdown('<div class="card"><div class="muted">Blackout time (critical)</div>'
                f'<div class="kpi">{float(row.get("blackout_minutes_running",0)):.0f} min</div>'
                '<div class="muted">Unserved essentials so far</div></div>', unsafe_allow_html=True)
with col3:
    st.markdown('<div class="card"><div class="muted">Solar autonomy</div>'
                f'<div class="kpi">{100*float(row.get("sar_running",0)):.1f}%</div>'
                '<div class="muted">Share of demand met by solar</div></div>', unsafe_allow_html=True)
with col4:
    st.markdown('<div class="card"><div class="muted">Battery wear proxy</div>'
                f'<div class="kpi">{float(row.get("throughput_kwh_running",0)):.2f} kWh</div>'
                '<div class="muted">Total charge/discharge throughput</div></div>', unsafe_allow_html=True)

# Weather card
st.markdown("### Current Weather")
wcols = st.columns([2, 2, 2, 2, 2])
if weather:
    icon_url = weather_icon_url(weather.get("icon",""))
    wcols[0].markdown(f"**Status**  \n{weather.get('description','').title()}")
    if icon_url:
        wcols[0].image(icon_url, width=72)
    wcols[1].metric("Temperature (°C)", f"{weather.get('temperature_c',0):.1f}")
    wcols[2].metric("Humidity (%)", f"{weather.get('humidity_pct',0):.0f}")
    wcols[3].metric("Cloud cover (%)", f"{weather.get('cloud_cover_pct',0):.0f}")
    wcols[4].metric("Wind (m/s)", f"{weather.get('wind_speed_mps',0):.1f}")
else:
    st.caption("Weather card requires OpenWeather key. The twin still runs with synthetic PV if needed.")

# Guidance display
st.markdown("### Recommendation")
gdf = pd.read_json(guidance_jsonl, lines=True)
gdf["ts"] = pd.to_datetime(gdf["timestamp"])
grow = gdf.iloc[min(step, len(gdf)-1)]

risk = str(grow.get("risk_level",""))
headline = str(grow.get("headline",""))
explanation = str(grow.get("explanation",""))
reason_codes = grow.get("reason_codes", [])
dominant = grow.get("dominant_factors", {})

gcol1, gcol2 = st.columns([3, 2])
with gcol1:
    st.markdown(f"{_risk_pill(risk)}", unsafe_allow_html=True)
    st.markdown(f"**{headline}**")
    st.write(explanation)
    if reason_codes:
        st.caption("Reason codes: " + ", ".join(reason_codes))
with gcol2:
    st.markdown('<div class="card"><div class="muted">Battery state</div>'
                f'<div class="kpi">{100*float(row.get("soc",0)):.0f}% SOC</div>'
                f'<div class="muted">Reserve protected automatically</div></div>', unsafe_allow_html=True)

# Forecast plot: PV power + cumulative energy for next 24/48h from replay point
st.markdown("### Solar Forecast: Power and Energy")
horizon_hours = st.radio("Forecast window", [24, 48], horizontal=True)
steps = int(horizon_hours * 60 / DT_MINUTES_DEFAULT)
i0 = step
i1 = min(i0 + steps, len(df))

pv_kw = df["pv_kw"].iloc[i0:i1].to_numpy(dtype=float)
ts = pd.date_range(now_ts, periods=len(pv_kw), freq=f"{DT_MINUTES_DEFAULT}min")

fig = plot_power_and_energy(ts, pv_kw, DT_MINUTES_DEFAULT)
st.plotly_chart(fig, use_container_width=True)

# Load vs served (less technical phrasing)
st.markdown("### Household Power Use")
sub = df.iloc[max(0, step-96):min(len(df), step+96)].copy()
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=sub["ts"], y=sub["load_requested_kw"], mode="lines", name="Requested load (kW)"))
fig2.add_trace(go.Scatter(x=sub["ts"], y=sub["load_served_kw"], mode="lines", name="Served load (kW)"))
fig2.add_trace(go.Scatter(x=sub["ts"], y=sub["pv_kw"], mode="lines", name="Solar power (kW)"))
fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
st.plotly_chart(fig2, use_container_width=True)

# Appliance advisory panel (green/red)
st.markdown("### Appliance Advisory (Now)")
selected_appliances = st.session_state.get("selected_appliances", [])
qty_map = st.session_state.get("qty_map", {})
catalog = {a.name: a for a in appliance_catalog()}

soc = float(row.get("soc", 0.0))
reserve = float(SystemConfig().soc_min)
pv_now = float(row.get("pv_kw", 0.0))

records = []
for name in selected_appliances:
    a = catalog[name]
    q = int(qty_map.get(a.id, 1))
    watts = float(a.power_w) * q
    kw = watts / 1000.0
    # simple advisories: protect reserve + avoid high loads when risk high or SOC low
    status = "OK"
    note = "Safe to use"
    if a.category != "critical" and (soc <= reserve + 0.05 or str(risk).lower() == "high"):
        status = "Avoid now"
        note = "Preserve battery reserve for essentials"
    if a.category != "critical" and pv_now > 0.5 and soc > reserve + 0.1 and str(risk).lower() == "low":
        status = "Best in solar window"
        note = "Prefer running during strong solar"
    records.append({
        "Appliance": f"{a.name} (x{q})",
        "Category": category_badge(a.category),
        "Power": f"{kw:.2f} kW",
        "Advisory": status,
        "Why": note,
    })

adv = pd.DataFrame(records)
def _style_advisory(v: str):
    if "Avoid" in v:
        return "background-color: rgba(239,68,68,0.12)"
    if "Best" in v:
        return "background-color: rgba(34,197,94,0.12)"
    return "background-color: rgba(59,130,246,0.06)"
st.dataframe(adv.style.applymap(_style_advisory, subset=["Advisory"]), use_container_width=True, hide_index=True)

# Schedule heatmap (existing file uses served_task_ids; keep using helper)
st.markdown("### Recommended Schedule (Heatmap)")
# Build schedule matrix directly from served_task_ids (per-step) for the selected day
day_df2 = df.copy()
day_df2["day"] = day_df2["ts"].dt.floor("D")
days_unique = sorted(day_df2["day"].unique())
if not days_unique:
    st.caption("No schedule available.")
else:
    # Match selected day to the appropriate index
    sel_day = pd.to_datetime(str(day_choice))
    # find closest
    day_match = None
    for d in days_unique:
        if d.date() == day_choice:
            day_match = d
            break
    if day_match is None:
        day_match = days_unique[0]
    one = day_df2[day_df2["day"] == day_match].reset_index(drop=True)

    # infer appliance id -> name from catalog
    id_to_name = {a.id: a.name for a in appliance_catalog()}
    def _parse_ids(s: str) -> list[str]:
        if not isinstance(s, str) or not s.strip() or s == "nan":
            return []
        out=[]
        for tid in s.split(";"):
            if tid:
                out.append(tid.split("_")[0])
        return out

    per_step = [_parse_ids(s) for s in one.get("served_task_ids","").astype(str).tolist()]
    apps_ids = sorted({a for step_ids in per_step for a in step_ids})
    apps = [id_to_name.get(a,a) for a in apps_ids]
    steps_in_day = int(24*60/DT_MINUTES_DEFAULT)
    matrix = np.zeros((len(apps), steps_in_day))
    for i, appl_id in enumerate(apps_ids):
        for sidx, ids in enumerate(per_step):
            if appl_id in ids and sidx < steps_in_day:
                matrix[i, sidx] = 1

    x_labels = [f"{(i*DT_MINUTES_DEFAULT)//60:02d}:{(i*DT_MINUTES_DEFAULT)%60:02d}" for i in range(steps_in_day)]
    fig_hm = go.Figure(data=go.Heatmap(z=matrix, x=x_labels, y=apps))
    fig_hm.update_layout(height=280 + 10*len(apps), margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig_hm, use_container_width=True)

# Downloads (make it meaningful)
st.markdown("### Downloads")
dcols = st.columns([2,2,2])
dcols[0].download_button("Download state log (CSV)", data=open(state_csv, "rb"), file_name="state_log.csv")
dcols[1].download_button("Download guidance log (JSONL)", data=open(guidance_jsonl, "rb"), file_name="guidance_log.jsonl")

include_tomorrow = True
if include_tomorrow:
    # Build a more meaningful PDF
    weather_summary = weather if weather else {}
    pdf_bytes = build_two_day_plan_pdf_from_logs(state_csv_path=state_csv, guidance_jsonl_path=guidance_jsonl, title="Solar-first Household Plan (Today + Tomorrow)", weather_summary=weather_summary)
    dcols[2].download_button("Download plan (PDF: Today + Tomorrow)", data=pdf_bytes, file_name="solar_plan_today_tomorrow.pdf", mime="application/pdf")
