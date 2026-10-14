"""Apply a typed rubric per immutable document unit, then publish one candidate."""

from __future__ import annotations

import hashlib
import json

from app.services import governed_assets as assets
from app.services.object_store import get_object_store


def evidence_for_asset(db, workspace, user, ref):
    asset = assets.resolve_asset_ref(
        db, workspace.id, ref, authorize=assets.native_authorizer(db, workspace, user)
    )
    values = []
    for entry in asset.manifest_json.get("evidence", []):
        value = {key: entry[key] for key in ("id", "kind", "sha256") if key in entry}
        value["asset_ref"] = assets.asset_ref(asset)
        value["text"] = (
            "" if entry.get("kind") == "image" else assets._saved_evidence_text(asset, entry)
        )
        values.append(value)
    if not values:
        raise ValueError("JUDGE_ASSET_EVIDENCE_REQUIRED")
    return asset, values


async def judge_document_set(config, ctx, reference, *, profile_ref=None, vision_route_ref=None):
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.evaluation.typed_judge import prepare_typed_judge_context, typed_evaluate

    with SessionLocal() as db:
        workspace = db.get(Workspace, ctx["workspace_id"])
        run = db.get(Run, ctx["run_id"])
        user = db.get(User, ctx.get("user_id") or run.initiated_by_user_id)
        if user is None:
            raise ValueError("JUDGE_ASSET_ACTOR_REQUIRED")
        asset, target = evidence_for_asset(db, workspace, user, reference)
        source_ref = asset.manifest_json.get("source_ref")
        if not source_ref:
            raise ValueError("JUDGE_SOURCE_ASSET_REQUIRED")
        source, origin = evidence_for_asset(db, workspace, user, source_ref)
        target_by = {entry["id"]: entry for entry in target}
        origin_by = {entry["id"]: entry for entry in origin}
        units = asset.manifest_json.get("units", {})
        unit_ids = list(units) if isinstance(units, dict) else [u["id"] for u in units]
        if (
            not unit_ids
            or len(unit_ids) > 2048
            or set(unit_ids) != set(target_by)
            or not set(unit_ids) <= set(origin_by)
        ):
            raise ValueError("JUDGE_UNIT_COVERAGE_INVALID")
        manifest = dict(asset.manifest_json)
    # One immutable source view disambiguates citation ids for the entire lot.
    # It verifies original bytes once rather than copying the 500-page graph
    # for each question.
    with SessionLocal() as db:
        source_view = assets.register_asset(
            db,
            workspace.id,
            "reference",
            f"judge-source:{source.id}"[:200],
            {
                **source.manifest_json,
                "evidence": [
                    {**entry, "id": "source-" + entry["id"]}
                    for entry in source.manifest_json["evidence"]
                ],
            },
            parents=[assets.asset_ref(source)],
            run_id=ctx["run_id"],
        )
        db.commit()
        source_view_ref = assets.asset_ref(source_view)
    results = []
    for unit_id in unit_ids:
        before, after = dict(origin_by[unit_id]), dict(target_by[unit_id])
        before["id"] = "source-" + unit_id
        before["asset_ref"] = source_view_ref
        request = {
            **config,
            "subject_ref": asset.digest + ":" + unit_id,
            "request_key": hashlib.sha256(
                (config["request_key"] + ":" + unit_id).encode()
            ).hexdigest(),
            "evidence": [before, after],
        }
        prepared = prepare_typed_judge_context(
            request, ctx, profile_ref=profile_ref, vision_route_ref=vision_route_ref
        )
        result = await typed_evaluate(request, prepared)
        results.append({"unit_id": unit_id, **result})
    complete = all(r["status"] == "completed" for r in results)
    quality = (
        "failed"
        if any(r["quality_status"] == "failed" for r in results)
        else "passed"
        if all(r["quality_status"] == "passed" for r in results)
        else "unassessed"
    )
    confidences = [r.get("confidence") for r in results]
    min_unit_confidence = min(confidences) if all(v is not None for v in confidences) else None
    # A bound for one document family is not a probability that the whole lot
    # is correct. Lot acceptance needs a separately calibrated lot-level unit.
    confidence = None
    known = [r.get("cost", {}).get("amount") for r in results]
    raw = json.dumps(
        {
            "schema_version": 2,
            "rubric_id": config["rubric_id"],
            "rubric_version": config["rubric_version"],
            "units": results,
        },
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    key = f"workspaces/{workspace.id}/governed-assets/judgements/{digest}.json"
    store = get_object_store()
    try:
        store.write_once(key, raw)
    except FileExistsError:
        if store.read_bytes(key) != raw:
            raise ValueError("JUDGE_RESULT_OBJECT_CHANGED") from None
    envelope = {
        "schema_version": 2,
        "evaluation_id": digest,
        "batch_mode": "per_unit",
        "answers": {},
        "status": "completed" if complete else "partial",
        "quality_status": quality,
        "confidence": confidence,
        "min_unit_confidence": min_unit_confidence,
        "disposition": "review",
        "coverage": {
            "units_total": len(unit_ids),
            "units_completed": sum(r["status"] == "completed" for r in results),
            "questions_total": sum(r["coverage"]["questions_total"] for r in results),
            "questions_answered": sum(r["coverage"]["questions_answered"] for r in results),
            "images_total": sum(r["coverage"]["images_total"] for r in results),
            "images_examined": sum(r["coverage"]["images_examined"] for r in results),
        },
        "cost": {
            "amount": sum(known) if all(v is not None for v in known) else None,
            "currency": "USD",
            "measurement_coverage": "measured"
            if all(v is not None for v in known)
            else "partial"
            if any(v is not None for v in known)
            else "unavailable",
        },
        "result_object_sha256": digest,
    }
    manifest["objects"] = [
        *manifest.get("objects", []),
        {"key": key, "sha256": digest, "size_bytes": len(raw)},
    ]
    manifest["output"] = {
        **manifest["output"],
        "technical_status": "completed" if complete else "partial",
        "typed_evaluation": envelope,
    }
    with SessionLocal() as db:
        candidate = assets.register_asset(
            db,
            workspace.id,
            "document_set",
            f"judged:{asset.logical_key}"[:200],
            manifest,
            parents=[
                assets.asset_ref(asset),
                *(ref for ref in (profile_ref, vision_route_ref) if ref is not None),
            ],
            run_id=ctx["run_id"],
        )
        assets.record_qualification(
            db,
            workspace.id,
            assets.asset_ref(candidate),
            status="review_required",
            policy={
                "authority": "typed_judge",
                "rubric_id": config["rubric_id"],
                "rubric_version": config["rubric_version"],
                "profile_ref": profile_ref,
            },
            evidence={
                "evaluation_object": key,
                "sha256": digest,
                "quality_status": quality,
                "technical_status": envelope["status"],
                "units": len(unit_ids),
            },
            confidence=confidence,
        )
        db.commit()
        return {
            **envelope,
            "asset_ref": assets.asset_ref(candidate),
            "technical_status": manifest["output"]["technical_status"] if complete else "partial",
        }
