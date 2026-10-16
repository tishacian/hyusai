"""Append-only asset manifests and qualifications; native bytes stay in place.

Callers own the transaction. These helpers flush, never commit. Public callers
must authenticate before registration; reference resolution always checks tenant.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.service_contract import AssetQualification, AssetVersion
from app.models.workspace import Workspace
from app.schemas.service_contract import AssetRef
from app.services.object_store import get_object_store


class GovernanceError(ValueError):
    def __init__(self, code: str, status_code: int = 409):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    except (TypeError, ValueError):
        raise GovernanceError("GOVERNANCE_INVALID_JSON", 422) from None


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def asset_ref(asset: AssetVersion) -> dict:
    return {
        "asset_id": asset.id,
        "workspace_id": asset.workspace_id,
        "kind": asset.kind,
        "version": asset.version,
        "digest": asset.digest,
    }


def _workspace(db, workspace_id):
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).with_for_update().first()
    if workspace is None or not workspace.is_active:
        raise GovernanceError("WORKSPACE_NOT_FOUND", 404)
    return workspace


def _native_refs(db, workspace_id, manifest, authorize=None, *, pin=False, _metadata_only=False):
    from app.models.knowledge_collection import KnowledgeCollection
    from app.models.tabular import MLModel, TabularDataset

    models = {"dataset": TabularDataset, "model": MLModel, "document_set": KnowledgeCollection}
    references = manifest.get("native_refs", [])
    if not isinstance(references, list) or len(references) > 256:
        raise GovernanceError("ASSET_NATIVE_REFS_INVALID", 422)
    for ref in references:
        if (
            not isinstance(ref, dict)
            or ref.get("kind") not in models
            or not isinstance(ref.get("id"), str)
        ):
            raise GovernanceError("ASSET_NATIVE_REFS_INVALID", 422)
        model = models[ref["kind"]]
        row = (
            db.query(model)
            .filter(model.id == ref["id"], model.workspace_id == workspace_id)
            .first()
        )
        if _metadata_only:
            # Historical metadata survives native removal/version changes, but
            # every still-existing object retains the same native grant.
            if (
                row is not None
                and authorize is not None
                and authorize(ref["kind"], row) is not True
            ):
                raise GovernanceError("ASSET_NATIVE_ACCESS_DENIED", 403)
            continue
        if row is None or getattr(row, "status", None) != "ready":
            raise GovernanceError("ASSET_NATIVE_REF_UNAVAILABLE", 404)
        if ref.get("version") is not None and ref["version"] != getattr(row, "version", None):
            raise GovernanceError("ASSET_NATIVE_VERSION_CHANGED")
        fields = {
            "dataset": ("version", "storage_key", "schema_json", "row_count"),
            "model": ("version", "model_uri", "signature_json", "runtime_json"),
            "document_set": (
                "active_generation",
                "artifact_prefix",
                "document_names",
                "embedding_model",
            ),
        }[ref["kind"]]
        identity = content_digest({key: getattr(row, key, None) for key in fields})
        if pin:
            if ref.get("identity_digest") and ref["identity_digest"] != identity:
                raise GovernanceError("ASSET_NATIVE_VERSION_CHANGED")
            ref["identity_digest"] = identity
            if getattr(row, "version", None) is not None:
                ref["version"] = row.version
        elif ref.get("identity_digest") is not None and ref["identity_digest"] != identity:
            raise GovernanceError("ASSET_NATIVE_VERSION_CHANGED")
        if authorize is not None and authorize(ref["kind"], row) is not True:
            raise GovernanceError("ASSET_NATIVE_ACCESS_DENIED", 403)


def _objects(workspace_id, manifest, *, verify=True):
    objects = manifest.get("objects", [])
    if not isinstance(objects, list) or len(objects) > 10_000:
        raise GovernanceError("ASSET_OBJECTS_INVALID", 422)
    store = get_object_store()
    seen = set()
    for item in objects:
        if not isinstance(item, dict):
            raise GovernanceError("ASSET_OBJECT_INVALID", 422)
        key, digest, size = item.get("key"), item.get("sha256"), item.get("size_bytes")
        if (
            not isinstance(key, str)
            or not key.startswith(f"workspaces/{workspace_id}/")
            or "\\" in key
            or ".." in PurePosixPath(key).parts
            or str(PurePosixPath(key)) != key
            or key in seen
        ):
            raise GovernanceError("ASSET_OBJECT_SCOPE_DENIED", 403)
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or type(size) is not int
            or size < 0
        ):
            raise GovernanceError("ASSET_OBJECT_MANIFEST_INVALID", 422)
        seen.add(key)
        if verify:
            actual = hashlib.sha256()
            count = 0
            try:
                source = (
                    store._local_path(key).open("rb")
                    if store.backend == "local"
                    else store._fsspec().open(store._remote_key(key), "rb")
                )
                with source as stream:
                    while block := stream.read(1024 * 1024):
                        count += len(block)
                        if count > size:
                            raise GovernanceError("ASSET_OBJECT_CHANGED")
                        actual.update(block)
            except OSError:
                raise GovernanceError("ASSET_OBJECT_MISSING", 404) from None
            if count != size or actual.hexdigest() != digest:
                raise GovernanceError("ASSET_OBJECT_CHANGED")


def _envelope(asset):
    return {
        "workspace_id": asset.workspace_id,
        "kind": asset.kind,
        "logical_key": asset.logical_key,
        "manifest": asset.manifest_json,
        "parents": asset.parents_json,
        "run_id": asset.run_id,
    }


def register_asset(
    db, workspace_id: str, kind: str, logical_key: str, manifest: dict, parents=(), run_id=None
) -> AssetVersion:
    if (
        kind not in {"dataset", "model", "document_set", "reference"}
        or not isinstance(logical_key, str)
        or not 1 <= len(logical_key) <= 200
        or not isinstance(manifest, dict)
    ):
        raise GovernanceError("ASSET_DEFINITION_INVALID", 422)
    if len(canonical_bytes(manifest)) > 2_000_000:
        raise GovernanceError("ASSET_MANIFEST_TOO_LARGE", 422)
    _workspace(db, workspace_id)
    manifest = json.loads(canonical_bytes(manifest))
    _native_refs(db, workspace_id, manifest, pin=True)
    _objects(workspace_id, manifest)
    parent_refs = [asset_ref(resolve_asset_ref(db, workspace_id, ref)) for ref in parents]
    if len(parent_refs) > 256:
        raise GovernanceError("ASSET_TOO_MANY_PARENTS", 422)
    if run_id is not None:
        from app.models.run import Run

        if (
            db.query(Run.id).filter(Run.id == run_id, Run.workspace_id == workspace_id).first()
            is None
        ):
            raise GovernanceError("ASSET_RUN_SCOPE_DENIED", 403)
    manifest = json.loads(canonical_bytes(manifest))
    body = {
        "workspace_id": workspace_id,
        "kind": kind,
        "logical_key": logical_key,
        "manifest": manifest,
        "parents": parent_refs,
        "run_id": run_id,
    }
    digest = content_digest(body)
    query = db.query(AssetVersion).filter_by(
        workspace_id=workspace_id, kind=kind, logical_key=logical_key
    )
    existing = query.filter_by(digest=digest).first()
    if existing:
        return resolve_asset_ref(db, workspace_id, asset_ref(existing))
    version = (query.with_entities(func.max(AssetVersion.version)).scalar() or 0) + 1
    key = f"workspaces/{workspace_id}/governed-assets/manifests/{digest}.json"
    store = get_object_store()
    raw = canonical_bytes(body)
    # Only the small manifest is written. A concurrent identical manifest is
    # acceptable; a conflicting content-addressed object is never overwritten.
    try:
        store.write_once(key, raw)
    except Exception:
        if not store.exists(key) or store.read_bytes(key) != raw:
            raise GovernanceError("ASSET_MANIFEST_COMMIT_FAILED", 503) from None
    row = AssetVersion(
        workspace_id=workspace_id,
        kind=kind,
        logical_key=logical_key,
        version=version,
        digest=digest,
        manifest_key=key,
        manifest_json=manifest,
        parents_json=parent_refs,
        run_id=run_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = query.filter_by(digest=digest).first()
        if existing is None:
            raise GovernanceError("ASSET_VERSION_CONFLICT") from None
        return existing
    return row


def resolve_asset_ref(
    db,
    workspace_id: str,
    ref,
    *,
    authorize=None,
    _seen=None,
    verify_objects=True,
    _metadata_only=False,
) -> AssetVersion:
    """Resolve the native asset graph; metadata reads never grant consumption.

    The internal metadata mode preserves historical facts after unavailable
    bytes or native versions, while applying the same grants to every existing
    asset/native reference/parent. Default callers still verify all evidence.
    """
    try:
        ref = AssetRef.model_validate(ref).model_dump()
    except ValueError:
        raise GovernanceError("ASSET_REF_INVALID", 422) from None
    if ref["workspace_id"] != workspace_id:
        raise GovernanceError("ASSET_SCOPE_DENIED", 403)
    row = db.query(AssetVersion).filter_by(id=ref["asset_id"], workspace_id=workspace_id).first()
    if row is None:
        if _metadata_only:
            return None
        raise GovernanceError("ASSET_NOT_FOUND", 404)
    if asset_ref(row) != ref or content_digest(_envelope(row)) != row.digest:
        raise GovernanceError("ASSET_REF_CHANGED")
    if not _metadata_only:
        try:
            saved = get_object_store().read_bytes(row.manifest_key)
        except OSError:
            raise GovernanceError("ASSET_MANIFEST_MISSING", 404) from None
        if saved != canonical_bytes(_envelope(row)):
            raise GovernanceError("ASSET_MANIFEST_CHANGED")
    _native_refs(db, workspace_id, row.manifest_json, authorize, _metadata_only=_metadata_only)
    if authorize is not None and authorize("asset", row) is not True:
        raise GovernanceError("ASSET_NATIVE_ACCESS_DENIED", 403)
    if not _metadata_only:
        _objects(workspace_id, row.manifest_json, verify=verify_objects)
    if authorize is not None:
        seen = set() if _seen is None else _seen
        if row.id in seen or len(seen) > 256:
            raise GovernanceError("ASSET_PARENT_GRAPH_INVALID")
        seen.add(row.id)
        for parent in row.parents_json or []:
            resolve_asset_ref(
                db,
                workspace_id,
                parent,
                authorize=authorize,
                _seen=seen,
                verify_objects=verify_objects,
                _metadata_only=_metadata_only,
            )
        seen.remove(row.id)
    return row


def mark_for_requalification(db, workspace_id, ref, *, actor, reason):
    """Append invalidation evidence through descendants; preserve receipts."""
    if not isinstance(reason, str) or not reason.strip():
        raise GovernanceError("ASSET_REQUALIFICATION_REASON_REQUIRED", 422)
    root = resolve_asset_ref(db, workspace_id, ref)
    rows = db.query(AssetVersion).filter_by(workspace_id=workspace_id).all()
    pending, seen = [root], set()
    while pending:
        asset = pending.pop()
        if asset.id in seen:
            continue
        seen.add(asset.id)
        previous = current_qualification(db, workspace_id, asset.id)
        record_qualification(
            db,
            workspace_id,
            asset_ref(asset),
            status="needs_requalification",
            policy=previous.policy_json if previous else {"authority": "asset_owner"},
            evidence={"actor": actor, "reason": reason[:2000], "invalidated_by": asset_ref(root)},
            confidence=None,
        )
        pending.extend(
            child
            for child in rows
            if any(parent.get("asset_id") == asset.id for parent in child.parents_json or [])
        )
    return len(seen)


def current_qualification(db, workspace_id, asset_id):
    return (
        db.query(AssetQualification)
        .filter_by(workspace_id=workspace_id, asset_id=asset_id)
        .order_by(AssetQualification.version.desc())
        .first()
    )


def record_qualification(
    db, workspace_id, ref, *, status, policy: dict, evidence: dict, confidence=None
) -> AssetQualification:
    """Trusted producer callback, never an API accepting a claimed verdict.

    A changed policy/evidence is a new record. Old qualifications and receipts
    remain unchanged; only the newest record may authorize a new publication.
    """
    _workspace(db, workspace_id)
    asset = resolve_asset_ref(db, workspace_id, ref)
    if (
        status not in {"qualified", "rejected", "review_required", "needs_requalification"}
        or not isinstance(policy, dict)
        or not isinstance(evidence, dict)
    ):
        raise GovernanceError("ASSET_QUALIFICATION_INVALID", 422)
    if confidence is not None and (
        type(confidence) not in {int, float}
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise GovernanceError("ASSET_CONFIDENCE_INVALID", 422)
    if confidence is not None:
        confidence = float(confidence)
    payload = {
        "asset_digest": asset.digest,
        "policy_digest": content_digest(policy),
        "evidence_digest": content_digest(evidence),
        "status": status,
        "confidence": confidence,
    }
    digest = content_digest(payload)
    previous = current_qualification(db, workspace_id, asset.id)
    if previous and previous.digest == digest:
        return previous
    row = AssetQualification(
        workspace_id=workspace_id,
        asset_id=asset.id,
        version=(previous.version if previous else 0) + 1,
        digest=digest,
        policy_json=json.loads(canonical_bytes(policy)),
        evidence_json=json.loads(canonical_bytes(evidence)),
        **payload,
    )
    db.add(row)
    db.flush()
    return row


def validate_qualification(qualification, asset):
    if (
        qualification is None
        or qualification.status != "qualified"
        or qualification.asset_digest != asset.digest
    ):
        raise GovernanceError("ASSET_QUALIFICATION_REQUIRED")
    payload = {
        "asset_digest": qualification.asset_digest,
        "policy_digest": content_digest(qualification.policy_json),
        "evidence_digest": content_digest(qualification.evidence_json),
        "status": qualification.status,
        "confidence": qualification.confidence,
    }
    if (
        payload["policy_digest"] != qualification.policy_digest
        or payload["evidence_digest"] != qualification.evidence_digest
        or content_digest(payload) != qualification.digest
    ):
        raise GovernanceError("ASSET_QUALIFICATION_CHANGED")
    return qualification


def native_authorizer(db, workspace, user):
    """Reuse native collection/Run rules; a receipt never widens their grants."""
    from fastapi import HTTPException

    from app.models.run import Run
    from app.services.collection_access import require_read_collection
    from app.services.run_access import readable_runs

    def authorize(kind, row):
        if kind == "document_set":
            try:
                require_read_collection(db, workspace=workspace, collection=row, user_id=user.id)
            except HTTPException:
                return False
        if getattr(row, "run_id", None):
            run = db.query(Run).filter_by(id=row.run_id, workspace_id=workspace.id).first()
            if run is None or not readable_runs(db, runs=[run], workspace=workspace, user=user):
                return False
        return True

    return authorize


def _saved_evidence_text(asset, entry):
    if isinstance(entry.get("text"), str):
        return entry["text"]
    locator = entry.get("locator")
    if not isinstance(locator, dict) or set(locator) - {"object_key", "json_pointer"}:
        raise GovernanceError("JUDGE_EVIDENCE_LOCATOR_INVALID", 403)
    key = locator.get("object_key")
    declared = next(
        (obj for obj in asset.manifest_json.get("objects", []) if obj["key"] == key), None
    )
    if declared is None or declared["size_bytes"] > 2_000_000:
        raise GovernanceError("JUDGE_EVIDENCE_OBJECT_INVALID", 403)
    raw = get_object_store().read_bytes(key)
    if len(raw) != declared["size_bytes"] or hashlib.sha256(raw).hexdigest() != declared["sha256"]:
        raise GovernanceError("JUDGE_EVIDENCE_OBJECT_CHANGED", 403)
    try:
        if "json_pointer" not in locator:
            return raw.decode("utf-8")
        value = json.loads(raw)
        pointer = locator["json_pointer"]
        if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
            raise ValueError
        for part in pointer.split("/")[1:] if pointer else []:
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
        if not isinstance(value, str):
            raise ValueError
        return value
    except (UnicodeError, ValueError, KeyError, IndexError, TypeError):
        raise GovernanceError("JUDGE_EVIDENCE_LOCATOR_INVALID", 403) from None


def authorize_judge_evidence(evidence, ctx):
    """Confirm bytes against persisted, authorized evidence, never caller hashes."""
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.user import User
    from app.models.workspace import WorkspaceMember
    from app.services.run_access import readable_runs

    with SessionLocal() as db:
        workspace = (
            db.query(Workspace).filter_by(id=ctx.get("workspace_id"), is_active=True).first()
        )
        run = (
            db.query(Run)
            .filter_by(id=ctx.get("run_id"), workspace_id=ctx.get("workspace_id"))
            .first()
        )
        user = (
            db.query(User).filter_by(id=ctx.get("user_id"), is_active=True).first()
            if ctx.get("user_id")
            else None
        )
        if workspace is None or run is None or run.status in {"cancelled", "failed"}:
            raise GovernanceError("JUDGE_EVIDENCE_ACTOR_INVALID", 403)
        if ctx.get("user_id") and (
            user is None
            or db.query(WorkspaceMember.id)
            .filter_by(workspace_id=workspace.id, user_id=user.id)
            .first()
            is None
        ):
            raise GovernanceError("JUDGE_EVIDENCE_ACTOR_INVALID", 403)
        if user and not readable_runs(db, runs=[run], workspace=workspace, user=user):
            raise GovernanceError("JUDGE_EVIDENCE_RUN_DENIED", 403)
        if not isinstance(evidence, list) or len(evidence) > 64:
            raise GovernanceError("JUDGE_EVIDENCE_INVALID", 422)
        confirmed = {}
        persisted = (run.input_ref or {}).get("evidence", [])
        for item in evidence:
            if (
                not isinstance(item, dict)
                or item.get("kind", "text") != "text"
                or not isinstance(item.get("id"), str)
            ):
                raise GovernanceError("JUDGE_EVIDENCE_UNSUPPORTED", 403)
            ref = item.get("asset_ref")
            if ref:
                asset = resolve_asset_ref(
                    db,
                    workspace.id,
                    ref,
                    authorize=native_authorizer(db, workspace, user) if user else None,
                    verify_objects=False,
                )
                # An unattended Run may only read its own produced asset or
                # an exact asset reference authorized in its persisted input.
                declared = any(
                    isinstance(saved, dict) and saved.get("asset_ref") == ref for saved in persisted
                )
                if not user and asset.run_id != run.id and not declared:
                    raise GovernanceError("JUDGE_EVIDENCE_ASSET_DENIED", 403)
                matches = [
                    entry
                    for entry in asset.manifest_json.get("evidence", [])
                    if isinstance(entry, dict) and entry.get("id") == item["id"]
                ]
                if len(matches) != 1 or matches[0].get("kind", "text") != "text":
                    raise GovernanceError("JUDGE_EVIDENCE_LOCATOR_INVALID", 403)
                saved = matches[0]
                text = _saved_evidence_text(asset, saved)
            else:
                matches = [
                    entry
                    for entry in persisted
                    if isinstance(entry, dict)
                    and entry.get("id") == item["id"]
                    and not entry.get("asset_ref")
                ]
                if len(matches) != 1:
                    raise GovernanceError("JUDGE_EVIDENCE_UNAUTHORIZED", 403)
                saved = matches[0]
                text = saved.get("text")
            if not isinstance(text, str) or text != item.get("text"):
                raise GovernanceError("JUDGE_EVIDENCE_HASH_MISMATCH", 403)
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest != item.get("sha256") or (
                saved.get("sha256") is not None and saved["sha256"] != digest
            ):
                raise GovernanceError("JUDGE_EVIDENCE_HASH_MISMATCH", 403)
            if item["id"] in confirmed:
                raise GovernanceError("JUDGE_EVIDENCE_DUPLICATE", 403)
            confirmed[item["id"]] = digest
        return confirmed
