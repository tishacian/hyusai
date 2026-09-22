"""A frozen chart over dossier rows. A point without proof does not invent a Run."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class AutomationChartRefusal(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def freeze_chart(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    points = [
        {
            "id": f"{row.get('slug')}:{row.get('version')}",
            "name": row.get("name") or "",
            "slug": row.get("slug") or "",
            "version": int(row.get("version") or 1),
            "proof": row.get("proof") or "absent",
            "waiting": row.get("waiting") is True,
            "run_id": row.get("run_id") if row.get("proof") == "present" else None,
            "run_status": row.get("run_status") if row.get("proof") == "present" else None,
        }
        for row in rows
    ]
    digest = hashlib.sha256(json.dumps(points, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"hash": digest, "points": points}


def open_point(chart: Mapping[str, Any], point_id: str) -> dict[str, Any]:
    points = chart.get("points") if isinstance(chart.get("points"), list) else []
    point = next((item for item in points if isinstance(item, Mapping) and item.get("id") == point_id), None)
    if point is None:
        raise AutomationChartRefusal("point_unknown", "This point is not on the frozen chart")
    run = None
    if point.get("proof") == "present" and point.get("run_id"):
        run = {"id": point["run_id"], "status": point.get("run_status")}
    return {
        "hash": chart.get("hash"),
        "point_id": point["id"],
        "dossier": {
            "name": point.get("name"),
            "slug": point.get("slug"),
            "version": point.get("version"),
            "proof": point.get("proof"),
            "waiting": point.get("waiting") is True,
        },
        "run": run,
    }
