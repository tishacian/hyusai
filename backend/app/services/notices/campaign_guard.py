"""Fail-closed health gates for sequential Needlepunch notice campaigns."""
from __future__ import annotations

import shutil
from collections.abc import Iterable
from math import ceil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.core.settings_manager import get_resolved_settings
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
)
from app.models.workspace import Workspace
from app.services.rag.document_service import DocumentService
from app.services.rag.vector_store_config import resolve_vector_db_type


class NoticeCampaignGateError(RuntimeError):
    """A campaign invariant failed and no later wave may be queued."""


def assert_notice_disk_capacity(
    *,
    docker_path: str | Path,
    deposit_path: str | Path,
    docker_min_free_ratio: float = 0.25,
    deposit_min_free_ratio: float = 0.15,
    docker_min_free_bytes: int | None = None,
    deposit_min_free_bytes: int | None = None,
    docker_estimated_growth_bytes: int = 0,
    deposit_estimated_growth_bytes: int = 0,
    projection_multiplier: float = 2.0,
) -> dict[str, Any]:
    """Require current and projected free-space floors on both volumes.

    The absolute byte floors and growth estimates are optional so single-project
    canaries retain the historical ratio-only behaviour.  When an estimate is
    supplied, the remaining free-space ratio is checked after applying the
    default x2 safety margin.
    """

    if projection_multiplier < 1:
        raise NoticeCampaignGateError(
            f"capacity_projection_multiplier_invalid:{projection_multiplier}"
        )

    report: dict[str, Any] = {}
    for label, raw_path, floor, byte_floor, estimated_growth in (
        (
            "docker",
            docker_path,
            docker_min_free_ratio,
            docker_min_free_bytes,
            docker_estimated_growth_bytes,
        ),
        (
            "secure_deposit",
            deposit_path,
            deposit_min_free_ratio,
            deposit_min_free_bytes,
            deposit_estimated_growth_bytes,
        ),
    ):
        if not 0 <= floor <= 1:
            raise NoticeCampaignGateError(f"{label}_minimum_free_ratio_invalid:{floor}")
        if byte_floor is not None and int(byte_floor) < 0:
            raise NoticeCampaignGateError(f"{label}_minimum_free_bytes_invalid:{byte_floor}")
        if int(estimated_growth) < 0:
            raise NoticeCampaignGateError(
                f"{label}_estimated_growth_bytes_invalid:{estimated_growth}"
            )
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise NoticeCampaignGateError(f"{label}_capacity_path_missing:{path}")
        usage = shutil.disk_usage(path)
        ratio = usage.free / usage.total if usage.total else 0.0
        projected_growth = int(ceil(int(estimated_growth) * projection_multiplier))
        projected_free = max(0, int(usage.free) - projected_growth)
        projected_ratio = projected_free / usage.total if usage.total else 0.0
        report[label] = {
            "path": str(path.resolve()),
            "total_bytes": int(usage.total),
            "free_bytes": int(usage.free),
            "free_ratio": ratio,
            "minimum_free_ratio": floor,
            "minimum_free_bytes": int(byte_floor) if byte_floor is not None else None,
            "estimated_growth_bytes": int(estimated_growth),
            "projection_multiplier": projection_multiplier,
            "projected_growth_bytes": projected_growth,
            "projected_free_bytes": projected_free,
            "projected_free_ratio": projected_ratio,
        }
        if ratio < floor:
            raise NoticeCampaignGateError(f"{label}_free_ratio_below_floor:{ratio:.4f}<{floor:.4f}")
        if byte_floor is not None and int(usage.free) < int(byte_floor):
            raise NoticeCampaignGateError(
                f"{label}_free_bytes_below_floor:{int(usage.free)}<{int(byte_floor)}"
            )
        if projected_ratio < floor:
            raise NoticeCampaignGateError(
                f"{label}_projected_free_ratio_below_floor:" f"{projected_ratio:.4f}<{floor:.4f}"
            )
    return report


def _qdrant_collection_status(vector_db: Any) -> str:
    client = getattr(vector_db, "client", None)
    collection_name = str(getattr(vector_db, "collection_name", "") or "")
    if client is None or not collection_name or not hasattr(client, "get_collection"):
        raise NoticeCampaignGateError("qdrant_health_probe_unavailable")
    try:
        info = client.get_collection(collection_name)
    except Exception as exc:  # noqa: BLE001 - a failed probe is a hard stop.
        raise NoticeCampaignGateError(f"qdrant_health_probe_failed:{exc}") from exc
    raw_status = getattr(info, "status", None)
    status = str(getattr(raw_status, "value", raw_status) or "").strip().lower()
    if status != "green":
        raise NoticeCampaignGateError(f"qdrant_collection_not_green:{status or 'unknown'}")
    return status


