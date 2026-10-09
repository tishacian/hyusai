"""Transactional admission, immutable selections, grants and durable Hub jobs.

The singleton row serializes quota admissions across API and worker processes.
Network acquisition never holds this lock. Each worker completion is fenced by
a renewable lease so a retried delivery cannot publish after cancellation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.models.huggingface import (
    HFPlatformConfig,
    HubArtifact,
    HubArtifactGrant,
    HubArtifactUsage,
    HubImportRequest,
    HubImportReservation,
)
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import policy
from app.services.huggingface.connection import Connection
from app.services.huggingface.errors import HFError

LIMITS = {
    "model_max_bytes": 20 * 1024**3,
    "workspace_max_bytes": 50 * 1024**3,
    "platform_max_bytes": 150 * 1024**3,
    "workspace_imports": 1,
    "platform_imports": 2,
}
MODEL_FORMATS = {"safetensors", "gguf", "onnx"}
SHA = re.compile(r"^[0-9a-f]{40}$")


def _now():
    return datetime.utcnow()


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def admission_lock(db):
    """Return the locked platform row; caller owns commit/rollback."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise HFError(
            "HF_DATABASE_UNSUPPORTED", "Hub admission requires PostgreSQL or SQLite.", 503
        )
    db.execute(
        insert(HFPlatformConfig)
        .values(id="default", connection={}, policy={}, limits={}, updated_at=_now())
        .on_conflict_do_nothing(index_elements=["id"])
    )
    # SQLite has no SELECT FOR UPDATE: acquire its write lock before reading
    # quotas. PostgreSQL locks only the singleton row.
    if dialect == "sqlite":
        db.query(HFPlatformConfig).filter_by(id="default").update({"updated_at": _now()})
    return db.execute(
        select(HFPlatformConfig).where(HFPlatformConfig.id == "default").with_for_update()
    ).scalar_one()


def effective_limits(db) -> dict:
    row = db.get(HFPlatformConfig, "default", populate_existing=True)
    values = {**LIMITS, **((row.limits or {}) if row else {})}
    values.update(
        dataset_max_bytes=int(settings.tabular_upload_max_bytes),
        dataset_max_rows=int(settings.tabular_transform_max_rows),
        dataset_max_columns=int(settings.tabular_max_columns),
        cache_max_bytes=int(settings.hf_cache_max_bytes),
    )
    return values


def set_limits(db, values: dict, *, actor: str) -> dict:
    if set(values) - set(LIMITS) or any(
        isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in values.values()
    ):
        raise HFError("HF_LIMITS_INVALID", "Provide positive integers for known platform limits.")
    if values.get("model_max_bytes", 0) > 80 * 1024**3:
        raise HFError("HF_LIMITS_INVALID", "The model ceiling is 80 GiB.")
    row = admission_lock(db)
    row.limits = {**(row.limits or {}), **values}
    _audit(db, None, "limits.updated", actor, values)
    db.commit()
    return effective_limits(db)


def _audit(db, workspace_id, action, actor, details):
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        workspace_id=workspace_id,
        event_type="hf." + action,
        actor=actor or "system",
        details=details,
        db=db,
    )


def _workspace(db, workspace_id):
    workspace = db.get(Workspace, workspace_id, populate_existing=True)
    if workspace is None:
        raise HFError("HF_WORKSPACE_REQUIRED", "The workspace no longer exists.", 404)
    if not workspace.is_active or workspace.deleted_at:
        raise HFError("HF_WORKSPACE_UNAVAILABLE", "The workspace is disabled or deleted.", 403)
    return workspace


