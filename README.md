# Solar-First Off-Grid PV–Battery Planning Framework

## Overview

This repository contains the implementation of a **solar-first, day-ahead adequacy assessment and explainable planning framework** for off-grid photovoltaic–battery household energy systems.

The framework is designed to support **grid-independent energy users** in making informed daily decisions under variable solar availability. It combines a lightweight digital twin, deterministic demand–solar matching, and an explainable advisory layer to translate system conditions into actionable household guidance.

---

## 📄 Manuscript Status

The research work associated with this repository is currently **under peer review** in an international journal.

* Journal: *Sustainable Energy, Grids and Networks (Elsevier)*
* Status: *Under Review*
* Title: *Solar-First Day-Ahead Adequacy Assessment for Off-Grid PV–Battery Systems*

This repository serves as the **official implementation and reproducibility companion** to the manuscript.

Updates will be provided upon completion of the review process.

---

## 🔍 Core Concept

Unlike conventional energy management systems that focus on optimisation or automated control, this framework:

* Separates **intrinsic solar adequacy** from controller behaviour
* Provides **day-ahead feasibility signals** based on solar availability
* Translates system conditions into **interpretable, user-facing guidance**
* Operates in **advisory mode**, without requiring automation or hardware control

The goal is to improve **energy reliability, utilisation, and decision-making** in decentralised and resource-constrained environments.

---

## ⚙️ Key Features

### 1. Digital Twin Simulation Engine

* Time-stepped PV–battery household model
* SOC dynamics with operational constraints
* Multiple dispatch heuristic strategies

### 2. Deterministic Adequacy Assessment

* Solar Supply Ratio (SSR)
* Daily energy margin
* Surplus and deficit window extraction

### 3. Explainable Advisory Layer

* Rule-based guidance generation
* Traceable reason codes (e.g., LOW_SOC, PV_SURPLUS)
* Appliance-level scheduling recommendations

### 4. Dual Execution Modes

* **Interactive dashboard** (Streamlit)
* **Batch validation pipeline** for reproducible experiments

### 5. Real Data Validation

* Integration with **UK-DALE aggregate residential demand dataset**
* Multi-day validation of adequacy–reliability behaviour

---

## 🧪 Validation Scope

The framework has been evaluated across:

* Multiple geographic solar regimes
* Controlled scenario-based household demand
* Empirical aggregate residential demand (UK-DALE)

The results demonstrate stable coupling between:

* **Solar adequacy (SSR)**
* **Reliability metrics (CLSR, CID)**
* **User-facing advisory outputs**

---

## 🚀 Getting Started

### Requirements

* Python 3.10+
* Recommended: virtual environment

### Installation

```bash
git clone https://github.com/ogatech4real/offgrid_solar_dt.git
cd offgrid_solar_dt
pip install -r requirements.txt
```

---

## 💻 Usage

### 1. Run Interactive Dashboard

```bash
streamlit run app.py
```

### 2. Run Validation Pipeline

```bash
python scripts/validate_ukdale.py
```

Outputs include:

* State logs (CSV)
* Guidance logs (JSONL)
* Planning reports (PDF)

---

## 📊 Outputs

Each simulation produces structured artefacts:

* **State logs**: PV, SOC, load, dispatch actions
* **Guidance logs**: recommendations, risk levels, reason codes
* **Planning reports**: day-ahead summaries and schedules

All outputs are deterministic and reproducible.

---

## 🧭 Positioning

This work is positioned as a **planning and adequacy assessment framework**, not a control optimisation system.

It is particularly suited for:

* Off-grid and weak-grid households
* Energy access applications
* Sustainability-focused system design
* Human-centred energy decision support

---

## 🔗 Live Demo

Interactive dashboard:
https://offgridsolardt.streamlit.app/

---

## 📦 Repository Structure

```
offgrid_solar_dt/
│
├── app.py                  # Streamlit interface
├── scripts/                # Validation and batch processing
├── core/                   # Simulation engine
├── data/                   # Input datasets
├── outputs/                # Generated results
├── reports/                # PDF planning reports
└── README.md
```

---

## 📢 Disclaimer

This repository represents a **research prototype** intended for:

* academic validation
* methodological development
* reproducibility support

It is not yet optimised for production deployment.

---

## 📬 Contact

**Adewale Ogabi**
Email: [hello@adewaleogabi.info](mailto:hello@adewaleogabi.info)

---

## 📌 Citation (to be updated)

A formal citation will be provided once the manuscript completes peer review.

---

## License

This project is released under an open-source license (see LICENSE file).

---
