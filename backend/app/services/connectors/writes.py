"""Approve immutable contracts and dispatch exactly one write identity.

No timeout or broker redelivery can reset sent/unknown to approved. A reconciler
can attest application; humans may abandon an uncertainty, never silently retry.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from uuid import uuid4

from app.models.connector_connection import ConnectorConnection
from app.models.connector_write import ConnectorWrite
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services import compute_runs
from app.services.connectors import connections
from app.services.connectors.profiles import get_profile
from app.services.huggingface.access import is_workspace_admin


class WriteError(RuntimeError):
    def __init__(self, code, status_code=400):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _admin(db, workspace_id, user):
    workspace = db.get(Workspace, workspace_id)
    if (
        not workspace
        or not workspace.is_active
        or workspace.deleted_at
        or not is_workspace_admin(db, user, workspace)
    ):
        raise WriteError("WORKSPACE_PERMISSION_DENIED", 403)


def _dataset(db, workspace_id, dataset_id):
    row = (
        db.query(TabularDataset)
        .filter_by(id=dataset_id, workspace_id=workspace_id, status="ready")
        .one_or_none()
    )
    if row is None or not row.storage_key:
        raise WriteError("CONNECTOR_DATASET_NOT_READY", 404)
    return row


def dataset_contract(row):
    storage = (row.lineage_json or {}).get("storage", {})
    # Legacy metadata-only identities do not authorize byte-sensitive writes.
    # Their producer must backfill the content hash in a worker first.
    if storage.get("format") == "delta":
        if not storage.get("log_sha256") or not storage.get("parts"):
            raise WriteError("CONNECTOR_DATASET_FINGERPRINT_REQUIRED", 409)
    elif not re.fullmatch(r"[a-f0-9]{64}", str(storage.get("sha256", ""))):
        raise WriteError("CONNECTOR_DATASET_FINGERPRINT_REQUIRED", 409)
    return {
        key: getattr(row, key)
        for key in ("id", "version", "storage_key", "row_count", "size_bytes", "schema_json")
    } | {"storage": storage}


def get_write(db, workspace_id, operation_id):
    row = (
        db.query(ConnectorWrite)
        .filter_by(id=operation_id, workspace_id=workspace_id)
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        raise WriteError("CONNECTOR_WRITE_NOT_FOUND", 404)
    return row


def _target(connection, operation, parameters):
    allowed = (
        {"schema", "table", "columns", "keys", "create_table"}
        if operation != "export"
        else {"prefix", "expected_pointer_etag", "format", "mode"}
    )
    if connection.profile_key == "iceberg_rest":
        allowed |= {"expected_snapshot_id", "expected_table_uuid", "expected_schema_id"}
        snapshot_id = parameters.get("expected_snapshot_id")
        schema_id = parameters.get("expected_schema_id")
        from uuid import UUID

        try:
            table_uuid = parameters["expected_table_uuid"]
            if not isinstance(table_uuid, str) or str(UUID(table_uuid)) != table_uuid:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise WriteError("CONNECTOR_TABLE_IDENTITY_REQUIRED") from None
        valid_snapshot = (
            snapshot_id is None
            or (type(snapshot_id) is int and 1 <= snapshot_id <= 2**63 - 1)
            or (
                isinstance(snapshot_id, str)
                and re.fullmatch(r"[1-9][0-9]{0,18}", snapshot_id) is not None
                and int(snapshot_id) <= 2**63 - 1
            )
        )
        if "expected_snapshot_id" not in parameters or not valid_snapshot:
            raise WriteError("CONNECTOR_TABLE_IDENTITY_REQUIRED")
        if type(schema_id) is not int or schema_id < 0:
            raise WriteError("CONNECTOR_TABLE_IDENTITY_REQUIRED")
    if set(parameters) - allowed:
        raise WriteError("CONNECTOR_PARAMETERS_INVALID")
    if operation == "export":
        from app.services.connectors.adapters.object_clients import object_key

        if parameters.get("format", "parquet") not in ("parquet", "delta") or parameters.get(
            "mode", "append"
        ) not in ("append", "overwrite"):
            raise WriteError("CONNECTOR_PARAMETERS_INVALID")
        if parameters.get("format", "parquet") == "parquet" and "mode" in parameters:
            # A Parquet export publishes a complete immutable version. Row
            # append/overwrite are Delta operations, never silently ignored.
            raise WriteError("CONNECTOR_PARAMETERS_INVALID")

        etag = parameters.get("expected_pointer_etag")
        if etag is not None and (
            not isinstance(etag, str) or not 1 <= len(etag) <= 512 or any(ord(c) < 32 for c in etag)
        ):
            raise WriteError("CONNECTOR_PARAMETERS_INVALID")
        prefix = object_key(
            parameters.get("prefix", connection.values.get("prefix", "")),
            connection.values.get("prefix", ""),
        )
        if not prefix:
            raise WriteError("CONNECTOR_EXPORT_PREFIX_REQUIRED")
        return {"prefix": prefix}
    for key in ("schema", "table"):
        value = parameters.get(key)
        if (
            not isinstance(value, str)
            or (
                not value
                and not (key == "schema" and get_profile(connection.profile_key).family == "search")
            )
            or len(value) > 127
            or any(ord(c) < 32 for c in value)
        ):
            raise WriteError("CONNECTOR_IDENTIFIER_INVALID")
    if connection.allowed_schemas and parameters["schema"] not in connection.allowed_schemas:
        raise WriteError("CONNECTOR_SOURCE_FORBIDDEN", 403)
    if (
        connection.allowed_tables
        and parameters["table"] not in connection.allowed_tables
        and parameters["schema"] + "." + parameters["table"] not in connection.allowed_tables
    ):
        raise WriteError("CONNECTOR_SOURCE_FORBIDDEN", 403)
    for key in ("columns", "keys"):
        value = parameters.get(key, [])
        if (
            not isinstance(value, list)
            or len(value) > 2000
            or not all(isinstance(v, str) and v and len(v) <= 127 for v in value)
            or len(value) != len(set(value))
        ):
            raise WriteError("CONNECTOR_COLUMNS_INVALID")
    if operation == "write_upsert" and not parameters.get("keys"):
        raise WriteError("CONNECTOR_UPSERT_KEY_REQUIRED")
    return {key: parameters[key] for key in ("schema", "table")}


def _origin(db, workspace_id, actor_id, origin):
    """Resolve internal Flow provenance from persisted authority, never HTTP input."""
    from app.models.run import Run
    from app.models.system import System
    from app.models.system_version import SystemVersion

    if origin is None:
        return None
    if not isinstance(origin, dict) or set(origin) != {"run_id", "node_id"}:
        raise WriteError("CONNECTOR_ORIGIN_INVALID", 403)
    run = db.get(Run, origin["run_id"], populate_existing=True)
    if not run or run.workspace_id != workspace_id or run.initiated_by_user_id != actor_id:
        raise WriteError("CONNECTOR_ORIGIN_INVALID", 403)
    node_id = origin["node_id"]
    if node_id is not None:
        nodes = (run.execution_contract or {}).get("nodes") or (run.flow_snapshot or {}).get(
            "nodes", []
        )
        identifiers = (
            set(nodes)
            if isinstance(nodes, dict)
            else {n.get("id") for n in nodes if isinstance(n, dict)}
        )
        if not isinstance(node_id, str) or len(node_id) > 160 or node_id not in identifiers:
            raise WriteError("CONNECTOR_ORIGIN_INVALID", 403)
    version_id = run.published_flow_version_id
    if run.system_id:
        system = db.get(System, run.system_id, populate_existing=True)
        version = db.get(SystemVersion, version_id) if version_id else None
        if (
            not system
            or system.workspace_id != workspace_id
            or not version
            or version.system_id != system.id
            or version.workspace_id != workspace_id
            or version.release_kind not in {"publish", "rollback"}
        ):
            raise WriteError("CONNECTOR_ORIGIN_INVALID", 403)
    elif version_id:
        raise WriteError("CONNECTOR_ORIGIN_INVALID", 403)
    return {
        "run_id": run.id,
        "node_id": node_id,
        "system_id": run.system_id,
        "system_version_id": version_id,
    }


def _origin_fields(db, row):
    origin = row.contract.get("origin")
    if origin is None:
        return {}
    current = _origin(
        db,
        row.workspace_id,
        row.created_by,
        {"run_id": origin.get("run_id"), "node_id": origin.get("node_id")},
    )
    if current != origin:
        raise WriteError("CONNECTOR_ORIGIN_INVALID", 403)
    return current


def prepare(
    db,
    *,
    workspace_id,
    user,
    connection_id,
    request_key,
    operation,
    dataset_id,
    parameters,
    origin=None,
):
    _admin(db, workspace_id, user)
    origin = _origin(db, workspace_id, user.id, origin)
    compute_runs._lock_workspace(db, workspace_id)
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", request_key):
        raise WriteError("CONNECTOR_REQUEST_KEY_INVALID")
    connection = connections.get_connection(db, workspace_id, connection_id)
    profile = get_profile(connection.profile_key)
    capability = "export_files" if operation == "export" else operation
    tool_write = operation == "tool_write" and profile.family in ("mcp", "openapi")
    if not tool_write and (
        operation not in compute_runs.WRITES or not getattr(profile.capabilities, capability, False)
    ):
        raise WriteError("CONNECTOR_OPERATION_UNSUPPORTED")
    if connection.access != "read_write":
        raise WriteError("CONNECTOR_READ_ONLY", 403)
    if connection.profile_key == "sap_hana":
        raise WriteError("CONNECTOR_OPERATION_UNSUPPORTED")
    parameters = compute_runs._public_parameters(parameters)
    if tool_write:
        if dataset_id is not None or set(parameters) != {"operation_id", "arguments"}:
            raise WriteError("CONNECTOR_WRITE_CONTRACT_INVALID")
        from app.services.connectors.tool_contracts import prepare_tool_contract

        tool = prepare_tool_contract(
            connection, parameters["operation_id"], parameters["arguments"]
        )
        target = {"tool": parameters["operation_id"]}
        dataset = None
    else:
        if not isinstance(dataset_id, str):
            raise WriteError("CONNECTOR_DATASET_NOT_READY", 404)
        target = _target(connection, operation, parameters)
        dataset = _dataset(db, workspace_id, dataset_id)
    contract = {
        "connection_id": connection.id,
        "connection_revision": connection.revision,
        "profile_digest": profile.digest,
        "operation": operation,
        "parameters": parameters,
        "dataset": dataset_contract(dataset) if dataset is not None else None,
    }
    if tool_write:
        contract["tool"] = tool
    if origin is not None:
        contract["origin"] = origin
    contract_hash = digest(contract)
    existing = (
        db.query(ConnectorWrite)
        .filter_by(workspace_id=workspace_id, request_key=request_key)
        .one_or_none()
    )
    if existing:
        if existing.contract_digest != contract_hash:
            raise WriteError("CONNECTOR_IDEMPOTENCY_CONFLICT", 409)
        return existing
    row = ConnectorWrite(
        id=str(uuid4()),
        workspace_id=workspace_id,
        connection_id=connection_id,
        request_key=request_key,
        connection_revision=connection.revision,
        profile_digest=profile.digest,
        operation=operation,
        target_digest=digest({"connection": connection.id, "target": target}),
        contract=contract,
        contract_digest=contract_hash,
        created_by=user.id,
        expires_at=datetime.utcnow() + timedelta(hours=1),
        state="prepared",
    )
    db.add(row)
    connections.audit(
        db,
        connection,
        "connection.write.prepared",
        user.id,
        operation_id=row.id,
        contract_digest=contract_hash,
    )
    db.flush()
    return row


def validate_current(db, row):
    _origin_fields(db, row)
    connection = connections.get_connection(db, row.workspace_id, row.connection_id)
    if connection.access != "read_write":
        raise WriteError("CONNECTOR_READ_ONLY", 403)
    profile = get_profile(connection.profile_key)
    if connection.revision != row.connection_revision or profile.digest != row.profile_digest:
        raise WriteError("CONNECTOR_CONNECTION_CHANGED", 409)
    if row.operation == "tool_write":
        from app.services.connectors.tool_contracts import prepare_tool_contract

        params = row.contract["parameters"]
        current = prepare_tool_contract(connection, params["operation_id"], params["arguments"])
        dataset = None
        matches = current == row.contract.get("tool") and row.contract.get("dataset") is None
    else:
        dataset = _dataset(db, row.workspace_id, row.contract["dataset"]["id"])
        matches = dataset_contract(dataset) == row.contract["dataset"]
    if not matches or digest(row.contract) != row.contract_digest:
        raise WriteError("CONNECTOR_WRITE_CONTRACT_CHANGED", 409)
    return connection, dataset


def _preview_run(db, row):
    from app.models.compute_run import ComputeRun

    previews = (
        db.query(ComputeRun)
        .filter(
            ComputeRun.workspace_id == row.workspace_id,
            ComputeRun.connection_id == row.connection_id,
            ComputeRun.connection_revision == row.connection_revision,
            ComputeRun.operation == "write_preview",
            ComputeRun.status == "succeeded",
            ComputeRun.input_json["write_operation_id"].as_string() == row.id,
        )
        .order_by(ComputeRun.created_at.desc())
        .all()
    )
    for preview in previews:
        result = preview.output_json or {}
        if (
            result.get("dry_run") is True
            and result.get("applied") is False
            and result.get("operation_id") == row.id
            and result.get("contract_digest") == row.contract_digest
            and result.get("write_operation") == row.operation
        ):
            return preview
    return None


def approve(db, *, workspace_id, user, operation_id, contract_digest):
    _admin(db, workspace_id, user)
    compute_runs._lock_workspace(db, workspace_id)
    row = get_write(db, workspace_id, operation_id)
    if row.state not in ("prepared", "approved") or row.expires_at <= datetime.utcnow():
        raise WriteError("CONNECTOR_APPROVAL_EXPIRED", 409)
    if row.contract_digest != contract_digest:
        raise WriteError("CONNECTOR_APPROVAL_MISMATCH", 409)
    connection, _ = validate_current(db, row)
    if _preview_run(db, row) is None:
        raise WriteError("CONNECTOR_WRITE_PREVIEW_REQUIRED", 409)
    row.state, row.approved_by, row.approved_at = "approved", user.id, datetime.utcnow()
    connections.audit(
        db,
        connection,
        "connection.write.approved",
        user.id,
        operation_id=row.id,
        contract_digest=row.contract_digest,
    )
    db.flush()
    return row


def dispatch(db, *, workspace_id, user, operation_id):
    _admin(db, workspace_id, user)
    compute_runs._lock_workspace(db, workspace_id)
    row = get_write(db, workspace_id, operation_id)
    if row.compute_run_id:
        return row
    if row.state != "approved" or row.expires_at <= datetime.utcnow():
        raise WriteError("CONNECTOR_APPROVAL_REQUIRED", 409)
    connection, _ = validate_current(db, row)
    active = (
        db.query(ConnectorWrite.id)
        .filter(
            ConnectorWrite.workspace_id == workspace_id,
            ConnectorWrite.target_digest == row.target_digest,
            ConnectorWrite.state.in_(("approved", "sent", "unknown")),
            ConnectorWrite.compute_run_id.isnot(None),
            ConnectorWrite.id != row.id,
        )
        .first()
    )
    if active:
        raise WriteError("CONNECTOR_TARGET_BUSY", 409)
    run = compute_runs.create_run(
        db,
        workspace_id=workspace_id,
        user_id=user.id,
        connection_id=connection.id,
        operation=row.operation,
        parameters={"write_operation_id": row.id},
        **_origin_fields(db, row),
    )
    row.compute_run_id = run.id
    connections.audit(
        db,
        connection,
        "connection.write.queued",
        user.id,
        operation_id=row.id,
        compute_run_id=run.id,
    )
    db.flush()
    compute_runs.dispatch_run(db, run)
    return row


def start_execution(db, run):
    """Called before launch. Persists sent before the first possible mutation."""
    compute_runs._lock_workspace(db, run.workspace_id)
    row = (
        db.query(ConnectorWrite)
        .filter_by(compute_run_id=run.id, workspace_id=run.workspace_id)
        .populate_existing()
        .one_or_none()
    )
    if row is None or row.state != "approved" or row.expires_at <= datetime.utcnow():
        raise WriteError("CONNECTOR_APPROVAL_REQUIRED", 409)
    validate_current(db, row)
    row.state = "sent"
    db.commit()
    return row


def settle(db, run, output=None):
    row = (
        db.query(ConnectorWrite).filter_by(compute_run_id=run.id).populate_existing().one_or_none()
    )
    if row is None or row.state in ("applied", "failed", "abandoned"):
        return
    if (
        run.status == "succeeded"
        and output
        and output.get("operation_id") == row.id
        and output.get("applied") is True
        and output.get("contract_digest") == row.contract_digest
    ):
        row.state, row.receipt = "applied", output
        _close_unknown_review(db, row)
    elif row.state == "sent" or run.outcome_unknown:
        row.state = "unknown"
    elif run.status in compute_runs.TERMINAL_STATUSES:
        row.state = "failed"
    else:
        return
    if row.state == "unknown":
        open_unknown_review(db, row, run)
    row.finished_at, row.error_code = datetime.utcnow(), run.error_code
    connection = db.get(ConnectorConnection, row.connection_id)
    connections.audit(
        db,
        connection,
        "connection.write." + row.state,
        run.user_id or "system",
        operation_id=row.id,
    )
    db.flush()


def view(row):
    from sqlalchemy.orm import object_session

    db = object_session(row)
    preview = _preview_run(db, row) if db else None
    return {
        "preview_ready": preview is not None and row.expires_at > datetime.utcnow(),
        "preview_compute_run_id": preview.id if preview else None,
        "review_decision_id": _review_id(row.id) if row.state in ("unknown", "abandoned") else None,
    } | {
        key: getattr(row, key)
        for key in (
            "id",
            "connection_id",
            "operation",
            "contract",
            "contract_digest",
            "state",
            "expires_at",
            "approved_by",
            "approved_at",
            "compute_run_id",
            "receipt",
            "error_code",
        )
    }


def dispatch_reconciliation(db, *, workspace_id, user, operation_id):
    _admin(db, workspace_id, user)
    compute_runs._lock_workspace(db, workspace_id)
    row = get_write(db, workspace_id, operation_id)
    if row.state != "unknown":
        raise WriteError("CONNECTOR_RECONCILIATION_NOT_REQUIRED", 409)
    connection = connections.get_connection(db, workspace_id, row.connection_id)
    if get_profile(connection.profile_key).capabilities.write_outcome_check == "none":
        raise WriteError("CONNECTOR_WRITE_OUTCOME_UNKNOWN", 409)
    run = compute_runs.create_run(
        db,
        workspace_id=workspace_id,
        user_id=user.id,
        connection_id=connection.id,
        operation="reconcile_write",
        parameters={"write_operation_id": row.id},
        **_origin_fields(db, row),
    )
    connections.audit(
        db,
        connection,
        "connection.write.reconcile_requested",
        user.id,
        operation_id=row.id,
        compute_run_id=run.id,
    )
    db.flush()
    compute_runs.dispatch_run(db, run)
    return compute_runs.serialize_run(run)


def settle_reconciliation(db, run, output):
    operation_id = (run.input_json or {}).get("write_operation_id")
    row = get_write(db, run.workspace_id, operation_id)
    if row.connection_id != run.connection_id:
        raise WriteError("CONNECTOR_WRITE_NOT_FOUND", 404)
    if row.state == "applied":
        return
    if row.state != "unknown" or run.status != "succeeded":
        return
    if not output or output.get("operation_id") != row.id or output.get("applied") is not True:
        return
    # Adapter verifies its native receipt/manifest against the immutable
    # contract. A negative lookup never authorizes a retry of the original run.
    if output.get("contract_digest") != row.contract_digest:
        raise WriteError("CONNECTOR_RECEIPT_MISMATCH", 409)
    row.state, row.receipt, row.finished_at = "applied", output, datetime.utcnow()
    row.error_code = None
    _close_unknown_review(db, row)
    connection = db.get(ConnectorConnection, row.connection_id)
    connections.audit(
        db,
        connection,
        "connection.write.reconciled",
        run.user_id or "system",
        operation_id=row.id,
        compute_run_id=run.id,
    )
    db.flush()


def dispatch_preview(db, *, workspace_id, user, operation_id):
    _admin(db, workspace_id, user)
    row = get_write(db, workspace_id, operation_id)
    if row.state not in ("prepared", "approved") or row.expires_at <= datetime.utcnow():
        raise WriteError("CONNECTOR_APPROVAL_EXPIRED", 409)
    connection, _ = validate_current(db, row)
    run = compute_runs.create_run(
        db,
        workspace_id=workspace_id,
        user_id=user.id,
        connection_id=connection.id,
        operation="write_preview",
        parameters={"write_operation_id": row.id},
        **_origin_fields(db, row),
    )
    connections.audit(
        db,
        connection,
        "connection.write.preview_requested",
        user.id,
        operation_id=row.id,
        compute_run_id=run.id,
    )
    db.flush()
    compute_runs.dispatch_run(db, run)
    return compute_runs.serialize_run(run)


def _review_id(operation_id):
    from uuid import NAMESPACE_URL, uuid5

    return str(uuid5(NAMESPACE_URL, "agentium:connector-write-review:" + operation_id))


def _close_unknown_review(db, row):
    from app.models.decision import Decision

    review = db.get(Decision, _review_id(row.id))
    if review and review.status == "proposed":
        review.status = "applied"
        review.applied_at = datetime.utcnow()
        review.applied_by = "connector_reconciliation"


def open_unknown_review(db, row, run):
    """A durable inbox item, assigned to the contract owner or approving admin."""
    from app.models.decision import Decision
    from app.models.service_contract import ServiceContract

    identifier = _review_id(row.id)
    if db.get(Decision, identifier):
        return
    contract = (
        db.query(ServiceContract)
        .filter(
            ServiceContract.workspace_id == row.workspace_id,
            ServiceContract.system_id == run.system_id,
            ServiceContract.published_at.isnot(None),
        )
        .order_by(ServiceContract.version.desc())
        .first()
        if run.system_id
        else None
    )
    owner = contract.owner_user_id if contract else row.approved_by or row.created_by
    db.add(
        Decision(
            id=identifier,
            workspace_id=row.workspace_id,
            scope="system" if run.system_id else "run",
            target_id=run.system_id or row.compute_run_id,
            kind="connector_write_unknown",
            status="proposed",
            title="Connector write outcome needs review",
            rationale={
                "code": "CONNECTOR_WRITE_OUTCOME_UNKNOWN",
                "operation_id": row.id,
                "connection_id": row.connection_id,
                "contract_digest": row.contract_digest,
                "owner_user_id": owner,
                "automatic_retry": False,
                "target_blocked": True,
            },
        )
    )
    db.flush()


def abandon_unknown(
    db,
    *,
    workspace_id,
    user,
    operation_id,
    contract_digest,
    reason,
    acknowledge_possible_application,
):
    _admin(db, workspace_id, user)
    compute_runs._lock_workspace(db, workspace_id)
    row = get_write(db, workspace_id, operation_id)
    if row.state != "unknown" or contract_digest != row.contract_digest:
        raise WriteError("CONNECTOR_APPROVAL_MISMATCH", 409)
    if (
        acknowledge_possible_application is not True
        or not isinstance(reason, str)
        or not 20 <= len(reason.strip()) <= 2000
    ):
        raise WriteError("CONNECTOR_UNKNOWN_REVIEW_REQUIRED")
    from app.models.decision import Decision

    review = db.get(Decision, _review_id(row.id))
    row.state, row.finished_at = "abandoned", datetime.utcnow()
    # This records a human choice to stop reconciliation. It is never a receipt
    # of absence, a retry permission for this operation, or a successful write.
    row.receipt = {
        "operation_id": row.id,
        "contract_digest": row.contract_digest,
        "applied": None,
        "resolution": "abandoned_by_operator",
        "reason": reason.strip(),
        "actor": user.id,
    }
    if review:
        review.status = "accepted"
        review.approved_by = user.id
        review.approved_at = datetime.utcnow()
        review.notes = reason.strip()
    connection = db.get(ConnectorConnection, row.connection_id)
    connections.audit(
        db,
        connection,
        "connection.write.abandoned",
        user.id,
        operation_id=row.id,
        contract_digest=row.contract_digest,
        reason=reason.strip(),
    )
    db.flush()
    return row