def _path(name):
    if not isinstance(name, str) or not name or len(name) > 400 or "\\" in name or "\0" in name:
        raise HFError("HF_UNSAFE_FORMAT", "Invalid repository file path.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        raise HFError("HF_UNSAFE_FORMAT", "Repository paths must remain inside their snapshot.")
    return name


def select_files(metadata: dict, selection: dict) -> tuple[dict, dict]:
    from app.services.huggingface.client import validate_repo

    validate_repo(metadata.get("kind"), metadata.get("repo_id"))
    if not SHA.fullmatch(str(metadata.get("revision", ""))):
        raise HFError("HF_REVISION_UNRESOLVED", "The import must resolve to an immutable commit.")
    if metadata.get("requires_remote_code"):
        raise HFError("HF_REMOTE_CODE_REQUIRED", "Custom Hub code cannot run in an import.")
    selection = dict(selection)
    inventory = {_path(f["path"]): dict(f) for f in metadata.get("files", [])}
    kind = metadata["kind"]
    fmt = selection.get("format", "parquet" if kind == "dataset" else "safetensors")
    if kind == "dataset":
        from app.services.huggingface.datasets import normalize_plan

        selection = normalize_plan(metadata, selection)
        chosen = selection.get("paths") or selection.get("shards")
    else:
        if not isinstance(fmt, str) or fmt not in MODEL_FORMATS:
            raise HFError("HF_UNSAFE_FORMAT", "Select safetensors, GGUF or ONNX weights.")
        chosen = selection.get("files") or selection.get("paths")
        if not chosen:
            weights = [p for p in inventory if p.endswith("." + fmt)]
            if fmt == "gguf":
                variant = selection.get("variant")
                weights = [p for p in weights if p == variant] if variant else weights
                if len(weights) != 1:
                    raise HFError(
                        "HF_VARIANT_REQUIRED", "Choose one GGUF quantification explicitly."
                    )
            chosen = weights + [p for p in inventory if _support_file(p)]
    if (
        not isinstance(chosen, list)
        or not chosen
        or len(chosen) > settings.hf_max_files
        or any(not isinstance(path, str) for path in chosen)
        or len(chosen) != len(set(chosen))
    ):
        raise HFError("HF_UNSAFE_FORMAT", "Select a bounded, nonempty set of unique files.")
    result = {}
    for name in sorted(chosen):
        _path(name)
        entry = inventory.get(name)
        if not entry:
            raise HFError("HF_NOT_FOUND", "A selected file does not exist at this revision.", 404)
        if kind == "dataset":
            safe = name.endswith(".parquet")
        else:
            safe = name.endswith("." + fmt) or _support_file(name)
        if not safe:
            raise HFError("HF_UNSAFE_FORMAT", "The selection contains an unsupported file type.")
        size = entry.get("size_bytes")
        upstream = entry.get("upstream_hash") or {}
        length = {"sha256": 64, "git-blob-sha1": 40}.get(upstream.get("algorithm"))
        if not length or not re.fullmatch(r"[a-f0-9]{%d}" % length, str(upstream.get("value", ""))):
            raise HFError(
                "HF_CHECKSUM_UNAVAILABLE", "A selected file has no supported upstream checksum."
            )
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise HFError("HF_TOO_LARGE", "A selected file has no reliable size.")
        result[name] = {"size_bytes": size, "upstream_hash": upstream}
    if kind == "model" and not any(p.endswith("." + fmt) for p in result):
        raise HFError("HF_UNSAFE_FORMAT", "No weights match the selected format.")
    if kind == "model":
        # Alias spelling, request order and presentation metadata are not part
        # of an immutable byte selection's identity.
        if fmt == "gguf":
            weights = [p for p in result if p.endswith(".gguf")]
            if len(weights) != 1:
                raise HFError("HF_VARIANT_REQUIRED", "Choose exactly one GGUF quantification.")
            if selection.get("variant") and selection["variant"] != weights[0]:
                raise HFError("HF_VARIANT_INVALID", "The variant must name the selected GGUF file.")
            selection["variant"] = weights[0]
        selection = {
            key: selection[key] for key in ("format", "variant", "name") if key in selection
        }
    selection["format"] = fmt
    selection["files"] = list(result)
    return result, selection


def _support_file(path):
    return path.endswith((".json", ".spm")) or PurePosixPath(path).name in {
        "tokenizer.model",
        "vocab.txt",
        "merges.txt",
        "added_tokens.txt",
        "vocabulary.txt",
    }


def _file_union(artifacts) -> dict:
    union = {}
    for artifact in artifacts:
        if artifact.kind != "model" or artifact.purged_at:
            continue
        for path, entry in (artifact.files_json or {}).items():
            key = (artifact.hub_endpoint, artifact.kind, artifact.repo_id, artifact.revision, path)
            union[key] = int(entry["size_bytes"])
    return union


def workspace_reserved_artifacts(db, workspace_id):
    """Offline imports reserve bytes before their verified grant can exist."""
    return (
        db.query(HubArtifact)
        .join(HubImportReservation, HubImportReservation.artifact_id == HubArtifact.id)
        .filter(HubImportReservation.workspace_id == workspace_id)
        .all()
    )


def inflight_admissions(db):
    reservations = db.query(HubImportReservation).all()
    reserved_jobs = {row.job_id for row in reservations}
    bundles = (
        db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.kind.in_(["hf_bundle_import", "hf_bundle_export"]),
            WorkspaceJob.status.in_(["created", "queued", "running"]),
        )
        .all()
    )
    return reservations, [job for job in bundles if job.id not in reserved_jobs]


def reservation_bytes(reservations, bundles, *, db=None):
    total = sum(row.temporary_bytes for row in reservations)
    for job in bundles:
        size = int((job.input_ref or {}).get("upload_bytes") or 0)
        if not size and job.kind == "hf_bundle_export" and db is not None:
            artifact = db.get(HubArtifact, (job.input_ref or {}).get("artifact_id"))
            size = (artifact.total_bytes if artifact else LIMITS["model_max_bytes"]) + 16 * 1024**2
        total += 2 * size
    return total


