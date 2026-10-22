"""Plural, read-only evaluation projections shared by Run and Quality surfaces.

EvaluationScore is the retained observation. Run.evaluation_scores remains the
legacy auto-evaluation lifecycle, never a last-writer-wins typed Judge result.
Reading a record neither calls a provider nor changes a Run or its draft.
"""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy

from fastapi import HTTPException

from app.models.evaluation_feedback import EvaluationFeedback
from app.models.run import Run, SkillInvocation
from app.services.run_access import readable_runs, readable_skill_invocations_for_runs


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def scalar_metric(row, name):
    """A legacy ORM default is not a measurement for a typed evaluation."""
    if (row.metadata_ or {}).get("source") == "evaluate_v2":
        return None
    return _number(getattr(row, name, None))


def historical_evidence_authorizer(db, workspace, user):
    """Extend native asset grants with exact invocation lineage, recursively.

    resolve_asset_ref applies this callback to every parent, so exporting an
    immutable qualification case never launders a source invocation's grants.
    """
    from app.services import governed_assets as assets

    native = assets.native_authorizer(db, workspace, user)
    checked = {}

    def authorize(kind, row):
        if native(kind, row) is not True:
            return False
        if kind != "asset":
            return True
        manifest = row.manifest_json or {}
        provenance = manifest.get("provenance") or []
        if manifest.get("type") == "run_evidence_snapshot" and (
            not provenance
            or any(
                not isinstance(source, dict) or not source.get("invocation_id")
                for source in provenance
            )
        ):
            return False
        identifiers = {
            source["invocation_id"]
            for source in provenance
            if isinstance(source, dict) and source.get("invocation_id")
        }
        missing = identifiers - checked.keys()
        if missing:
            invocations = db.query(SkillInvocation).filter(SkillInvocation.id.in_(missing)).all()
            runs = (
                db.query(Run)
                .filter(
                    Run.workspace_id == workspace.id,
                    Run.id.in_({inv.run_id for inv in invocations}),
                )
                .all()
            )
            visible_runs = readable_runs(db, runs=runs, user=user, workspace=workspace)
            visible_ids = {run.id for run in visible_runs}
            allowed = readable_skill_invocations_for_runs(
                db,
                invocations=[inv for inv in invocations if inv.run_id in visible_ids],
                runs=visible_runs,
                user=user,
                workspace=workspace,
            )
            allowed_ids = {inv.id for inv in allowed}
            checked.update({identifier: identifier in allowed_ids for identifier in missing})
        return all(checked[identifier] for identifier in identifiers)

    return authorize


def _typed_evidence_available(db, result, *, run, workspace, user):
    """Re-authorize historical evidence without requiring an executable Run.

    The execution authorizer intentionally rejects failed/cancelled Runs; this
    reader instead validates the saved assets, current grants and exact bytes.
    Any missing source suppresses all derived text, not only the citation link.
    """
    from app.services import governed_assets as assets

    evidence = result.get("evidence")
    if not isinstance(evidence, list) or not evidence or len(evidence) > 64:
        return False
    resolved = {}
    sources = []
    for item in evidence:
        if not isinstance(item, dict):
            return False
        ref = item.get("asset_ref")
        try:
            if ref:
                key = (ref.get("asset_id"), ref.get("digest")) if isinstance(ref, dict) else None
                if key not in resolved:
                    asset = assets.resolve_asset_ref(
                        db,
                        workspace.id,
                        ref,
                        authorize=historical_evidence_authorizer(db, workspace, user),
                    )
                    resolved[key] = asset
                asset = resolved[key]
                entries = asset.manifest_json.get("evidence") or []
            else:
                asset = None
                entries = (run.input_ref or {}).get("evidence") or []
            matches = [
                entry
                for entry in entries
                if isinstance(entry, dict)
                and entry.get("id") == item.get("id")
                and (asset is not None or not entry.get("asset_ref"))
            ]
            if len(matches) != 1:
                return False
            saved = matches[0]
            if saved.get("sha256") != item.get("sha256") or saved.get("kind", "text") != item.get(
                "kind", "text"
            ):
                return False
            if item.get("kind", "text") == "text":
                text = assets._saved_evidence_text(asset, saved) if asset else saved.get("text")
                if (
                    not isinstance(text, str)
                    or len(text) > 32000
                    or hashlib.sha256(text.encode()).hexdigest() != item.get("sha256")
                ):
                    return False
            elif asset is None:
                # Image consumption must be backed by a verified asset graph.
                return False
            else:
                text = None
            provenance = (
                next(
                    (
                        source
                        for source in (asset.manifest_json.get("provenance") or [])
                        if source.get("evidence_id") == item.get("id")
                    ),
                    {},
                )
                if asset
                else {}
            )
            sources.append(
                {
                    "evidence_id": item.get("id"),
                    "sha256": item.get("sha256"),
                    "text": text,
                    "asset_ref": deepcopy(ref),
                    "invocation_id": provenance.get("invocation_id"),
                    "node_id": provenance.get("node_id"),
                    "paths": deepcopy(provenance.get("paths") or []),
                    "native_refs": deepcopy(asset.manifest_json.get("native_refs") or [])
                    if asset
                    else [],
                }
            )
        except (assets.GovernanceError, HTTPException, OSError, ValueError, KeyError, TypeError):
            return False
    return sources


