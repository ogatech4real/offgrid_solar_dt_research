# Off-grid Solar-First DT + Streamlit Advisory UI

This project implements a modular digital twin (PV + battery + household loads) and a Streamlit dashboard that replays scenarios from log files and shows actionable, explainable recommendations.

## Quick start
1) Create a virtual env and install requirements.
2) Copy `.streamlit/secrets.template.toml` to `.streamlit/secrets.toml` and add keys (optional).
3) Run the Streamlit app:
   
   `streamlit run streamlit_app/app.py`

## Security model
Secrets are loaded from Streamlit secrets. They are never committed to the repo.
The simulation engine is isolated under `src/offgrid_dt/` and the Streamlit UI only consumes the engine via imports and log files.