def _grant(db, workspace, artifact, actor, decision):
    row = db.get(HubArtifactGrant, (workspace.id, artifact.id), populate_existing=True)
    if row is None:
        row = HubArtifactGrant(workspace_id=workspace.id, artifact_id=artifact.id)
        db.add(row)
    row.granted_by = actor
    row.granted_at = _now()
    row.revoked_at = None
    row.revocation_reason = None
    row.license_digest = decision["license_digest"]
    row.policy_version = decision["policy_version"]
    row.license_accepted_by = decision.get("accepted_by")
    row.license_accepted_at = (
        datetime.fromisoformat(decision["accepted_at"]) if decision.get("accepted_at") else None
    )
    return row


def request_import(
    db,
    *,
    workspace_id: str,
    actor_id: str,
    metadata: dict,
    selection: dict,
    job_key: str | None = None,
    dispatch: bool = True,
):
    workspace = _workspace(db, workspace_id)
    from app.services.huggingface.client import HFClient

    connection = Connection.resolve(db, workspace)
    if connection.endpoint != metadata.get("hub_endpoint"):
        raise HFError(
            "HF_CONNECTION_CHANGED",
            "Resolve the repository again using the active connection.",
            409,
        )
    if metadata.get("private") or metadata.get("gated"):
        HFClient(connection).check_access(metadata, require_workspace_token=True)
    decision = policy.require_acceptance(
        db, workspace, metadata, metadata.get("license_text", ""), actor=actor_id
    )
    files, plan = select_files(metadata, selection)
    # Presentation labels never alter the byte selection or idempotent content.
    content_plan = {k: v for k, v in plan.items() if k not in {"name", "request_key"}}
    selection_hash = digest({"plan": content_plan, "files": files})
    identity = digest(
        [
            connection.endpoint,
            metadata["kind"],
            metadata["repo_id"],
            metadata["revision"],
            selection_hash,
        ]
    )
    admission_lock(db)
    workspace = _workspace(db, workspace_id)
    decision = policy.require_acceptance(
        db, workspace, metadata, metadata.get("license_text", ""), actor=actor_id
    )
    limits = effective_limits(db)
    total_bytes = sum(v["size_bytes"] for v in files.values())
    ceiling = (
        limits["dataset_max_bytes"] if metadata["kind"] == "dataset" else limits["model_max_bytes"]
    )
    if total_bytes > ceiling:
        raise HFError("HF_TOO_LARGE", "The selected files exceed the import byte limit.", 413)
    request_key = job_key or str(uuid4())
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
        raise HFError("HF_REQUEST_INVALID", "The idempotency key must contain 1–128 characters.")
    existing_request = (
        db.query(HubImportRequest)
        .filter_by(workspace_id=workspace_id, request_key=request_key)
        .first()
    )
    if existing_request:
        if existing_request.request_digest != identity:
            raise HFError(
                "HF_IDEMPOTENCY_CONFLICT",
                "This request key already names a different selection.",
                409,
            )
        job = db.get(WorkspaceJob, existing_request.job_id)
        artifact = db.get(HubArtifact, job.input_ref["artifact_id"])
        db.commit()
        return artifact, job
    artifact = db.query(HubArtifact).filter_by(identity_hash=identity).first()
    if artifact and artifact.status == "revoked":
        raise HFError(
            "HF_ARTIFACT_REVOKED", "This selection has been revoked by the platform.", 409
        )
    if artifact is None:
        artifact = HubArtifact(
            id=str(uuid4()),
            identity_hash=identity,
            hub_endpoint=connection.endpoint,
            kind=metadata["kind"],
            repo_id=metadata["repo_id"],
            revision=metadata["revision"],
            requested_ref=metadata.get("requested_ref") or metadata["revision"],
            format=plan["format"],
            variant=plan.get("variant"),
            selection_digest=selection_hash,
            files_json=files,
            selection_json=content_plan,
            metadata_json={
                **metadata,
                "license_class": decision["license_class"],
                "initial_license_decision": decision,
            },
            total_bytes=total_bytes,
            status="pending",
        )
        db.add(artifact)
        db.flush()
    existing = (
        db.query(HubArtifact)
        .join(HubArtifactGrant)
        .filter(
            HubArtifactGrant.workspace_id == workspace_id,
            HubArtifactGrant.revoked_at.is_(None),
            HubArtifact.status != "failed",
        )
        .all()
    )
    reserved_artifacts = workspace_reserved_artifacts(db, workspace_id)
    if (
        sum(_file_union([*existing, *reserved_artifacts, artifact]).values())
        > limits["workspace_max_bytes"]
    ):
        raise HFError("HF_QUOTA_EXCEEDED", "The workspace model quota would be exceeded.", 409)
    # Failed imports can already own verified immutable blobs. Until a purge
    # proves those references absent, do not let repeated failures evade quota.
    platform_artifacts = db.query(HubArtifact).filter(HubArtifact.purged_at.is_(None)).all()
    if sum(_file_union([*platform_artifacts, artifact]).values()) > limits["platform_max_bytes"]:
        raise HFError("HF_QUOTA_EXCEEDED", "The shared model quota would be exceeded.", 409)
    if artifact.status != "ready":
        reservations, bundles = inflight_admissions(db)
        if (
            sum(r.workspace_id == workspace_id for r in [*reservations, *bundles])
            >= limits["workspace_imports"]
            or len(reservations) + len(bundles) >= limits["platform_imports"]
        ):
            raise HFError("HF_QUOTA_EXCEEDED", "The concurrent import limit has been reached.", 409)
        # Dedicated workers may use a different mount, so they repeat the
        # physical admission check before transferring bytes.
        root = Path(settings.hf_cache_dir)
        while not root.exists() and root != root.parent:
            root = root.parent
        reserved = reservation_bytes(reservations, bundles, db=db)
        temporary_bytes = total_bytes * 2
        if artifact.kind == "dataset":
            # Decoded/projected output may be much larger than compressed
            # input. Reserve both retained and user-visible tabular writes.
            temporary_bytes += 2 * int(os.getenv("HF_DATASET_MAX_MEMORY_BYTES", str(512 * 1024**2)))
        if (
            shutil.disk_usage(root).free - reserved - temporary_bytes
            < settings.hf_disk_min_free_bytes
        ):
            raise HFError("HF_QUOTA_EXCEEDED", "Insufficient disk headroom for the import.", 409)
    _grant(db, workspace, artifact, actor_id, decision)
    complete = artifact.status == "ready"
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace_id,
        kind="hf_import",
        title=f"Import {artifact.repo_id}",
        status="completed" if complete else "queued",
        stage="ready" if complete else "queued",
        progress=100 if complete else 0,
        input_ref={"artifact_id": artifact.id, "actor_id": actor_id, "selection": plan},
        result={"artifact_id": artifact.id},
        created_by_user_id=actor_id,
        queued_at=_now(),
        completed_at=_now() if complete else None,
    )
    db.add(job)
    db.flush()
    db.add(
        HubImportRequest(
            workspace_id=workspace_id,
            request_key=request_key,
            request_digest=identity,
            job_id=job.id,
        )
    )
    if not complete:
        artifact.status = "pending" if artifact.status == "failed" else artifact.status
        db.add(
            HubImportReservation(
                job_id=job.id,
                workspace_id=workspace_id,
                artifact_id=artifact.id,
                temporary_bytes=temporary_bytes,
                expires_at=_now() + timedelta(seconds=settings.hf_import_timeout_seconds),
            )
        )
    _audit(
        db,
        workspace_id,
        "import.requested",
        actor_id,
        {"artifact_id": artifact.id, "job_id": job.id},
    )
    db.commit()
    if complete and artifact.kind == "dataset":
        from app.services.huggingface.datasets import replay_dataset

        dataset = replay_dataset(
            db,
            workspace_id=workspace_id,
            artifact_id=artifact.id,
            selection_digest=artifact.selection_digest,
            name=plan.get("name") or artifact.repo_id,
        )
        job.result = {**job.result, "dataset_id": dataset.id}
        db.commit()
    elif dispatch and not complete:
        dispatch_import(db, job)
    return artifact, job


