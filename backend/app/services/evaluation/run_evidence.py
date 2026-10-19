"""Freeze reviewed fields from completed invocations for a same-Run typed judge.

The caller cannot submit excerpts, select another Run, or replace the selectors.
The published Flow owns selectors and source permissions. The A1 snapshot pins
their native versions and is re-authorized by the existing judge before and
after its provider call. It records observations, not ground truth or calibration.
"""

from __future__ import annotations

import hashlib
import json

from app.models.run import SkillInvocation
from app.schemas.typed_evaluation import RunEvidenceSnapshot
from app.services import governed_assets as assets
from app.services.evaluation.typed_judge import TypedEvaluationError, _authorize, _run_user_id

MAX_SOURCE_BYTES = 32_000
MAX_SNAPSHOT_BYTES = 96_000
_SENSITIVE_FIELDS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "secrets",
        "token",
        "tokens",
        "accesstoken",
        "refreshtoken",
        "apikey",
        "authorization",
        "cookie",
        "credentials",
        "connectionstring",
        "databaseurl",
        "privatekey",
    }
)


def run_evidence_context(db, ctx):
    """Bind an unattended call to its persisted authority for every later read."""
    _, user, run = _authorize(db, ctx)
    if run is None:
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_CONTEXT_REQUIRED")
    actor_id = user.id if user else _run_user_id(db, run)
    if not actor_id:
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_ACTOR_REQUIRED")
    authorized = {**ctx, "user_id": actor_id}
    _authorize(db, authorized)
    return authorized


def _recorded_collection_refs(value, *, depth=0, budget=None):
    """Retain source ACLs even when a selector chooses only a citation's text."""
    budget = [4096] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0 or depth > 16:
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")
    refs = set()
    if isinstance(value, dict):
        if len(value) > 1024:
            raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")
        for key, item in value.items():
            if key in {
                "collection",
                "collection_id",
                "collection_name",
                "collection_slug",
                "source_collection",
            }:
                if isinstance(item, str) and item.strip():
                    refs.add(item.strip())
                elif isinstance(item, dict):
                    candidate = item.get("id") or item.get("slug")
                    if isinstance(candidate, str) and candidate.strip():
                        refs.add(candidate.strip())
            if isinstance(item, (dict, list)):
                refs.update(_recorded_collection_refs(item, depth=depth + 1, budget=budget))
    elif isinstance(value, list):
        for item in value:
            refs.update(_recorded_collection_refs(item, depth=depth + 1, budget=budget))
    return refs


def _reviewed_value(value, *, depth=0):
    """Bound object work and refuse credential-shaped fields, including nested ones."""
    if depth > 12:
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")
    if isinstance(value, dict):
        if len(value) > 128:
            raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")
        for key, item in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized in _SENSITIVE_FIELDS or normalized.endswith(
                ("password", "secret", "apikey", "token")
            ):
                raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_SENSITIVE_FIELD")
            _reviewed_value(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 128:
            raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")
        for item in value:
            _reviewed_value(item, depth=depth + 1)
    elif isinstance(value, str) and len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")


def _select(value, pointer):
    try:
        for token in pointer.split("/")[1:]:
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not token.isdecimal() or str(int(token)) != token:
                    raise ValueError
                value = value[int(token)]
            elif isinstance(value, dict):
                value = value[token]
            else:
                raise ValueError
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_PATH_MISSING") from None


def capture_run_evidence(db, ctx, definition, *, node_id):
    """Return an immutable A1 reference, reusing the existing identity on replay."""
    from app.models.user import User
    from app.services.run_access import readable_runs

    spec = RunEvidenceSnapshot.model_validate(definition)
    ctx = run_evidence_context(db, ctx)
    workspace, user, run = _authorize(db, ctx)
    if run is None or not isinstance(node_id, str) or not node_id:
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_CONTEXT_REQUIRED")
    actor_id = user.id if user else _run_user_id(db, run)
    actor = user or (db.get(User, actor_id) if actor_id else None)
    if actor is None or not actor.is_active:
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_ACTOR_REQUIRED")
    if not readable_runs(db, runs=[run], workspace=workspace, user=actor):
        raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_ACCESS_DENIED")

    # Permission/version checks precede reading any selected invocation output.
    native = [ref.model_dump() for ref in spec.native_refs]
    assets._native_refs(
        db,
        workspace.id,
        {"native_refs": native},
        assets.native_authorizer(db, workspace, actor),
        pin=True,
    )
    evidence, provenance = [], []
    total_bytes = 0
    for source in spec.sources:
        query = db.query(SkillInvocation).filter_by(run_id=run.id, skill_slug=source.skill_slug)
        if source.node_id is not None:
            query = query.filter(SkillInvocation.trace["node_id"].as_string() == source.node_id)
        invocation = query.order_by(
            SkillInvocation.started_at.desc(), SkillInvocation.id.desc()
        ).first()
        if invocation is None or invocation.status != "completed":
            raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_SOURCE_MISSING")
        from app.services.collection_access import require_named_collection_read

        for collection_ref in sorted(_recorded_collection_refs(invocation.output_ref)):
            collection = require_named_collection_read(
                db, workspace=workspace, user_id=actor.id, collection_ref=collection_ref
            )
            if collection is None:
                raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_COLLECTION_UNREGISTERED")
            if not any(
                ref["kind"] == "document_set" and ref["id"] == collection.id for ref in native
            ):
                native.append({"kind": "document_set", "id": collection.id})
        if len(native) > 32:
            raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")
        projection = {path: _select(invocation.output_ref, path) for path in source.paths}
        for path, value in projection.items():
            # Checking the path as well also covers direct scalar secret selection.
            _reviewed_value({part: None for part in path.split("/")[1:]})
            _reviewed_value(value)
        try:
            text = json.dumps(
                projection,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (ValueError, TypeError):
            raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_INVALID") from None
        size = len(text.encode("utf-8"))
        total_bytes += size
        if size > MAX_SOURCE_BYTES or total_bytes > MAX_SNAPSHOT_BYTES:
            raise TypedEvaluationError("JUDGE_RUN_EVIDENCE_TOO_LARGE")
        evidence.append(
            {
                "id": source.id,
                "kind": "text",
                "text": text,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        provenance.append(
            {
                "evidence_id": source.id,
                "invocation_id": invocation.id,
                "skill_slug": invocation.skill_slug,
                "node_id": (invocation.trace or {}).get("node_id"),
                "paths": source.paths,
            }
        )
    manifest = {
        "type": "run_evidence_snapshot",
        "schema_version": 1,
        "evidence": evidence,
        "native_refs": native,
        "provenance": provenance,
        "selector_sha256": assets.content_digest(spec.model_dump()),
        "actor_user_id": actor.id,
    }
    asset = assets.register_asset(
        db,
        workspace.id,
        "reference",
        f"judge-run:{run.id}:{node_id}"[:200],
        manifest,
        run_id=run.id,
    )
    # Commit before the existing judge opens its independent authorization session.
    db.commit()
    return assets.asset_ref(asset)
