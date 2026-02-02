
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
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
          .load-board {border: 1px solid rgba(49, 51, 63, 0.25); border-radius: 12px; padding: 12px 16px; margin: 8px 0;}
          .load-circuit {display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid rgba(49,51,63,0.1);}
          .load-total {font-size: 1.1rem; font-weight: 700; margin-top: 8px;}
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
    # Typical appliances + EV + others; watt ratings shown on load board; user toggles and quantity.
    return [
        # Critical (always-on / essentials)
        Appliance(id="light", name="Lighting", category="critical", power_w=60, duration_steps=1),
        Appliance(id="fan", name="Ceiling Fan", category="critical", power_w=70, duration_steps=1),
        Appliance(id="fridge", name="Refrigerator", category="critical", power_w=150, duration_steps=1),
        Appliance(id="phone", name="Phone Charging", category="critical", power_w=15, duration_steps=1),
        Appliance(id="router", name="Wi‑Fi Router", category="critical", power_w=12, duration_steps=1),
        # Flexible
        Appliance(id="tv", name="Television", category="flexible", power_w=120, duration_steps=4, earliest_start_step=60, latest_end_step=92),
        Appliance(id="laptop", name="Laptop", category="flexible", power_w=65, duration_steps=4, earliest_start_step=20, latest_end_step=92),
        Appliance(id="microwave", name="Microwave", category="flexible", power_w=1200, duration_steps=1, earliest_start_step=20, latest_end_step=92),
        Appliance(id="ac", name="Small Air Conditioner", category="flexible", power_w=1200, duration_steps=8, earliest_start_step=56, latest_end_step=92),
        # Deferrable
        Appliance(id="washing", name="Washing Machine", category="deferrable", power_w=500, duration_steps=8, earliest_start_step=32, latest_end_step=80, daily_quota_steps=8),
        Appliance(id="iron", name="Ironing", category="deferrable", power_w=1000, duration_steps=4, earliest_start_step=36, latest_end_step=84, daily_quota_steps=4),
        Appliance(id="pump", name="Water Pump", category="deferrable", power_w=750, duration_steps=4, earliest_start_step=28, latest_end_step=88, daily_quota_steps=4),
        # EV (deferrable, high load)
        Appliance(id="ev", name="Electric Vehicle (AC charge)", category="deferrable", power_w=3500, duration_steps=16, earliest_start_step=24, latest_end_step=84, daily_quota_steps=16),
        # Others (catch-all flexible)
        Appliance(id="others", name="Others (misc loads)", category="flexible", power_w=500, duration_steps=4, earliest_start_step=20, latest_end_step=92),
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

    # Run modes
    st.subheader("Run Mode")
    auto_enabled = st.toggle("Auto-run every 15 minutes", value=auto_enabled)
    st.session_state["auto_enabled"] = auto_enabled

    _controllers_list = get_controllers()
    _name_to_controller = {c.name: c for c in _controllers_list}
    controller_names = list(_name_to_controller.keys())
    controller_name = st.selectbox("Control strategy", controller_names, index=controller_names.index(st.session_state.get("controller_name", "forecast_heuristic")) if st.session_state.get("controller_name", "forecast_heuristic") in controller_names else 0)
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

# ---------------------------- Main: Load (distribution board) ----------------------------
st.markdown("### Load — distribution board")
st.caption("Switch loads on/off as if they were circuits on a distribution board. Total load updates from your selection. Advisory only — no physical switching.")
catalog = appliance_catalog()
# Initialize toggle state: critical ON by default, rest OFF
for a in catalog:
    if f"load_on_{a.id}" not in st.session_state:
        st.session_state[f"load_on_{a.id}"] = a.category == "critical"
    if f"qty_{a.id}" not in st.session_state:
        st.session_state[f"qty_{a.id}"] = 1

total_load_w = 0.0
selected_names = []
qty_map = {}

# Build in two rows: Critical | Flexible | Deferrable | EV/Others
for cat_label, cat_key in [("Critical", "critical"), ("Flexible", "flexible"), ("Deferrable", "deferrable")]:
    items = [a for a in catalog if a.category == cat_key]
    if not items:
        continue
    with st.expander(f"{cat_label} loads", expanded=(cat_key == "critical")):
        for a in items:
            cols = st.columns([1, 2, 1, 1])
            with cols[0]:
                on = st.toggle("ON", value=st.session_state.get(f"load_on_{a.id}", a.category == "critical"), key=f"load_on_{a.id}", label_visibility="collapsed")
            with cols[1]:
                st.markdown(f"**{a.name}** — {int(a.power_w):,} W")
            with cols[2]:
                qty = st.number_input("Qty", min_value=1, max_value=10, value=int(st.session_state.get(f"qty_{a.id}", 1)), key=f"qty_{a.id}", label_visibility="collapsed")
            with cols[3]:
                if on:
                    circuit_w = float(a.power_w) * qty
                    total_load_w += circuit_w
                    selected_names.append(a.name)
                    qty_map[a.id] = qty
                    st.metric("", f"{circuit_w/1000:.2f} kW")
                else:
                    st.caption("—")

total_load_kw = total_load_w / 1000.0
st.markdown(f'<div class="load-board"><span class="load-total">Total load (selected): **{total_load_kw:.2f} kW**</span></div>', unsafe_allow_html=True)
st.session_state["selected_appliances"] = selected_names
st.session_state["qty_map"] = qty_map

# Auto-run trigger on autorefresh
if st.session_state.get("auto_enabled", False) and not run_btn:
    # Run if last run older than ~14 minutes
    last_run_time = st.session_state.get("last_run_time")
    if isinstance(last_run_time, datetime):
        last_utc = last_run_time.replace(tzinfo=timezone.utc) if last_run_time.tzinfo is None else last_run_time
        if datetime.now(timezone.utc) - last_utc > timedelta(minutes=14):
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

    _name_to_controller = {c.name: c for c in get_controllers()}
    controller = _name_to_controller[st.session_state.get("controller_name", "forecast_heuristic")]

    with st.spinner("Running digital twin…"):
        result = simulate(
            cfg=cfg,
            appliances=appliances,
            controller=controller,
            days=int(st.session_state.get("sim_days", 2)),
            openweather_api_key=api_key,
            openai_api_key=openai_key,
            openai_model=openai_model,
        )

    st.session_state["last_run"] = result
    st.session_state["last_run_time"] = datetime.now(timezone.utc)

# ---------------------------- Load result ----------------------------
res = st.session_state.get("last_run")
if not res:
    st.info("Run the digital twin to see results. Use **Run demo (2 days)** if you want a quick start.")
    st.stop()

state_csv = res["state_csv"]
guidance_jsonl = res["guidance_jsonl"]
df = pd.read_csv(state_csv)
df["ts"] = pd.to_datetime(df["timestamp"])
t0 = pd.to_datetime(res.get("start_time", df["timestamp"].iloc[0] if len(df) else None))

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

# KPI summary cards (state CSV columns: kpi_CLSR, kpi_Blackout_minutes, kpi_SAR, kpi_Battery_throughput_kwh)
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown('<div class="card"><div class="muted">Critical power reliability</div>'
                f'<div class="kpi">{100*float(row.get("kpi_CLSR", 0)):.1f}%</div>'
                '<div class="muted">How consistently essentials stay powered</div></div>', unsafe_allow_html=True)
with col2:
    st.markdown('<div class="card"><div class="muted">Blackout time (critical)</div>'
                f'<div class="kpi">{float(row.get("kpi_Blackout_minutes", 0)):.0f} min</div>'
                '<div class="muted">Unserved essentials so far</div></div>', unsafe_allow_html=True)
with col3:
    st.markdown('<div class="card"><div class="muted">Solar autonomy</div>'
                f'<div class="kpi">{100*float(row.get("kpi_SAR", 0)):.1f}%</div>'
                '<div class="muted">Share of demand met by solar</div></div>', unsafe_allow_html=True)
with col4:
    st.markdown('<div class="card"><div class="muted">Battery wear proxy</div>'
                f'<div class="kpi">{float(row.get("kpi_Battery_throughput_kwh", 0)):.2f} kWh</div>'
                '<div class="muted">Total charge/discharge throughput</div></div>', unsafe_allow_html=True)

# Instantaneous power available on inverter vs total selected load
pv_now_kw = float(row.get("pv_now_kw", 0.0))
soc_now = float(row.get("soc_now", 0.0))
soc_min = float(row.get("soc_min", 0.25))
inv_kw = float(st.session_state.get("inv_kw", 2.5))
battery_available_kw = inv_kw if soc_now > soc_min else 0.0
power_available_kw = pv_now_kw + battery_available_kw
total_selected_kw = sum(
    float(a.power_w) * int(st.session_state.get(f"qty_{a.id}", 1))
    for a in appliance_catalog()
    if st.session_state.get(f"load_on_{a.id}", False)
) / 1000.0
st.markdown("#### Power available (inverter) vs load")
pcols = st.columns(3)
with pcols[0]:
    st.metric("PV now (kW)", f"{pv_now_kw:.2f}")
with pcols[1]:
    st.metric("Power available (PV + battery)", f"{power_available_kw:.2f} kW")
with pcols[2]:
    st.metric("Total selected load", f"{total_selected_kw:.2f} kW")
st.caption("Power available = PV at this timestep + inverter capacity from battery (when SOC > reserve). Compare with total load from the distribution board.")

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

# Guidance display (align by step index; guidance JSONL has same row count as state CSV)
st.markdown("### Recommendation")
gdf = pd.read_json(guidance_jsonl, lines=True)
if "timestamp" in gdf.columns:
    gdf["ts"] = pd.to_datetime(gdf["timestamp"], utc=True)
grow = gdf.iloc[min(step, len(gdf) - 1)]

risk = str(grow.get("risk_level", ""))
headline = str(grow.get("headline", ""))
explanation = str(grow.get("explanation", ""))
reason_codes = grow.get("reason_codes", [])
if isinstance(reason_codes, str):
    reason_codes = [x.strip() for x in reason_codes.split(",")] if reason_codes else []
dominant = grow.get("dominant_factors", {})

gcol1, gcol2 = st.columns([3, 2])
with gcol1:
    st.markdown(f"{_risk_pill(risk)}", unsafe_allow_html=True)
    st.markdown(f"**{headline}**")
    st.write(explanation)
    if reason_codes:
        st.caption("Reason codes: " + ", ".join(reason_codes))
with gcol2:
    soc_pct = 100 * float(row.get("soc_now", 0))
    risk_lower = str(risk).lower()
    battery_state_label = "Safe" if risk_lower == "low" else ("Caution" if risk_lower == "medium" else "Risk")
    st.markdown('<div class="card"><div class="muted">Battery state</div>'
                f'<div class="kpi">{soc_pct:.0f}% SOC · {battery_state_label}</div>'
                '<div class="muted">Reserve protected automatically (advisory only)</div></div>', unsafe_allow_html=True)

# Forecast plot: PV power + cumulative energy for next 24/48h from replay point (§5.3: labeled as forecast, not certainty)
st.markdown("### Solar Forecast: Power and Energy")
st.caption("Forecast, not certainty — based on simulated PV for the digital twin. Use for planning only.")
horizon_hours = st.radio("Forecast window", [24, 48], horizontal=True)
steps = int(horizon_hours * 60 / DT_MINUTES_DEFAULT)
i0 = step
i1 = min(i0 + steps, len(df))

pv_kw = df["pv_now_kw"].iloc[i0:i1].to_numpy(dtype=float)
ts = pd.date_range(now_ts, periods=len(pv_kw), freq=f"{DT_MINUTES_DEFAULT}min")

fig = plot_power_and_energy(ts, pv_kw, DT_MINUTES_DEFAULT)
st.plotly_chart(fig, width="stretch")

# Load vs served (less technical phrasing)
st.markdown("### Household Power Use")
sub = df.iloc[max(0, step - 96) : min(len(df), step + 96)].copy()
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=sub["ts"], y=sub["load_requested_kw"], mode="lines", name="Requested load (kW)"))
fig2.add_trace(go.Scatter(x=sub["ts"], y=sub["load_served_kw"], mode="lines", name="Served load (kW)"))
fig2.add_trace(go.Scatter(x=sub["ts"], y=sub["pv_now_kw"], mode="lines", name="Solar power (kW)"))
fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
st.plotly_chart(fig2, width="stretch")

