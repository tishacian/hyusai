"""Shared validation for the immutable pre-wave collection baseline."""
from __future__ import annotations

from typing import Any

from app.models.knowledge_collection import KnowledgeCollection


class NoticeWaveBaselineError(ValueError):
    """The persisted incremental baseline is absent or malformed."""


def notice_wave_baseline(
    ingest_options: dict[str, Any],
) -> tuple[list[str], int, int]:
    required = {
        "baseline_document_names",
        "baseline_document_count",
        "baseline_chunk_count",
    }
    if not required <= set(ingest_options):
        raise NoticeWaveBaselineError("notice_wave_baseline_missing")
    raw_names = ingest_options.get("baseline_document_names")
    if not isinstance(raw_names, list):
        raise NoticeWaveBaselineError("notice_wave_baseline_names_invalid")
    names = [str(name) for name in raw_names if str(name or "").strip()]
    if len(names) != len(raw_names) or len(names) != len(set(names)):
        raise NoticeWaveBaselineError("notice_wave_baseline_names_invalid")
    try:
        document_count = int(ingest_options["baseline_document_count"])
        chunk_count = int(ingest_options["baseline_chunk_count"])
    except (TypeError, ValueError) as exc:
        raise NoticeWaveBaselineError("notice_wave_baseline_counts_invalid") from exc
    if document_count < 0 or chunk_count < 0:
        raise NoticeWaveBaselineError("notice_wave_baseline_counts_invalid")
    return names, document_count, chunk_count


def restore_notice_wave_baseline(
    collection: KnowledgeCollection,
    ingest_options: dict[str, Any],
) -> tuple[list[str], int, int]:
    names, document_count, chunk_count = notice_wave_baseline(ingest_options)
    collection.document_names = names
    collection.document_count = document_count
    collection.chunk_count = chunk_count
    return names, document_count, chunk_count


__all__ = [
    "NoticeWaveBaselineError",
    "notice_wave_baseline",
    "restore_notice_wave_baseline",
]
