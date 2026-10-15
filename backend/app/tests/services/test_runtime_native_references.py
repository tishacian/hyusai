"""Native read adapter qualification requires no optional runtime dependencies."""
from dataclasses import replace

import pytest

from app.models.recipe import RecipeExecution
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.execution.runtimes.contracts import ExecutionScope, NativeReference, native_port
from app.services.execution.runtimes.references import observe_native


def test_no_production_submission_adapter_is_implicitly_installed():
    with pytest.raises(RuntimeError, match="NATIVE_SUBMISSION_ADAPTER_UNQUALIFIED"):
        native_port()


def test_native_observation_requires_workspace_parent_frozen_contract_and_current_actor(db_session):
    db = db_session
    db.add(Workspace(id="native-ws", slug="native-ws", name="Native"))
    db.add(User(id="native-admin", username="native-admin", role="admin", is_active=True))
    db.commit()
    db.add_all([
        Run(id="parent", workspace_id="native-ws", status="running", flow_sha256="a"*64, published_flow_version_id="version"),
        RecipeExecution(id="calculation", workspace_id="native-ws", run_id="parent", status="running"),
        RecipeExecution(id="unrelated", workspace_id="native-ws", run_id="another-parent", status="succeeded"),
    ])
    db.commit()
    scope = ExecutionScope("native-ws", "parent", "native-admin", "version", "a"*64)
    reference = NativeReference("recipe_execution", "calculation", "native-ws", "parent")
    assert observe_native(db, scope, reference).status == "running"
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        observe_native(db, scope, replace(reference, workspace_id="another-workspace"))
    with pytest.raises(ValueError, match="PARENT_MISMATCH"):
        observe_native(db, scope, replace(reference, id="unrelated"))
    with pytest.raises(ValueError, match="CONTRACT_MISMATCH"):
        observe_native(db, replace(scope, flow_digest="b"*64), reference)
    with pytest.raises(ValueError, match="FROZEN_CONTRACT_REQUIRED"):
        observe_native(db, replace(scope, flow_digest=None, version_id=None), reference)
    with pytest.raises(ValueError, match="KIND_UNSUPPORTED"):
        observe_native(db, scope, replace(reference, kind="decision"))
    db.get(User, "native-admin").is_active = False
    db.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        observe_native(db, scope, reference)
