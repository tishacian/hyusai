"""Workspace-scoped SFTP operations and reconciliation helpers."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.audit_logger import emit_audit_event
from app.services.workspace_jobs import transition_job

SFTP_RECONCILIATION_JOB_KIND = "sftp_reconciliation"
SFTP_UPLOAD_IDLE_SECONDS = 60
SFTP_RECONCILIATION_CONFIRM_TTL_HOURS = 2
SFTP_DEFAULT_STALE_AFTER_HOURS = 24
SFTP_MAX_OPERATION_ITEMS = 200


def sftp_upload_sidecar_path(part_path: Path) -> Path:
    return part_path.with_name(f"{part_path.name}.meta.json")


def write_sftp_upload_sidecar(
    part_path: Path,
    *,
    access_id: str,
    workspace_id: str,
    filename: str,
    max_bytes: int,
) -> Path:
    sidecar = sftp_upload_sidecar_path(part_path)
    payload = {
        "access_id": access_id,
        "workspace_id": workspace_id,
        "filename": filename,
        "created_at": datetime.utcnow().isoformat(),
        "max_bytes": int(max_bytes),
        "part_file": part_path.name,
    }
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return sidecar


def delete_sftp_upload_sidecar(part_path: Path) -> None:
    try:
        sftp_upload_sidecar_path(part_path).unlink(missing_ok=True)
    except OSError:
        pass


def get_sftp_operations_snapshot(
    db: DBSession,
    *,
    workspace: Workspace,
    stale_after_hours: int = SFTP_DEFAULT_STALE_AFTER_HOURS,
) -> dict[str, Any]:
    partials = _scan_partials(db, workspace=workspace, stale_after_hours=stale_after_hours)
    links = _workspace_links(db, workspace.id)
    status_rows = (
        db.query(DepositFile.status, DepositFile.size_bytes)
        .filter(DepositFile.workspace_id == workspace.id)
        .all()
    )
    latest_file = (
        db.query(DepositFile)
        .filter(DepositFile.workspace_id == workspace.id)
        .order_by(DepositFile.uploaded_at.desc())
        .first()
    )
    last_jobs = (
        db.query(WorkspaceJob)
        .filter(WorkspaceJob.workspace_id == workspace.id, WorkspaceJob.kind == SFTP_RECONCILIATION_JOB_KIND)
        .order_by(WorkspaceJob.updated_at.desc(), WorkspaceJob.created_at.desc())
        .limit(5)
        .all()
    )
    latest_reconciliation = last_jobs[0].result if last_jobs else {}
    active_uploads = [item for item in partials["items"] if item["attributed"]]
    return {
        "stale_after_hours": stale_after_hours,
        "poll_interval_seconds": 5,
        "active_uploads": active_uploads,
        "stale_partials": [item for item in active_uploads if item["status"] == "stale_candidate"],
        "storage_summary": {
            "active_count": sum(1 for item in active_uploads if item["status"] == "receiving"),
            "idle_count": sum(1 for item in active_uploads if item["status"] == "idle"),
            "stale_count": sum(1 for item in active_uploads if item["status"] == "stale_candidate"),
            "temporary_count": len(active_uploads),
            "temporary_size_bytes": sum(int(item["size_bytes"] or 0) for item in active_uploads),
            "unattributed_partial_count": partials["unattributed_count"],
            "unattributed_partial_size_bytes": partials["unattributed_size_bytes"],
            "last_received_at": latest_file.uploaded_at.isoformat() if latest_file and latest_file.uploaded_at else None,
            "last_received_filename": latest_file.filename if latest_file else None,
            "deposit_counts": _deposit_counts(status_rows),
            "link_count": len(links),
        },
        "reconciliation_summary": _compact_reconciliation_summary(latest_reconciliation),
        "last_jobs": [_serialize_workspace_job(job) for job in last_jobs],
    }


def run_sftp_reconciliation_job(job_id: str) -> dict[str, Any]:
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
        if not job:
            return {"status": "failed", "error": "workspace_job_not_found"}
        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        if not workspace:
            return {"status": "failed", "error": "workspace_not_found"}

        input_ref = dict(job.input_ref or {})
        mode = str(input_ref.get("mode") or "dry_run")
        stale_after_hours = _safe_stale_hours(input_ref.get("stale_after_hours"))
        actor = str(input_ref.get("actor") or "system")

        transition_job(db, workspace, job, "running", progress=10, stage="scanning", user=None)
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="deposit.sftp.reconciliation.started",
            actor=actor,
            details={"job_id": job.id, "mode": mode, "stale_after_hours": stale_after_hours},
        )
        db.commit()

        if mode == "dry_run":
            result = _build_reconciliation_report(db, workspace=workspace, stale_after_hours=stale_after_hours)
            result["mode"] = "dry_run"
            result["status"] = "dry_run"
            transition_job(db, workspace, job, "completed", progress=100, stage="dry_run_completed", result=result, user=None)
        elif mode == "quarantine":
            result = _run_quarantine(db, workspace=workspace, job=job, stale_after_hours=stale_after_hours, actor=actor)
            transition_job(db, workspace, job, "completed", progress=100, stage="quarantine_completed", result=result, user=None)
        else:
            raise ValueError("Unsupported reconciliation mode")

        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="deposit.sftp.reconciliation.completed",
            actor=actor,
            details={"job_id": job.id, "mode": mode, "result": _compact_reconciliation_summary(job.result or result)},
        )
        _emit_sftp_file_arrived_event(db, workspace=workspace, job=job, mode=mode, result=result)
        db.commit()
        return job.result or result
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first() if job else None
        if job and workspace:
            transition_job(db, workspace, job, "failed", progress=job.progress, stage="failed", error=str(exc), user=None)
            db.commit()
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


def _emit_sftp_file_arrived_event(
    db: DBSession,
    *,
    workspace: Workspace,
    job: WorkspaceJob,
    mode: str,
    result: dict[str, Any],
) -> None:
    """Fire the Phase 3 ``sftp.file_arrived`` event trigger (flag-gated, safe).

    Inert unless the global master switch OR workspace opt-in is ON. Governance
    restricts this event to analysis / notification runs ONLY — it can NEVER
    trigger ingestion (that stays an explicit operator promotion). Any failure
    is swallowed so a trigger problem never breaks reconciliation.
    """
    try:
        from app.services.run_engine import triggers

        if not triggers.is_event_triggers_enabled(workspace.id, db=db):
            return
        summary = _compact_reconciliation_summary(result) if isinstance(result, dict) else {}
        triggers.emit_sftp_file_arrived(
            db,
            workspace_id=workspace.id,
            payload={
                "workspace_id": workspace.id,
                "job_id": job.id,
                "mode": mode,
                "reconciled_at": summary.get("generated_at"),
                "source": "sftp_reconciliation",
            },
        )
    except Exception:  # noqa: BLE001 — never break reconciliation.
        pass


def _run_quarantine(
    db: DBSession,
    *,
    workspace: Workspace,
    job: WorkspaceJob,
    stale_after_hours: int,
    actor: str,
) -> dict[str, Any]:
    input_ref = dict(job.input_ref or {})
    confirm_from_job_id = str(input_ref.get("confirm_from_job_id") or "")
    dry_run_job = (
        db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.id == confirm_from_job_id,
            WorkspaceJob.workspace_id == workspace.id,
            WorkspaceJob.kind == SFTP_RECONCILIATION_JOB_KIND,
            WorkspaceJob.status == "completed",
        )
        .first()
    )
    if not dry_run_job:
        raise ValueError("A completed dry-run job is required before quarantine")
    dry_result = dict(dry_run_job.result or {})
    if dry_result.get("mode") != "dry_run":
        raise ValueError("Confirmation job is not a dry-run")
    if int(dry_result.get("stale_after_hours") or 0) != stale_after_hours:
        raise ValueError("Dry-run threshold does not match quarantine threshold")
    if dry_run_job.completed_at and dry_run_job.completed_at < datetime.utcnow() - timedelta(hours=SFTP_RECONCILIATION_CONFIRM_TTL_HOURS):
        raise ValueError("Dry-run confirmation is too old")

    transition_job(db, workspace, job, "running", progress=40, stage="quarantining", user=None)
    db.commit()

    quarantine_root = _quarantine_root(workspace.id, job.id)
    cutoff = datetime.utcnow() - timedelta(hours=stale_after_hours)
    partial_results = []
    final_results = []
    for item in dry_result.get("stale_partials", []):
        partial_results.append(_quarantine_partial(db, workspace=workspace, item=item, root=quarantine_root, actor=actor, cutoff=cutoff))
    for item in dry_result.get("orphan_files", []):
        final_results.append(_quarantine_orphan(db, workspace=workspace, item=item, root=quarantine_root, actor=actor, cutoff=cutoff))

    result = {
        "mode": "quarantine",
        "status": "quarantined",
        "workspace_id": workspace.id,
        "stale_after_hours": stale_after_hours,
        "confirm_from_job_id": dry_run_job.id,
        "quarantine_root": _relative_to_storage(quarantine_root),
        "partial_results": partial_results,
        "orphan_results": final_results,
        "quarantined_partial_count": sum(1 for item in partial_results if item["status"] == "quarantined"),
        "quarantined_orphan_count": sum(1 for item in final_results if item["status"] == "quarantined"),
        "skipped_count": sum(1 for item in [*partial_results, *final_results] if item["status"] != "quarantined"),
    }
    result["summary"] = _compact_reconciliation_summary(result)
    return result


def _build_reconciliation_report(
    db: DBSession,
    *,
    workspace: Workspace,
    stale_after_hours: int,
) -> dict[str, Any]:
    cutoff = datetime.utcnow() - timedelta(hours=stale_after_hours)
    partials = _scan_partials(db, workspace=workspace, stale_after_hours=stale_after_hours)
    stale_partials = [item for item in partials["items"] if item["attributed"] and item["status"] == "stale_candidate"]
    db_files = db.query(DepositFile).filter(DepositFile.workspace_id == workspace.id).all()
    known_keys = {str(row.object_key) for row in db_files if row.object_key and row.object_key != "pending"}
    expected_rows = {str(row.object_key): row for row in db_files if row.object_key and row.object_key != "pending"}

    orphan_files = []
    for path in _iter_workspace_storage_files(workspace.id):
        key = _relative_to_storage(path)
        if not key or key in known_keys:
            continue
        modified_at = _datetime_from_mtime(path)
        item = _file_item(path, key=key, modified_at=modified_at)
        item["status"] = "orphan_stale" if modified_at < cutoff else "orphan_recent"
        item["actionable"] = bool(modified_at < cutoff)
        if len(orphan_files) < SFTP_MAX_OPERATION_ITEMS:
            orphan_files.append(item)

    missing_db_files = []
    pending_rows = []
    for row in db_files:
        if row.object_key == "pending" or not row.object_key or not row.sha256:
            pending_rows.append(_deposit_row_item(row))
            continue
        if row.object_key in expected_rows and not _storage_path(row.object_key).is_file():
            missing_db_files.append(_deposit_row_item(row))

    report = {
        "workspace_id": workspace.id,
        "stale_after_hours": stale_after_hours,
        "generated_at": datetime.utcnow().isoformat(),
        "stale_partials": stale_partials[:SFTP_MAX_OPERATION_ITEMS],
        "orphan_files": [item for item in orphan_files if item["actionable"]],
        "recent_orphan_files": [item for item in orphan_files if not item["actionable"]],
        "missing_db_files": missing_db_files[:SFTP_MAX_OPERATION_ITEMS],
        "pending_rows": pending_rows[:SFTP_MAX_OPERATION_ITEMS],
        "unattributed_partial_count": partials["unattributed_count"],
        "unattributed_partial_size_bytes": partials["unattributed_size_bytes"],
        "counts": {
            "stale_partials": len(stale_partials),
            "orphan_files": sum(1 for item in orphan_files if item["actionable"]),
            "recent_orphan_files": sum(1 for item in orphan_files if not item["actionable"]),
            "missing_db_files": len(missing_db_files),
            "pending_rows": len(pending_rows),
            "unattributed_partials": partials["unattributed_count"],
        },
        "sizes": {
            "stale_partial_bytes": sum(int(item["size_bytes"] or 0) for item in stale_partials),
            "orphan_file_bytes": sum(int(item["size_bytes"] or 0) for item in orphan_files if item["actionable"]),
        },
    }
    report["summary"] = _compact_reconciliation_summary(report)
    return report


def _scan_partials(
    db: DBSession,
    *,
    workspace: Workspace,
    stale_after_hours: int,
) -> dict[str, Any]:
    links = _workspace_links(db, workspace.id)
    access_to_link = {link.access_id: link for link in links}
    cutoff = datetime.utcnow() - timedelta(hours=stale_after_hours)
    items = []
    unattributed_count = 0
    unattributed_size = 0
    for path in _sftp_temp_dir().glob("*.part"):
        sidecar = _read_sidecar(path)
        stat = path.stat()
        modified_at = _datetime_from_mtime(path)
        created_at = _parse_datetime(sidecar.get("created_at")) if sidecar else None
        attributed = bool(
            sidecar
            and sidecar.get("workspace_id") == workspace.id
            and str(sidecar.get("access_id") or "") in access_to_link
        )
        if not attributed:
            unattributed_count += 1
            unattributed_size += int(stat.st_size or 0)
            items.append(_partial_item(path, sidecar, None, modified_at, created_at, cutoff, attributed=False))
            continue
        link = access_to_link[str(sidecar.get("access_id"))]
        items.append(_partial_item(path, sidecar, link, modified_at, created_at, cutoff, attributed=True))
    return {"items": items, "unattributed_count": unattributed_count, "unattributed_size_bytes": unattributed_size}


def _partial_item(
    path: Path,
    sidecar: dict[str, Any] | None,
    link: DepositAccessLink | None,
    modified_at: datetime,
    created_at: datetime | None,
    cutoff: datetime,
    *,
    attributed: bool,
) -> dict[str, Any]:
    now = datetime.utcnow()
    size = path.stat().st_size
    idle_seconds = max(0, int((now - modified_at).total_seconds()))
    age_seconds = max(0, int((now - (created_at or modified_at)).total_seconds()))
    if modified_at < cutoff:
        status = "stale_candidate"
    elif idle_seconds > SFTP_UPLOAD_IDLE_SECONDS:
        status = "idle"
    else:
        status = "receiving"
    filename = str((sidecar or {}).get("filename") or path.name)
    return {
        "id": _stable_id(_relative_to_storage(path) or path.name),
        "temp_name": path.name,
        "filename": filename,
        "access_id": str((sidecar or {}).get("access_id") or ""),
        "link_id": link.id if link else None,
        "link_label": link.label if link else None,
        "workspace_id": str((sidecar or {}).get("workspace_id") or ""),
        "size_bytes": int(size or 0),
        "max_bytes": int((sidecar or {}).get("max_bytes") or 0),
        "created_at": (created_at or modified_at).isoformat(),
        "modified_at": modified_at.isoformat(),
        "age_seconds": age_seconds,
        "idle_seconds": idle_seconds,
        "status": status,
        "attributed": attributed,
        "actionable": bool(attributed and status == "stale_candidate"),
    }


def _quarantine_partial(
    db: DBSession,
    *,
    workspace: Workspace,
    item: dict[str, Any],
    root: Path,
    actor: str,
    cutoff: datetime,
) -> dict[str, Any]:
    path = _sftp_temp_dir() / str(item.get("temp_name") or "")
    if not path.is_file():
        return {"status": "skipped", "reason": "missing", "temp_name": item.get("temp_name")}
    if _datetime_from_mtime(path) >= cutoff:
        return {"status": "skipped", "reason": "recent_or_active", "temp_name": path.name}
    sidecar = _read_sidecar(path)
    if not sidecar or sidecar.get("workspace_id") != workspace.id:
        return {"status": "skipped", "reason": "unattributed_or_mismatched", "temp_name": path.name}
    destination = _safe_destination(root / "partials", Path(path.name))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), destination)
    sidecar_path = sftp_upload_sidecar_path(path)
    if sidecar_path.exists():
        sidecar_destination = destination.with_name(f"{destination.name}.meta.json")
        shutil.move(str(sidecar_path), sidecar_destination)
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.sftp.partial.quarantined",
        actor=actor,
        details={"filename": item.get("filename"), "temp_name": path.name, "destination": _relative_to_storage(destination)},
    )
    return {
        "status": "quarantined",
        "filename": item.get("filename"),
        "temp_name": path.name,
        "destination": _relative_to_storage(destination),
        "size_bytes": item.get("size_bytes") or 0,
    }


def _quarantine_orphan(
    db: DBSession,
    *,
    workspace: Workspace,
    item: dict[str, Any],
    root: Path,
    actor: str,
    cutoff: datetime,
) -> dict[str, Any]:
    key = str(item.get("object_key") or "")
    path = _storage_path(key)
    if not path.is_file():
        return {"status": "skipped", "reason": "missing", "object_key": key}
    if _datetime_from_mtime(path) >= cutoff:
        return {"status": "skipped", "reason": "recent_or_active", "object_key": key}
    if not key.startswith(f"workspaces/{workspace.id}/secure-deposit/"):
        return {"status": "skipped", "reason": "workspace_mismatch", "object_key": key}
    destination = _safe_destination(root / "orphan-files", Path(key))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), destination)
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.sftp.orphan.quarantined",
        actor=actor,
        details={"object_key": key, "destination": _relative_to_storage(destination), "size_bytes": item.get("size_bytes") or 0},
    )
    return {
        "status": "quarantined",
        "object_key": key,
        "destination": _relative_to_storage(destination),
        "size_bytes": item.get("size_bytes") or 0,
    }


def _workspace_links(db: DBSession, workspace_id: str) -> list[DepositAccessLink]:
    return db.query(DepositAccessLink).filter(DepositAccessLink.workspace_id == workspace_id).all()


def _deposit_counts(rows: list[tuple[str, int]]) -> dict[str, dict[str, int]]:
    counts = {
        "received": {"count": 0, "size_bytes": 0},
        "promoted": {"count": 0, "size_bytes": 0},
        "rejected": {"count": 0, "size_bytes": 0},
    }
    for status, size in rows:
        bucket = counts.setdefault(str(status or "unknown"), {"count": 0, "size_bytes": 0})
        bucket["count"] += 1
        bucket["size_bytes"] += int(size or 0)
    return counts


def _compact_reconciliation_summary(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {}
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    sizes = result.get("sizes") if isinstance(result.get("sizes"), dict) else {}
    return {
        "mode": result.get("mode"),
        "status": result.get("status"),
        "stale_after_hours": result.get("stale_after_hours"),
        "stale_partials": counts.get("stale_partials", result.get("quarantined_partial_count", 0)),
        "orphan_files": counts.get("orphan_files", result.get("quarantined_orphan_count", 0)),
        "missing_db_files": counts.get("missing_db_files", 0),
        "pending_rows": counts.get("pending_rows", 0),
        "unattributed_partials": counts.get("unattributed_partials", result.get("unattributed_partial_count", 0)),
        "stale_partial_bytes": sizes.get("stale_partial_bytes", 0),
        "orphan_file_bytes": sizes.get("orphan_file_bytes", 0),
        "generated_at": result.get("generated_at"),
        "confirm_from_job_id": result.get("confirm_from_job_id"),
    }


def _serialize_workspace_job(job: WorkspaceJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "title": job.title,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
        "input_ref": job.input_ref or {},
        "result": job.result or {},
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "poll_url": f"/workspace-jobs/{job.id}",
    }


def _deposit_row_item(row: DepositFile) -> dict[str, Any]:
    return {
        "id": row.id,
        "filename": row.filename,
        "object_key": row.object_key,
        "status": row.status,
        "size_bytes": int(row.size_bytes or 0),
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
    }


def _file_item(path: Path, *, key: str, modified_at: datetime) -> dict[str, Any]:
    stat = path.stat()
    return {
        "id": _stable_id(key),
        "object_key": key,
        "filename": path.name,
        "size_bytes": int(stat.st_size or 0),
        "modified_at": modified_at.isoformat(),
    }


def _iter_workspace_storage_files(workspace_id: str):
    root = _storage_path(f"workspaces/{workspace_id}/secure-deposit")
    if not root.exists():
        return
    quarantine = _storage_root() / "_quarantine"
    for path in root.rglob("*"):
        if path.is_file() and quarantine not in path.parents:
            yield path


def _read_sidecar(part_path: Path) -> dict[str, Any] | None:
    sidecar = sftp_upload_sidecar_path(part_path)
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


def _datetime_from_mtime(path: Path) -> datetime:
    return datetime.utcfromtimestamp(path.stat().st_mtime)


def _storage_root() -> Path:
    root = Path(settings.secure_deposit_storage_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _storage_path(key: str) -> Path:
    root = _storage_root()
    path = (root / str(key).strip("/")).resolve()
    if root not in path.parents and path != root:
        raise ValueError("Secure Deposit path escapes storage root")
    return path


def _relative_to_storage(path: Path) -> str:
    root = _storage_root()
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return ""


def _sftp_temp_dir() -> Path:
    path = Path(settings.secure_deposit_sftp_temp_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quarantine_root(workspace_id: str, job_id: str) -> Path:
    return _storage_root() / "_quarantine" / workspace_id / datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") / job_id


def _safe_destination(root: Path, relative: Path) -> Path:
    clean_parts = [part for part in relative.parts if part not in {"", "/", ".", ".."}]
    destination = (root / Path(*clean_parts)).resolve()
    root_resolved = root.resolve()
    if root_resolved not in destination.parents and destination != root_resolved:
        raise ValueError("Quarantine destination escapes root")
    return destination


def _safe_stale_hours(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:  # noqa: BLE001
        parsed = SFTP_DEFAULT_STALE_AFTER_HOURS
    return max(1, min(parsed, 24 * 30))


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]