def _projection(db, row, run, *, workspace, user, invocations, allowed_ids, reviews):
    metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
    typed = metadata.get("typed_evaluation") if metadata.get("source") == "evaluate_v2" else None
    typed = typed if isinstance(typed, dict) else None
    matched = [
        inv
        for inv in invocations
        if inv.skill_slug == "evaluate_v2"
        and isinstance(inv.output_ref, dict)
        and inv.output_ref.get("evaluation_id") == row.id
    ]
    producer_id = metadata.get("producer_invocation_id")
    subject_id = metadata.get("invocation_id")
    # New records bind their producer; historical records use exact result IDs,
    # never proximity in time or the mutable Skill catalogue.
    targets = {value for value in (producer_id, subject_id) if value}
    if typed and not producer_id:
        targets.update(inv.id for inv in matched)
    if not targets.issubset(allowed_ids):
        return None
    producer = next((inv for inv in invocations if inv.id == producer_id), None)
    if producer_id and producer is None:
        return None
    if producer is None and len(matched) == 1:
        producer = matched[0]
    source = metadata.get("source") or (
        "auto_eval" if metadata.get("preset") or "threshold_outcome" in metadata else "historical"
    )
    execution_status = (typed or {}).get("status") or metadata.get("status") or "historical"
    quality_status = "unassessed"
    availability = "not_applicable"
    public_typed = None
    public_legacy = None
    reason = (typed or {}).get("reason") or metadata.get("reason")
    metrics = {
        name: scalar_metric(row, name)
        for name in ("composite_score", "hallucination_rate", "drift_rate")
    }
    coverage = {}
    rubric = None
    evidence_sources = []
    if typed:
        available = _typed_evidence_available(db, typed, run=run, workspace=workspace, user=user)
        availability = "available" if available else "unavailable"
        if available:
            evidence_sources = available
            public_typed = deepcopy(typed)
            quality_status = (
                typed.get("quality_status")
                if typed.get("quality_status") in {"passed", "failed", "unassessed"}
                else "unassessed"
            )
            # Invalid/failed controls cannot certify the business result.
            if execution_status == "failed":
                quality_status = "unassessed"
            coverage = {
                name: _count((typed.get("coverage") or {}).get(name))
                for name in (
                    "questions_total",
                    "questions_answered",
                    "evidence_total",
                    "evidence_examined",
                )
            }
            rubric = {
                "id": typed.get("rubric_id"),
                "version": typed.get("rubric_version"),
                "sha256": typed.get("rubric_sha256"),
            }
        else:
            reason = "evidence_unavailable"
    else:
        from app.services.evaluation.lifecycle import public_evaluation_snapshot

        public_legacy = public_evaluation_snapshot(
            db,
            {
                "metadata": deepcopy(metadata),
                "claim_audit": deepcopy(row.claim_audit or {}),
                "scores": deepcopy(row.scores or {}),
                **metrics,
            },
            workspace=workspace,
            user=user,
            run=run,
        )
        missing = any(
            entry.get("availability") == "source_unavailable"
            for entry in public_legacy["metadata"].get("excerpts", [])
        )
        if missing:
            # The formatted answer/claim text may quote an unavailable source.
            public_legacy = None
            metrics = {name: None for name in metrics}
            availability, reason = "unavailable", "evidence_unavailable"
        else:
            availability = (
                "available" if public_legacy["metadata"].get("excerpts") else "not_applicable"
            )
            threshold = metadata.get("threshold_outcome")
            if (
                execution_status == "completed"
                and isinstance(threshold, dict)
                and type(threshold.get("breach")) is bool
            ):
                quality_status = "failed" if threshold["breach"] else "passed"
    invocation_ids = sorted(
        {inv.id for inv in matched if inv.id in allowed_ids}
        | ({producer.id} if producer else set())
    )
    node_id = metadata.get("node_id") or (
        (producer.trace or {}).get("node_id") if producer else None
    )
    record = {
        "id": row.id,
        "evaluation_id": row.id,
        "run_id": run.id,
        "source": source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "execution_status": execution_status,
        "quality_status": quality_status,
        "reason": reason,
        "producer_invocation_id": producer.id if producer else None,
        "invocation_ids": invocation_ids,
        "node_id": node_id,
        "job_id": metadata.get("producer_job_id") or metadata.get("job_id"),
        "rubric": rubric,
        "coverage": coverage,
        "typed_evaluation": public_typed,
        "legacy_evaluation": public_legacy,
        "metrics": metrics,
        "evidence_sources": evidence_sources,
        "evidence_availability": availability,
        "review": {"count": len(reviews), "labels": [review.label for review in reviews]},
        "links": {
            "run": f"/runs/{run.id}",
            "record": f"/evaluation/records/{row.id}",
            "invocation": f"/runs/{run.id}/invocations/{producer.id}" if producer else None,
        },
    }
    return record


