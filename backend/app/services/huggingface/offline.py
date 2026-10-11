"""Durable offline import/export jobs on the role-appropriate preparation worker."""

from __future__ import annotations

import base64
import fcntl
import json
import os
import shutil
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.models.huggingface import HubArtifact, HubArtifactGrant, HubImportReservation
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.huggingface import bundles, policy, registry
from app.services.huggingface.errors import HFError
from app.services.huggingface.storage import CHUNK_BYTES, HubStore, blob_key


def spool_root() -> Path:
    root = Path(os.getenv("HF_BUNDLE_SPOOL_DIR", "/data/hub-bundles"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def job_directory(job_id: str) -> Path:
    try:
        identity = str(UUID(job_id))
    except ValueError as exc:
        raise HFError("HF_BUNDLE_INVALID", "Invalid bundle job identifier") from exc
    return spool_root() / identity


def trust_keys() -> dict:
    try:
        configured = json.loads(os.getenv("HF_BUNDLE_TRUST_KEYS_JSON", "{}"))
        if not isinstance(configured, dict) or not configured:
            raise ValueError
        return {
            str(key): value.encode()
            if value.startswith("-----BEGIN")
            else base64.b64decode(value, validate=True)
            for key, value in configured.items()
        }
    except (ValueError, TypeError, AttributeError) as exc:
        raise HFError(
            "HF_BUNDLE_UNCONFIGURED", "Configure trusted Ed25519 bundle exporters", 503
        ) from exc


def inspect_bundle(stream, workspace_id: str) -> dict:
    """Read only bounded, authenticated metadata; leave the stream at its start."""
    start = stream.tell()
    try:
        manifest = bundles._metadata(stream, "manifest.json")
        proof = bundles._metadata(stream, "attestation.json")
        bundles.verify_attestation(
            proof, manifest, target_workspace_id=workspace_id, trust_keys=trust_keys()
        )
        bundles.durable_files(manifest)
        return manifest
    finally:
        stream.seek(start)


def _admit(db, job, manifest):
    """Same selection/quota rules as online import, with signed offline access."""
    workspace = db.get(Workspace, job.workspace_id)
    if workspace is None:
        raise HFError("HF_ACCESS_REVOKED", "The target workspace no longer exists", 403)
    if manifest.get("version") != 2 or manifest.get("kind") not in {"model", "dataset"}:
        raise HFError("HF_MANIFEST_INVALID", "Offline import requires an artifact manifest v2")
    try:
        artifact_id = str(UUID(str(manifest.get("artifact_id", ""))))
    except ValueError as exc:
        raise HFError("HF_MANIFEST_INVALID", "Invalid offline artifact identity") from exc
    from app.services.huggingface.connection import normalize_endpoint

    endpoint = normalize_endpoint(manifest.get("hub_endpoint"))
    if endpoint != manifest.get("hub_endpoint"):
        raise HFError("HF_MANIFEST_INVALID", "Offline endpoint provenance is not canonical")
    sources = (
        manifest.get("source_files") if manifest["kind"] == "dataset" else manifest.get("files")
    )
    if not isinstance(sources, dict):
        raise HFError("HF_MANIFEST_INVALID", "Offline source inventory is missing")
    metadata = {**manifest, "files": [{"path": path, **entry} for path, entry in sources.items()]}
    files, plan = registry.select_files(metadata, manifest.get("selection") or {})
    content_plan = {k: v for k, v in plan.items() if k not in {"name", "request_key"}}
    selection_hash = registry.digest({"plan": content_plan, "files": files})
    if selection_hash != manifest.get("selection_digest"):
        raise HFError(
            "HF_MANIFEST_INVALID", "The offline manifest selection digest is inconsistent"
        )
    identity = registry.digest(
        [endpoint, manifest["kind"], manifest["repo_id"], manifest["revision"], selection_hash]
    )
    decision = policy.require_acceptance(
        db, workspace, metadata, manifest.get("license_text", ""), actor=job.created_by_user_id
    )
    registry.admission_lock(db)
    artifact = db.get(HubArtifact, artifact_id)
    if artifact and artifact.identity_hash != identity:
        raise HFError(
            "HF_BUNDLE_IDENTITY_CONFLICT",
            "This artifact ID names a different immutable selection",
            409,
        )
    other = db.query(HubArtifact).filter_by(identity_hash=identity).first()
    if other and other.id != artifact_id:
        raise HFError(
            "HF_BUNDLE_IDENTITY_CONFLICT",
            "This selection already exists under another artifact ID",
            409,
        )
    if artifact and (artifact.status == "revoked" or artifact.purged_at):
        raise HFError("HF_ARTIFACT_REVOKED", "The offline selection was revoked", 403)
    if not artifact:
        artifact = HubArtifact(
            id=artifact_id,
            identity_hash=identity,
            hub_endpoint=endpoint,
            kind=manifest["kind"],
            repo_id=manifest["repo_id"],
            revision=manifest["revision"],
            requested_ref=manifest.get("requested_ref") or manifest["revision"],
            format=plan["format"],
            variant=plan.get("variant"),
            selection_digest=selection_hash,
            files_json=files,
            selection_json=content_plan,
            metadata_json=metadata,
            total_bytes=sum(item["size_bytes"] for item in files.values()),
            status="pending",
        )
        db.add(artifact)
        db.flush()
    limits = registry.effective_limits(db)
    retained = sum(item["size_bytes"] for item in bundles.durable_files(manifest).values())
    maximum = (
        limits["dataset_max_bytes"] if artifact.kind == "dataset" else limits["model_max_bytes"]
    )
    if retained > maximum or artifact.total_bytes > maximum:
        raise HFError("HF_TOO_LARGE", "The offline selection exceeds its byte limit", 413)
    current = (
        db.query(HubArtifact)
        .join(HubArtifactGrant)
        .filter(
            HubArtifactGrant.workspace_id == workspace.id, HubArtifactGrant.revoked_at.is_(None)
        )
        .all()
    )
    # The pending artifact participates before bytes are published.
    if (
        sum(
            registry._file_union(
                [*current, *registry.workspace_reserved_artifacts(db, workspace.id), artifact]
            ).values()
        )
        > limits["workspace_max_bytes"]
    ):
        raise HFError("HF_QUOTA_EXCEEDED", "The workspace model quota would be exceeded", 409)
    if (
        sum(
            registry._file_union(
                db.query(HubArtifact).filter(HubArtifact.purged_at.is_(None)).all()
            ).values()
        )
        > limits["platform_max_bytes"]
    ):
        raise HFError("HF_QUOTA_EXCEEDED", "The shared model quota would be exceeded", 409)
    # A grant is created only after hash verification and publication below.
    job.input_ref = {**job.input_ref, "artifact_id": artifact.id}
    reservation = db.get(HubImportReservation, job.id)
    if reservation is None:
        db.add(
            HubImportReservation(
                job_id=job.id,
                workspace_id=workspace.id,
                artifact_id=artifact.id,
                temporary_bytes=retained * 2,
                expires_at=datetime.utcnow()
                + timedelta(seconds=settings.hf_import_timeout_seconds),
            )
        )
    db.commit()
    return artifact, workspace, decision, maximum


def _export(db, job, directory):
    artifact = registry.require_artifact(db, job.workspace_id, job.input_ref["artifact_id"])
    manifest = dict(artifact.manifest_json)
    workspace = db.get(Workspace, job.workspace_id)
    if "license_text" not in manifest:
        raise HFError(
            "HF_BUNDLE_INVALID", "Reimport the legacy artifact to retain its license evidence"
        )
    key_path, key_id = (
        os.getenv("HF_BUNDLE_SIGNING_KEY_PATH"),
        os.getenv("HF_BUNDLE_SIGNING_KEY_ID"),
    )
    if not key_path or not key_id:
        raise HFError("HF_BUNDLE_UNCONFIGURED", "Configure an Ed25519 exporter signing key", 503)
    signing_key = Path(key_path).read_bytes()
    store = HubStore(use_hub_credentials=artifact.kind == "model")
    limits = registry.effective_limits(db)
    maximum = limits["model_max_bytes"] if artifact.kind == "model" else limits["dataset_max_bytes"]

    def authorize(_manifest, target):
        db.expire_all()
        from app.services.huggingface.access import require_job_actor

        require_job_actor(db, job)
        registry.require_artifact(db, target, artifact.id)

    def access(_manifest, target):
        from app.services.huggingface.client import HFClient
        from app.services.huggingface.connection import Connection

        with HFClient(Connection.resolve(db, workspace)) as hub:
            hub.check_access(artifact.metadata_json, require_workspace_token=True)

    with ExitStack() as handles:

        def open_file(path):
            if artifact.kind == "model":
                key = blob_key(artifact, path)
                if manifest["files"][path].get("object_key") != key:
                    raise HFError("HF_PATH_INVALID", "Artifact object reference is inconsistent")
            else:
                result = manifest["dataset_result"]
                key = f"workspaces/{result['owner_workspace_id']}/tabular/hub-artifacts/{artifact.id}/result.parquet"
                if result.get("object_key") != key:
                    raise HFError("HF_PATH_INVALID", "Dataset result reference is inconsistent")
            return handles.enter_context(store.open(key))

        destination = directory / "export.tar"
        temporary = directory / "export.partial"
        with temporary.open("wb") as output:
            proof = bundles.export_bundle(
                output,
                manifest=manifest,
                open_file=open_file,
                target_workspace_id=job.workspace_id,
                license_digest=policy.license_digest(manifest, manifest.get("license_text", "")),
                signing_key=signing_key,
                key_id=key_id,
                authorize=authorize,
                verify_hub_access=access,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=job.input_ref.get("expiry_seconds", 86400)),
                max_total_bytes=maximum,
                max_file_bytes=maximum,
            )
        authorize(manifest, job.workspace_id)
        temporary.replace(destination)
    return {
        "artifact_id": artifact.id,
        "size_bytes": destination.stat().st_size,
        "expires_at": proof["payload"]["expires_at"],
        "download_available": True,
    }


def _import(db, job, directory):
    with (directory / "upload.tar").open("rb") as source:
        manifest = inspect_bundle(source, job.workspace_id)
        artifact, workspace, decision, maximum = _admit(db, job, manifest)
        stage = directory / "verified"
        if stage.exists():
            shutil.rmtree(stage)

        def accept(value, license_digest):
            effective = policy.require_acceptance(
                db, workspace, value, value.get("license_text", ""), actor=job.created_by_user_id
            )
            return effective["license_digest"] == license_digest

        bundles.import_bundle(
            source,
            destination_dir=stage,
            target_workspace_id=workspace.id,
            trust_keys=trust_keys(),
            accept_license=accept,
            max_total_bytes=maximum,
            max_file_bytes=maximum,
        )
    store = HubStore(use_hub_credentials=artifact.kind == "model")
    if artifact.kind == "model":
        from app.services.huggingface.fetch import _inspect_configuration

        published = {}
        for path, expected in manifest["files"].items():
            with (stage / "files" / path).open("rb") as source:
                key = blob_key(artifact, path)
                published[path] = store.publish_verified(
                    key, iter(lambda: source.read(CHUNK_BYTES), b""), expected, max_bytes=maximum
                )
            _inspect_configuration(store, key, path, expected["size_bytes"])
        manifest = {**manifest, "files": published}
    else:
        from app.services.huggingface.datasets import read_bounded_parquet

        retained = manifest["dataset_result"]
        path = next(iter(bundles.durable_files(manifest)))
        row_count, column_count = retained.get("row_count"), retained.get("column_count")
        if (
            type(row_count) is not int
            or type(column_count) is not int
            or row_count < 0
            or row_count > int(settings.tabular_transform_max_rows)
            or not 0 < column_count <= int(settings.tabular_max_columns)
        ):
            raise HFError("HF_TOO_LARGE", "The retained dataset shape exceeds the tabular limits")
        frame = read_bounded_parquet(
            [stage / "files" / path], {"max_rows": row_count + 1, "columns": None}
        )
        if frame.height != row_count or frame.width != column_count:
            raise HFError(
                "HF_MANIFEST_INVALID", "The retained dataset differs from its signed shape"
            )
        key = f"workspaces/{workspace.id}/tabular/hub-artifacts/{artifact.id}/result.parquet"
        published = store.publish_file(key, stage / "files" / path, max_bytes=maximum)
        manifest = {
            **manifest,
            "dataset_result": {**retained, **published, "owner_workspace_id": workspace.id},
        }
    registry.admission_lock(db)
    db.refresh(artifact)
    db.refresh(job)
    reservation = db.get(HubImportReservation, job.id, populate_existing=True)
    if job.status == "cancelled" or not reservation or reservation.expires_at <= datetime.utcnow():
        raise HFError("HF_JOB_INACTIVE", "The offline import was cancelled or expired", 409)
    from app.services.huggingface.access import require_job_actor

    workspace = require_job_actor(db, job)
    if artifact.status == "revoked":
        raise HFError(
            "HF_ARTIFACT_REVOKED", "The artifact was revoked during offline preparation", 403
        )
    # A long transfer must not create a grant from an attestation that expired
    # after initial admission.
    with (directory / "upload.tar").open("rb") as source:
        inspect_bundle(source, workspace.id)
    decision = policy.require_acceptance(
        db,
        workspace,
        artifact.metadata_json,
        manifest.get("license_text", ""),
        actor=job.created_by_user_id,
    )
    if artifact.status == "ready" and artifact.manifest_json != manifest:
        raise HFError(
            "HF_BUNDLE_IDENTITY_CONFLICT",
            "The offline manifest differs from its existing immutable selection",
            409,
        )
    store.publish_manifest(artifact.id, manifest)
    artifact.manifest_json, artifact.manifest_key = (
        manifest,
        f"hub/artifacts/{artifact.id}/manifest.json",
    )
    artifact.status, artifact.imported_at = "ready", artifact.imported_at or datetime.utcnow()
    artifact.files_json = manifest.get("files", artifact.files_json)
    registry._grant(db, workspace, artifact, job.created_by_user_id, decision)
    if reservation:
        db.delete(reservation)
    db.commit()
    return {"artifact_id": artifact.id}


def run_bundle_job(db, job_id: str) -> dict:
    directory = job_directory(job_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / ".worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HFError("HF_JOB_BUSY", "Another worker owns this offline bundle", 409) from exc
        job = db.get(WorkspaceJob, job_id)
        if not job or job.kind not in {"hf_bundle_import", "hf_bundle_export"}:
            raise HFError("HF_NOT_FOUND", "Bundle job not found", 404)
        if job.status == "completed":
            return job.result
        if job.status == "cancelled":
            raise HFError("HF_JOB_INACTIVE", "Bundle job was cancelled", 409)
        try:
            from app.services.huggingface.access import require_job_actor

            require_job_actor(db, job)
            job.status, job.stage, job.started_at = "running", "verifying", datetime.utcnow()
            db.commit()
            result = (
                _export(db, job, directory)
                if job.kind == "hf_bundle_export"
                else _import(db, job, directory)
            )
            db.refresh(job)
            if job.status == "cancelled":
                raise HFError("HF_JOB_INACTIVE", "The offline operation was cancelled", 409)
            job.status, job.stage, job.progress, job.result = "completed", "ready", 100, result
            job.completed_at = datetime.utcnow()
            registry._audit(
                db,
                job.workspace_id,
                "bundle.completed",
                job.created_by_user_id,
                {"job_id": job.id, **result},
            )
            db.commit()
            return result
        except Exception as exc:
            db.rollback()
            job = db.get(WorkspaceJob, job_id)
            if job.status != "cancelled":
                job.status, job.stage = "failed", "failed"
            job.error = getattr(exc, "code", "HF_BUNDLE_FAILED")
            reservation = db.get(HubImportReservation, job.id)
            if reservation:
                db.delete(reservation)
            failed_artifact_id = (job.input_ref or {}).get("artifact_id")
            artifact = db.get(HubArtifact, failed_artifact_id) if failed_artifact_id else None
            if (
                job.kind == "hf_bundle_import"
                and artifact
                and artifact.status not in {"ready", "revoked"}
            ):
                artifact.status, artifact.error_code = "failed", job.error
            registry._audit(
                db,
                job.workspace_id,
                "bundle.failed",
                job.created_by_user_id,
                {"job_id": job.id, "error_code": job.error},
            )
            db.commit()
            raise
        finally:
            if job.kind == "hf_bundle_import":
                shutil.rmtree(directory / "verified", ignore_errors=True)
                (directory / "upload.tar").unlink(missing_ok=True)


def recover_bundle_jobs(db) -> dict:
    """Retry undispatched intents and reclaim expired spool under worker locks."""
    from app.workers.celery_app import celery_app

    now, cleaned, dispatched = datetime.utcnow(), 0, 0
    jobs = (
        db.query(WorkspaceJob)
        .filter(WorkspaceJob.kind.in_(["hf_bundle_import", "hf_bundle_export"]))
        .all()
    )
    for job in jobs:
        directory = job_directory(job.id)
        if not directory.exists():
            continue
        if (
            job.status == "queued"
            and job.stage == "dispatch_pending"
            and job.input_ref.get("task_name")
        ):
            try:
                task = celery_app.send_task(
                    job.input_ref["task_name"],
                    args=[job.id],
                    queue=settings.celery_task_default_queue
                    if job.input_ref.get("dataset_worker")
                    else "hub_fetch",
                )
                job.input_ref = {**job.input_ref, "celery_task_id": task.id}
                job.stage = "queued"
                dispatched += 1
            except Exception:
                pass
        expires = (job.created_at or now) + timedelta(seconds=settings.hf_import_timeout_seconds)
        if (
            job.kind == "hf_bundle_export"
            and job.status == "completed"
            and job.result.get("expires_at")
        ):
            expires = datetime.fromisoformat(job.result["expires_at"]).replace(tzinfo=None)
        if job.status not in {"failed", "cancelled"} and expires > now:
            continue
        with (directory / ".worker.lock").open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            # Preserve the lock inode permanently; a crashed/duplicate worker
            # must not acquire a different inode while cleanup owns this one.
            for child in directory.iterdir():
                if child.name == ".worker.lock":
                    continue
                shutil.rmtree(child) if child.is_dir() else child.unlink(missing_ok=True)
            if job.status not in {"completed", "failed", "cancelled"}:
                job.status, job.stage, job.error = "failed", "expired", "HF_JOB_EXPIRED"
            if job.status == "completed":
                job.result = {**job.result, "download_available": False}
            reservation = db.get(HubImportReservation, job.id)
            if reservation:
                db.delete(reservation)
            cleaned += 1
    db.commit()
    return {"cleaned": cleaned, "dispatched": dispatched}
