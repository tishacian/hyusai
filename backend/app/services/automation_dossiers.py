"""Business rows over existing dataset versions. A new version does not erase the old one."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def dossier_rows(
    datasets: list[Mapping[str, Any]],
    runs_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One row per dataset version. A run from another system is not its proof."""

    rows: list[dict[str, Any]] = []
    for item in datasets:
        if item.get("status") == "deleted":
            continue
        run_id = item.get("run_id") if isinstance(item.get("run_id"), str) else None
        run = runs_by_id.get(run_id) if run_id else None
        system_id = item.get("system_id")
        same = (
            isinstance(run, Mapping)
            and (not system_id or run.get("system_id") == system_id)
        )
        status = run.get("status") if same else None
        rows.append(
            {
                "name": item.get("name") or "",
                "slug": item.get("slug") or "",
                "version": int(item.get("version") or 1),
                "run_id": run_id if same else None,
                "run_status": status,
                "waiting": status == "hitl_pending",
                "proof": "present" if same else "absent",
            }
        )
    rows.sort(key=lambda row: (row["slug"], row["version"], row["name"]))
    return rows