def project_records(db, rows, *, workspace, user):
    """Batch load access anchors once; returned records are all authorized."""
    run_ids = {row.run_id for row in rows if row.run_id}
    runs = db.query(Run).filter(Run.workspace_id == workspace.id, Run.id.in_(run_ids)).all()
    allowed_runs = readable_runs(db, runs=runs, user=user, workspace=workspace)
    by_run = {run.id: run for run in allowed_runs}
    invocations = db.query(SkillInvocation).filter(SkillInvocation.run_id.in_(by_run)).all()
    allowed = readable_skill_invocations_for_runs(
        db, invocations=invocations, runs=allowed_runs, user=user, workspace=workspace
    )
    allowed_ids = {inv.id for inv in allowed}
    feedback = (
        db.query(EvaluationFeedback)
        .filter(
            EvaluationFeedback.workspace_id == workspace.id,
            EvaluationFeedback.evaluation_score_id.in_([row.id for row in rows]),
        )
        .all()
    )
    records = []
    for row in rows:
        run = by_run.get(row.run_id)
        if run is None or row.workspace_id != workspace.id:
            continue
        record = _projection(
            db,
            row,
            run,
            workspace=workspace,
            user=user,
            invocations=[inv for inv in invocations if inv.run_id == run.id],
            allowed_ids=allowed_ids,
            reviews=[review for review in feedback if review.evaluation_score_id == row.id],
        )
        if record is not None:
            records.append(record)
    return records


def evaluation_totals(records):
    """Count observations, not invocations/cached references; rates state a base."""
    unique = {record["evaluation_id"]: record for record in records}.values()
    records = list(unique)
    passed = sum(record["quality_status"] == "passed" for record in records)
    failed = sum(record["quality_status"] == "failed" for record in records)
    return {
        "evaluations": len(records),
        "distinct_runs": len({record["run_id"] for record in records}),
        "technical_failures": sum(record["execution_status"] == "failed" for record in records),
        "completed": sum(record["execution_status"] == "completed" for record in records),
        "partial": sum(record["execution_status"] == "partial" for record in records),
        "assessed": passed + failed,
        "passed": passed,
        "failed": failed,
        "unassessed": len(records) - passed - failed,
        "pass_rate": passed / (passed + failed) if passed + failed else None,
        "pass_rate_denominator": passed + failed,
        "questions_total": sum(record["coverage"].get("questions_total", 0) for record in records),
        "questions_answered": sum(
            record["coverage"].get("questions_answered", 0) for record in records
        ),
        "evidence_unavailable": sum(
            record["evidence_availability"] == "unavailable" for record in records
        ),
        "reviewed": sum(record["review"]["count"] > 0 for record in records),
    }


