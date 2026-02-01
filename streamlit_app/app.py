import sys
from pathlib import Path

# Ensure src/ is importable when running Streamlit without installing the package
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from offgrid_dt.control.controllers import get_controllers
from offgrid_dt.dt.simulator import simulate
from offgrid_dt.forecast.openweather import OpenWeatherSolarClient
from offgrid_dt.io.schema import Appliance, SystemConfig
from offgrid_dt.io.pdf_report import build_plan_pdf, build_two_day_plan_pdf, schedule_from_state_csv


st.set_page_config(page_title="Off-grid Solar DT", layout="wide")


def _inject_css() -> None:
    st.markdown(
        """
        <style>
          .app-title {font-size: 2.0rem; font-weight: 700; margin-bottom: 0.25rem;}
          .app-sub {opacity: 0.8; margin-top: 0;}
          .card {border: 1px solid rgba(49, 51, 63, 0.2); border-radius: 14px; padding: 14px 16px; background: rgba(255,255,255,0.02);}
          .pill {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.85rem; border: 1px solid rgba(49, 51, 63, 0.2);} 
          .pill.good {background: rgba(0, 200, 83, 0.12);}
          .pill.bad {background: rgba(255, 82, 82, 0.12);}
          .pill.mid {background: rgba(255, 193, 7, 0.12);}
          .muted {opacity: 0.75;}
          .section-title {font-weight: 700; margin-top: 0.5rem;}
          .small {font-size: 0.9rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _appliance_catalog() -> list[dict]:
    """Curated appliance library (editable per-selection in the sidebar)."""
    return [
        # Critical
        {"id": "lighting", "name": "Lighting (LED)", "category": "critical", "power_w": 120, "notes": "Typical evening lighting"},
        {"id": "fans", "name": "Ceiling fans", "category": "critical", "power_w": 160, "notes": "2 fans average"},
        {"id": "fridge", "name": "Refrigerator", "category": "critical", "power_w": 150, "notes": "Average running power"},
        {"id": "router", "name": "Wi‑Fi router", "category": "critical", "power_w": 15, "notes": "Always-on"},
        {"id": "phone", "name": "Phone charging", "category": "critical", "power_w": 20, "notes": "2 phones"},
        # Flexible tasks
        {
            "id": "pump",
            "name": "Water pumping",
            "category": "flexible",
            "power_w": 750,
            "duration_steps": 4,
            "earliest_start_step": 20,
            "latest_end_step": 80,
            "notes": "Shift to solar hours",
        },
        {
            "id": "wash",
            "name": "Washing machine",
            "category": "flexible",
            "power_w": 500,
            "duration_steps": 4,
            "earliest_start_step": 20,
            "latest_end_step": 80,
            "notes": "One cycle",
        },
        {
            "id": "dishwasher",
            "name": "Dishwasher",
            "category": "flexible",
            "power_w": 1200,
            "duration_steps": 6,
            "earliest_start_step": 24,
            "latest_end_step": 88,
            "notes": "If applicable",
        },
        # Deferrable tasks
        {
            "id": "iron",
            "name": "Ironing",
            "category": "deferrable",
            "power_w": 1000,
            "duration_steps": 2,
            "earliest_start_step": 24,
            "latest_end_step": 84,
            "notes": "Avoid at low SOC",
        },
        {
            "id": "vacuum",
            "name": "Vacuum cleaner",
            "category": "deferrable",
            "power_w": 900,
            "duration_steps": 2,
            "earliest_start_step": 24,
            "latest_end_step": 88,
            "notes": "Short run",
        },
        {
            "id": "laundry_quota",
            "name": "Small daily quota (misc)",
            "category": "deferrable",
            "power_w": 200,
            "daily_quota_steps": 6,
            "earliest_start_step": 16,
            "latest_end_step": 88,
            "notes": "Distributed tasks",
        },
    ]


def _fmt_place(p: dict) -> str:
    bits = [p.get("name"), p.get("state"), p.get("country")]
    bits = [b for b in bits if b]
    lat = p.get("lat")
    lon = p.get("lon")
    if lat is not None and lon is not None:
        bits.append(f"({lat:.4f}, {lon:.4f})")
    return ", ".join(bits)


def _risk_pill(risk: str) -> str:
    risk = (risk or "").lower()
    if risk == "low":
        return '<span class="pill good">Risk: low</span>'
    if risk == "medium":
        return '<span class="pill mid">Risk: medium</span>'
    return '<span class="pill bad">Risk: high</span>'


def _kwh(kw: float, minutes: int) -> float:
    return float(kw) * (minutes / 60.0)


def _build_appliances_from_selection(catalog: list[dict], selected: dict) -> list[Appliance]:
    out: list[Appliance] = []
    by_id = {a["id"]: a for a in catalog}
    for ap_id, meta in selected.items():
        base = by_id.get(ap_id)
        if not base:
            continue
        qty = int(meta.get("qty", 1))
        if qty <= 0:
            continue
        power_w = float(meta.get("power_w", base.get("power_w"))) * qty
        out.append(
            Appliance(
                id=ap_id,
                name=base.get("name", ap_id),
                category=base.get("category", "flexible"),
                power_w=power_w,
                duration_steps=int(meta.get("duration_steps", base.get("duration_steps", 1)) or 1),
                earliest_start_step=int(meta.get("earliest_start_step", base.get("earliest_start_step", 0)) or 0),
                latest_end_step=int(meta.get("latest_end_step", base.get("latest_end_step", 96)) or 96),
                daily_quota_steps=int(meta.get("daily_quota_steps", base.get("daily_quota_steps", 0)) or 0),
            )
        )
    return out


def _advisory_table(appliances: list[Appliance], last_row: pd.Series, dt_minutes: int) -> pd.DataFrame:
    soc = float(last_row.get("soc_now", 0.0))
    soc_min = float(last_row.get("soc_min", 0.25)) if "soc_min" in last_row else 0.25
    risk = str(last_row.get("risk_level", "medium")).lower()
    pv_now = float(last_row.get("pv_now_kw", 0.0))
    load_served = float(last_row.get("load_served_kw", 0.0))

    rows = []
    for a in appliances:
        kw = float(a.power_w) / 1000.0
        daily_kwh_est = _kwh(kw, dt_minutes) * (96 if dt_minutes == 15 else int(24 * 60 / dt_minutes)) if a.category == "critical" else None

        # Simple policy for UI guidance (separate from controller):
        # - If risk high or SOC close to reserve: flag high-power flexible/deferrable as "avoid now"
        # - Otherwise OK
        avoid = False
        if a.category != "critical":
            if (risk == "high") or (soc <= soc_min + 0.05):
                avoid = kw >= 0.7
        status = "OK" if not avoid else "Avoid now"
        color = "green" if status == "OK" else "red"

        rows.append(
            {
                "Appliance": a.name,
                "Category": a.category,
                "Power (W)": int(round(a.power_w)),
                "Status": status,
                "Why": "Reserve protection / low solar" if avoid else "Within safe operating envelope",
                "_color": color,
            }
        )

    df = pd.DataFrame(rows)
    return df


_inject_css()

st.markdown('<div class="app-title">Solar-first Off-grid Household Energy Assistant</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-sub muted">Digital Twin + forecast-informed advisory + explainable guidance. Designed for publication-ready evidence.</div>',
    unsafe_allow_html=True,
)


controllers = get_controllers()
controller_names = [c.name for c in controllers]


with st.sidebar:
    st.markdown("### Intelligent System Configuration")

    openweather_key = st.secrets.get("openweather_api_key", None)
    openweather_base = st.secrets.get("openweather_base_url", "https://api.openweathermap.org")
    openai_key = st.secrets.get("openai_api_key", None)
    openai_model = st.secrets.get("openai_model", "gpt-4.1-mini")

    # Location block
    with st.expander("Location", expanded=True):
        default_query = st.session_state.get("location_query", "New Delhi")
        location_query = st.text_input("Search city / town", value=default_query, help="Uses OpenWeather geocoding (if API key is set).")
        st.session_state["location_query"] = location_query

        lat = st.session_state.get("lat", 28.6139)
        lon = st.session_state.get("lon", 77.2090)
        location_name = st.session_state.get("location_name", "Demo")

        places = []
        if openweather_key and location_query.strip():
            try:
                client = OpenWeatherSolarClient(openweather_key, base_url=openweather_base)
                places = client.geocode(location_query.strip(), limit=5)
            except Exception:
                places = []

        if places:
            options = [_fmt_place(p) for p in places]
            pick = st.selectbox("Matches", options, index=0)
            chosen = places[options.index(pick)]
            location_name = chosen.get("name") or location_query
            lat = float(chosen.get("lat"))
            lon = float(chosen.get("lon"))
            st.caption("Auto-filled from geocoding")
        else:
            st.caption("No geocoding match (or API key missing). Enter coordinates manually.")
            location_name = st.text_input("Location label", value=location_name)
            lat = st.number_input("Latitude", value=float(lat), format="%.6f")
            lon = st.number_input("Longitude", value=float(lon), format="%.6f")

        st.session_state["lat"] = float(lat)
        st.session_state["lon"] = float(lon)
        st.session_state["location_name"] = str(location_name)

    # System block
    with st.expander("Solar + Battery", expanded=True):
        pv_kw = st.number_input("PV capacity (kW)", min_value=0.5, value=float(st.session_state.get("pv_kw", 3.5)), step=0.1)
        bat_kwh = st.number_input("Battery capacity (kWh)", min_value=1.0, value=float(st.session_state.get("bat_kwh", 7.5)), step=0.5)
        inv_kw = st.number_input("Inverter max (kW)", min_value=0.5, value=float(st.session_state.get("inv_kw", 2.5)), step=0.1)
        soc_init = st.slider("Initial SOC", 0.0, 1.0, float(st.session_state.get("soc_init", 0.6)), 0.01)
        soc_min = st.slider("Minimum reserve SOC", 0.0, 1.0, float(st.session_state.get("soc_min", 0.25)), 0.01)
        soc_max = st.slider("Maximum SOC", 0.0, 1.0, float(st.session_state.get("soc_max", 0.95)), 0.01)
        horizon_steps = st.select_slider("Forecast horizon", options=[24, 48, 72, 96, 120], value=int(st.session_state.get("horizon_steps", 96)), help="15-min steps; 96 ≈ 24 hours")
        days = st.selectbox("Simulation days", [1, 3, 5, 7, 14], index=[1, 3, 5, 7, 14].index(int(st.session_state.get("days", 5))))

        st.session_state.update(
            {
                "pv_kw": float(pv_kw),
                "bat_kwh": float(bat_kwh),
                "inv_kw": float(inv_kw),
                "soc_init": float(soc_init),
                "soc_min": float(soc_min),
                "soc_max": float(soc_max),
                "horizon_steps": int(horizon_steps),
                "days": int(days),
            }
        )

    with st.expander("Control", expanded=True):
        default_ctrl = st.session_state.get("controller_name", "forecast_heuristic")
        controller_name = st.selectbox(
            "Decision engine",
            controller_names,
            index=controller_names.index(default_ctrl) if default_ctrl in controller_names else 0,
            help="Use baselines for comparison; forecast_heuristic is the survivability-first scheduler.",
        )
        st.session_state["controller_name"] = controller_name

    st.divider()
    st.markdown("### Appliance Selection")
    catalog = _appliance_catalog()
    catalog_by_id = {a["id"]: a for a in catalog}
    label_map = {a["name"]: a["id"] for a in catalog}
    name_options = list(label_map.keys())

    # Persist selections
    if "appliance_selection" not in st.session_state:
        st.session_state.appliance_selection = {
            "lighting": {"qty": 1},
            "fans": {"qty": 1},
            "fridge": {"qty": 1},
            "phone": {"qty": 1},
            "pump": {"qty": 1},
            "wash": {"qty": 1},
        }

    selected_names = [catalog_by_id[k]["name"] for k in st.session_state.appliance_selection.keys() if k in catalog_by_id]
    chosen_names = st.multiselect(
        "Choose appliances", name_options, default=selected_names, help="Select what exists in the household. Quantity applies a power multiplier."
    )
    chosen_ids = [label_map[n] for n in chosen_names]

    # Remove deselected
    st.session_state.appliance_selection = {k: v for k, v in st.session_state.appliance_selection.items() if k in chosen_ids}
    # Add newly selected
    for ap_id in chosen_ids:
        st.session_state.appliance_selection.setdefault(ap_id, {"qty": 1})

    # Quantity + advanced overrides
    for ap_id in chosen_ids:
        meta = st.session_state.appliance_selection.get(ap_id, {"qty": 1})
        base = catalog_by_id[ap_id]
        with st.container():
            cols = st.columns([1.6, 1.0])
            with cols[0]:
                st.markdown(f"**{base['name']}**  ")
                st.caption(f"{base['category'].title()} · Typical {int(base['power_w'])} W · {base.get('notes','')}")
            with cols[1]:
                qty = st.number_input("Qty", min_value=1, max_value=10, value=int(meta.get("qty", 1)), key=f"qty_{ap_id}")
                meta["qty"] = int(qty)

            with st.expander(f"Advanced settings: {base['name']}"):
                meta["power_w"] = st.number_input(
                    "Override wattage (W)",
                    min_value=1,
                    value=int(meta.get("power_w", base.get("power_w", 100))),
                    key=f"w_{ap_id}",
                    help="Per unit. Quantity multiplier applies.",
                )

                if base["category"] != "critical":
                    meta["duration_steps"] = st.number_input(
                        "Duration (15-min steps)",
                        min_value=1,
                        value=int(meta.get("duration_steps", base.get("duration_steps", 1) or 1)),
                        key=f"dur_{ap_id}",
                    )
                    meta["earliest_start_step"] = st.number_input(
                        "Earliest start (step)",
                        min_value=0,
                        value=int(meta.get("earliest_start_step", base.get("earliest_start_step", 0) or 0)),
                        key=f"es_{ap_id}",
                        help="0 = 00:00. For 15-min steps, 20 ≈ 05:00.",
                    )
                    meta["latest_end_step"] = st.number_input(
                        "Latest end (step)",
                        min_value=1,
                        value=int(meta.get("latest_end_step", base.get("latest_end_step", 96) or 96)),
                        key=f"le_{ap_id}",
                        help="96 = 24:00 for 15-min steps.",
                    )
                    meta["daily_quota_steps"] = st.number_input(
                        "Daily quota (optional, steps)",
                        min_value=0,
                        value=int(meta.get("daily_quota_steps", base.get("daily_quota_steps", 0) or 0)),
                        key=f"dq_{ap_id}",
                        help="If >0, creates that many 1-step tasks per day.",
                    )

            st.session_state.appliance_selection[ap_id] = meta

    st.divider()
    run = st.button("Run digital twin", type="primary", use_container_width=True)


cfg = SystemConfig(
    location_name=str(st.session_state.get("location_name", "Demo")),
    latitude=float(st.session_state.get("lat", 28.6139)),
    longitude=float(st.session_state.get("lon", 77.2090)),
    pv_capacity_kw=float(st.session_state.get("pv_kw", 3.5)),
    battery_capacity_kwh=float(st.session_state.get("bat_kwh", 7.5)),
    inverter_max_kw=float(st.session_state.get("inv_kw", 2.5)),
    soc_init=float(st.session_state.get("soc_init", 0.6)),
    soc_min=float(st.session_state.get("soc_min", 0.25)),
    soc_max=float(st.session_state.get("soc_max", 0.95)),
    horizon_steps=int(st.session_state.get("horizon_steps", 96)),
)

appliances = _build_appliances_from_selection(_appliance_catalog(), st.session_state.get("appliance_selection", {}))


top_row = st.columns([1.2, 1.2, 1.2, 1.2])
with top_row[0]:
    st.markdown(
        f"""
        <div class="card">
          <div class="section-title">Site</div>
          <div class="small"><b>{cfg.location_name}</b></div>
          <div class="muted small">Lat {cfg.latitude:.4f} · Lon {cfg.longitude:.4f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with top_row[1]:
    st.markdown(
        f"""
        <div class="card">
          <div class="section-title">System</div>
          <div class="small"><b>PV</b> {cfg.pv_capacity_kw:.1f} kW · <b>Battery</b> {cfg.battery_capacity_kwh:.1f} kWh</div>
          <div class="muted small">Inverter {cfg.inverter_max_kw:.1f} kW · Reserve {cfg.soc_min:.0%}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with top_row[2]:
    crit_kw = sum(a.power_w for a in appliances if a.category == "critical") / 1000.0
    flex_kw = sum(a.power_w for a in appliances if a.category != "critical") / 1000.0
    st.markdown(
        f"""
        <div class="card">
          <div class="section-title">Loads</div>
          <div class="small"><b>Critical</b> {crit_kw:.2f} kW</div>
          <div class="muted small"><b>Schedulable peak</b> {flex_kw:.2f} kW (tasks)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with top_row[3]:
    st.markdown(
        f"""
        <div class="card">
          <div class="section-title">Explainability</div>
          <div class="small">Deterministic reason codes + optional OpenAI rewrite</div>
          <div class="muted small">OpenAI enabled: <b>{'Yes' if bool(openai_key) else 'No'}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.divider()

main_left, main_right = st.columns([1.3, 1.0])

with main_left:
    st.markdown("### Forecast-aware operational view")
    st.caption("Runs a closed-loop simulation and logs everything for reproducibility. Use the results for paper plots and user-study scenarios.")

with main_right:
    st.markdown("### What this recommends")
    st.caption("Single-line guidance + plain-language explanation, backed by reason codes.")

if run:
    ctrl = next(c for c in controllers if c.name == st.session_state.get("controller_name", controller_names[0]))
    out_dir = Path("logs") / f"run_{ctrl.name}"
    paths = simulate(
        cfg=cfg,
        appliances=appliances,
        controller=ctrl,
        days=int(st.session_state.get("days", 5)),
        openweather_api_key=openweather_key,
        openweather_base_url=openweather_base,
        openai_api_key=openai_key,
        openai_model=openai_model,
        out_dir=out_dir,
    )
    st.session_state.last_run = paths


paths = st.session_state.get("last_run")
if not paths:
    st.info("Configure the system and appliances on the left sidebar, then click **Run digital twin**.")
    st.stop()

state_csv = paths["state_csv"]
df = pd.read_csv(state_csv)

# Parse timestamp for better plotting
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

# ---------- Scenario replay controls (time scrubber) ----------
if "replay_idx" not in st.session_state:
    st.session_state.replay_idx = len(df) - 1

replay_cols = st.columns([1.8, 1.2, 1.2, 1.2])
with replay_cols[0]:
    st.markdown("### Scenario replay")
    st.caption("Scrub through the run to review recommendations, risks, and scheduling decisions at any time step.")
with replay_cols[1]:
    back = st.button("◀ Step", use_container_width=True)
with replay_cols[2]:
    fwd = st.button("Step ▶", use_container_width=True)
with replay_cols[3]:
    to_end = st.button("Jump to latest", use_container_width=True)

if back:
    st.session_state.replay_idx = max(0, int(st.session_state.replay_idx) - 1)
if fwd:
    st.session_state.replay_idx = min(len(df) - 1, int(st.session_state.replay_idx) + 1)
if to_end:
    st.session_state.replay_idx = len(df) - 1

idx = st.slider(
    "Replay time index",
    min_value=0,
    max_value=len(df) - 1,
    value=int(st.session_state.replay_idx),
    step=1,
    help="Move the slider to replay the simulation. All panels update to the selected time.",
)
st.session_state.replay_idx = int(idx)
sel = df.iloc[int(idx)]
sel_ts = pd.to_datetime(sel["timestamp"], utc=True)
st.caption(f"Selected time: **{sel_ts.strftime('%Y-%m-%d %H:%M UTC')}**")

# Convenience handles
last = df.iloc[-1]

with main_right:
    st.markdown(_risk_pill(str(sel.get("risk_level", "medium"))), unsafe_allow_html=True)
    st.markdown(f"**{sel.get('headline','')}**")
    st.write(str(sel.get("explanation", "")))
    st.caption(f"Reasons: {str(sel.get('reason_codes','')).replace(';', ', ')}")

    k1, k2, k3, k4 = st.columns(4)
    # KPIs are running totals; show the latest totals for the run (not the selected step)
    if "kpi_CLSR" in df.columns:
        k1.metric("CLSR", f"{float(last['kpi_CLSR']):.3f}")
    if "kpi_Blackout_minutes" in df.columns:
        k2.metric("Blackout (min)", f"{int(float(last['kpi_Blackout_minutes']))}")
    if "kpi_SAR" in df.columns:
        k3.metric("SAR", f"{float(last['kpi_SAR']):.3f}")
    if "kpi_Solar_utilization" in df.columns:
        k4.metric("Solar util", f"{100*float(last['kpi_Solar_utilization']):.1f}%")


with main_left:
    # PV vs load
    fig1 = px.line(
        df,
        x="timestamp",
        y=["pv_now_kw", "load_served_kw", "load_requested_kw"],
        title="PV output, served load, and requested load",
    )
    fig1.add_vline(x=sel_ts, line_dash="dash")
    st.plotly_chart(fig1, use_container_width=True)

    # SOC + reserve band
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=df["timestamp"], y=df["soc_now"], mode="lines", name="SOC"))
    fig2.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=[cfg.soc_min] * len(df),
            mode="lines",
            name="Reserve",
            line=dict(dash="dash"),
        )
    )
    fig2.update_layout(title="Battery SOC with reserve threshold", yaxis=dict(range=[0, 1]))
    fig2.add_vline(x=sel_ts, line_dash="dash")
    st.plotly_chart(fig2, use_container_width=True)

    # Daily energy summaries (useful for reviewers)
    daily = df.set_index("timestamp").resample("1D").agg(
        pv_kwh=("pv_now_kw", lambda s: float(s.sum()) * (cfg.timestep_minutes / 60.0)),
        served_kwh=("load_served_kw", lambda s: float(s.sum()) * (cfg.timestep_minutes / 60.0)),
        curtailed_kwh=("curtailed_solar_kw", lambda s: float(s.sum()) * (cfg.timestep_minutes / 60.0)),
    )
    daily = daily.reset_index()
    fig3 = px.bar(daily, x="timestamp", y=["pv_kwh", "served_kwh", "curtailed_kwh"], title="Daily energy: PV generated vs used vs curtailed")
    st.plotly_chart(fig3, use_container_width=True)

    # Schedule timeline heatmap
    st.markdown("### Recommended schedule timeline")
    st.caption("Heatmap of served task decisions (per 15-minute slot). Use this as a reviewer-facing visual and user-study stimulus.")
    df_h = df.copy()
    df_h["day"] = pd.to_datetime(df_h["timestamp"], utc=True).dt.floor("D")
    days = sorted(df_h["day"].unique())
    if days:
        selected_day = pd.to_datetime(sel_ts, utc=True).floor("D")
        day_idx = days.index(selected_day) if selected_day in days else 0
        day_choice = st.selectbox(
            "Day to visualize",
            options=list(range(len(days))),
            index=day_idx,
            format_func=lambda i: pd.to_datetime(days[i]).strftime("%Y-%m-%d"),
        )
        d0 = days[int(day_choice)]
        day_df = df_h[df_h["day"] == d0].reset_index(drop=True)

        # Build matrix: appliances x steps (served=1 else 0)
        appliance_ids = [a.id for a in appliances if a.category != "critical"]
        appliance_names = {a.id: a.name for a in appliances}

        def _parse_ids(s: str):
            if not isinstance(s, str) or not s.strip():
                return []
            return [x for x in s.split(";") if x]

        z = []
        y_labels = []
        for aid in appliance_ids:
            row = []
            for s in day_df.get("served_task_ids", "").astype(str).tolist():
                tids = _parse_ids(s)
                served_aids = {t.split("_")[0] for t in tids if t}
                row.append(1 if aid in served_aids else 0)
            z.append(row)
            y_labels.append(appliance_names.get(aid, aid))

        if z and len(z[0]) > 0:
            x_labels = [
                pd.to_datetime(day_df.loc[i, "timestamp"], utc=True).strftime("%H:%M")
                for i in range(len(day_df))
            ]
            # downsample x labels for readability
            x_tickvals = list(range(0, len(x_labels), 4))
            x_ticktext = [x_labels[i] for i in x_tickvals]
            fig_hm = go.Figure(
                data=go.Heatmap(
                    z=z,
                    x=list(range(len(x_labels))),
                    y=y_labels,
                    showscale=False,
                )
            )
            fig_hm.update_layout(
                height=max(320, 40 * len(y_labels) + 120),
                xaxis=dict(
                    title="Time (15-min steps)",
                    tickmode="array",
                    tickvals=x_tickvals,
                    ticktext=x_ticktext,
                ),
                yaxis=dict(title="Appliance"),
                margin=dict(l=10, r=10, t=30, b=10),
            )
            # mark the selected timestamp if it belongs to this day
            if pd.to_datetime(sel_ts, utc=True).floor("D") == pd.to_datetime(d0, utc=True):
                # find nearest index within this day
                try:
                    day_ts = pd.to_datetime(day_df["timestamp"], utc=True)
                    nearest = int((day_ts - sel_ts).abs().idxmin())
                except Exception:
                    nearest = 0
                fig_hm.add_vline(x=nearest, line_dash="dash")
            st.plotly_chart(fig_hm, use_container_width=True)
        else:
            st.info("No schedulable appliances selected (heatmap is empty).")


st.divider()
st.markdown("### Appliance advisory (selected loads)")
adv = _advisory_table(appliances, sel, cfg.timestep_minutes)


def _style_status(row):
    if row.get("Status") == "Avoid now":
        return ["" if c != "Status" else "background-color: rgba(255, 82, 82, 0.18); font-weight: 700" for c in row.index]
    return ["" if c != "Status" else "background-color: rgba(0, 200, 83, 0.16); font-weight: 700" for c in row.index]


st.dataframe(
    adv.drop(columns=["_color"], errors="ignore").style.apply(_style_status, axis=1),
    use_container_width=True,
)


st.divider()
with st.expander("Downloads and raw logs"):
    st.success(f"Logs written: {paths}")
    st.download_button(
        "Download state CSV",
        data=Path(state_csv).read_bytes(),
        file_name=Path(state_csv).name,
        mime="text/csv",
        use_container_width=True,
    )
    if "guidance_jsonl" in paths:
        gpath = paths["guidance_jsonl"]
        st.download_button(
            "Download guidance JSONL",
            data=Path(gpath).read_bytes(),
            file_name=Path(gpath).name,
            mime="application/jsonl",
            use_container_width=True,
        )

    # PDF handout for today + optional tomorrow
    st.markdown("#### Plan PDF")
    include_tomorrow = st.checkbox(
        "Include tomorrow’s plan (forecast-based)",
        value=True,
        help="Generates a 48h handout (Today + Tomorrow). Tomorrow’s schedule is conditional on the simulated end-of-day SOC and available forecast horizon.",
    )
    appliance_id_to_name = {a.id: a.name for a in appliances}
    df_days = df.copy()
    df_days["day"] = pd.to_datetime(df_days["timestamp"], utc=True).dt.floor("D")
    uniq_days = sorted(df_days["day"].unique())
    cur_day = pd.to_datetime(sel_ts, utc=True).floor("D")
    day_idx = uniq_days.index(cur_day) if cur_day in uniq_days else 0
    schedule_today = schedule_from_state_csv(
        df,
        appliance_id_to_name=appliance_id_to_name,
        day_index=day_idx,
        timestep_minutes=cfg.timestep_minutes,
    )

    # Tomorrow extraction (Option A: 48h rolling plan) — uses next day from the simulated log.
    tomorrow_idx = day_idx + 1
    schedule_tomorrow = None
    tomorrow_outlook = None
    rec_tomorrow = None
    if include_tomorrow:
        if tomorrow_idx < len(uniq_days):
            schedule_tomorrow = schedule_from_state_csv(
                df,
                appliance_id_to_name=appliance_id_to_name,
                day_index=tomorrow_idx,
                timestep_minutes=cfg.timestep_minutes,
            )
            tday = uniq_days[tomorrow_idx]
            tdf = df_days[df_days["day"] == tday].reset_index(drop=True)
            if not tdf.empty:
                # Tomorrow recommendation: use the first step of the day as the plan anchor.
                t0 = tdf.iloc[0]
                rec_tomorrow = {
                    "headline": str(t0.get("headline", "")),
                    "explanation": str(t0.get("explanation", "")),
                    "risk": str(t0.get("risk_level", "")),
                    "reasons": str(t0.get("reason_codes", "")).replace(";", ", "),
                }

                # Outlook numbers for tomorrow
                dt_h = cfg.timestep_minutes / 60.0
                pv_kwh = float(tdf["pv_now_kw"].sum()) * dt_h
                served_kwh = float(tdf["load_served_kw"].sum()) * dt_h
                curtailed_kwh = float(tdf.get("curtailed_solar_kw", 0.0).sum()) * dt_h

                # Risk outlook = max risk during the day
                risk_order = {"low": 0, "medium": 1, "high": 2}
                risks = [str(x).lower() for x in tdf.get("risk_level", []).tolist()]
                max_r = "low"
                for r in risks:
                    if risk_order.get(r, 1) >= risk_order.get(max_r, 0):
                        max_r = r

                # Best heavy-load window: pick the 2-hour window with highest PV
                best_start = 0
                if len(tdf) >= 8:
                    pv = tdf["pv_now_kw"].astype(float).tolist()
                    best_val = -1.0
                    for i in range(0, len(pv) - 8 + 1):
                        v = sum(pv[i : i + 8])
                        if v > best_val:
                            best_val = v
                            best_start = i
                t_start = pd.to_datetime(tdf.loc[best_start, "timestamp"], utc=True)
                t_end = pd.to_datetime(tdf.loc[min(best_start + 8, len(tdf) - 1), "timestamp"], utc=True)
                best_window = f"{t_start.strftime('%H:%M')}–{t_end.strftime('%H:%M')}"

                tomorrow_outlook = {
                    "Expected PV energy": f"{pv_kwh:.1f} kWh",
                    "Served energy": f"{served_kwh:.1f} kWh",
                    "Curtailed solar": f"{curtailed_kwh:.1f} kWh",
                    "Risk outlook": max_r,
                    "Best heavy-load window": best_window,
                }
        else:
            st.warning("Tomorrow plan requires at least 2 simulated days. Increase **Simulation days** in the sidebar.")

    # Build PDF
    base_system = {
        "Location": f"{cfg.location_name} ({cfg.latitude:.4f}, {cfg.longitude:.4f})",
        "PV": f"{cfg.pv_capacity_kw:.1f} kW",
        "Battery": f"{cfg.battery_capacity_kwh:.1f} kWh",
        "Inverter": f"{cfg.inverter_max_kw:.1f} kW",
        "Reserve": f"{cfg.soc_min:.0%}",
        "Horizon": f"{cfg.horizon_steps} steps",
    }
    base_kpis = {
        "CLSR": f"{float(last.get('kpi_CLSR', 0.0)):.3f}" if 'kpi_CLSR' in df.columns else "-",
        "Blackout (min)": f"{int(float(last.get('kpi_Blackout_minutes', 0.0)))}" if 'kpi_Blackout_minutes' in df.columns else "-",
        "SAR": f"{float(last.get('kpi_SAR', 0.0)):.3f}" if 'kpi_SAR' in df.columns else "-",
        "Solar utilization": f"{100*float(last.get('kpi_Solar_utilization', 0.0)):.1f}%" if 'kpi_Solar_utilization' in df.columns else "-",
    }

    rec_today = {
        "headline": str(sel.get("headline", "")),
        "explanation": str(sel.get("explanation", "")),
        "risk": str(sel.get("risk_level", "")),
        "reasons": str(sel.get("reason_codes", "")).replace(";", ", "),
    }

    if include_tomorrow and schedule_tomorrow is not None:
        pdf_bytes = build_two_day_plan_pdf(
            title="Off-grid Solar Assistant — 48h Plan (Today + Tomorrow)",
            system_summary=base_system,
            kpis=base_kpis,
            recommendations_today=rec_today,
            schedule_rows_today=schedule_today if schedule_today else [{"time_window": "-", "appliance": "No schedulable tasks", "advisory": "-"}],
            recommendations_tomorrow=rec_tomorrow or {"headline": "", "explanation": "", "risk": "", "reasons": ""},
            schedule_rows_tomorrow=schedule_tomorrow if schedule_tomorrow else [{"time_window": "-", "appliance": "No schedulable tasks", "advisory": "-"}],
            tomorrow_outlook=tomorrow_outlook,
            notes="Advisory-only prototype. The 48h plan is forecast-informed and updated via rolling replanning; follow guidance with household discretion.",
        )
        fname = "plan_48h_today_tomorrow.pdf"
        label = "Download 48h Plan (PDF)"
    else:
        pdf_bytes = build_plan_pdf(
            title="Off-grid Solar Assistant — Today’s Plan",
            system_summary=base_system,
            kpis=base_kpis,
            recommendations=rec_today,
            schedule_rows=schedule_today if schedule_today else [{"time_window": "-", "appliance": "No schedulable tasks", "advisory": "-"}],
            notes="Advisory-only prototype. Use the schedule as guidance; critical loads remain protected by reserve logic.",
        )
        fname = "todays_plan.pdf"
        label = "Download Today’s Plan (PDF)"

    st.download_button(
        label,
        data=pdf_bytes,
        file_name=fname,
        mime="application/pdf",
        use_container_width=True,
    )

with st.expander("Full state log table"):
    st.dataframe(df, use_container_width=True, height=420)
