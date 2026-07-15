"""Controlled SPL ingestion waves for Andritz Secure Deposit archives.

V1 promotes a small pilot set. V2 expands by project code with a wave ledger.
V3 ingests remaining unique archives (folder + size-aware batches) with ledger resume.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.knowledge_collection import KnowledgeCollection
from app.models.secure_deposit import DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.iam.app_entitlements import (
    lock_workspace_for_app_entitlement_mutation,
)
from app.services.knowledge_collections import (
    create_or_get_collection,
    create_worker_job,
    document_manifest_key,
    original_key,
    update_collection_status,
)
from app.services.object_store import get_object_store
from app.services.secure_deposit import (
    _read_supported_archive_documents,
    _unique_archive_name,
    archive_document_namespace,
    extension_for,
    staged_file_path,
)
from app.services.worker_dispatch import dispatch_worker_job

DEFAULT_SPL_COLLECTION = "andritz-notices-techniques-spl-pilot"
DEFAULT_SPL_PREFIX = "Notices_Techniques_SPL/"
V1_DEFAULT_ARCHIVES = (
    "Notices_Techniques_SPL/B/Manual_BBA120.zip",
    "Notices_Techniques_SPL/A/ACO140.zip",
)
V1_DEFAULT_COPY_FROM = "andritz-manuals-bba120-pilot"
V2_DEFAULT_PROJECTS = ("ACO_130", "AKK200", "ACO150", "ARA200", "DCI110", "DCI 110")
ARCHIVE_LIMIT_OVERRIDES: dict[str, dict[str, int | float]] = {
    "Notices_Techniques_SPL/A/AKK200.zip": {"max_files": 450, "max_archive_mb": 800},
    "Notices_Techniques_SPL/A/Manual_ASY100.zip": {"max_files": 2000, "max_archive_mb": 3500},
    "Notices_Techniques_SPL/A/Manual_ASY200.zip": {"max_files": 2000, "max_archive_mb": 3500},
    "Notices_Techniques_SPL/A/Manual_ACJ200-revA.zip": {"max_files": 1500, "max_archive_mb": 3000},
    "Notices_Techniques_SPL/A/Manual_AKI500_revA.zip": {"max_files": 1200, "max_archive_mb": 2000},
    "Notices_Techniques_SPL/A/Manual_AKI500.zip": {"max_files": 1200, "max_archive_mb": 2000},
    "Notices_Techniques_SPL/B/Manual_BHX100_revD.zip": {"max_files": 3000, "max_archive_mb": 9000},
    "Notices_Techniques_SPL/B/Manual_BHX100_revC.zip": {"max_files": 2500, "max_archive_mb": 6000},
    "Notices_Techniques_SPL/B/Manual_BIO100 rev A.zip": {"max_files": 2500, "max_archive_mb": 6000},
    "Notices_Techniques_SPL/B/Manual_BHX100_revB.zip": {"max_files": 2000, "max_archive_mb": 5000},
    "Notices_Techniques_SPL/B/Manual_BHX100_revA.zip": {"max_files": 2000, "max_archive_mb": 5000},
    "Notices_Techniques_SPL/B/Manual_BCX300 rev C.zip": {"max_files": 1500, "max_archive_mb": 4000},
}
V2_LARGE_ARCHIVE_OVERRIDES = ARCHIVE_LIMIT_OVERRIDES
V3_SOLO_ARCHIVE_MB = 800.0


@dataclass(frozen=True)
class WaveLimits:
    max_archive_mb: float = 500.0
    max_files_per_archive: int = 200
    max_documents_per_wave: int = 250

    @classmethod
    def v1(cls) -> "WaveLimits":
        return cls(max_archive_mb=500.0, max_files_per_archive=200, max_documents_per_wave=250)

    @classmethod
    def v2(cls) -> "WaveLimits":
        return cls(max_archive_mb=800.0, max_files_per_archive=450, max_documents_per_wave=450)

    @classmethod
    def v3(cls) -> "WaveLimits":
        return cls(max_archive_mb=1200.0, max_files_per_archive=800, max_documents_per_wave=500)


V1_MAX_ARCHIVE_MB = WaveLimits.v1().max_archive_mb
V1_MAX_FILES_PER_ARCHIVE = WaveLimits.v1().max_files_per_archive
V1_MAX_DOCUMENTS_PER_WAVE = WaveLimits.v1().max_documents_per_wave


@dataclass
class ArchiveInspectResult:
    deposit_file_id: str
    filename: str
    status: str
    compressed_mb: float
    supported_files: int
    supported_uncompressed_mb: float
    truncated_files: int = 0
    promotable: bool = True
    reason: str | None = None


@dataclass
class WavePlan:
    workspace_slug: str
    collection_slug: str
    wave_id: str = "spl_v1"
    archives: list[ArchiveInspectResult] = field(default_factory=list)
    total_documents: int = 0
    total_uncompressed_mb: float = 0.0
    dry_run: bool = True
    skipped_ledger: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace_slug": self.workspace_slug,
            "collection_slug": self.collection_slug,
            "wave_id": self.wave_id,
            "dry_run": self.dry_run,
            "skipped_ledger": self.skipped_ledger,
            "archive_count": len(self.archives),
            "total_documents": self.total_documents,
            "total_uncompressed_mb": round(self.total_uncompressed_mb, 2),
            "archives": [
                {
                    "deposit_file_id": item.deposit_file_id,
                    "filename": item.filename,
                    "status": item.status,
                    "compressed_mb": round(item.compressed_mb, 2),
                    "supported_files": item.supported_files,
                    "supported_uncompressed_mb": round(item.supported_uncompressed_mb, 2),
                    "truncated_files": item.truncated_files,
                    "promotable": item.promotable,
                    "reason": item.reason,
                }
                for item in self.archives
            ],
        }


def _archive_limits(filename: str, limits: WaveLimits) -> tuple[int, float]:
    override = ARCHIVE_LIMIT_OVERRIDES.get(filename) or {}
    max_files = int(override.get("max_files") or limits.max_files_per_archive)
    max_mb = float(override.get("max_archive_mb") or limits.max_archive_mb)
    return max_files, max_mb


def _normalize_project_token(token: str) -> str:
    return re.sub(r"[\s_]+", "", (token or "").upper())


def _project_code_from_filename(filename: str) -> str | None:
    name = (filename or "").split("/")[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    match = re.search(r"([A-Z]{3})[\s_]?(\d{2,4})", stem.upper())
    if not match:
        return None
    return f"{match.group(1)}{match.group(2)}"


def get_wave_ledger(workspace: Workspace, *, collection_slug: str) -> dict[str, Any]:
    settings = dict(workspace.settings or {})
    ledger = settings.get("spl_wave_ledger") or {}
    return dict(ledger.get(collection_slug) or {})


def record_wave_ledger(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_slug: str,
    wave_id: str,
    filenames: Iterable[str],
    job_id: str | None,
    new_document_count: int,
) -> None:
    workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    recorded_filenames = tuple(str(name) for name in filenames if name)
    settings = dict(workspace.settings or {})
    ledger = dict(settings.get("spl_wave_ledger") or {})
    bucket = dict(ledger.get(collection_slug) or {})
    promoted = set(bucket.get("promoted_filenames") or [])
    promoted.update(recorded_filenames)
    waves = list(bucket.get("waves") or [])
    waves.append(
        {
            "wave_id": wave_id,
            "filenames": list(recorded_filenames),
            "job_id": job_id,
            "new_document_count": new_document_count,
            "completed_at": datetime.utcnow().isoformat(),
        }
    )
    bucket["promoted_filenames"] = sorted(promoted)
    bucket["waves"] = waves[-50:]
    ledger[collection_slug] = bucket
    settings["spl_wave_ledger"] = ledger
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)


def resolve_archives_for_projects(
    db: DBSession,
    *,
    workspace: Workspace,
    projects: Iterable[str],
) -> list[str]:
    tokens = {_normalize_project_token(token) for token in projects if token}
    matches: list[tuple[float, str]] = []
    for row in list_spl_zip_deposits(db, workspace_id=workspace.id):
        code = _project_code_from_filename(str(row.filename or ""))
        if not code:
            continue
        if _normalize_project_token(code) not in tokens:
            continue
        matches.append((float(row.size_bytes or 0), str(row.filename or "")))
    matches.sort(key=lambda item: item[0])
    return [filename for _, filename in matches]


def inspect_archive_deposit_file(
    deposit_file: DepositFile,
    *,
    limits: WaveLimits | None = None,
    max_files: int | None = None,
    max_uncompressed_mb: float | None = None,
) -> ArchiveInspectResult:
    limits = limits or WaveLimits.v1()
    filename = str(deposit_file.filename or "")
    default_files, default_mb = _archive_limits(filename, limits)
    max_files = int(max_files or default_files)
    max_uncompressed_mb = float(
        max_uncompressed_mb if max_uncompressed_mb is not None else default_mb
    )
    compressed_mb = float(deposit_file.size_bytes or 0) / (1024 * 1024)
    base = ArchiveInspectResult(
        deposit_file_id=deposit_file.id,
        filename=str(deposit_file.filename or ""),
        status=str(deposit_file.status or ""),
        compressed_mb=compressed_mb,
        supported_files=0,
        supported_uncompressed_mb=0.0,
    )
    if deposit_file.status == "rejected":
        base.promotable = False
        base.reason = "rejected"
        return base
    source_path = staged_file_path(deposit_file)
    if not source_path.exists():
        base.promotable = False
        base.reason = "staged_file_missing"
        return base
    if extension_for(deposit_file.filename or "") != "zip":
        base.promotable = False
        base.reason = "not_a_zip"
        return base
    try:
        documents, stats = _read_supported_archive_documents(
            source_path,
            deposit_filename=deposit_file.filename,
            max_files=max_files,
            max_uncompressed_bytes=int(max_uncompressed_mb * 1024 * 1024),
            on_limit="truncate",
            include_content=False,
        )
    except Exception as exc:  # noqa: BLE001
        base.promotable = False
        base.reason = str(exc)
        return base
    uncompressed = sum(int(doc.get("size_bytes") or 0) for doc in documents)
    base.supported_files = len(documents)
    base.supported_uncompressed_mb = uncompressed / (1024 * 1024)
    base.truncated_files = int(stats.get("truncated_files") or 0)
    if not documents:
        base.promotable = False
        base.reason = "no_supported_documents"
    return base


def _spl_folder_letter(filename: str) -> str:
    relative = str(filename or "").replace(DEFAULT_SPL_PREFIX, "")
    return relative.split("/")[0] if "/" in relative else "_"


def list_remaining_spl_archive_filenames(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_slug: str,
    skip_ledger: bool = True,
    folder: str | None = None,
) -> list[str]:
    """Unique SPL zip paths not yet recorded in the wave ledger."""
    ledger = get_wave_ledger(workspace, collection_slug=collection_slug)
    promoted = set(ledger.get("promoted_filenames") or [])
    seen: set[str] = set()
    remaining: list[str] = []
    for row in list_spl_zip_deposits(db, workspace_id=workspace.id):
        filename = str(row.filename or "")
        if filename in seen:
            continue
        seen.add(filename)
        if skip_ledger and filename in promoted:
            continue
        if folder and _spl_folder_letter(filename) != folder:
            continue
        remaining.append(filename)
    return remaining


def list_spl_zip_deposits(
    db: DBSession,
    *,
    workspace_id: str,
    prefix: str = DEFAULT_SPL_PREFIX,
) -> list[DepositFile]:
    rows = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace_id,
            DepositFile.filename.like(f"{prefix}%"),
            DepositFile.filename.like("%.zip"),
        )
        .all()
    )
    return sorted(rows, key=lambda row: float(row.size_bytes or 0))


def build_wave_plan(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_slug: str,
    archive_filenames: Iterable[str],
    allow_repromote: bool = True,
    dry_run: bool = True,
    limits: WaveLimits | None = None,
    wave_id: str = "spl_v1",
    skip_ledger: bool = True,
) -> WavePlan:
    limits = limits or WaveLimits.v1()
    plan = WavePlan(
        workspace_slug=workspace.slug,
        collection_slug=collection_slug,
        dry_run=dry_run,
        wave_id=wave_id,
    )
    ledger = get_wave_ledger(workspace, collection_slug=collection_slug)
    promoted_filenames = set(ledger.get("promoted_filenames") or [])
    by_name = _deposit_by_unique_filename(db, workspace_id=workspace.id)
    for filename in archive_filenames:
        if skip_ledger and filename in promoted_filenames:
            plan.skipped_ledger.append(filename)
            continue
        deposit_file = by_name.get(filename)
        if not deposit_file:
            plan.archives.append(
                ArchiveInspectResult(
                    deposit_file_id="",
                    filename=filename,
                    status="missing",
                    compressed_mb=0.0,
                    supported_files=0,
                    supported_uncompressed_mb=0.0,
                    promotable=False,
                    reason="deposit_file_not_found",
                )
            )
            continue
        if deposit_file.status == "promoted" and not allow_repromote:
            plan.archives.append(
                ArchiveInspectResult(
                    deposit_file_id=deposit_file.id,
                    filename=filename,
                    status=deposit_file.status,
                    compressed_mb=float(deposit_file.size_bytes or 0) / (1024 * 1024),
                    supported_files=0,
                    supported_uncompressed_mb=0.0,
                    promotable=False,
                    reason="already_promoted",
                )
            )
            continue
        inspected = inspect_archive_deposit_file(deposit_file, limits=limits)
        plan.archives.append(inspected)
        if inspected.promotable:
            plan.total_documents += inspected.supported_files
            plan.total_uncompressed_mb += inspected.supported_uncompressed_mb
    promotable_count = sum(1 for item in plan.archives if item.promotable and item.deposit_file_id)
    if promotable_count > 1 and plan.total_documents > limits.max_documents_per_wave:
        plan.archives.append(
            ArchiveInspectResult(
                deposit_file_id="",
                filename="__wave_limit__",
                status="blocked",
                compressed_mb=0.0,
                supported_files=0,
                supported_uncompressed_mb=0.0,
                promotable=False,
                reason=f"wave_exceeds_{limits.max_documents_per_wave}_documents",
            )
        )
    return plan


def build_v2_wave_plans(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_slug: str,
    projects: Iterable[str] | None = None,
    dry_run: bool = True,
    skip_ledger: bool = True,
) -> list[WavePlan]:
    """Split V2 work into promotable batches (large AKK200 isolated)."""
    limits = WaveLimits.v2()
    filenames = resolve_archives_for_projects(
        db, workspace=workspace, projects=projects or V2_DEFAULT_PROJECTS
    )
    akk = [name for name in filenames if "AKK200" in name.upper()]
    rest = [name for name in filenames if name not in akk]
    batches: list[list[str]] = []
    if rest:
        batches.append(rest)
    if akk:
        batches.append(akk)
    plans: list[WavePlan] = []
    for index, batch in enumerate(batches, start=1):
        plans.append(
            build_wave_plan(
                db,
                workspace=workspace,
                collection_slug=collection_slug,
                archive_filenames=batch,
                allow_repromote=True,
                dry_run=dry_run,
                limits=limits,
                wave_id=f"spl_v2_{index}",
                skip_ledger=skip_ledger,
            )
        )
    return plans


def _deposit_by_unique_filename(
    db: DBSession,
    *,
    workspace_id: str,
) -> dict[str, DepositFile]:
    def _score(row: DepositFile) -> tuple[int, float, datetime]:
        status_rank = 0 if row.status == "rejected" else 1
        uploaded_at = row.uploaded_at or datetime.min
        return (status_rank, float(row.size_bytes or 0), uploaded_at)

    by_name: dict[str, DepositFile] = {}
    for row in list_spl_zip_deposits(db, workspace_id=workspace_id):
        filename = str(row.filename or "")
        existing = by_name.get(filename)
        if existing is None or _score(row) > _score(existing):
            by_name[filename] = row
    return by_name


def _pack_v3_archive_batches(
    db: DBSession,
    *,
    workspace: Workspace,
    filenames: Iterable[str],
    limits: WaveLimits,
    solo_archive_mb: float = V3_SOLO_ARCHIVE_MB,
) -> list[list[str]]:
    """Greedy batches: large archives isolated, smaller ones packed by doc count."""
    by_name = _deposit_by_unique_filename(db, workspace_id=workspace.id)
    inspected_rows: list[tuple[float, str, ArchiveInspectResult]] = []
    for filename in filenames:
        deposit_file = by_name.get(filename)
        if not deposit_file:
            inspected_rows.append(
                (
                    0.0,
                    filename,
                    ArchiveInspectResult(
                        deposit_file_id="",
                        filename=filename,
                        status="missing",
                        compressed_mb=0.0,
                        supported_files=0,
                        supported_uncompressed_mb=0.0,
                        promotable=False,
                        reason="deposit_file_not_found",
                    ),
                )
            )
            continue
        inspected = inspect_archive_deposit_file(deposit_file, limits=limits)
        inspected_rows.append((float(deposit_file.size_bytes or 0), filename, inspected))

    inspected_rows.sort(key=lambda item: item[0], reverse=True)
    batches: list[list[str]] = []
    current: list[str] = []
    current_docs = 0
    for compressed_bytes, filename, inspected in inspected_rows:
        compressed_mb = compressed_bytes / (1024 * 1024)
        doc_count = inspected.supported_files if inspected.promotable else 0
        needs_solo = compressed_mb >= solo_archive_mb or doc_count >= limits.max_documents_per_wave
        if needs_solo:
            if current:
                batches.append(current)
                current = []
                current_docs = 0
            batches.append([filename])
            continue
        if current and current_docs + doc_count > limits.max_documents_per_wave:
            batches.append(current)
            current = [filename]
            current_docs = doc_count
        else:
            current.append(filename)
            current_docs += doc_count
    if current:
        batches.append(current)
    return batches


def build_v3_wave_plans(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_slug: str,
    dry_run: bool = True,
    skip_ledger: bool = True,
    folder: str | None = None,
    batch_index: int | None = None,
) -> list[WavePlan]:
    """V3: remaining SPL archives by folder letter, size-aware sub-batches."""
    limits = WaveLimits.v3()
    remaining = list_remaining_spl_archive_filenames(
        db,
        workspace=workspace,
        collection_slug=collection_slug,
        skip_ledger=skip_ledger,
        folder=folder,
    )
    by_folder: dict[str, list[str]] = {}
    for filename in remaining:
        by_folder.setdefault(_spl_folder_letter(filename), []).append(filename)

    all_batches: list[list[str]] = []
    for folder_key in sorted(by_folder.keys()):
        all_batches.extend(
            _pack_v3_archive_batches(
                db,
                workspace=workspace,
                filenames=by_folder[folder_key],
                limits=limits,
            )
        )

    plans: list[WavePlan] = []
    for index, batch in enumerate(all_batches, start=1):
        plans.append(
            build_wave_plan(
                db,
                workspace=workspace,
                collection_slug=collection_slug,
                archive_filenames=batch,
                allow_repromote=True,
                dry_run=dry_run,
                limits=limits,
                wave_id=f"spl_v3_{index}",
                skip_ledger=skip_ledger,
            )
        )
    if batch_index is not None:
        if batch_index < 1 or batch_index > len(plans):
            raise ValueError(f"batch index {batch_index} out of range (1..{len(plans)})")
        return [plans[batch_index - 1]]
    return plans


def _v3_archive_wave_id(archive_filenames: Iterable[str]) -> str:
    names = [str(name or "") for name in archive_filenames if name]
    stem = (names[0].rsplit("/", 1)[-1].rsplit(".", 1)[0] if names else "archive").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "archive"
    if len(names) > 1:
        slug = f"{slug}_plus_{len(names) - 1}"
    return f"spl_v3_archive_{slug[:48]}"


def build_v3_archive_wave_plan(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_slug: str,
    archive_filenames: Iterable[str],
    dry_run: bool = True,
    skip_ledger: bool = True,
    wave_id: str | None = None,
) -> WavePlan:
    """Build a V3 plan for exact archive path(s), avoiding mutable batch numbers."""
    filenames = [str(name) for name in archive_filenames if str(name or "").strip()]
    if not filenames:
        raise ValueError("at least one archive filename is required")
    limits = WaveLimits.v3()
    return build_wave_plan(
        db,
        workspace=workspace,
        collection_slug=collection_slug,
        archive_filenames=filenames,
        allow_repromote=True,
        dry_run=dry_run,
        limits=limits,
        wave_id=wave_id or _v3_archive_wave_id(filenames),
        skip_ledger=skip_ledger,
    )


def copy_collection_documents(
    db: DBSession,
    *,
    workspace: Workspace,
    source_slug: str,
    target_slug: str,
) -> dict[str, Any]:
    source = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == source_slug,
        )
        .first()
    )
    if not source:
        raise ValueError(f"Source collection not found: {source_slug}")
    target = create_or_get_collection(
        db,
        workspace=workspace,
        name=target_slug,
        description=f"SPL wave copy from {source_slug}",
        slug=target_slug,
    )
    store = get_object_store()
    source_manifest_key = document_manifest_key(source)
    target_manifest_key = document_manifest_key(target)
    source_manifest: dict[str, Any] = {}
    if store.exists(source_manifest_key):
        source_manifest = json.loads(store.read_bytes(source_manifest_key).decode("utf-8"))
    target_manifest: dict[str, Any] = {}
    if store.exists(target_manifest_key):
        loaded = json.loads(store.read_bytes(target_manifest_key).decode("utf-8"))
        if isinstance(loaded, dict):
            target_manifest = loaded

    copied: list[str] = []
    skipped_missing: list[str] = []
    document_names = list(target.document_names or [])
    document_name_set = set(document_names)
    for name in list(source.document_names or []):
        if name in document_name_set:
            continue
        source_key = original_key(source, name)
        if not store.exists(source_key):
            skipped_missing.append(name)
            continue
        payload = store.read_bytes(source_key)
        store.write_bytes(original_key(target, name), payload)
        document_names.append(name)
        document_name_set.add(name)
        copied.append(name)
        if name in source_manifest:
            target_manifest[name] = source_manifest[name]

    if not copied:
        return {
            "status": "noop",
            "collection_slug": target.slug,
            "copied_documents": [],
            "skipped_missing": skipped_missing,
        }

    store.write_text(
        target_manifest_key,
        json.dumps(target_manifest, ensure_ascii=True, indent=2, sort_keys=True),
    )
    update_collection_status(
        db,
        target.id,
        status="queued",
        document_names=document_names,
        document_count=len(document_names),
    )
    job = create_worker_job(
        db, workspace_id=workspace.id, collection_id=target.id, kind="document_ingest_index"
    )
    job.result = {
        "ingest_options": {
            "mode": "incremental",
            "document_names": copied,
            "wave_id": "spl_v1_copy",
        }
    }
    db.commit()
    dispatch_worker_job(db, job)
    db.commit()
    return {
        "status": "queued",
        "collection_slug": target.slug,
        "copied_documents": copied,
        "job_id": job.id,
    }


def execute_wave_plan(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    plan: WavePlan,
    allow_repromote: bool = True,
    limits: WaveLimits | None = None,
    document_ocr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if plan.dry_run:
        raise ValueError("Wave plan is dry-run only")
    limits = limits or WaveLimits.v1()

    collection = create_or_get_collection(
        db,
        workspace=workspace,
        name=plan.collection_slug,
        description="SPL controlled wave import",
        created_by_user_id=user.id,
        slug=plan.collection_slug,
    )
    store = get_object_store()
    manifest_key = document_manifest_key(collection)
    document_manifest: dict[str, Any] = {}
    if store.exists(manifest_key):
        loaded = json.loads(store.read_bytes(manifest_key).decode("utf-8"))
        if isinstance(loaded, dict):
            document_manifest = loaded

    document_names = list(collection.document_names or [])
    document_name_set = set(document_names)
    new_document_names: list[str] = []
    job_document_names: list[str] = []
    job_document_name_set: set[str] = set()
    promoted_archives: list[dict[str, Any]] = []
    promoted_deposit_files: list[DepositFile] = []
    collisions: list[dict[str, Any]] = []
    # Share the de-dup set across every archive in this wave (not just within a
    # single ZIP) so two archives in the same wave cannot reuse a document name.
    # Seeded empty (within-wave scope) so the write-time guard below remains the
    # authoritative detector for collisions against the *existing* corpus.
    wave_used_names: set[str] = set()

    by_name = _deposit_by_unique_filename(db, workspace_id=workspace.id)
    for archive in plan.archives:
        if not archive.promotable or archive.deposit_file_id == "":
            continue
        deposit_file = by_name.get(archive.filename)
        if not deposit_file:
            continue
        if deposit_file.status == "promoted" and not allow_repromote:
            continue
        source_path = staged_file_path(deposit_file)
        max_files, max_mb = _archive_limits(archive.filename, limits)
        namespace = archive_document_namespace(deposit_file.filename)
        item_documents: list[dict[str, Any]] = []
        new_source = str(deposit_file.filename or "")

        def store_document(document: dict[str, Any]) -> None:
            document_name = str(document["filename"])
            # Collision guard: never clobber a document that already belongs to a
            # *different* source. Re-running the same archive (same source) is an
            # allowed idempotent refresh; a different source is disambiguated to a
            # fresh unique name and recorded so the overwrite is visible.
            target_key = original_key(collection, document_name)
            if document_name in document_name_set or store.exists(target_key):
                existing_source = str(
                    (document_manifest.get(document_name) or {}).get("source_deposit_path") or ""
                )
                if existing_source and existing_source != new_source:
                    guard_used = set(wave_used_names) | document_name_set
                    disambiguated = _unique_archive_name(document_name, guard_used)
                    collisions.append(
                        {
                            "requested_name": document_name,
                            "stored_as": disambiguated,
                            "existing_source": existing_source,
                            "new_source": new_source,
                        }
                    )
                    document_name = disambiguated
                    wave_used_names.add(document_name)
                    target_key = original_key(collection, document_name)
            store.write_bytes(target_key, bytes(document.get("content") or b""))
            if document_name not in document_name_set:
                document_names.append(document_name)
                document_name_set.add(document_name)
                new_document_names.append(document_name)
            if document_name not in job_document_name_set:
                job_document_names.append(document_name)
                job_document_name_set.add(document_name)
            metadata = dict(document.get("metadata") or {})
            metadata.setdefault("wave_id", plan.wave_id)
            if metadata:
                document_manifest[document_name] = metadata
            item_documents.append(
                {
                    "document_name": document_name,
                    "archive_path": document.get("archive_path"),
                    "size_bytes": document.get("size_bytes"),
                }
            )

        _ignored_documents, stats = _read_supported_archive_documents(
            source_path,
            deposit_filename=deposit_file.filename,
            max_files=max_files,
            max_uncompressed_bytes=int(max_mb * 1024 * 1024),
            on_limit="truncate",
            document_namespace=namespace,
            used_names=wave_used_names,
            include_content=True,
            document_callback=store_document,
        )
        promoted_archives.append(
            {
                "file_id": deposit_file.id,
                "filename": deposit_file.filename,
                "documents": item_documents,
                "stats": stats,
            }
        )
        promoted_deposit_files.append(deposit_file)
        if deposit_file.status != "promoted":
            deposit_file.status = "promoted"
            deposit_file.promoted_at = datetime.utcnow()
            deposit_file.promoted_by_user_id = user.id
        deposit_file.promoted_collection_slug = collection.slug
        deposit_file.promotion_result = {
            "status": "queued",
            "mode": plan.wave_id,
            "collection_slug": collection.slug,
            "wave": plan.as_dict(),
            "indexing_status": "queued",
        }

    if not job_document_names:
        db.commit()
        return {
            "status": "noop",
            "collection_slug": collection.slug,
            "promoted_archives": promoted_archives,
            "collisions": collisions,
        }

    store.write_text(
        manifest_key, json.dumps(document_manifest, ensure_ascii=True, indent=2, sort_keys=True)
    )
    update_collection_status(
        db,
        collection.id,
        status="queued",
        document_names=document_names,
        document_count=len(document_names),
    )
    job = create_worker_job(
        db, workspace_id=workspace.id, collection_id=collection.id, kind="document_ingest_index"
    )
    promoted_filenames = [item["filename"] for item in promoted_archives]
    ingest_options: dict[str, Any] = {
        "mode": "incremental",
        "document_names": job_document_names,
        "wave_id": plan.wave_id,
        "wave_ledger": {
            "collection_slug": collection.slug,
            "wave_id": plan.wave_id,
            "filenames": promoted_filenames,
            "job_id": job.id,
            "new_document_count": len(job_document_names),
        },
    }
    if document_ocr is not None:
        ingest_options["document_ocr"] = document_ocr
    job.result = {"ingest_options": ingest_options}
    for deposit_file in promoted_deposit_files:
        deposit_file.worker_job_id = job.id
        result = dict(deposit_file.promotion_result or {})
        result["job_id"] = job.id
        result["indexing_status"] = "queued"
        deposit_file.promotion_result = result
    db.commit()
    celery_task_id = dispatch_worker_job(db, job)
    db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="spl.wave.promoted",
        actor=user.email or user.username or user.id,
        details={
            "collection_slug": collection.slug,
            "job_id": job.id,
            "wave_id": plan.wave_id,
            "new_document_count": len(new_document_names),
            "job_document_count": len(job_document_names),
            "archives": promoted_filenames,
            "collision_count": len(collisions),
            "collisions": collisions[:50],
        },
    )
    db.commit()
    return {
        "status": "queued",
        "collection_slug": collection.slug,
        "job_id": job.id,
        "celery_task_id": celery_task_id,
        "wave_id": plan.wave_id,
        "new_document_count": len(new_document_names),
        "job_document_count": len(job_document_names),
        "promoted_archives": promoted_archives,
        "collisions": collisions,
    }


def execute_v2_wave_plans(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    collection_slug: str,
    projects: Iterable[str] | None = None,
    skip_ledger: bool = True,
) -> list[dict[str, Any]]:
    limits = WaveLimits.v2()
    results: list[dict[str, Any]] = []
    for plan in build_v2_wave_plans(
        db,
        workspace=workspace,
        collection_slug=collection_slug,
        projects=projects,
        dry_run=False,
        skip_ledger=skip_ledger,
    ):
        if not any(item.promotable for item in plan.archives):
            results.append(
                {"status": "skipped", "wave_id": plan.wave_id, "reason": "no_promotable_archives"}
            )
            continue
        if any(item.filename == "__wave_limit__" for item in plan.archives):
            results.append({"status": "blocked", "wave_id": plan.wave_id, "plan": plan.as_dict()})
            continue
        results.append(
            execute_wave_plan(
                db,
                workspace=workspace,
                user=user,
                plan=plan,
                allow_repromote=True,
                limits=limits,
            )
        )
    return results


def execute_v3_wave_plans(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    collection_slug: str,
    skip_ledger: bool = True,
    folder: str | None = None,
    batch_index: int | None = None,
    document_ocr: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    limits = WaveLimits.v3()
    results: list[dict[str, Any]] = []
    for plan in build_v3_wave_plans(
        db,
        workspace=workspace,
        collection_slug=collection_slug,
        dry_run=False,
        skip_ledger=skip_ledger,
        folder=folder,
        batch_index=batch_index,
    ):
        if not any(item.promotable for item in plan.archives):
            results.append(
                {"status": "skipped", "wave_id": plan.wave_id, "reason": "no_promotable_archives"}
            )
            continue
        if any(item.filename == "__wave_limit__" for item in plan.archives):
            results.append({"status": "blocked", "wave_id": plan.wave_id, "plan": plan.as_dict()})
            continue
        results.append(
            execute_wave_plan(
                db,
                workspace=workspace,
                user=user,
                plan=plan,
                allow_repromote=True,
                limits=limits,
                document_ocr=document_ocr,
            )
        )
    return results


def execute_v3_archive_wave_plan(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    collection_slug: str,
    archive_filenames: Iterable[str],
    skip_ledger: bool = True,
    wave_id: str | None = None,
    document_ocr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    limits = WaveLimits.v3()
    plan = build_v3_archive_wave_plan(
        db,
        workspace=workspace,
        collection_slug=collection_slug,
        archive_filenames=archive_filenames,
        dry_run=False,
        skip_ledger=skip_ledger,
        wave_id=wave_id,
    )
    if not any(item.promotable for item in plan.archives):
        return {
            "status": "skipped",
            "wave_id": plan.wave_id,
            "reason": "no_promotable_archives",
            "plan": plan.as_dict(),
        }
    if any(item.filename == "__wave_limit__" for item in plan.archives):
        return {"status": "blocked", "wave_id": plan.wave_id, "plan": plan.as_dict()}
    return execute_wave_plan(
        db,
        workspace=workspace,
        user=user,
        plan=plan,
        allow_repromote=True,
        limits=limits,
        document_ocr=document_ocr,
    )
