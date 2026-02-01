from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd

from offgrid_dt.io.schema import StepRecord


@dataclass
class RunLogger:
    out_dir: Path

    def __post_init__(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._records: List[StepRecord] = []

    def append(self, rec: StepRecord) -> None:
        self._records.append(rec)

    def flush(self, prefix: str) -> dict:
        """Write CSV state log and JSONL guidance log. Returns file paths."""
        if not self._records:
            return {}

        state_path = self.out_dir / f"{prefix}_state.csv"
        guidance_path = self.out_dir / f"{prefix}_guidance.jsonl"

        rows = []
        with guidance_path.open("w", encoding="utf-8") as f:
            for r in self._records:
                rows.append(
                    {
                        "timestamp": r.timestamp.isoformat(),
                        "step_index": r.step_index,
                        "pv_now_kw": r.pv_now_kw,
                        "soc_now": r.soc_now,
                        "load_requested_kw": r.load_requested_kw,
                        "load_served_kw": r.load_served_kw,
                        "crit_requested_kw": r.crit_requested_kw,
                        "crit_served_kw": r.crit_served_kw,
                        "curtailed_solar_kw": r.curtailed_solar_kw,
                        "charge_kw": r.decision.charge_kw,
                        "discharge_kw": r.decision.discharge_kw,
                        "served_task_ids": ";".join(r.decision.served_task_ids),
                        "deferred_task_ids": ";".join(r.decision.deferred_task_ids),
                        "risk_level": r.guidance.risk_level,
                        "headline": r.guidance.headline,
                        "explanation": r.guidance.explanation,
                        "reason_codes": ";".join(r.guidance.reason_codes),
                        **{f"kpi_{k}": v for k, v in r.kpis_running.items()},
                    }
                )
                line = {"timestamp": r.timestamp.isoformat(), **r.guidance.model_dump()}
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        pd.DataFrame(rows).to_csv(state_path, index=False)
        return {"state_csv": str(state_path), "guidance_jsonl": str(guidance_path)}