def dispatch_import(db, job):
    from app.workers.celery_app import celery_app

    try:
        task = celery_app.send_task("agentium.hf_import", args=[job.id], queue="hub_fetch")
        job.input_ref = {**job.input_ref, "celery_task_id": task.id}
        job.stage = "queued"
    except Exception:
        # Durable queued intent remains recoverable; never import in the API.
        job.stage = "dispatch_pending"
    db.commit()


def require_artifact(db, workspace_id: str, artifact_id: str, usage: str | None = None):
    artifact = db.get(HubArtifact, artifact_id, populate_existing=True)
    grant = db.get(HubArtifactGrant, (workspace_id, artifact_id), populate_existing=True)
    if artifact is None or grant is None:
        raise HFError("HF_NOT_FOUND", "Artifact not available in this workspace.", 404)
    if grant.revoked_at:
        raise HFError("HF_ACCESS_REVOKED", "The workspace authorization was withdrawn.", 403)
    if artifact.status == "revoked":
        raise HFError("HF_ARTIFACT_REVOKED", "The platform revoked this artifact.", 403)
    if artifact.status != "ready" or not artifact.manifest_json or artifact.purged_at:
        raise HFError("HF_ARTIFACT_NOT_READY", "The artifact is not ready for use.", 409)
    policy.require_acceptance(
        db,
        _workspace(db, workspace_id),
        artifact.metadata_json,
        artifact.metadata_json.get("license_text", ""),
    )
    if usage in {"embedding", "reranker", "forecasting", "llm"} and artifact.kind != "model":
        raise HFError("HF_INCOMPATIBLE_USAGE", "This usage requires a model artifact.", 409)
    artifact.last_used_at = _now()
    return artifact


authorize_artifact = require_artifact