# Appliance advisory panel (§5.4: Status Allowed / Delay / Avoid; green = safe, red = avoid; no physical switching)
st.markdown("### Appliance Advisory (Now)")
st.caption("Advisory only — no automatic control. Green = safe to run, red = avoid now.")
selected_appliances = st.session_state.get("selected_appliances", [])
qty_map = st.session_state.get("qty_map", {})
catalog = {a.name: a for a in appliance_catalog()}

soc = float(row.get("soc_now", 0.0))
reserve = float(row.get("soc_min", 0.25))  # schema default; state CSV may not have soc_min
pv_now = float(row.get("pv_now_kw", 0.0))
risk_lower = str(risk).lower()

records = []
for name in selected_appliances:
    a = catalog[name]
    q = int(qty_map.get(a.id, 1))
    watts = float(a.power_w) * q
    kw = watts / 1000.0
    # §5.4: Status Allowed / Delay / Avoid
    status = "Allowed"
    note = "Safe to use"
    if a.category != "critical" and (soc <= reserve + 0.05 or risk_lower == "high"):
        status = "Avoid"
        note = "Preserve battery reserve for essentials"
    elif a.category != "critical" and risk_lower == "medium" and soc <= reserve + 0.12:
        status = "Delay"
        note = "Prefer waiting until solar improves or SOC rises"
    elif a.category != "critical" and pv_now > 0.5 and soc > reserve + 0.1 and risk_lower == "low":
        status = "Allowed"
        note = "Good time — strong solar; prefer this window"
    records.append({
        "Appliance": f"{a.name} (x{q})",
        "Category": category_badge(a.category),
        "Power": f"{kw:.2f} kW",
        "Status": status,
        "Why": note,
    })

