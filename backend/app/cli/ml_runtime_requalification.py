"""Bulk reference capture and runtime requalification around an image upgrade.

Usage:
  python -m app.cli.ml_runtime_requalification capture \
      (--workspace ID ... | --all-workspaces) [--model ID] (--dry-run | --apply)
  python -m app.cli.ml_runtime_requalification requalify \
      (--workspace ID ... | --all-workspaces) [--model ID] (--dry-run | --apply)

Before deploying a new image, run ``capture --apply`` with the CURRENT image:
it records reference predictions for each ready model that lacks them while
the reader still is the producer runtime. After deploying, run ``requalify
--apply`` with the NEW image: this process is the reader being attested, so it
must run the image the API serves with. Dry-run reads metadata only — no
dataset, artifact or subprocess. Both are idempotent: a captured, current or
attested model is reported and skipped. One JSON line per model; the exit
status is 1 when a supported model was (or would be) refused or failed.
"""

from __future__ import annotations

import argparse
import json

from app.db.base import SessionLocal
from app.models.ml_requalification import MLRuntimeAttestation
from app.models.tabular import MLModel
from app.models.workspace import Workspace
from app.services import ml_requalification as service
from app.services.ml.artifacts import runtime_digest
from app.services.tabular_datasets import TabularError


def _models(db, workspaces, model_id):
    query = (
        db.query(MLModel)
        .join(Workspace, Workspace.id == MLModel.workspace_id)
        .filter(MLModel.status == "ready", Workspace.deleted_at.is_(None))
    )
    if workspaces is not None:
        query = query.filter(MLModel.workspace_id.in_(workspaces))
    if model_id:
        query = query.filter(MLModel.id == model_id)
    return [row.id for row in query.order_by(MLModel.workspace_id, MLModel.id).all()]


def plan(db, model, action: str) -> dict:
    """What ``--apply`` would do, from metadata only."""
    reason = service.support(model)
    if reason:
        return {"action": "skipped", "reason": reason}
    producer = service._artifact(model).get("runtime")
    reader = service.reader_runtime(model)
    summary = service.reference_summary(model)
    if action == "capture":
        if summary is not None:
            return {"action": "already_captured"}
        if producer != reader or "missing" in reader.values():
            return {"action": "refused", "code": "ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED"}
        if ((model.metrics_json or {}).get("evaluation") or {}).get("status") != "stored":
            return {"action": "refused", "code": "ML_REFERENCE_SOURCE_UNAVAILABLE"}
        return {"action": "would_capture"}
    if producer == reader:
        return {"action": "current"}
    attested = (
        service._active(db, model)
        .filter(MLRuntimeAttestation.reader_digest == runtime_digest(reader))
        .first()
    )
    if attested is not None:
        return {"action": "attested", "attestation_id": attested.id}
    if summary is None:
        return {"action": "refused", "code": "ML_REFERENCE_MISSING"}
    return {"action": "would_requalify"}


def apply(db, model, action: str) -> dict:
    planned = plan(db, model, action)
    if planned["action"] not in {"would_capture", "would_requalify"}:
        return planned
    try:
        if action == "capture":
            outcome = service.capture_reference(db, model, actor=service.OPERATOR)
            return {"action": outcome["action"], "rows": outcome["reference"].get("rows")}
        outcome = service.requalify(db, model, actor=service.OPERATOR)
    except TabularError as exc:
        db.rollback()
        return {"action": "refused", "code": exc.code}
    attestation = outcome["attestation"]
    return {
        "action": outcome["action"],
        "attestation_id": attestation["id"],
        "verdict": attestation["verdict"],
        "code": attestation["error_code"],
        "metrics": attestation["metrics"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=("capture", "requalify"))
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--workspace", action="append", metavar="ID")
    scope.add_argument("--all-workspaces", action="store_true")
    parser.add_argument("--model", metavar="ID")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    # Register mappings for SQLAlchemy relationships; no schema mutation or seeding.
    import app.models  # noqa: F401

    failed = False
    with SessionLocal() as db:
        for model_id in _models(db, None if args.all_workspaces else args.workspace, args.model):
            model = db.get(MLModel, model_id, populate_existing=True)
            if model is None:
                continue
            row = (apply if args.apply else plan)(db, model, args.action)
            failed = failed or row["action"] in {"refused", "failed"}
            print(
                json.dumps(
                    {
                        "workspace_id": model.workspace_id,
                        "model_id": model.id,
                        "version": model.version,
                        **row,
                    },
                    sort_keys=True,
                )
            )
            db.rollback()  # Each model is its own unit; read the next one fresh.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
