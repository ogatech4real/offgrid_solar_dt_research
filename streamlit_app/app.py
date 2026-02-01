import json
import sys
from pathlib import Path

# Ensure src/ is importable when running Streamlit without installing the package
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pandas as pd
import plotly.express as px
import streamlit as st

from offgrid_dt.control.controllers import get_controllers
from offgrid_dt.dt.simulator import simulate
from offgrid_dt.io.schema import Appliance, SystemConfig


st.set_page_config(page_title="Off-grid Solar DT", layout="wide")

st.title("Solar-first Off-grid Household Energy Assistant (Digital Twin)")

with st.sidebar:
    st.header("System configuration")
    location_name = st.text_input("Location name", value="Demo")
    lat = st.number_input("Latitude", value=28.6139, format="%.6f")
    lon = st.number_input("Longitude", value=77.2090, format="%.6f")
    pv_kw = st.number_input("PV capacity (kW)", min_value=0.5, value=3.5, step=0.1)
    bat_kwh = st.number_input("Battery capacity (kWh)", min_value=1.0, value=7.5, step=0.5)
    inv_kw = st.number_input("Inverter max (kW)", min_value=0.5, value=2.5, step=0.1)

    soc_init = st.slider("Initial SOC", 0.0, 1.0, 0.6, 0.01)
    soc_min = st.slider("Minimum reserve SOC", 0.0, 1.0, 0.25, 0.01)
    soc_max = st.slider("Maximum SOC", 0.0, 1.0, 0.95, 0.01)

    days = st.selectbox("Simulation days", [1, 3, 7, 14], index=2)

    controllers = get_controllers()
    controller_names = [c.name for c in controllers]
    controller_name = st.selectbox("Controller", controller_names, index=controller_names.index("forecast_heuristic"))

    st.header("API keys (via secrets)")
    openweather_key = st.secrets.get("openweather_api_key", None)
    openweather_base = st.secrets.get("openweather_base_url", "https://api.openweathermap.org")
    openai_key = st.secrets.get("openai_api_key", None)
    openai_model = st.secrets.get("openai_model", "gpt-4.1-mini")

cfg = SystemConfig(
    location_name=location_name,
    latitude=float(lat),
    longitude=float(lon),
    pv_capacity_kw=float(pv_kw),
    battery_capacity_kwh=float(bat_kwh),
    inverter_max_kw=float(inv_kw),
    soc_init=float(soc_init),
    soc_min=float(soc_min),
    soc_max=float(soc_max),
)

st.subheader("Appliance library")

def _default_appliances():
    return [
        Appliance(id="lighting", name="Lighting", category="critical", power_w=120),
        Appliance(id="fan", name="Fans", category="critical", power_w=160),
        Appliance(id="fridge", name="Refrigerator", category="critical", power_w=150),
        Appliance(id="phone", name="Phone charging", category="critical", power_w=20),
        Appliance(id="pump", name="Water pumping", category="flexible", power_w=750, duration_steps=4, earliest_start_step=20, latest_end_step=80),
        Appliance(id="wash", name="Washing machine", category="flexible", power_w=500, duration_steps=4, earliest_start_step=20, latest_end_step=80),
        Appliance(id="iron", name="Ironing", category="deferrable", power_w=1000, duration_steps=2, earliest_start_step=24, latest_end_step=84),
        Appliance(id="laundry_quota", name="Small deferrable quota", category="deferrable", power_w=200, daily_quota_steps=6, earliest_start_step=16, latest_end_step=88),
    ]

if "appliances" not in st.session_state:
    st.session_state.appliances = _default_appliances()

# Render editable table
ap_df = pd.DataFrame([a.model_dump() for a in st.session_state.appliances])
edited = st.data_editor(
    ap_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "category": st.column_config.SelectboxColumn("category", options=["critical", "flexible", "deferrable"]),
    },
)

# Update appliances from table
try:
    st.session_state.appliances = [Appliance(**row) for row in edited.to_dict(orient="records") if row.get("id")]
except Exception as e:
    st.warning("Appliance table contains invalid rows. Fix values to continue.")

colA, colB = st.columns([1, 2])

with colA:
    run = st.button("Run simulation", type="primary")

if run:
    ctrl = next(c for c in controllers if c.name == controller_name)
    out_dir = Path("logs") / f"run_{controller_name}"
    paths = simulate(
        cfg=cfg,
        appliances=st.session_state.appliances,
        controller=ctrl,
        days=int(days),
        openweather_api_key=openweather_key,
        openweather_base_url=openweather_base,
        openai_api_key=openai_key,
        openai_model=openai_model,
        out_dir=out_dir,
    )
    st.session_state.last_run = paths

with colB:
    st.markdown("""**How to use this dashboard**
    - Configure system capacity and reserve
    - Edit appliances (watts, durations, windows, category)
    - Run a controller and compare outcomes
    - Export logs for paper figures and user study stimuli
    """)

paths = st.session_state.get("last_run")
if paths:
    st.success(f"Logs written: {paths}")
    state_csv = paths["state_csv"]
    df = pd.read_csv(state_csv)

    st.subheader("Operational overview")
    c1, c2, c3, c4 = st.columns(4)
    kpi_cols = [c for c in df.columns if c.startswith("kpi_")]
    last = df.iloc[-1]
    if "kpi_CLSR" in df.columns:
        c1.metric("CLSR", f"{last['kpi_CLSR']:.3f}")
    if "kpi_Blackout_minutes" in df.columns:
        c2.metric("Blackout (min)", f"{int(last['kpi_Blackout_minutes'])}")
    if "kpi_SAR" in df.columns:
        c3.metric("SAR", f"{last['kpi_SAR']:.3f}")
    if "kpi_Solar_utilization" in df.columns:
        c4.metric("Solar utilization", f"{100*last['kpi_Solar_utilization']:.1f}%")

    fig1 = px.line(df, x="timestamp", y=["pv_now_kw", "load_served_kw"], title="PV output vs served load")
    st.plotly_chart(fig1, use_container_width=True)

    fig2 = px.line(df, x="timestamp", y=["soc_now"], title="Battery SOC")
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Recommendations (latest)")
    st.write(f"**{last['headline']}**")
    st.write(last["explanation"])
    st.caption(f"Risk: {last['risk_level']} | Reasons: {last['reason_codes']}")

    with st.expander("View full log table"):
        st.dataframe(df, use_container_width=True)

    st.download_button(
        "Download state CSV",
        data=Path(state_csv).read_bytes(),
        file_name=Path(state_csv).name,
        mime="text/csv",
    )
