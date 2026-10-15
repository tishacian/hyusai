"""Operator reconciliation releases capacity only after explicit attestation."""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.models.execution_control import ExecutionReservation
from app.models.workspace import Workspace
from app.services.execution.admission import reserve
from scripts import execution_operations as operations


def test_reconcile_requires_stopped_evidence_and_preserves_unknown_usage(
    db_session, tmp_path, capsys
):
    workspace = Workspace(id=str(uuid4()), slug=str(uuid4()), name="Operations")
    db_session.add(workspace)
    db_session.commit()
    row = reserve(
        db_session,
        workspace_id=workspace.id,
        entity_kind="recipe_execution",
        entity_id=str(uuid4()),
        cpu_cores=1,
        memory_mb=512,
        deadline_at=datetime.utcnow() + timedelta(minutes=1),
    )
    row.outcome = "reconciliation_required"
    db_session.commit()
    identifier = row.id
    evidence = tmp_path / "stop.json"
    evidence.write_text('{"process_stopped":true,"host":"disposable-local-probe"}')
    args = [
        "reconcile-stopped",
        identifier,
        "--operator",
        "test-operator",
        "--evidence",
        str(evidence),
    ]
    with pytest.raises(SystemExit):
        operations.main(args)
    db_session.expire_all()
    assert row.released_at is None
    operations.main([*args, "--confirm-process-stopped"])
    result = json.loads(capsys.readouterr().out)
    assert result["cpu_seconds"] is None
    assert result["evidence_sha256"] == hashlib.sha256(evidence.read_bytes()).hexdigest()
    db_session.expire_all()
    assert db_session.get(ExecutionReservation, identifier).released_at is not None
    assert row.policy["reconciliation"]["operator"] == "test-operator"
    with pytest.raises(SystemExit, match="not already released"):
        operations.main([*args, "--confirm-process-stopped"])