def register_usage(db, workspace_id, artifact_id, kind, target_id, *, details=None):
    admission_lock(db)
    artifact = require_artifact(db, workspace_id, artifact_id, usage=kind)
    row = (
        db.query(HubArtifactUsage)
        .filter_by(workspace_id=workspace_id, kind=kind, target_id=target_id)
        .first()
    )
    if row is None:
        row = HubArtifactUsage(workspace_id=workspace_id, kind=kind, target_id=target_id)
        db.add(row)
    row.artifact_id = artifact.id
    row.status = "active"
    row.details_json = dict(details or {})
    db.flush()
    return row


def revoke_grant(db, workspace_id, artifact_id, *, actor, reason):
    admission_lock(db)
    grant = db.get(HubArtifactGrant, (workspace_id, artifact_id), populate_existing=True)
    if not grant:
        raise HFError("HF_NOT_FOUND", "Artifact not available in this workspace.", 404)
    grant.revoked_at, grant.revocation_reason = _now(), reason
    db.query(HubArtifactUsage).filter_by(workspace_id=workspace_id, artifact_id=artifact_id).update(
        {"status": "unavailable"}
    )
    _audit(db, workspace_id, "grant.revoked", actor, {"artifact_id": artifact_id, "reason": reason})
    db.commit()
    _schedule_drain(artifact_id, workspace_id)


def revoke_artifact(db, artifact_id, *, actor, reason):
    admission_lock(db)
    artifact = db.get(HubArtifact, artifact_id, populate_existing=True)
    if not artifact:
        raise HFError("HF_NOT_FOUND", "Artifact not found.", 404)
    artifact.status, artifact.revoked_at, artifact.revocation_reason = "revoked", _now(), reason
    db.query(HubArtifactUsage).filter_by(artifact_id=artifact_id).update({"status": "unavailable"})
    _audit(db, None, "artifact.revoked", actor, {"artifact_id": artifact_id, "reason": reason})
    db.commit()
    _schedule_drain(artifact_id)


def _schedule_drain(artifact_id, workspace_id=None):
    from app.workers.celery_app import celery_app

    try:
        celery_app.send_task(
            "agentium.hf_drain_revoked",
            args=[artifact_id, workspace_id],
            queue="hub_fetch",
            retry=False,
        )
    except Exception:
        pass  # The unavailable usage rows are the durable drain intent.


def claim_import(db, job_id):
    admission_lock(db)
    job = db.get(WorkspaceJob, job_id, populate_existing=True)
    reservation = db.get(HubImportReservation, job_id, populate_existing=True)
    if (
        not job
        or job.kind != "hf_import"
        or job.status in {"completed", "failed", "cancelled"}
        or not reservation
    ):
        raise HFError("HF_JOB_INACTIVE", "This import is no longer active.", 409)
    if reservation.expires_at <= _now():
        raise HFError("HF_JOB_EXPIRED", "The import exceeded its execution deadline.", 409)
    if reservation.lease_expires_at and reservation.lease_expires_at > _now():
        raise HFError("HF_JOB_BUSY", "Another worker owns this import.", 409)
    artifact = db.get(HubArtifact, reservation.artifact_id, populate_existing=True)
    grant = db.get(
        HubArtifactGrant, (job.workspace_id, reservation.artifact_id), populate_existing=True
    )
    if artifact is None or artifact.status == "revoked" or not grant or grant.revoked_at:
        raise HFError(
            "HF_ACCESS_REVOKED", "Authorization was withdrawn while the import was queued.", 403
        )
    # One publication owner per artifact, even when workspaces race.
    other = (
        db.query(HubImportReservation)
        .filter(
            HubImportReservation.artifact_id == artifact.id,
            HubImportReservation.job_id != job.id,
            HubImportReservation.lease_expires_at > _now(),
        )
        .first()
    )
    if other:
        raise HFError("HF_JOB_BUSY", "Another worker is preparing this selection.", 409)
    from app.services.huggingface.access import require_job_actor

    workspace = require_job_actor(db, job, artifact.kind)
    policy.require_acceptance(
        db, workspace, artifact.metadata_json, artifact.metadata_json.get("license_text", "")
    )
    reservation.lease_owner = str(uuid4())
    reservation.lease_expires_at = _now() + timedelta(seconds=settings.hf_import_lease_seconds)
    job.result = {**(job.result or {}), "lease_owner": reservation.lease_owner}
    job.status, job.started_at = "running", job.started_at or _now()
    if artifact.status != "ready":
        artifact.status = "fetching"
    db.commit()
    return artifact, job


def _check_lease(db, job_id, lease_owner):
    reservation = db.get(HubImportReservation, job_id, populate_existing=True)
    if (
        not reservation
        or not lease_owner
        or reservation.lease_owner != lease_owner
        or not reservation.lease_expires_at
        or reservation.lease_expires_at <= _now()
    ):
        raise HFError("HF_JOB_LEASE_LOST", "This worker no longer owns the import.", 409)
    if reservation.expires_at <= _now():
        raise HFError("HF_JOB_EXPIRED", "The import exceeded its execution deadline.", 409)
    return reservation


