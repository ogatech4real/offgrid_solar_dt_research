from __future__ import annotations

from typing import List, Tuple

import numpy as np

from offgrid_dt.io.schema import Appliance, TaskInstance


def build_daily_tasks(appliances: List[Appliance], day_steps: int, rng: np.random.Generator) -> Tuple[float, List[TaskInstance]]:
    critical_w = sum(a.power_w for a in appliances if a.category == "critical")
    critical_base_kw = critical_w / 1000.0

    tasks: List[TaskInstance] = []
    for a in appliances:
        if a.category == "critical":
            continue

        if a.category == "deferrable" and a.daily_quota_steps > 0:
            for i in range(a.daily_quota_steps):
                tasks.append(
                    TaskInstance(
                        task_id=f"{a.id}_quota_{i}",
                        appliance_id=a.id,
                        name=a.name,
                        category=a.category,
                        power_w=a.power_w,
                        duration_steps=1,
                        earliest_start_step=max(0, a.earliest_start_step),
                        latest_end_step=min(day_steps, a.latest_end_step),
                        must_complete=True,
                    )
                )
            continue

        tasks.append(
            TaskInstance(
                task_id=f"{a.id}_day",
                appliance_id=a.id,
                name=a.name,
                category=a.category,
                power_w=a.power_w,
                duration_steps=a.duration_steps,
                earliest_start_step=max(0, a.earliest_start_step),
                latest_end_step=min(day_steps, a.latest_end_step),
                must_complete=a.category == "deferrable",
            )
        )

    rng.shuffle(tasks)
    return critical_base_kw, tasks


def requested_kw_for_step(critical_base_kw: float, pending_tasks: List[TaskInstance], step: int) -> Tuple[float, float, List[str]]:
    avail = []
    flex_w = 0.0
    for t in pending_tasks:
        if t.earliest_start_step <= step < t.latest_end_step:
            avail.append(t.task_id)
            flex_w += t.power_w
    return critical_base_kw + flex_w / 1000.0, critical_base_kw, avail
