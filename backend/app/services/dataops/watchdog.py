"""Retire lost worker reservations so they cannot stay in progress forever."""

from datetime import datetime, timedelta

from app.models.recipe import RecipeExecution
from app.models.tabular import TabularDataset
from app.services.recipe_executions import finalize_execution


def sweep(db, *, now=None, workspace_id=None, limit=100):
    now = now or datetime.utcnow()
    query = db.query(RecipeExecution).filter(
        RecipeExecution.status.in_(["queued", "running"]),
        RecipeExecution.input_json["kind"].as_string().in_(["data_prep", "ml_stream_score"]),
    )
    if workspace_id is not None:
        query = query.filter_by(workspace_id=workspace_id)
    changed = []
    for row in (
        query.order_by(RecipeExecution.created_at).with_for_update(skip_locked=True).limit(limit)
    ):
        spec = row.input_json or {}
        if spec.get("kind") not in {"data_prep", "ml_stream_score"}:
            continue
        start = row.started_at or row.created_at
        # Queue starvation and a dead worker are both visible failures; an
        # operator can retry with a new execution. A stale message sees the
        # terminal row before loading data or publishing any output.
        if now < start + timedelta(seconds=float(row.timeout_s or 900) + 60):
            continue
        row.cancel_requested = True
        finalize_execution(row, status="failed", error="DATAOPS_WORKER_LOST")
        output_ids = list(spec.get("outputs", {}).values())
        if spec.get("output_id"):
            output_ids.append(spec["output_id"])
        for identifier in output_ids:
            output = db.get(TabularDataset, identifier)
            if output and output.workspace_id == row.workspace_id and output.status == "ingesting":
                output.status = "failed"
                output.error = "DATAOPS_WORKER_LOST"
        changed.append(row.id)
    db.flush()
    return changed