def runtime_judgment_payload_visible(db, run, *, workspace, user):
    """Gate canonical runtime IO as well as the dedicated Quality projection.

    Runtime checkpoints and later nodes can copy Judge answers into arbitrary
    fields. When an original source is no longer readable, suppress that Run's
    payloads conservatively rather than trying to identify quoted substrings.
    Execution identities, statuses and measured timing remain available.
    """
    from app.models.evaluation import EvaluationScore

    rows = [
        row
        for row in db.query(EvaluationScore)
        .filter_by(workspace_id=run.workspace_id, run_id=run.id)
        .all()
        if (row.metadata_ or {}).get("source") == "evaluate_v2"
    ]
    retained_ids = {row.id for row in rows}
    producers = db.query(SkillInvocation).filter_by(run_id=run.id, skill_slug="evaluate_v2").all()
    for producer in producers:
        output = producer.output_ref if isinstance(producer.output_ref, dict) else {}
        if output.get("batch_mode") == "per_unit":
            # A document batch owns an immutable result object rather than one
            # EvaluationScore whose ID equals the batch digest.
            from app.services import governed_assets as assets

            if workspace is None or user is None:
                return False
            try:
                asset = assets.resolve_asset_ref(
                    db,
                    workspace.id,
                    output.get("asset_ref"),
                    authorize=historical_evidence_authorizer(db, workspace, user),
                )
                saved = (asset.manifest_json.get("output") or {}).get("typed_evaluation")
                if not isinstance(saved, dict) or any(
                    output.get(key) != value for key, value in saved.items()
                ):
                    return False
            except (
                assets.GovernanceError,
                HTTPException,
                OSError,
                ValueError,
                KeyError,
                TypeError,
            ):
                return False
            continue
        if output.get("schema_version") == 2 and output.get("evaluation_id") not in retained_ids:
            return False
    if not rows:
        return True
    if workspace is None or user is None:
        return False
    records = project_records(db, rows, workspace=workspace, user=user)
    return len(records) == len(rows) and all(
        record["evidence_availability"] == "available" for record in records
    )


def restricted_runtime_checkpoint(checkpoint):
    """Only structural timeline fields survive a revoked evidence grant."""
    if not isinstance(checkpoint, dict):
        return {"payload_unavailable_reason": "evidence_unavailable"}
    return {
        **{
            key: checkpoint[key]
            for key in ("kind", "t", "node_id", "decision_id", "decision_status", "status", "plane")
            if key in checkpoint
        },
        "payload_unavailable_reason": "evidence_unavailable",
    }


def unrecorded_controls(db, run, *, workspace, user, records):
    """Pending/failed producers do not become invented EvaluationScore rows."""
    from app.models.workspace_job import WorkspaceJob

    invocations = db.query(SkillInvocation).filter_by(run_id=run.id, skill_slug="evaluate_v2").all()
    allowed = readable_skill_invocations_for_runs(
        db, invocations=invocations, runs=[run], user=user, workspace=workspace
    )
    known = {record["evaluation_id"] for record in records}
    controls = []
    for invocation in allowed:
        result = invocation.output_ref if isinstance(invocation.output_ref, dict) else {}
        if result.get("evaluation_id") in known:
            continue
        controls.append(
            {
                "id": f"invocation:{invocation.id}",
                "evaluation_id": None,
                "source": "evaluate_v2",
                "execution_status": invocation.status,
                "producer_invocation_id": invocation.id,
                "node_id": (invocation.trace or {}).get("node_id"),
                "job_id": None,
                "quality_status": "unassessed",
                "reason": "evaluation_pending"
                if invocation.status in {"pending", "running"}
                else "no_persisted_evaluation",
                "links": {"invocation": f"/runs/{run.id}/invocations/{invocation.id}"},
            }
        )
    # Auto-evaluation jobs can precede the first scalar score. A targeted job
    # inherits its target invocation's current visibility.
    jobs = (
        db.query(WorkspaceJob)
        .filter_by(workspace_id=workspace.id, run_id=run.id, kind="run_evaluation")
        .filter(WorkspaceJob.status.in_(["created", "queued", "running"]))
        .all()
    )
    target_ids = {(job.input_ref or {}).get("invocation_id") for job in jobs} - {None}
    target_invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id, SkillInvocation.id.in_(target_ids))
        .all()
    )
    readable_ids = {
        inv.id
        for inv in readable_skill_invocations_for_runs(
            db, invocations=target_invocations, runs=[run], user=user, workspace=workspace
        )
    }
    for job in jobs:
        target = (job.input_ref or {}).get("invocation_id")
        if target and target not in readable_ids:
            continue
        controls.append(
            {
                "id": f"job:{job.id}",
                "evaluation_id": None,
                "source": "auto_eval",
                "execution_status": job.status,
                "producer_invocation_id": None,
                "node_id": None,
                "job_id": job.id,
                "quality_status": "unassessed",
                "reason": "evaluation_pending",
                "links": {"run": f"/runs/{run.id}"},
            }
        )
    return controls