adv = pd.DataFrame(records)
def _style_advisory(v: str):
    if v == "Avoid":
        return "background-color: rgba(239,68,68,0.12)"
    if v == "Allowed":
        return "background-color: rgba(34,197,94,0.12)"
    if v == "Delay":
        return "background-color: rgba(234,179,8,0.12)"
    return ""
st.dataframe(adv.style.applymap(_style_advisory, subset=["Status"]), width="stretch", hide_index=True)

# Schedule heatmap (log-driven; §2.2 Digital twin replay)
st.markdown("### Recommended Schedule (Heatmap)")
day_df2 = df.copy()
day_df2["day"] = day_df2["ts"].dt.floor("D")
days_unique = sorted(day_df2["day"].unique())
if not days_unique:
    st.caption("No schedule available.")
else:
    # Day to show: default to the day containing the current replay step
    now_day = now_ts.floor("D") if hasattr(now_ts, "floor") else pd.Timestamp(now_ts).floor("D")
    day_index = next((i for i, d in enumerate(days_unique) if d == now_day), 0)
    day_options = list(range(len(days_unique)))
    day_choice_idx = st.selectbox(
        "Day to show",
        options=day_options,
        index=day_index,
        format_func=lambda i: str(days_unique[i].date()) if i < len(days_unique) else "",
    )
    day_match = days_unique[day_choice_idx]
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
    st.plotly_chart(fig_hm, width="stretch")

