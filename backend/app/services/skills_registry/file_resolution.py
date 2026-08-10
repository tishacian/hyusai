"""Resolve a skill payload's file reference to Secure Deposit bytes.

Shared by the file-consuming extraction skills (``spreadsheet_table_extract_v1``,
``invoice_document_extract_v1``) so the same System graph serves every ingress:

* **Deposit path** — ``file_ids`` (the ``deposit.promoted`` event payload) or a
  single ``file_id``: the referenced :class:`DepositFile` rows are the
  candidates.
* **Collection path** — ``collection_slug`` (+ optional ``filename_pattern``,
  case-insensitive glob or substring): candidates are the deposit files whose
  ``promoted_collection_slug`` matches. Reading object-store originals from a
  knowledge collection is deliberately NOT reimplemented here: the Secure
  Deposit staging area remains the immutable source of truth for original
  bytes (see ``collection_source_backing``), and promotion stamps
  ``promoted_collection_slug`` on the row, so the deposit lookup covers the
  collection use case without a second byte-reading path.

The final candidate is selected by wanted extension(s) and, among several
matches, the most recently uploaded one. Bytes are read through the canonical
:func:`app.services.collection_source_backing.read_backing_source_bytes` with a
``secure_deposit_file`` locator, which re-checks workspace ownership, staged
size and content digest.

Tenant isolation invariant: every query here is scoped to the calling run's
``workspace_id``; a ``file_id`` belonging to another workspace resolves to
"not found", never to bytes.
"""
from __future__ import annotations

import fnmatch
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.secure_deposit import DepositFile
from app.services.collection_source_backing import (
    SourceBackingError,
    read_backing_source_bytes,
)


class FileResolutionError(ValueError):
    """No deposit file matches the payload's reference, or bytes are unreadable.

    Raised (never returned) so the run engine records the invocation as failed
    with this message as the error payload — the platform convention for bound
    wrappers (cf. ``_execute_task_node``).
    """


@dataclass(frozen=True)
class ResolvedFile:
    deposit_file_id: str
    filename: str
    data: bytes


def _payload_file_ids(payload: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    raw_list = payload.get("file_ids")
    if isinstance(raw_list, list | tuple):
        ids.extend(str(item).strip() for item in raw_list if str(item or "").strip())
    single = str(payload.get("file_id") or "").strip()
    if single and single not in ids:
        ids.append(single)
    return ids


def _matches_pattern(filename: str, pattern: str) -> bool:
    name = filename.lower()
    needle = pattern.lower()
    if any(char in needle for char in "*?["):
        return fnmatch.fnmatch(name, needle)
    return needle in name


def resolve_skill_file(
    db: DBSession,
    *,
    workspace_id: str,
    payload: Mapping[str, Any],
    extensions: tuple[str, ...],
) -> ResolvedFile:
    """Resolve one file matching ``extensions`` from a skill payload.

    ``extensions`` are lowercase suffixes including the dot (e.g. ``(".xlsx",)``).
    """
    workspace_id = str(workspace_id or "").strip()
    if not workspace_id:
        raise FileResolutionError(
            "file_resolution_workspace_missing: the run context carries no workspace_id"
        )

    file_ids = _payload_file_ids(payload)
    collection_slug = str(payload.get("collection_slug") or "").strip()
    filename_pattern = str(payload.get("filename_pattern") or "").strip()

    query = db.query(DepositFile).filter(DepositFile.workspace_id == workspace_id)
    if file_ids:
        query = query.filter(DepositFile.id.in_(file_ids[:200]))
        reference = f"file_ids={file_ids}"
    elif collection_slug:
        query = query.filter(DepositFile.promoted_collection_slug == collection_slug)
        reference = f"collection_slug={collection_slug!r}"
    else:
        raise FileResolutionError(
            "file_resolution_reference_missing: payload must carry file_ids, "
            "file_id, or collection_slug"
        )

    candidates = [
        row
        for row in query.all()
        if str(row.filename or "").lower().endswith(extensions)
        and (not filename_pattern or _matches_pattern(str(row.filename or ""), filename_pattern))
    ]
    if not candidates:
        wanted = "/".join(extensions)
        raise FileResolutionError(
            f"file_resolution_no_match: no {wanted} deposit file matches {reference}"
            + (f" filename_pattern={filename_pattern!r}" if filename_pattern else "")
            + " in this workspace"
        )

    candidates.sort(key=lambda row: (row.uploaded_at is not None, row.uploaded_at, row.id))
    row = candidates[-1]
    try:
        data = read_backing_source_bytes(
            db,
            workspace_id=workspace_id,
            locator={"kind": "secure_deposit_file", "deposit_file_id": row.id},
        )
    except SourceBackingError as exc:
        raise FileResolutionError(
            f"file_resolution_unreadable: deposit file {row.id} ({row.filename}): {exc}"
        ) from exc
    return ResolvedFile(deposit_file_id=row.id, filename=str(row.filename or ""), data=data)