def touch_import(db, job_id, stage, progress, *, lease_owner=None):
    admission_lock(db)
    job = db.get(WorkspaceJob, job_id, populate_existing=True)
    reservation = _check_lease(db, job_id, lease_owner)
    if job is None or job.status != "running":
        raise HFError("HF_JOB_INACTIVE", "This import is no longer running.", 409)
    artifact = db.get(HubArtifact, reservation.artifact_id, populate_existing=True)
    grant = db.get(
        HubArtifactGrant, (job.workspace_id, reservation.artifact_id), populate_existing=True
    )
    if not artifact or artifact.status == "revoked" or not grant or grant.revoked_at:
        raise HFError("HF_ACCESS_REVOKED", "Authorization was withdrawn during the import.", 403)
    from app.services.huggingface.access import require_job_actor

    workspace = require_job_actor(db, job, artifact.kind)
    policy.require_acceptance(
        db, workspace, artifact.metadata_json, artifact.metadata_json.get("license_text", "")
    )
    reservation.lease_expires_at = _now() + timedelta(seconds=settings.hf_import_lease_seconds)
    job.stage, job.progress, job.updated_at = stage, max(0, min(99, int(progress))), _now()
    db.commit()


def _validate_publication(artifact, manifest):
    from app.services.huggingface.storage import blob_key

    if not isinstance(manifest, dict) or manifest.get("version") != 2:
        raise HFError("HF_MANIFEST_INVALID", "Publication requires a complete v2 manifest.")
    expected = {
        "artifact_id": artifact.id,
        "hub_endpoint": artifact.hub_endpoint,
        "kind": artifact.kind,
        "repo_id": artifact.repo_id,
        "revision": artifact.revision,
        "format": artifact.format,
        "variant": artifact.variant,
        "selection_digest": artifact.selection_digest,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise HFError(
            "HF_MANIFEST_INVALID", "The publication does not match the reserved selection."
        )
    if manifest.get("selection") != artifact.selection_json:
        raise HFError(
            "HF_MANIFEST_INVALID", "The publication changed the admitted transformation or files."
        )
    metadata = artifact.metadata_json or {}
    if (
        manifest.get("license") != metadata.get("license")
        or bool(manifest.get("private")) != bool(metadata.get("private"))
        or bool(manifest.get("gated")) != bool(metadata.get("gated"))
    ):
        raise HFError(
            "HF_MANIFEST_INVALID",
            "The publication changed the repository's authorization metadata.",
        )
    files = manifest.get("source_files") if artifact.kind == "dataset" else manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(artifact.files_json):
        raise HFError(
            "HF_MANIFEST_INVALID",
            "The publication is missing admitted files or contains additional files.",
        )
    total = 0
    for path, admitted in artifact.files_json.items():
        entry = files[path]
        if (
            not isinstance(entry, dict)
            or entry.get("size_bytes") != admitted["size_bytes"]
            or entry.get("upstream_hash") != admitted["upstream_hash"]
            or not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("sha256", "")))
        ):
            raise HFError(
                "HF_MANIFEST_INVALID", "Every admitted file needs its verified size and checksums."
            )
        if (
            admitted["upstream_hash"]["algorithm"] == "sha256"
            and entry["sha256"] != admitted["upstream_hash"]["value"]
        ):
            raise HFError(
                "HF_MANIFEST_INVALID", "A verified checksum differs from its admitted LFS checksum."
            )
        if artifact.kind == "model" and entry.get("object_key") != blob_key(artifact, path):
            raise HFError(
                "HF_MANIFEST_INVALID", "A model file points outside its immutable blob namespace."
            )
        if artifact.kind == "dataset" and "object_key" in entry:
            raise HFError(
                "HF_MANIFEST_INVALID",
                "Temporary dataset sources must not become durable object references.",
            )
        total += entry["size_bytes"]
    if artifact.kind == "dataset":
        result = manifest.get("dataset_result")
        if not isinstance(result, dict) or manifest.get("files") != {}:
            raise HFError(
                "HF_MANIFEST_INVALID", "A dataset publication requires its retained tabular result."
            )
        owner = result.get("owner_workspace_id")
        if (
            not isinstance(owner, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", owner)
            or result.get("object_key")
            != f"workspaces/{owner}/tabular/hub-artifacts/{artifact.id}/result.parquet"
            or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("sha256", "")))
        ):
            raise HFError(
                "HF_MANIFEST_INVALID", "The retained dataset result has invalid provenance."
            )
        for field, ceiling in (
            ("size_bytes", 2**63 - 1),
            ("row_count", artifact.selection_json["max_rows"]),
            ("column_count", settings.tabular_max_columns),
        ):
            value = result.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ceiling:
                raise HFError(
                    "HF_MANIFEST_INVALID", "The dataset result exceeds its admitted bounds."
                )
        total = result["size_bytes"]
    if manifest.get("total_bytes") != total:
        raise HFError(
            "HF_MANIFEST_INVALID", "The published total does not match the verified files."
        )