async def _assert_project_filter_isolation(
    vector_db: Any,
    *,
    project_codes: Iterable[str],
    page_size: int = 500,
    maximum_payloads_per_project: int = 1_000_000,
) -> dict[str, int]:
    if not hasattr(vector_db, "list_payloads"):
        raise NoticeCampaignGateError("qdrant_payload_probe_unavailable")
    counts: dict[str, int] = {}
    for raw_code in project_codes:
        code = str(raw_code or "").strip().upper()
        if not code:
            continue
        offset = 0
        seen = 0
        while True:
            rows = await vector_db.list_payloads(
                filters={"project_code": code},
                limit=page_size,
                offset=offset,
            )
            payloads = [dict(row or {}) for row in rows or []]
            for payload in payloads:
                actual = str(payload.get("project_code") or "").strip().upper()
                if actual != code:
                    raise NoticeCampaignGateError(
                        f"project_filter_leak:{code}->{actual or 'missing'}"
                    )
            seen += len(payloads)
            if seen > maximum_payloads_per_project:
                raise NoticeCampaignGateError(f"project_filter_probe_limit_exceeded:{code}")
            if len(payloads) < page_size:
                break
            offset += len(payloads)
        counts[code] = seen
    return counts


async def _exact_document_chunk_count(
    vector_db: Any,
    *,
    document_id: str,
    project_code: str,
    page_size: int = 500,
    maximum_payloads: int = 1_000_000,
) -> int:
    """Count one document exactly and reject filter or project leakage."""

    if not hasattr(vector_db, "list_payloads"):
        raise NoticeCampaignGateError("qdrant_payload_probe_unavailable")
    offset = 0
    seen = 0
    while True:
        rows = await vector_db.list_payloads(
            filters={"document_id": document_id},
            limit=page_size,
            offset=offset,
        )
        payloads = [dict(row or {}) for row in rows or []]
        for payload in payloads:
            actual_document_id = str(payload.get("document_id") or "").strip()
            if actual_document_id != document_id:
                raise NoticeCampaignGateError(
                    "document_filter_leak:" f"{document_id}->{actual_document_id or 'missing'}"
                )
            actual_project_code = str(payload.get("project_code") or "").strip().upper()
            if actual_project_code != project_code:
                raise NoticeCampaignGateError(
                    "document_project_leak:"
                    f"{document_id}:{project_code}->"
                    f"{actual_project_code or 'missing'}"
                )
        seen += len(payloads)
        if seen > maximum_payloads:
            raise NoticeCampaignGateError(f"document_filter_probe_limit_exceeded:{document_id}")
        if len(payloads) < page_size:
            break
        offset += len(payloads)
    return seen


