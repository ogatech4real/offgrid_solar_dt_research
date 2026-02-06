
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
from streamlit_autorefresh import st_autorefresh

from offgrid_dt.control.controllers import get_controllers
from offgrid_dt.dt.simulator import simulate
from offgrid_dt.forecast.openweather import OpenWeatherSolarClient
from offgrid_dt.io.schema import Appliance, SystemConfig
from offgrid_dt.io.pdf_report import build_two_day_plan_pdf_from_logs
from offgrid_dt.matching import compute_day_ahead_matching, format_day_ahead_statements

st.set_page_config(page_title="Off-Grid Solar Energy Planner", layout="wide")

DT_MINUTES_DEFAULT = 15
AUTO_REFRESH_MS = 15 * 60 * 1000  # 15 minutes

# ---------------------------- UI styling ----------------------------

def _inject_css() -> None:
    st.markdown(
        """
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
          /* Warm colour grade & typography */
          :root {
            --bg-warm: #faf7f2;
            --bg-card: rgba(255, 252, 248, 0.9);
            --border-warm: rgba(194, 65, 12, 0.12);
            --text-soft: #2d3748;
            --text-muted: #5a6578;
            --accent-solar: #c2410c;
            --accent-amber: #d97706;
            --accent-success: #059669;
            --accent-caution: #ca8a04;
            --accent-risk: #dc2626;
          }
          html, body, [class*="css"], .stApp { font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important; }
          .stApp { background: linear-gradient(180deg, #fefcf8 0%, #faf5ed 50%, #f7f0e4 100%) !important; }
          .stSidebar { background: linear-gradient(180deg, #fdfaf5 0%, #f8f3eb 100%) !important; }
          .stSidebar [data-testid="stSidebarContent"] { border-right: 1px solid var(--border-warm); }
          /* Header block */
          .hero-wrap { margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border-warm); }
          .app-title {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent-solar);
            letter-spacing: -0.02em;
            margin-bottom: 0.35rem;
          }
          .app-sub {
            font-size: 1.05rem;
            color: var(--text-muted);
            line-height: 1.5;
            margin-top: 0;
            max-width: 42rem;
          }
          /* Cards: warm, soft shadow */
          .card {
            border: 1px solid var(--border-warm);
            border-radius: 16px;
            padding: 14px 16px;
            background: var(--bg-card);
            box-shadow: 0 1px 3px rgba(194, 65, 12, 0.06);
          }
          .kpi { font-size: 1.35rem; font-weight: 700; color: var(--text-soft); }
          .muted { color: var(--text-muted); font-size: 0.9rem; opacity: 0.95; }
          /* Risk pills: warmer tones */
          .pill {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 0.85rem;
            font-weight: 500;
          }
          .pill.low { background: rgba(5, 150, 105, 0.14); border: 1px solid rgba(5, 150, 105, 0.35); color: #047857; }
          .pill.med { background: rgba(202, 138, 4, 0.14); border: 1px solid rgba(202, 138, 4, 0.35); color: #a16207; }
          .pill.high { background: rgba(220, 38, 38, 0.12); border: 1px solid rgba(220, 38, 38, 0.35); color: #b91c1c; }
          /* Load board */
          .load-board {
            border: 1px solid var(--border-warm);
            border-radius: 12px;
            padding: 12px 16px;
            margin: 8px 0;
            background: var(--bg-card);
            box-shadow: 0 1px 2px rgba(194, 65, 12, 0.04);
          }
          .load-circuit { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px solid rgba(194, 65, 12, 0.08); }
          .load-total { font-size: 1.1rem; font-weight: 700; color: var(--accent-solar); margin-top: 8px; }
          /* Compact expanders (load groups) */
          [data-testid="stExpander"] details summary { padding: 0.35rem 0; }
          [data-testid="stExpander"] div[style*="overflow"] { padding-top: 0.2rem; padding-bottom: 0.2rem; }
          /* Section headings: warmer */
          h1, h2, h3 { font-family: 'Plus Jakarta Sans', sans-serif !important; color: var(--text-soft) !important; }
          /* Metric and caption text */
          [data-testid="stMetricValue"] { font-family: 'Plus Jakarta Sans', sans-serif !important; color: var(--text-soft) !important; }
          .stCaption { color: var(--text-muted) !important; }
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
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"), font=dict(family="Plus Jakarta Sans, sans-serif"))
    fig.update_yaxes(title_text="kW", secondary_y=False)
    fig.update_yaxes(title_text="kWh", secondary_y=True)
    return fig

# ---------------------------- App ----------------------------

_inject_css()

st.markdown(
    '<div class="hero-wrap">'
    '<div class="app-title">Off-Grid Solar Energy Planner</div>'
    '<p class="app-sub">Day-ahead household energy planning using real solar data. Clear guidance to protect essential loads and use solar efficiently.</p>'
    '</div>',
    unsafe_allow_html=True,
)

# Optional auto-refresh (every 15 minutes) — triggers full rerun so "run if last run >14 min" runs
auto_enabled = st.session_state.get("auto_enabled", False)
if auto_enabled:
    st_autorefresh(interval=AUTO_REFRESH_MS, key="dt_autorefresh")

client = get_openweather_client()

# ---------------------------- Sidebar: smart configuration ----------------------------
with st.sidebar:
    st.header("System Setup")
    st.caption("Set your system once — we'll generate your daily plan automatically.")

    # Location: search -> geocode -> auto-fill
    st.subheader("Select Location")
    loc_query = st.text_input("Search your location", value=st.session_state.get("loc_query", ""))
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
        st.caption("We use OpenWeather for location and weather; your solar estimates come from NASA POWER.")

    cols = st.columns(2)
    lat = cols[0].number_input("Latitude", value=float(lat), format="%.6f")
    lon = cols[1].number_input("Longitude", value=float(lon), format="%.6f")
    st.session_state["latitude"] = lat
    st.session_state["longitude"] = lon
    if not loc_label:
        loc_label = f"{lat:.4f}, {lon:.4f}"
        st.session_state["location_name"] = loc_label

    # System capacity
    st.subheader("Solar + Battery config")
    st.caption("Set your system configuration.")
    pv_kw = st.number_input("PV capacity (kW)", min_value=0.5, max_value=30.0, value=float(st.session_state.get("pv_kw", 3.0)), step=0.1)
    bat_kwh = st.number_input("Battery capacity (kWh)", min_value=0.5, max_value=50.0, value=float(st.session_state.get("bat_kwh", 5.0)), step=0.1)
    inv_kw = st.number_input("Inverter max (kW)", min_value=0.3, max_value=30.0, value=float(st.session_state.get("inv_kw", 2.5)), step=0.1)
    st.session_state["pv_kw"] = pv_kw
    st.session_state["bat_kwh"] = bat_kwh
    st.session_state["inv_kw"] = inv_kw

    # Run modes
    st.subheader("Run Mode")
    auto_enabled = st.toggle("Auto-refresh every 15 minutes", value=auto_enabled, help="We'll refresh the app every 15 min and re-run your plan if the last run was more than 14 min ago.")
    st.session_state["auto_enabled"] = auto_enabled

    _controllers_list = get_controllers()
    _name_to_controller = {c.name: c for c in _controllers_list}
    controller_names = list(_name_to_controller.keys())
    controller_name = st.selectbox("Control strategy", controller_names, index=controller_names.index(st.session_state.get("controller_name", "forecast_heuristic")) if st.session_state.get("controller_name", "forecast_heuristic") in controller_names else 0)
    st.session_state["controller_name"] = controller_name

    days = st.selectbox("Planning horizon (days)", [2, 3, 7], index=0, help="Number of days to simulate for replay and day-ahead plan (first day = next planning day).")
    st.session_state["sim_days"] = days

    run_btn = st.button("Run my plan", type="primary")
    demo_btn = st.button("Try a quick demo (2 days)", help="See the full dashboard with a sample location and 2-day plan.")
    if demo_btn:
        st.session_state["loc_query"] = st.session_state.get("loc_query", "London")
        st.session_state["latitude"] = st.session_state.get("latitude", 51.5074)
        st.session_state["longitude"] = st.session_state.get("longitude", -0.1278)
        st.session_state["location_name"] = st.session_state.get("location_name", "London, GB")
        run_btn = True
        st.session_state["sim_days"] = 2

    st.caption("Solar data: NASA POWER. Location: OpenWeather.")

# ---------------------------- Main: Current Weather (top; updates when location is set) ----------------------------
st.markdown("### Current weather at your location")
st.caption("Updates when you change your location in the sidebar.")
weather = None
if client:
    try:
        lat_w = float(st.session_state.get("latitude", 0))
        lon_w = float(st.session_state.get("longitude", 0))
        if abs(lat_w) <= 90 and abs(lon_w) <= 180:
            weather = client.current_weather(lat_w, lon_w)
    except Exception:
        weather = None
st.session_state["current_weather"] = weather
if weather:
    wcols = st.columns([2, 2, 2, 2, 2])
    icon_url = weather_icon_url(weather.get("icon", ""))
    wcols[0].markdown(f"**Status**  \n{weather.get('description', '').title()}")
    if icon_url:
        wcols[0].image(icon_url, width=72)
    wcols[1].metric("Temperature (°C)", f"{weather.get('temperature_c', 0):.1f}")
    wcols[2].metric("Humidity (%)", f"{weather.get('humidity_pct', 0):.0f}")
    wcols[3].metric("Cloud cover (%)", f"{weather.get('cloud_cover_pct', 0):.0f}")
    wcols[4].metric("Wind (m/s)", f"{weather.get('wind_speed_mps', 0):.1f}")
else:
    st.caption("Set your location in the sidebar and add an OpenWeather API key in secrets to see the weather here.")

# ---------------------------- Main: Load (distribution board) — three columns, expanders, compact rows ----------------------------
st.markdown("### Your loads")
st.caption("Turn loads on or off to match your household. Your total load updates as you select — this is advisory only; nothing is switched automatically.")
catalog = appliance_catalog()
# Toggle and qty widgets own their keys (load_on_*, qty_*); do not set them via session_state.

total_load_w = 0.0
selected_names = []
qty_map = {}

load_cols = st.columns(3)
for idx, (cat_label, cat_key) in enumerate([("Critical loads", "critical"), ("Flexible loads", "flexible"), ("Deferrable loads", "deferrable")]):
    items = [a for a in catalog if a.category == cat_key]
    with load_cols[idx]:
        expanded = (cat_key == "critical")  # Critical open by default; others collapsed to save space
        with st.expander(f"**{cat_label}**", expanded=expanded):
            for a in items:
                r1, r2, r3, r4 = st.columns([0.6, 2, 0.8, 0.8])  # compact: toggle | name + W | qty | kW
                with r1:
                    on = st.toggle("ON", value=st.session_state.get(f"load_on_{a.id}", a.category == "critical"), key=f"load_on_{a.id}", label_visibility="collapsed")
                with r2:
                    st.markdown(f"{a.name} — {int(a.power_w):,} W")
                with r3:
                    qty = st.number_input("Qty", min_value=1, max_value=10, value=int(st.session_state.get(f"qty_{a.id}", 1)), key=f"qty_{a.id}", label_visibility="collapsed")
                with r4:
                    if on:
                        circuit_w = float(a.power_w) * qty
                        total_load_w += circuit_w
                        selected_names.append(a.name)
                        qty_map[a.id] = qty
                        st.caption(f"{circuit_w/1000:.2f} kW")
                    else:
                        st.caption("—")

total_load_kw = total_load_w / 1000.0
st.markdown(f'<div class="load-board"><span class="load-total">Your total load: **{total_load_kw:.2f} kW**</span></div>', unsafe_allow_html=True)
st.session_state["selected_appliances"] = selected_names
st.session_state["qty_map"] = qty_map

# Running hours per group (per day, 00:00–24:00) — for planning and consumption estimate
st.markdown("#### Running hours (per day)")
st.caption("Hours per day each group is expected to run. Used for 24h / 12h consumption estimate and planning. Critical default 24h; adjust for flexible and deferrable.")
run_hrs_cols = st.columns(3)
with run_hrs_cols[0]:
    run_hrs_critical = st.number_input("Critical (h/day)", min_value=0.0, max_value=24.0, value=24.0, step=0.5, key="run_hrs_critical")
with run_hrs_cols[1]:
    run_hrs_flexible = st.number_input("Flexible (h/day)", min_value=0.0, max_value=24.0, value=4.0, step=0.5, key="run_hrs_flexible")
with run_hrs_cols[2]:
    run_hrs_deferrable = st.number_input("Deferrable (h/day)", min_value=0.0, max_value=24.0, value=2.0, step=0.5, key="run_hrs_deferrable")

# Estimated consumption for next 12h and 24h (00:00–24:00) based on load DB selections and running hours
st.markdown("#### Your estimated consumption (next day)")
st.caption("Based on your selected loads and running hours — use this to compare with the solar outlook below.")
run_hrs_by_cat = {"critical": run_hrs_critical, "flexible": run_hrs_flexible, "deferrable": run_hrs_deferrable}
energy_24h_kwh = 0.0
for a in catalog:
    if not st.session_state.get(f"load_on_{a.id}", False):
        continue
    qty = int(st.session_state.get(f"qty_{a.id}", 1))
    power_kw = (float(a.power_w) * qty) / 1000.0
    hrs = run_hrs_by_cat.get(a.category, 24.0)
    energy_24h_kwh += power_kw * hrs
energy_12h_kwh = energy_24h_kwh * (12.0 / 24.0)
avg_power_24h_kw = energy_24h_kwh / 24.0 if energy_24h_kwh else 0.0
avg_power_12h_kw = energy_12h_kwh / 12.0 if energy_12h_kwh else 0.0

est_cols = st.columns(2)
with est_cols[0]:
    st.markdown("**Next 24h (00:00–24:00)**")
    st.metric("Estimated energy", f"{energy_24h_kwh:.2f} kWh")
    st.metric("Average power", f"{avg_power_24h_kw:.2f} kW")
with est_cols[1]:
    st.markdown("**Next 12h (00:00–12:00)**")
    st.metric("Estimated energy", f"{energy_12h_kwh:.2f} kWh")
    st.metric("Average power", f"{avg_power_12h_kw:.2f} kW")

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

    with st.spinner("Building your plan…"):
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
    st.info("Run your plan to see results. Use **Try a quick demo (2 days)** in the sidebar for a one-click preview.")
    st.stop()

state_csv = res["state_csv"]
guidance_jsonl = res["guidance_jsonl"]
df = pd.read_csv(state_csv)
df["ts"] = pd.to_datetime(df["timestamp"])
t0 = pd.to_datetime(res.get("start_time", df["timestamp"].iloc[0] if len(df) else None))

# Replay control
st.markdown("### Explore your plan over time")
st.caption("Scrub through the next day (00:00–24:00) to see how solar and your loads interact at each step.")
step_max = max(0, len(df) - 1)
default_step = int(st.session_state.get("replay_step", min(step_max, 0)))
step = st.slider("Time step", min_value=0, max_value=step_max, value=default_step, help="Move the slider to see any moment in your plan.")
st.session_state["replay_step"] = step

row = df.iloc[step]
now_ts = pd.to_datetime(row["ts"])

# Day-ahead matching: expected demand vs expected solar (first planning day 00:00–24:00)
# Simulator stores matching as dict; fallback compute returns object — normalize for display
matching = res.get("matching_first_day")
if matching is None:
    try:
        cfg_ui = SystemConfig(
            location_name=st.session_state.get("location_name", ""),
            latitude=float(st.session_state.get("latitude", 0.0)),
            longitude=float(st.session_state.get("longitude", 0.0)),
            pv_capacity_kw=float(st.session_state.get("pv_kw", 3.0)),
            battery_capacity_kwh=float(st.session_state.get("bat_kwh", 5.0)),
            inverter_max_kw=float(st.session_state.get("inv_kw", 2.5)),
            timestep_minutes=DT_MINUTES_DEFAULT,
            horizon_steps=48,
        )
        appliances_ui = _build_appliances(st.session_state.get("selected_appliances", []), st.session_state.get("qty_map", {}))
        steps_per_day_ui = int(24 * 60 / DT_MINUTES_DEFAULT)
        first_day_df = df.head(steps_per_day_ui)
        matching = compute_day_ahead_matching(first_day_df, appliances_ui, cfg_ui, cfg_ui.inverter_max_kw, DT_MINUTES_DEFAULT)
    except Exception:
        matching = None

def _m(v, key, default=None):
    if v is None: return default
    return v.get(key, default) if isinstance(v, dict) else getattr(v, key, default)

def _fmt_tw(tw, step_min):
    if isinstance(tw, dict):
        s, e = tw.get("start_step", 0), tw.get("end_step", 0)
    else:
        s, e = tw.start_step, tw.end_step
    start_min = s * step_min
    end_min = (e + 1) * step_min
    sh, sm = divmod(start_min, 60)
    eh, em = divmod(end_min, 60)
    return f"{int(sh):02d}:{int(sm):02d}–{int(eh):02d}:{int(em):02d}"

# ---------------------------- Day-ahead outlook (Advisory) ----------------------------
st.markdown("### Your day-ahead outlook (00:00–24:00)")
st.markdown('**What to expect** — How your demand compares with expected solar for the next planning day. Based on real solar data; conditions may vary.')
if matching:
    step_min = _m(matching, "timestep_minutes", DT_MINUTES_DEFAULT)
    risk_val = _m(matching, "risk_level", "")
    risk_matching = str(risk_val).lower()
    risk_cls = {"low": "low", "medium": "med", "high": "high"}.get(risk_matching, "")

    # 1) Chart: Expected solar (PV power kW) over 24h; show data source on chart
    solar_source = (res.get("solar_source") or "synthetic").lower()
    if solar_source == "nasa_power_historical":
        source_label = "NASA POWER (7-day mean)"
    elif solar_source == "nasa_power":
        source_label = "NASA POWER"
    else:
        source_label = "Synthetic (demo)"
    steps_24h = int(24 * 60 / DT_MINUTES_DEFAULT)
    df_day = df.head(steps_24h)
    pv_kw_24h = df_day["pv_now_kw"].to_numpy(dtype=float)
    ts_24h = pd.to_datetime(df_day["ts"])
    fig_solar = go.Figure()
    fig_solar.add_trace(go.Scatter(x=ts_24h, y=pv_kw_24h, mode="lines", line_shape="spline", name="Expected PV power (kW)", line=dict(color="#0ea5e9")))
    fig_solar.update_layout(
        title="Expected solar over the next 24 hours",
        height=300,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title="Time (UTC)",
        yaxis_title="kW",
        font=dict(family="Plus Jakarta Sans, sans-serif"),
        annotations=[
            dict(
                x=1,
                y=1,
                xref="paper",
                yref="paper",
                text=f"Source: {source_label}",
                showarrow=False,
                xanchor="right",
                yanchor="top",
                font=dict(size=11),
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="rgba(0,0,0,0.1)",
                borderwidth=1,
                borderpad=6,
            )
        ],
    )
    st.plotly_chart(fig_solar, use_container_width=True)
    st.caption(f"Solar data for this run: **{source_label}**.")
    if solar_source == "nasa_power_historical":
        st.caption("Expected solar: mean profile from last 7 days at your location (smoothed).")

    # 2) Summary: total expected solar, planned demand
    st.markdown("#### Your 24h summary")
    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
    with mcol1:
        st.metric("Expected solar", f"{float(_m(matching, 'total_solar_kwh', 0)):.2f} kWh")
    with mcol2:
        st.metric("Your planned demand", f"{float(_m(matching, 'total_demand_kwh', 0)):.2f} kWh")
    with mcol3:
        margin_label = f"{float(_m(matching, 'energy_margin_kwh', 0)):+.2f} kWh"
        st.metric("Energy margin", margin_label)
    with mcol4:
        st.markdown(f'<span class="pill {risk_cls}">Risk: {str(risk_val).title()}</span>', unsafe_allow_html=True)
        st.caption("Day-ahead risk (overall tomorrow)")

    # 3) Comparative metrics and advisory text
    st.markdown(f'<div class="card"><p class="kpi">{_m(matching, "daily_outlook_text", "")}</p></div>', unsafe_allow_html=True)

    # 4) Colourful bar chart: surplus (green) vs deficit (red) by 15-min — verifiable from data
    load_kw_day = df_day["load_requested_kw"].to_numpy(dtype=float)
    surplus_flag = pv_kw_24h >= load_kw_day
    colors = ["#22c55e" if s else "#ef4444" for s in surplus_flag]
    fig_bars = go.Figure(go.Bar(x=ts_24h, y=[1 if s else -1 for s in surplus_flag], marker_color=colors, name="Surplus (green) / Deficit (red)"))
    fig_bars.update_layout(title="When you have surplus (green) vs deficit (red) — 15-min steps", height=220, margin=dict(l=10, r=10, t=40, b=10), xaxis_title="Time (UTC)", yaxis_title="", yaxis=dict(tickvals=[-1, 1], ticktext=["Deficit", "Surplus"]), font=dict(family="Plus Jakarta Sans, sans-serif"))
    st.plotly_chart(fig_bars, use_container_width=True)

    # 5) Surplus/deficit windows list — matches bar chart; note on critical load and inverter
    with st.expander("Surplus and deficit windows (solar ≥ demand vs demand > solar)"):
        sur = _m(matching, "surplus_windows") or []
        def_ = _m(matching, "deficit_windows") or []
        if sur:
            st.markdown("**Surplus windows** (solar ≥ demand): " + ", ".join(_fmt_tw(tw, step_min) for tw in sur))
        else:
            st.caption("No surplus windows in the first 24h.")
        if def_:
            st.markdown("**Deficit windows** (demand > solar): " + ", ".join(_fmt_tw(tw, step_min) for tw in def_))
        else:
            st.caption("No deficit windows.")
        st.caption("Green = surplus (solar covers demand). Red = deficit — during these times, prioritise essentials and consider shifting heavy loads to surplus windows.")
    if not _m(matching, "critical_fully_protected", True):
        st.warning("Your critical loads aren't fully protected in every timestep. Prioritise essentials and avoid adding heavy loads during deficit windows.")
else:
    st.caption("Run your plan to see your day-ahead outlook.")

# KPI summary cards (state CSV: cumulative at current replay step — real, from day-ahead simulation)
st.caption("At the current time step — cumulative over your run. Values update when you run your plan again.")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown('<div class="card"><div class="muted">Essential power reliability</div>'
                f'<div class="kpi">{100*float(row.get("kpi_CLSR", 0)):.1f}%</div>'
                '<div class="muted">How consistently your essentials stay powered</div></div>', unsafe_allow_html=True)
with col2:
    st.markdown('<div class="card"><div class="muted">Blackout time (essentials)</div>'
                f'<div class="kpi">{float(row.get("kpi_Blackout_minutes", 0)):.0f} min</div>'
                '<div class="muted">Unserved essentials so far</div></div>', unsafe_allow_html=True)
with col3:
    st.markdown('<div class="card"><div class="muted">Solar autonomy</div>'
                f'<div class="kpi">{100*float(row.get("kpi_SAR", 0)):.1f}%</div>'
                '<div class="muted">Share of your demand met by solar</div></div>', unsafe_allow_html=True)
with col4:
    st.markdown('<div class="card"><div class="muted">Battery throughput</div>'
                f'<div class="kpi">{float(row.get("kpi_Battery_throughput_kwh", 0)):.2f} kWh</div>'
                '<div class="muted">Charge/discharge so far (wear proxy)</div></div>', unsafe_allow_html=True)

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
st.markdown("#### Power available vs your load (at this time step)")
pcols = st.columns(3)
with pcols[0]:
    st.metric("Solar now", f"{pv_now_kw:.2f} kW")
with pcols[1]:
    st.metric("Power available (solar + battery)", f"{power_available_kw:.2f} kW")
with pcols[2]:
    st.metric("Your total selected load", f"{total_selected_kw:.2f} kW")
st.caption("What you can draw right now (solar + battery when SOC is above reserve) versus what your selected loads ask for.")

# Recommendation (for current replay step; regenerated when you run again)
st.markdown("### Recommendation for this time step")
st.caption("Guidance for the moment you've selected — regenerated when you run your plan again.")
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
    st.caption("**Step risk** — for this moment only. Day-ahead risk is in **Your 24h summary** above.")
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
                '<div class="muted">We keep a reserve for you; this is advisory only.</div></div>', unsafe_allow_html=True)

# Forecast from replay point (24h or 48h) — for exploring the timeline
st.markdown("### Solar forecast from this time step")
horizon_hours = st.radio("Show next", [24, 48], format_func=lambda x: f"{x} hours", horizontal=True, key="forecast_horizon")
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

# Appliance advice (day-ahead) — statement list, not per-appliance table
st.markdown("### Appliance advice for tomorrow")
st.caption("Day-ahead outlook: load vs solar. This is advice only; you stay in control.")
selected_appliances = st.session_state.get("selected_appliances", [])
catalog = {a.name: a for a in appliance_catalog()}
has_flexible_or_deferrable = any(
    catalog.get(n) and catalog[n].category in ("flexible", "deferrable")
    for n in selected_appliances
) if selected_appliances else False

if matching:
    statements = format_day_ahead_statements(matching, has_flexible_or_deferrable=has_flexible_or_deferrable, timestep_minutes=DT_MINUTES_DEFAULT)
    if statements:
        for s in statements:
            st.markdown(f"- {s}")
    else:
        st.caption("No day-ahead statements (run your plan to see advice).")
else:
    st.caption("Run your plan to see appliance advice from your day-ahead outlook.")

# Schedule heatmap (log-driven; §2.2 Digital twin replay)
st.markdown("### Recommended schedule (when to run what)")
st.caption("From your plan run: when each load would be served. Compare with **Appliance advice for tomorrow** above (based on solar vs demand).")
day_df2 = df.copy()
day_df2["day"] = day_df2["ts"].dt.floor("D")
days_unique = sorted(day_df2["day"].unique())
if not days_unique:
    st.caption("No schedule data yet.")
else:
    # Day to show: default to the day containing the current replay step
    now_day = now_ts.floor("D") if hasattr(now_ts, "floor") else pd.Timestamp(now_ts).floor("D")
    day_index = next((i for i, d in enumerate(days_unique) if d == now_day), 0)
    day_options = list(range(len(days_unique)))
    day_choice_idx = st.selectbox(
        "Pick a day",
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
    fig_hm.update_layout(height=280 + 10*len(apps), margin=dict(l=10, r=10, t=30, b=10), font=dict(family="Plus Jakarta Sans, sans-serif"))
    st.plotly_chart(fig_hm, width="stretch")

# Downloads (§8: evidence artifacts — system summary, weather, today/tomorrow, KPIs, advisory disclaimer)
st.markdown("### Download your plan")
st.caption("Save your state log, guidance log, or a full PDF (today + tomorrow) for your records or sharing.")
dcols = st.columns([2, 2, 2])
with dcols[0]:
    st.download_button("Download state log (CSV)", data=Path(state_csv).read_bytes(), file_name="state_log.csv", mime="text/csv", width="stretch")
with dcols[1]:
    st.download_button("Download guidance log (JSONL)", data=Path(guidance_jsonl).read_bytes(), file_name="guidance_log.jsonl", mime="application/jsonl", width="stretch")

_solar_src = (res.get("solar_source") or "synthetic").lower()
_solar_src_label = "NASA POWER (7-day mean)" if _solar_src == "nasa_power_historical" else ("NASA POWER" if _solar_src == "nasa_power" else "Synthetic (demo)")
system_summary_for_pdf = {
    "Location": str(st.session_state.get("location_name", "")) or "Configured location",
    "PV capacity": f"{float(st.session_state.get('pv_kw', 0)):.1f} kW",
    "Battery": f"{float(st.session_state.get('bat_kwh', 0)):.1f} kWh",
    "Inverter limit": f"{float(st.session_state.get('inv_kw', 0)):.1f} kW",
    "Solar source": _solar_src_label,
}
weather_summary = st.session_state.get("current_weather") or {}
# Pass matching as dict so PDF builder gets a serializable format (avoids TypeError on Cloud/serialization)
raw_matching = res.get("matching_first_day")
matching_for_pdf = None
if raw_matching is not None:
    if hasattr(raw_matching, "to_dict"):
        try:
            matching_for_pdf = raw_matching.to_dict()
        except Exception:
            matching_for_pdf = None
    elif isinstance(raw_matching, dict):
        matching_for_pdf = raw_matching
try:
    pdf_bytes = build_two_day_plan_pdf_from_logs(
        state_csv_path=state_csv,
        guidance_jsonl_path=guidance_jsonl,
        title="Solar-first Household Plan (Today + Tomorrow)",
        weather_summary=weather_summary,
        system_summary_override=system_summary_for_pdf,
        matching_result=matching_for_pdf,
    )
except Exception:
    pdf_bytes = build_two_day_plan_pdf_from_logs(
        state_csv_path=state_csv,
        guidance_jsonl_path=guidance_jsonl,
        title="Solar-first Household Plan (Today + Tomorrow)",
        weather_summary=weather_summary,
        system_summary_override=system_summary_for_pdf,
        matching_result=None,
    )
with dcols[2]:
    st.download_button("Download plan (PDF: Today + Tomorrow)", data=pdf_bytes, file_name="solar_plan_today_tomorrow.pdf", mime="application/pdf", width="stretch")
