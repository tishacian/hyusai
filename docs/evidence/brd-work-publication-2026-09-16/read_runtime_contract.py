"""Read-only check of the new corpus resolver against retained real Run contracts."""
import json
import os
from datetime import datetime, timezone
from sqlalchemy import text
from app.db.base import SessionLocal
from app.models.run import Run
from app.models.evaluation_campaign import EvaluationSuite
from app.services.evaluation.campaigns import contract_collection_ids, corpus_manifest, validate_brd_corpus_bindings

sha = "b4fde677a75a7a9f6ab30898882104c37582709b"
assert os.environ.get("AGENTIUM_IMAGE_REVISION") == sha
workspace_id = "e2ed9e40-5fa6-4e32-8948-3e1220134fd3"
run_ids = ["a57c9f78-d805-42e6-91d2-1ac6d27a224a", "40e53546-a6af-40a4-a777-2204e2837d10"]
with SessionLocal() as db:
    db.execute(text("SET TRANSACTION READ ONLY"))
    suite = db.query(EvaluationSuite).filter_by(id="984d3c08-0340-4ffd-b90d-ef0ab6802116", workspace_id=workspace_id).one()
    checks = []
    for run_id in run_ids:
        run = db.query(Run).filter_by(id=run_id, workspace_id=workspace_id).one()
        ids = contract_collection_ids(db, workspace_id=workspace_id, contract=run.execution_contract)
        assert len(ids) == 2, ids
        manifest = corpus_manifest(db, workspace_id, ids)
        limitations = validate_brd_corpus_bindings(db, workspace_id=workspace_id, suite=suite, contract=run.execution_contract)
        assert limitations and suite.corpus_manifest == []
        checks.append({"retained_run_id": run.id, "status": run.status, "collection_ids": ids,
                       "current_ledger": manifest, "historical_suite_limitations": limitations})
    print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "reader_revision": sha,
                      "read_only": True, "new_run_created": False, "provider_called": False,
                      "historical_suite_id": suite.id, "checks": checks}, indent=2))