def complete_import(db, job_id, manifest, *, lease_owner=None):
    admission_lock(db)
    job = db.get(WorkspaceJob, job_id, populate_existing=True)
    reservation = _check_lease(db, job_id, lease_owner)
    if job is None or job.status != "running":
        raise HFError("HF_JOB_INACTIVE", "This import is no longer running.", 409)
    artifact = db.get(HubArtifact, reservation.artifact_id, populate_existing=True)
    grant = db.get(HubArtifactGrant, (job.workspace_id, artifact.id), populate_existing=True)
    if not grant or grant.revoked_at or artifact.status == "revoked":
        raise HFError("HF_ACCESS_REVOKED", "Authorization was withdrawn before publication.", 403)
    _validate_publication(artifact, manifest)
    if artifact.status == "ready" and artifact.manifest_json != manifest:
        raise HFError("HF_MANIFEST_INVALID", "A published artifact manifest is immutable.")
    from app.services.huggingface.access import require_job_actor

    workspace = require_job_actor(db, job, artifact.kind)
    policy.require_acceptance(
        db, workspace, artifact.metadata_json, artifact.metadata_json.get("license_text", "")
    )
    artifact.manifest_json = dict(manifest)
    artifact.manifest_key = f"hub/artifacts/{artifact.id}/manifest.json"
    if artifact.kind == "model":
        artifact.files_json = manifest["files"]
    artifact.status, artifact.imported_at, artifact.error_code = "ready", _now(), None
    job.status, job.stage, job.progress, job.completed_at = "completed", "ready", 100, _now()
    dataset_id = (job.result or {}).get("dataset_id")
    job.result = {"artifact_id": artifact.id, **({"dataset_id": dataset_id} if dataset_id else {})}
    db.delete(reservation)
    _audit(
        db,
        job.workspace_id,
        "import.completed",
        job.created_by_user_id,
        {"artifact_id": artifact.id, "job_id": job.id},
    )
    db.commit()
    return artifact


def fail_import(db, job_id, error_code, message="", *, lease_owner=None):
    db.rollback()
    admission_lock(db)
    job = db.get(WorkspaceJob, job_id, populate_existing=True)
    if not job or job.status in {"completed", "cancelled"}:
        db.commit()
        return
    reservation = db.get(HubImportReservation, job_id, populate_existing=True)
    if lease_owner and reservation and reservation.lease_owner != lease_owner:
        db.commit()
        return
    if (
        not lease_owner
        and reservation
        and reservation.lease_owner
        and reservation.lease_expires_at
        and reservation.lease_expires_at > _now()
        and reservation.expires_at > _now()
    ):
        # A failed duplicate claim never owns the live worker's job.
        db.commit()
        return
    artifact = db.get(HubArtifact, (job.input_ref or {}).get("artifact_id"), populate_existing=True)
    job.status, job.stage, job.error, job.completed_at = "failed", "failed", error_code, _now()
    job.result = {"artifact_id": artifact.id if artifact else None, "error_code": error_code}
    if reservation:
        db.delete(reservation)
        db.flush()
    if artifact and artifact.status not in {"ready", "revoked"}:
        active_peer = db.query(HubImportReservation).filter_by(artifact_id=artifact.id).first()
        if active_peer is None:
            artifact.status, artifact.error_code = "failed", error_code
    _audit(
        db,
        job.workspace_id,
        "import.failed",
        job.created_by_user_id,
        {"job_id": job.id, "error_code": error_code},
    )
    db.commit()
    _schedule_cleanup(job_id)


def run_import(db, job_id):
    from app.services.huggingface.fetch import execute_import

    lease = None
    try:
        artifact, job = claim_import(db, job_id)
        lease = job.result["lease_owner"]
        if artifact.status == "ready":
            if artifact.kind == "dataset":
                from app.services.huggingface.datasets import replay_dataset

                dataset = replay_dataset(
                    db,
                    workspace_id=job.workspace_id,
                    artifact_id=artifact.id,
                    selection_digest=artifact.selection_digest,
                    name=(job.input_ref.get("selection") or {}).get("name") or artifact.repo_id,
                    created_by=job.created_by_user_id,
                )
                job.result = {**job.result, "dataset_id": dataset.id}
                db.commit()
            return complete_import(db, job_id, artifact.manifest_json, lease_owner=lease)
        manifest = execute_import(db, artifact, job)
        if manifest.get("pending_dataset"):
            admission_lock(db)
            reservation = _check_lease(db, job.id, lease)
            job.result = {**job.result, "acquisition": manifest}
            job.stage, job.status = "dataset_queued", "queued"
            reservation.lease_owner = reservation.lease_expires_at = None
            db.commit()
            from app.workers.celery_app import celery_app

            celery_app.send_task(
                "agentium.hf_dataset_materialize",
                args=[job.id],
                queue=settings.celery_task_default_queue,
            )
            return None
        return complete_import(db, job.id, manifest, lease_owner=lease)
    except HFError as exc:
        if exc.code in {"HF_JOB_BUSY", "HF_JOB_INACTIVE"}:
            db.rollback()
            raise
        fail_import(db, job_id, exc.code, lease_owner=lease)
        raise
    except Exception:
        fail_import(db, job_id, "HF_IMPORT_FAILED", lease_owner=lease)
        raise HFError(
            "HF_IMPORT_FAILED", "The import failed; see its audited error code.", 502
        ) from None