async def verify_notice_collection_gate(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    document_names: Iterable[str] | None = None,
    wave_id: str | None = None,
) -> dict[str, Any]:
    """Validate Qdrant/SQL parity and, optionally, one completed wave."""

    db.refresh(collection)
    if collection.status != "ready":
        raise NoticeCampaignGateError(f"collection_not_ready:{collection.status or 'unknown'}")

    expected_names = {str(name) for name in document_names or () if str(name or "").strip()}
    project_codes: set[str] = set()
    source_report: list[dict[str, Any]] = []
    source_rows: list[KnowledgeCollectionSource] = []
    if expected_names:
        rows = (
            db.query(KnowledgeCollectionSource)
            .filter(
                KnowledgeCollectionSource.collection_id == collection.id,
                KnowledgeCollectionSource.normalized_name.in_(sorted(expected_names)),
            )
            .all()
        )
        by_name = {row.normalized_name: row for row in rows}
        missing = sorted(expected_names - set(by_name))
        if missing:
            raise NoticeCampaignGateError("wave_source_ledger_missing:" + ",".join(missing[:10]))
        for name in sorted(expected_names):
            row = by_name[name]
            source_rows.append(row)
            metadata = dict(row.source_metadata or {})
            if wave_id and str(metadata.get("wave_id") or "") != str(wave_id):
                raise NoticeCampaignGateError(f"wave_id_mismatch:{name}")
            if row.status not in {"ready", "indexed", "deduplicated"}:
                raise NoticeCampaignGateError(f"wave_source_not_terminal:{name}:{row.status}")
            if row.status != "deduplicated" and int(row.chunk_count or 0) <= 0:
                raise NoticeCampaignGateError(f"wave_source_zero_chunks:{name}")
            project_code = str(metadata.get("project_code") or "").strip().upper()
            if project_code:
                project_codes.add(project_code)
            source_report.append(
                {
                    "name": name,
                    "status": row.status,
                    "chunk_count": int(row.chunk_count or 0),
                    "project_code": project_code or None,
                }
            )

    app_settings = get_resolved_settings(workspace_id=workspace.id)
    db_type = resolve_vector_db_type(app_settings)
    if str(db_type).strip().lower() != "qdrant":
        raise NoticeCampaignGateError(f"authoritative_collection_not_qdrant:{db_type}")
    service = DocumentService(
        collection_name=collection.slug,
        vector_db_type=db_type,
        workspace_slug=workspace.slug,
    )
    qdrant_status = _qdrant_collection_status(service.vector_db)
    vector_chunk_count = int(await service.get_document_count())
    sql_chunk_count = int(collection.chunk_count or 0)
    if vector_chunk_count != sql_chunk_count:
        raise NoticeCampaignGateError(
            f"postgres_qdrant_chunk_drift:{sql_chunk_count}!={vector_chunk_count}"
        )

    report_by_name = {item["name"]: item for item in source_report}
    document_count_cache: dict[tuple[str, str], int] = {}

    async def checked_document_count(*, document_id: str, project_code: str) -> int:
        cache_key = (document_id, project_code)
        if cache_key not in document_count_cache:
            document_count_cache[cache_key] = await _exact_document_chunk_count(
                service.vector_db,
                document_id=document_id,
                project_code=project_code,
            )
        return document_count_cache[cache_key]

    duplicate_names = {
        str((row.source_metadata or {}).get("duplicate_of") or "").strip()
        for row in source_rows
        if row.status == "deduplicated"
    }
    duplicate_names.discard("")
    canonical_rows = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.normalized_name.in_(sorted(duplicate_names)),
        )
        .all()
        if duplicate_names
        else []
    )
    canonicals_by_name = {row.normalized_name: row for row in canonical_rows}

    for row in source_rows:
        name = row.normalized_name
        metadata = dict(row.source_metadata or {})
        project_code = str(metadata.get("project_code") or "").strip().upper()
        if not project_code:
            raise NoticeCampaignGateError(f"wave_source_project_code_missing:{name}")

        if row.status != "deduplicated":
            document_id = str(metadata.get("document_id") or "").strip()
            if not document_id:
                raise NoticeCampaignGateError(f"wave_source_document_id_missing:{name}")
            qdrant_chunks = await checked_document_count(
                document_id=document_id,
                project_code=project_code,
            )
            expected_chunks = int(row.chunk_count or 0)
            if qdrant_chunks != expected_chunks:
                raise NoticeCampaignGateError(
                    f"wave_source_chunk_drift:{name}:" f"{expected_chunks}!={qdrant_chunks}"
                )
            report_by_name[name].update(
                {
                    "document_id": document_id,
                    "qdrant_chunk_count": qdrant_chunks,
                }
            )
            continue

        duplicate_of = str(metadata.get("duplicate_of") or "").strip()
        if not duplicate_of:
            raise NoticeCampaignGateError(f"deduplicated_source_canonical_missing:{name}")
        canonical = canonicals_by_name.get(duplicate_of)
        if canonical is None or canonical.id == row.id:
            raise NoticeCampaignGateError(
                f"deduplicated_source_canonical_missing:{name}:{duplicate_of}"
            )
        if canonical.status not in {"ready", "indexed"}:
            raise NoticeCampaignGateError(
                f"deduplicated_source_canonical_not_terminal:"
                f"{name}:{duplicate_of}:{canonical.status}"
            )
        canonical_metadata = dict(canonical.source_metadata or {})
        canonical_project_code = str(canonical_metadata.get("project_code") or "").strip().upper()
        if canonical_project_code != project_code:
            raise NoticeCampaignGateError(
                f"deduplicated_source_project_mismatch:"
                f"{name}:{project_code}->{canonical_project_code or 'missing'}"
            )
        canonical_chunks = int(canonical.chunk_count or 0)
        if canonical_chunks <= 0:
            raise NoticeCampaignGateError(
                f"deduplicated_source_canonical_zero_chunks:{name}:{duplicate_of}"
            )
        canonical_document_id = str(canonical_metadata.get("document_id") or "").strip()
        if not canonical_document_id:
            raise NoticeCampaignGateError(
                f"deduplicated_source_canonical_document_id_missing:" f"{name}:{duplicate_of}"
            )
        qdrant_chunks = await checked_document_count(
            document_id=canonical_document_id,
            project_code=project_code,
        )
        if qdrant_chunks != canonical_chunks:
            raise NoticeCampaignGateError(
                f"deduplicated_source_canonical_chunk_drift:"
                f"{name}:{canonical_chunks}!={qdrant_chunks}"
            )
        report_by_name[name].update(
            {
                "duplicate_of": duplicate_of,
                "canonical_document_id": canonical_document_id,
                "canonical_chunk_count": canonical_chunks,
                "canonical_qdrant_chunk_count": qdrant_chunks,
            }
        )

    isolation_counts = await _assert_project_filter_isolation(
        service.vector_db,
        project_codes=sorted(project_codes),
    )
    empty_project_filters = sorted(
        code for code in project_codes if int(isolation_counts.get(code) or 0) <= 0
    )
    if empty_project_filters:
        raise NoticeCampaignGateError("project_filter_empty:" + ",".join(empty_project_filters))
    return {
        "collection_slug": collection.slug,
        "collection_status": collection.status,
        "qdrant_status": qdrant_status,
        "sql_chunk_count": sql_chunk_count,
        "qdrant_chunk_count": vector_chunk_count,
        "wave_id": wave_id,
        "sources": source_report,
        "project_filter_counts": isolation_counts,
    }


__all__ = [
    "NoticeCampaignGateError",
    "assert_notice_disk_capacity",
    "verify_notice_collection_gate",
]
