"""Connector runner: only registry IDs cross the broker boundary."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import UTC
from pathlib import Path

from app.core.config import settings
from app.models.compute_run import ComputeRun
from app.services import compute_runs as registry
from app.workers.celery_connectors import celery_connectors


def _grants_snapshot(db, workspace_id):
    from app.services.connectors.network_exceptions import load_grants

    return sorted(
        (
            {
                "cidr": grant.cidr,
                "ports": list(grant.ports),
                "expires_at": grant.expires_at.isoformat(),
            }
            for grant in load_grants(db, workspace_id)
        ),
        key=lambda grant: (grant["cidr"], grant["ports"], grant["expires_at"]),
    )


def _delegated_actor_id(db, row):
    """A scheduler uses an approved personal grant, never an invented user id."""
    from app.models.connector_connection import (
        ConnectorConnection,
        ConnectorDelegation,
        ConnectorGrant,
    )
    from app.models.run import Run
    from app.models.system import System

    run = db.get(Run, row.run_id, populate_existing=True) if row.run_id else None
    system = db.get(System, row.system_id, populate_existing=True) if row.system_id else None
    delegation = (
        db.get(ConnectorDelegation, row.delegation_id, populate_existing=True)
        if row.delegation_id
        else None
    )
    connection = db.get(ConnectorConnection, row.connection_id, populate_existing=True)
    now = registry.utcnow()
    if (
        row.operation not in {"catalog", "table", "preview", "import"}
        or not run
        or not system
        or not delegation
        or not connection
        or not row.system_version_id
        or run.workspace_id != row.workspace_id
        or run.system_id != row.system_id
        or run.initiated_by_user_id is not None
        or run.published_flow_version_id != row.system_version_id
        or run.status in {"cancelled", "failed"}
        or system.workspace_id != row.workspace_id
        or system.published_flow_version_id != row.system_version_id
        or delegation.workspace_id != row.workspace_id
        or delegation.system_id != row.system_id
        or delegation.system_version_id != row.system_version_id
        or delegation.approved_at is None
        or delegation.revoked_at is not None
        or delegation.expires_at <= now
        or connection.workspace_id != row.workspace_id
        or connection.disabled_at is not None
        or (connection.values or {}).get("auth_mode") != "oauth_user"
    ):
        raise registry.ComputeRunError("CONNECTOR_GRANT_REQUIRED", 403)
    grant = db.get(ConnectorGrant, delegation.grant_id, populate_existing=True)
    if (
        not grant
        or grant.workspace_id != row.workspace_id
        or grant.connection_id != row.connection_id
        or grant.revoked_at is not None
        or (grant.expires_at is not None and grant.expires_at <= now)
    ):
        raise registry.ComputeRunError("CONNECTOR_GRANT_REQUIRED", 403)
    return grant.owner_user_id


def _check_actor(db, row):
    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember
    from app.services.huggingface.access import can_import_dataset, is_workspace_admin

    workspace = db.get(Workspace, row.workspace_id, populate_existing=True)
    actor_id = row.user_id or _delegated_actor_id(db, row)
    user = db.get(User, actor_id, populate_existing=True)
    if (
        not user
        or not user.is_active
        or not workspace
        or not workspace.is_active
        or workspace.deleted_at
    ):
        raise registry.ComputeRunError("CONNECTOR_ACTOR_FORBIDDEN", 403)
    admin = is_workspace_admin(db, user, workspace)
    member = (
        db.query(WorkspaceMember.id)
        .filter_by(workspace_id=row.workspace_id, user_id=user.id)
        .first()
    )
    if (not row.user_id and not member) or (
        not admin
        and (
            not member
            or row.operation in {"test", "reconcile_write", "write_preview"}
            or row.operation in registry.WRITES
            or (row.operation == "import" and not can_import_dataset(db, user, workspace))
        )
    ):
        raise registry.ComputeRunError("CONNECTOR_ACTOR_FORBIDDEN", 403)


def _authorization_snapshot(db, row):
    from app.services.connectors.connections import authorization_snapshot, get_connection

    _check_actor(db, row)
    connection = get_connection(db, row.workspace_id, row.connection_id)
    snapshot = authorization_snapshot(
        db,
        connection,
        user_id=row.user_id,
        system_id=row.system_id,
        system_version_id=row.system_version_id,
        delegation_id=row.delegation_id,
        run_id=row.run_id,
    )
    if connection.revision != row.connection_revision:
        raise registry.ComputeRunError("CONNECTOR_CONNECTION_CHANGED", 409)
    return snapshot


def _load_spec(db, row):
    from app.services.connectors.connections import get_connection, resolve_credentials
    from app.services.connectors.profiles import get_profile

    _check_actor(db, row)
    connection = get_connection(db, row.workspace_id, row.connection_id)
    if connection.disabled_at is not None or connection.revision != row.connection_revision:
        raise registry.ComputeRunError("CONNECTOR_CONNECTION_CHANGED", 409)
    profile = get_profile(connection.profile_key)
    if str(profile.version) != str(connection.profile_version):
        raise registry.ComputeRunError("CONNECTOR_PROFILE_CHANGED", 409)
    capability = {"import": "read", "preview": "read", "export": "export_files"}.get(
        row.operation, row.operation
    )
    if (
        row.operation
        not in {"test", "catalog", "table", "reconcile_write", "tool_write", "write_preview"}
        and getattr(profile.capabilities, capability, False) is not True
    ):
        raise registry.ComputeRunError("CONNECTOR_OPERATION_UNSUPPORTED")
    if row.operation in registry.WRITES and connection.access != "read_write":
        raise registry.ComputeRunError("CONNECTOR_READ_ONLY", 403)
    from app.services.connectors.checkpoints import snapshot

    snapshot(db, row)
    credentials = resolve_credentials(
        db,
        connection,
        user_id=row.user_id,
        system_id=row.system_id,
        system_version_id=row.system_version_id,
        delegation_id=row.delegation_id,
        run_id=row.run_id,
    )
    return {
        "parent_pid": os.getpid(),
        "runner_image_sha256": settings.connector_runner_image_sha256,
        "profile_key": profile.key,
        "family": profile.family,
        "dialect": profile.dialect,
        "operation": row.operation,
        "config": profile.validate_values(connection.values, connection.secret_refs),
        "credentials": {
            key: value.reveal() for key, value in credentials.items() if key != "refresh_token"
        },
        "parameters": row.input_json,
        "deadline_at": row.deadline_at.replace(tzinfo=UTC).isoformat(),
        "access": {
            "mode": connection.access,
            "allowed_schemas": connection.allowed_schemas,
            "allowed_tables": connection.allowed_tables,
        },
        "limits": profile.limits.model_dump(),
        "network_policy": {
            # The child deliberately has no application env. Carry the enforced
            # policy explicitly instead of inheriting a legacy report window.
            "connector_network_policy_mode": "enforce",
            "hana_network_policy_mode": "enforce",
            "hana_allowed_hosts": settings.hana_allowed_hosts,
            "hana_allowed_cidrs": settings.hana_allowed_cidrs,
        },
        "network_grants": _grants_snapshot(db, row.workspace_id),
    }


def _publish_stream(db, row, output, scratch):
    """Publish only the complete, verified file; its pointer remains fenced by DB."""
    from app.services.tabular_datasets import dataset_reference, register_parquet_file

    if output.get("artifact") != "data.parquet":
        raise registry.ComputeRunError("CONNECTOR_ARTIFACT_INVALID")
    source = scratch / "data.parquet"
    if source.is_symlink() or not source.is_file() or source.stat().st_size != output.get("bytes"):
        raise registry.ComputeRunError("CONNECTOR_ARTIFACT_INVALID")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    if digest.hexdigest() != output.get("sha256"):
        raise registry.ComputeRunError("CONNECTOR_ARTIFACT_INVALID")
    dataset = register_parquet_file(
        db,
        workspace_id=row.workspace_id,
        name=f"connector-{row.connection_id}-{row.id}",
        path=source,
        source="connector",
        produced_by="connector_import",
        parent_ids=[previous]
        if (previous := (row.metrics_json or {}).get("read_checkpoint", {}).get("dataset_id"))
        else None,
        run_id=row.run_id,
        node_id=row.node_id,
        lineage={
            "connection_id": row.connection_id,
            "connection_revision": row.connection_revision,
            "profile": row.profile,
            "compute_run_id": row.id,
            "consistency": output.get("consistency", "none"),
            "source_sha256": output["sha256"],
            "source": "connector_read",
            "source_mode": output.get("source", "real"),
            "placement": "local",
            "source_objects": output.get("source_objects"),
            "source_fingerprint": output.get("source_fingerprint"),
        },
    )
    from app.services.connectors.checkpoints import advance

    advance(db, row, dataset, output)
    return {
        **{k: v for k, v in output.items() if k != "artifact"},
        "dataset": dataset_reference(dataset),
    }


def _publish_authorized(db, row, output, scratch, authorization):
    if _authorization_snapshot(db, row) != authorization:
        raise registry.ComputeRunError("CONNECTOR_AUTHORIZATION_CHANGED", 403)
    published = _publish_stream(db, row, output, scratch)
    # Upload/profiling can take time. Recheck before the transaction publishes
    # the pointer; a revoked token must never make a new dataset visible.
    if _authorization_snapshot(db, row) != authorization:
        raise registry.ComputeRunError("CONNECTOR_AUTHORIZATION_CHANGED", 403)
    return published


def _stage_write(db, row, scratch):
    from app.models.connector_write import ConnectorWrite
    from app.services.connectors import writes
    from app.services.dataops.storage import file_digest
    from app.services.tabular_datasets import materialize_dataset

    intent = (
        writes.get_write(db, row.workspace_id, (row.input_json or {}).get("write_operation_id"))
        if row.operation == "write_preview"
        else db.query(ConnectorWrite)
        .filter_by(compute_run_id=row.id, workspace_id=row.workspace_id)
        .one_or_none()
    )
    if intent is not None and (
        intent.connection_id != row.connection_id
        or (row.operation == "write_preview" and intent.state not in {"prepared", "approved"})
    ):
        raise registry.ComputeRunError("CONNECTOR_WRITE_CONTRACT_CHANGED")
    if intent is None:
        raise registry.ComputeRunError("CONNECTOR_APPROVAL_REQUIRED")
    _, dataset = writes.validate_current(db, intent)
    if intent.operation == "tool_write":
        tool = intent.contract.get("tool")
        if not isinstance(tool, dict) or not tool.get("arguments_digest"):
            raise registry.ComputeRunError("CONNECTOR_WRITE_CONTRACT_CHANGED")
        execution = {
            "operation_id": intent.id,
            "contract_digest": intent.contract_digest,
            "input_sha256": tool["arguments_digest"],
            "tool_contract": tool,
            "write_operation": "tool_write",
        }
        row.metrics_json = {
            **(row.metrics_json or {}),
            "write_input_sha256": execution["input_sha256"],
        }
        db.commit()
        return dict(intent.contract["parameters"]), execution
    directory = scratch / "input"
    files = materialize_dataset(dataset, directory, max_bytes=1024**3)
    expected = intent.contract["dataset"]["storage"]
    hashes = [file_digest(path) for path in files]
    if expected.get("format") == "delta":
        actual = {
            path.relative_to(directory).as_posix(): digest
            for path, digest in zip(files, hashes, strict=True)
        }
        if actual != expected.get("parts"):
            raise registry.ComputeRunError("CONNECTOR_WRITE_CONTRACT_CHANGED")
    elif len(hashes) != 1 or hashes[0] != expected.get("sha256"):
        raise registry.ComputeRunError("CONNECTOR_WRITE_CONTRACT_CHANGED")
    payload = {
        "operation_id": intent.id,
        "input_files": [str(path) for path in files],
        "input_sha256": hashlib.sha256(
            json.dumps(hashes, separators=(",", ":")).encode()
        ).hexdigest(),
        "contract_digest": intent.contract_digest,
        "dataset_id": dataset.id,
        "dataset_version": dataset.version,
        "write_operation": intent.operation,
    }
    row.metrics_json = {**(row.metrics_json or {}), "write_input_sha256": payload["input_sha256"]}
    db.commit()
    return dict(intent.contract["parameters"]), payload


def _stage_reconciliation(db, row):
    from app.services.connectors import writes

    intent = writes.get_write(
        db, row.workspace_id, (row.input_json or {}).get("write_operation_id")
    )
    if intent.connection_id != row.connection_id or intent.state not in {
        "sent",
        "unknown",
        "applied",
    }:
        raise registry.ComputeRunError("CONNECTOR_RECONCILIATION_INVALID")
    writes.validate_current(db, intent)
    original = db.get(ComputeRun, intent.compute_run_id)
    digest = (original.metrics_json or {}).get("write_input_sha256") if original else None
    if not digest:
        raise registry.ComputeRunError("CONNECTOR_WRITE_CONTRACT_CHANGED")
    return dict(intent.contract["parameters"]), {
        "operation_id": intent.id,
        "contract_digest": intent.contract_digest,
        "input_sha256": digest,
    }


def execute_run(compute_run_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.recipe_executions import supervise_harness

    with SessionLocal() as db:
        token = registry.claim_run(db, compute_run_id)
        if token is None:
            row = db.get(ComputeRun, compute_run_id)
            return {"id": compute_run_id, "status": row.status if row else "missing"}
        try:
            row = db.get(ComputeRun, compute_run_id)
            if not settings.connector_framework_enabled:
                raise registry.ComputeRunError("CONNECTOR_FRAMEWORK_DISABLED", 404)
            authorization = _authorization_snapshot(db, row)
            spec = _load_spec(db, row)
            if authorization != _authorization_snapshot(db, row):
                raise registry.ComputeRunError("CONNECTOR_AUTHORIZATION_CHANGED", 403)
            # Authorizations and grants were refreshed after claim/queue delay.
            if not registry.advance_run(db, row.id, token, "launching"):
                raise registry.ComputeRunError("CONNECTOR_CANCELLED")
            scratch_root = Path(getattr(settings, "connector_scratch_dir", "/tmp"))
            scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            # JSONL, typed Parquet and a verified staging copy can coexist.
            if shutil.disk_usage(scratch_root).free < 4 * 1024**3:
                raise registry.ComputeRunError("CONNECTOR_SCRATCH_SPACE_INSUFFICIENT")
            with tempfile.TemporaryDirectory(
                prefix=f"agentium-connector-run-{row.id}-", dir=scratch_root
            ) as directory:
                scratch = Path(directory)
                os.chmod(scratch, 0o700)
                from app.services.connectors.checkpoints import stage_previous

                checkpoint = stage_previous(db, row, scratch)
                if checkpoint is not None:
                    spec.setdefault("execution", {})["read_checkpoint"] = checkpoint
                if row.operation == "reconcile_write":
                    spec["parameters"], spec["execution"] = _stage_reconciliation(db, row)
                if row.operation in registry.WRITES or row.operation == "write_preview":
                    spec["parameters"], spec["execution"] = _stage_write(db, row, scratch)
                # Staging can download a large previous dataset or write input.
                # Queue-time credentials/grants may have been revoked while it
                # ran: check again before persisting sent or starting a child.
                if authorization != _authorization_snapshot(db, row):
                    raise registry.ComputeRunError("CONNECTOR_AUTHORIZATION_CHANGED", 403)
                if _grants_snapshot(db, row.workspace_id) != spec["network_grants"]:
                    raise registry.ComputeRunError("CONNECTOR_NETWORK_GRANT_CHANGED", 403)
                if not registry.heartbeat(db, row.id, token):
                    raise registry.ComputeRunError("CONNECTOR_LEASE_LOST")
                if row.operation in registry.WRITES:
                    # Staging and content verification finish before persisting
                    # sent. Only this private envelope contains local paths.
                    from app.services.connectors.writes import start_execution

                    start_execution(db, row)
                spec_path, result_path = scratch / "spec.json", scratch / "result.json"
                descriptor = os.open(spec_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as handle:
                    json.dump(spec, handle, allow_nan=False)
                grant_snapshot = spec["network_grants"]
                # Credentials never enter env, command arguments, logs or DB.
                spec.clear()
                if not registry.advance_run(
                    db, row.id, token, "running", write_started=row.operation in registry.WRITES
                ):
                    raise registry.ComputeRunError("CONNECTOR_CANCELLED")
                stop_reason = None

                def should_stop():
                    nonlocal stop_reason
                    try:
                        if _authorization_snapshot(db, row) != authorization:
                            stop_reason = "CONNECTOR_AUTHORIZATION_CHANGED"
                            return True
                        if _grants_snapshot(db, row.workspace_id) != grant_snapshot:
                            stop_reason = "CONNECTOR_NETWORK_GRANT_CHANGED"
                            return True
                        if not registry.heartbeat(db, row.id, token):
                            stop_reason = "CONNECTOR_LEASE_LOST"
                            return True
                        return False
                    except Exception:
                        stop_reason = "CONNECTOR_LEASE_UNAVAILABLE"
                        return True

                remaining = (row.deadline_at - registry.utcnow()).total_seconds()
                if remaining <= 0:
                    raise registry.ComputeRunError("CONNECTOR_TIMEOUT")
                # The sent/running transitions commit separately. Close that
                # window as well, before Popen can send any request remotely.
                if should_stop():
                    raise registry.ComputeRunError(stop_reason)
                result = supervise_harness(
                    [
                        sys.executable,
                        "-m",
                        "app.services.connectors.runner_child",
                        str(spec_path),
                        str(result_path),
                    ],
                    venv_python=Path(sys.executable),
                    scratch=scratch,
                    timeout_s=remaining,
                    should_cancel=should_stop,
                    timeout_error="CONNECTOR_TIMEOUT",
                    memory_limit_mb=row.memory_mb,
                    cpu_limit_s=max(1, math.ceil(remaining * row.cpu_cores)),
                    fsize_limit_mb=1024,
                    extra_env={"PYTHONPATH": str(Path(__file__).resolve().parents[2])},
                )
                if result.status:
                    registry.finish_run(
                        db,
                        row.id,
                        token,
                        status=result.status,
                        error_code=stop_reason or result.error,
                    )
                else:
                    if not result_path.is_file() or result_path.stat().st_size > 5 * 1024 * 1024:
                        raise registry.ComputeRunError("CONNECTOR_RESULT_INVALID")
                    payload = json.loads(result_path.read_text())
                    if payload.get("ok") is not True or result.exit_code != 0:
                        code = payload.get("error_code")
                        if not isinstance(code, str) or not re.fullmatch(
                            r"(?:CONNECTOR|HANA)_[A-Z_]+", code
                        ):
                            code = "CONNECTOR_ADAPTER_FAILED"
                        raise registry.ComputeRunError(code)
                    output = payload.get("output")
                    if not isinstance(output, dict):
                        raise registry.ComputeRunError("CONNECTOR_RESULT_INVALID")
                    if authorization != _authorization_snapshot(db, row):
                        raise registry.ComputeRunError("CONNECTOR_AUTHORIZATION_CHANGED", 403)
                    if not registry.advance_run(db, row.id, token, "committing"):
                        raise registry.ComputeRunError("CONNECTOR_LEASE_LOST")
                    registry.finish_run(
                        db,
                        row.id,
                        token,
                        status="succeeded",
                        output=output,
                        publish=(
                            lambda: _publish_authorized(db, row, output, scratch, authorization)
                        )
                        if row.operation == "import"
                        else None,
                    )
        except Exception as exc:
            db.rollback()
            code = getattr(exc, "code", None)
            if not isinstance(code, str) or not re.fullmatch(
                r"(?:CONNECTOR|HANA|SECRET)_[A-Z_]+", code
            ):
                code = "CONNECTOR_EXECUTION_FAILED"
            registry.finish_run(db, compute_run_id, token, status="failed", error_code=code)
        row = db.get(ComputeRun, compute_run_id)
        return {"id": row.id, "status": row.status, "error_code": row.error_code}


@celery_connectors.task(
    bind=True, name=registry.TASK_NAME, acks_late=True, reject_on_worker_lost=True, max_retries=None
)
def connector_execute(self, compute_run_id: str):
    try:
        return execute_run(compute_run_id)
    except registry.ComputeRunError as exc:
        if exc.code == "CONNECTOR_BUSY":
            # Only unclaimed work is retried. A launched write is never replayed.
            raise self.retry(countdown=1, max_retries=None) from None
        raise


@celery_connectors.task(name="agentium.connector_reap")
def connector_reap():
    from app.db.base import SessionLocal

    with SessionLocal() as db:
        reaped = registry.reap_runs(db)
        from app.services.connectors.scratch import reclaim
        from app.services.connectors.watches import tick

        return {"reaped": reaped, "watches_polled": tick(db), "scratch_reclaimed": reclaim(db)}