def cancel_import(db, workspace_id, job_id, *, actor):
    admission_lock(db)
    job = (
        db.query(WorkspaceJob)
        .populate_existing()
        .filter_by(id=job_id, workspace_id=workspace_id, kind="hf_import")
        .first()
    )
    if job is None:
        raise HFError("HF_NOT_FOUND", "Import job not found.", 404)
    if job.status not in {"completed", "failed", "cancelled"}:
        job.status, job.stage, job.completed_at = "cancelled", "cancelled", _now()
        reservation = db.get(HubImportReservation, job_id)
        if reservation:
            db.delete(reservation)
            db.flush()
            artifact = db.get(HubArtifact, reservation.artifact_id, populate_existing=True)
            peer = (
                db.query(HubImportReservation)
                .filter_by(artifact_id=reservation.artifact_id)
                .first()
            )
            if artifact and artifact.status not in {"ready", "revoked"} and peer is None:
                artifact.status, artifact.error_code = "failed", "HF_JOB_CANCELLED"
        _audit(db, workspace_id, "import.cancelled", actor, {"job_id": job_id})
    db.commit()
    _schedule_cleanup(job_id)
    return job


def _schedule_cleanup(job_id):
    """Only the Hub role can clean staging; its periodic sweeper retries."""
    from app.workers.celery_app import celery_app

    try:
        celery_app.send_task("agentium.hf_cleanup_temporary", args=[job_id], queue="hub_fetch")
    except Exception:
        pass  # Durable terminal job status is the cleanup intent.


def recover_imports(db):
    """Recover durable queue intents and expire abandoned reservations."""
    jobs = (
        db.query(WorkspaceJob)
        .populate_existing()
        .filter(WorkspaceJob.kind == "hf_import", WorkspaceJob.status.in_(["queued", "running"]))
        .all()
    )
    for job in jobs:
        reservation = db.get(HubImportReservation, job.id, populate_existing=True)
        if not reservation or reservation.expires_at <= _now():
            fail_import(db, job.id, "HF_JOB_EXPIRED")
        elif not reservation.lease_expires_at or reservation.lease_expires_at <= _now():
            if (job.result or {}).get("acquisition"):
                from app.workers.celery_app import celery_app

                try:
                    celery_app.send_task(
                        "agentium.hf_dataset_materialize",
                        args=[job.id],
                        queue=settings.celery_task_default_queue,
                    )
                except Exception:
                    # Keep the stage and acquired inputs intact for the next
                    # beat tick, without stranding unrelated pending jobs.
                    pass
            else:
                dispatch_import(db, job)


def public_artifact(artifact, *, grant=None):
    meta = artifact.metadata_json or {}
    return {
        "id": artifact.id,
        "artifact_id": artifact.id,
        "kind": artifact.kind,
        "repo_id": artifact.repo_id,
        "revision": artifact.revision,
        "requested_ref": artifact.requested_ref,
        "format": artifact.format,
        "variant": artifact.variant,
        "total_bytes": artifact.total_bytes,
        "status": artifact.status,
        "error_code": artifact.error_code,
        "in_catalogue": artifact.in_catalogue,
        "license": meta.get("license"),
        "license_class": policy.classify(meta.get("license")),
        "pipeline_tag": meta.get("pipeline_tag"),
        "library": meta.get("library"),
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "imported_at": artifact.imported_at.isoformat() if artifact.imported_at else None,
        "has_access": bool(grant and not grant.revoked_at),
        "files": [
            {"path": path, "size_bytes": info["size_bytes"], "sha256": info.get("sha256")}
            for path, info in (artifact.files_json or {}).items()
        ],
    }


def public_job(job):
    result = {
        k: v
        for k, v in (job.result or {}).items()
        if k
        in {
            "artifact_id",
            "model_id",
            "migration",
            "dataset_id",
            "error_code",
            "size_bytes",
            "expires_at",
            "download_available",
        }
    }
    probe = (job.result or {}).get("probe")
    if isinstance(probe, dict):
        result["probe"] = {
            key: probe[key]
            for key in (
                "artifact_id",
                "usage",
                "validation",
                "target_runtime",
                "engine",
                "dimension",
                "fingerprint",
                "revision",
                "runtime",
            )
            if key in probe
        }
    return {
        "id": job.id,
        "kind": job.kind,
        "artifact_id": (job.input_ref or {}).get("artifact_id"),
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "error": job.error,
        "result": result,
    }
