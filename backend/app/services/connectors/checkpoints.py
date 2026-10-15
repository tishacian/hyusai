"""A checkpoint advances in the same transaction as the published dataset.

Concurrent readers may finish independently. Only the first commit of an
observed revision wins; a late reader cannot overwrite the new checkpoint.
"""

from datetime import datetime

from app.models.connector_sync import ConnectorSyncState
from app.services import compute_runs
from app.services.connectors.writes import digest


def snapshot(db, run):
    parameters = run.input_json or {}
    if run.operation != "import" or not parameters.get("incremental"):
        return None
    config = parameters["incremental"]
    if not isinstance(config, dict) or set(config) - {
        "watermark_column",
        "key_column",
        "overlap",
        "type",
    }:
        raise compute_runs.ComputeRunError("CONNECTOR_WATERMARK_INVALID")
    compute_runs._lock_workspace(db, run.workspace_id)
    scope = digest(
        {
            "connection_id": run.connection_id,
            "connection_revision": run.connection_revision,
            "parameters": {
                k: v
                for k, v in parameters.items()
                if k not in ("max_rows", "max_bytes", "partitions")
            },
        }
    )
    state = (
        db.query(ConnectorSyncState)
        .filter_by(workspace_id=run.workspace_id, scope_digest=scope)
        .one_or_none()
    )
    if state is None:
        state = ConnectorSyncState(
            workspace_id=run.workspace_id, connection_id=run.connection_id, scope_digest=scope
        )
        db.add(state)
        db.flush()
    value = {
        "state_id": state.id,
        "revision": state.revision,
        "after": state.checkpoint,
        "dataset_id": state.dataset_id,
    }
    run.metrics_json = {**(run.metrics_json or {}), "read_checkpoint": value}
    db.flush()
    return value


def advance(db, run, dataset, output):
    expected = (run.metrics_json or {}).get("read_checkpoint")
    if expected is None:
        return
    state = (
        db.query(ConnectorSyncState)
        .filter_by(id=expected["state_id"], workspace_id=run.workspace_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if (
        state is None
        or state.connection_id != run.connection_id
        or state.revision != expected["revision"]
    ):
        raise compute_runs.ComputeRunError("CONNECTOR_CHECKPOINT_CONFLICT", 409)
    value = output.get("next_checkpoint")
    if value is not None and (
        not isinstance(value, list) or len(value) != 2 or any(v is None for v in value)
    ):
        raise compute_runs.ComputeRunError("CONNECTOR_WATERMARK_INVALID")
    if value is None and expected["after"] is not None:
        raise compute_runs.ComputeRunError("CONNECTOR_WATERMARK_INVALID")
    state.checkpoint, state.dataset_id, state.compute_run_id = value, dataset.id, run.id
    state.revision += 1
    state.updated_at = datetime.utcnow()
    db.flush()  # Caller owns the dataset/checkpoint commit and rollback.


def stage_previous(db, run, directory):
    from app.models.tabular import TabularDataset
    from app.services.tabular_datasets import materialize_dataset

    value = (run.metrics_json or {}).get("read_checkpoint")
    if not value:
        return None
    result = dict(value)
    result["previous_files"] = []
    if value.get("dataset_id"):
        dataset = db.get(TabularDataset, value["dataset_id"])
        if not dataset or dataset.workspace_id != run.workspace_id or dataset.status != "ready":
            raise compute_runs.ComputeRunError("CONNECTOR_CHECKPOINT_DATASET_UNAVAILABLE", 409)
        result["previous_files"] = [
            str(p) for p in materialize_dataset(dataset, directory / "previous", max_bytes=1024**3)
        ]
    return result