# Downloads (§8: evidence artifacts — system summary, weather, today/tomorrow, KPIs, advisory disclaimer)
st.markdown("### Downloads")
st.caption("Evidence artifacts for reproducibility. PDF includes system summary, weather context, today + tomorrow plan, KPIs, and advisory disclaimer.")
dcols = st.columns([2, 2, 2])
with dcols[0]:
    st.download_button("Download state log (CSV)", data=Path(state_csv).read_bytes(), file_name="state_log.csv", mime="text/csv", width="stretch")
with dcols[1]:
    st.download_button("Download guidance log (JSONL)", data=Path(guidance_jsonl).read_bytes(), file_name="guidance_log.jsonl", mime="application/jsonl", width="stretch")

system_summary_for_pdf = {
    "Location": str(st.session_state.get("location_name", "")) or "Configured location",
    "PV capacity": f"{float(st.session_state.get('pv_kw', 0)):.1f} kW",
    "Battery": f"{float(st.session_state.get('bat_kwh', 0)):.1f} kWh",
    "Inverter limit": f"{float(st.session_state.get('inv_kw', 0)):.1f} kW",
}
weather_summary = weather if weather else {}
pdf_bytes = build_two_day_plan_pdf_from_logs(
    state_csv_path=state_csv,
    guidance_jsonl_path=guidance_jsonl,
    title="Solar-first Household Plan (Today + Tomorrow)",
    weather_summary=weather_summary,
    system_summary_override=system_summary_for_pdf,
)
with dcols[2]:
    st.download_button("Download plan (PDF: Today + Tomorrow)", data=pdf_bytes, file_name="solar_plan_today_tomorrow.pdf", mime="application/pdf", width="stretch")
