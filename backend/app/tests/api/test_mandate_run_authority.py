"""HTTP admission and runtime select the same immutable mandate."""
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import systems
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services.flow_contracts import canonical_sha256
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication
from app.tests.iam_baseline import OPEN_IAM_FEATURES


def _fixture(db, *, published_model="model-approved", live_model="model-denied"):
    suffix = uuid4().hex[:10]
    workspace = Workspace(id=f"mandate-http-ws-{suffix}", slug=f"mandate-http-{suffix}", name="Mandate HTTP",
                          settings={"features": {"flow_publication_v1": True, **OPEN_IAM_FEATURES},
                                    "llm_portal": {"routing": {"default_model": published_model}}})
    user = User(id=f"mandate-http-admin-{suffix}", username=f"mandate-admin-{suffix}", role="admin")
    flow = {"schema_version": 3, "nodes": [
        {"id": "input", "kind": "source"}, {"id": "result", "kind": "sink"}],
        "edges": [{"from": "input", "to": "result", "kind": "data"}]}
    system = System(id=f"mandate-http-system-{suffix}", workspace_id=workspace.id, name="Mandate",
                    objective="test", status="active", default_model="model-approved",
                    flow_definition=flow, settings={})
    policy = ControlPolicy(id=f"mandate-http-policy-{suffix}", workspace_id=workspace.id,
                           scope="system", target_id=system.id, name="Mandate policy",
                           extra={"membrane_spec": {"version": 2, "enforcement_mode": "enforce",
                                  "capabilities": {"allowed_models": [published_model]}}})
    system.control_policy_id = policy.id
    db.add_all([workspace, user, system, policy])
    db.flush()
    contract = flow_publication.compile_execution_contract(db, flow, workspace, system=system)
    version = SystemVersion(id=f"mandate-http-version-{suffix}", workspace_id=workspace.id,
                            system_id=system.id, version_number=1, flow_definition=flow,
                            flow_sha256=canonical_flow_sha256(flow), execution_contract=contract,
                            release_kind="publish", draft_revision=1)
    db.add(version)
    db.flush()
    system.published_flow_version_id = version.id
    policy.extra = {"membrane_spec": {"version": 2, "enforcement_mode": "enforce",
                    "capabilities": {"allowed_models": [live_model]}}}
    db.commit()
    return workspace, user, system, contract


def _admit(db, fixture, **kwargs):
    workspace, user, system, _ = fixture
    systems._enforce_system_run_authority(db, user=user, workspace=workspace, system=system,
                                         execution_source="test", **kwargs)


def test_http_new_run_uses_published_policy_despite_live_edit(db_session):
    fixture = _fixture(db_session)
    _admit(db_session, fixture)


def test_http_replay_uses_its_stored_policy_and_legacy_keeps_live_checks(db_session):
    fixture = _fixture(db_session)
    _admit(db_session, fixture, execution_contract=fixture[3])
    with pytest.raises(HTTPException) as denied:
        _admit(db_session, fixture, execution_contract={})
    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "MEMBRANE_CAPABILITY_DENIED"


def test_live_policy_cannot_relax_frozen_run_mandate(db_session):
    fixture = _fixture(db_session, published_model="model-denied", live_model="model-approved")
    with pytest.raises(HTTPException) as denied:
        _admit(db_session, fixture)
    assert denied.value.status_code == 403


def test_frozen_mandate_does_not_bypass_current_iam(db_session, monkeypatch):
    fixture = _fixture(db_session)
    def revoked(*args, **kwargs):
        raise HTTPException(403, "IAM permission revoked")
    monkeypatch.setattr(systems, "enforce_action", revoked)
    with pytest.raises(HTTPException) as denied:
        _admit(db_session, fixture, execution_contract=fixture[3])
    assert denied.value.detail == "IAM permission revoked"


def test_frozen_mandate_tampering_fails_before_queueing(db_session):
    fixture = _fixture(db_session)
    invalid = deepcopy(fixture[3])
    invalid["control_policy_snapshot"]["system_id"] = "other-system"
    invalid.pop("contract_sha256")
    invalid["contract_sha256"] = canonical_sha256(invalid)
    with pytest.raises(HTTPException) as denied:
        _admit(db_session, fixture, execution_contract=invalid)
    assert denied.value.status_code == 409
    assert denied.value.detail["code"] == "CONTROL_POLICY_SNAPSHOT_INVALID"
