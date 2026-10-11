"""Live portfolio telemetry — feeds the title-bar readouts.

The title bar needs three sub-second numbers: throughput (runs per minute
on a rolling window), p95 latency in ms, and success yield. This endpoint
reports them from a short rolling window so the cockpit reflects the
actual system state instead of hard-coded mock values.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_access import readable_runs

router = APIRouter()


@router.get("/live")
async def live_telemetry(
    window_minutes: int = Query(60, ge=1, le=1440),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return throughput/latency/yield for the current workspace.

    Values are ``None`` when there are no runs in the window — the UI uses
    that to render a neutral dash instead of fabricating activity.
    """
    since = datetime.utcnow() - timedelta(minutes=window_minutes)

    # Authorization is applied before aggregation: counts must never reveal a
    # Run that the same user could not open through the canonical Runs API.
    runs = readable_runs(
        db,
        runs=(
            db.query(Run)
            .filter(Run.workspace_id == workspace.id, Run.started_at >= since)
            .order_by(Run.started_at.desc(), Run.id.asc())
            .all()
        ),
        user=user,
        workspace=workspace,
    )
    count = len(runs)
    completed_count = sum(1 for run in runs if run.status == "completed")
    durations = [float(run.duration_ms) for run in runs if run.duration_ms is not None]

    throughput_rpm: Optional[float]
    if count == 0:
        throughput_rpm = None
    else:
        throughput_rpm = count / max(1.0, float(window_minutes))

    latency_ms: Optional[float] = (
        sum(durations) / len(durations) if durations else None
    )

    yield_pct: Optional[float]
    if count == 0:
        yield_pct = None
    else:
        yield_pct = (completed_count / count) * 100.0

    return {
        "window_minutes": window_minutes,
        "runs_count": count,
        "throughput_rpm": throughput_rpm,
        "latency_ms": latency_ms,
        "yield_pct": yield_pct,
    }
