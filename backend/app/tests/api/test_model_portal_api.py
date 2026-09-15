"""Portal tests remain System-authorized canonical Workbench Runs."""
import copy
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import model_portal, models, flow_workbench
from app.models.run import Run, SkillInvocation
from app.models.system_flow_draft import SystemFlowDraft
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.tests.api.test_flow_workbench_api import _seed, _flow


@pytest.fixture
def portal(db_session, monkeypatch):
    workspace, user, system, skill = _seed(db_session)
    workspace.settings = {**workspace.settings, "features": {**workspace.settings["features"], "model_portal_beta": True}}
    skill.slug = f"ws.{workspace.id}.model-test"
    skill.executor = {"kind": "prompt_template", "params": {
        "provider": "openai", "model": "gpt-4o-mini", "template": "Summarize {text}"}}
    skill.input_schema = {"type": "object", "properties": {"text": {"type": "string"}, "model": {"type": "string"}},
                          "required": ["text"], "additionalProperties": False}
    flow = _flow("model-test", task={"id": "llm", "kind": "task", "config": {"skill_slug": skill.slug}})
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    draft.flow_definition = copy.deepcopy(flow)
    draft.flow_sha256 = canonical_flow_sha256(flow)
    db_session.commit()
    dispatches = []
    monkeypatch.setattr(flow_workbench, "schedule_run", dispatches.append)
    app = FastAPI()
    app.include_router(models.router, prefix="/models")
    app.include_router(model_portal.router, prefix="/models")
    app.dependency_overrides[model_portal.get_current_workspace] = lambda: workspace
    app.dependency_overrides[model_portal.get_current_user] = lambda: user
    app.dependency_overrides[model_portal.get_db] = lambda: db_session
    return TestClient(app), workspace, user, system, skill, flow, dispatches


def _test_body(system, flow):
    return {"system_id": system.id, "node_id": "llm", "provider": "openai", "model": "gpt-4o-mini",
            "expected_flow_sha256": canonical_flow_sha256(flow), "input_ref": {"text": "Synthetic fixture"},
            "acknowledge_real_side_effects": True}


def test_targets_use_current_draft_and_create_one_canonical_run(portal, db_session):
    client, workspace, user, system, skill, flow, dispatches = portal
    response = client.get("/models/test-targets", params={"provider": "openai", "model": "gpt-4o-mini"})
    assert response.status_code == 200, response.text
    target = response.json()["targets"][0]
    assert target["system_id"] == system.id and target["node_id"] == "llm"
    assert target["input_schema"] == skill.input_schema
    before = copy.deepcopy(system.flow_definition)
    response = client.post("/models/test", json=_test_body(system, flow))
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    assert dispatches == [run_id]
    run = db_session.get(Run, run_id)
    assert run.system_id == system.id and run.workspace_id == workspace.id
    assert run.execution_surface == "node_preview"
    assert run.execution_contract["nodes"]["llm"]["executor"] == skill.executor
    assert response.json()["run_url"] == f"/runs/{run_id}"
    assert system.flow_definition == before, "the test cannot publish or edit the System"


@pytest.mark.parametrize("change,expected", [("provider", 409), ("model", 409), ("stale", 409), ("foreign", 404), ("ack", 422)])
def test_rejected_test_never_enqueues_or_creates_a_run(portal, db_session, change, expected):
    client, workspace, user, system, skill, flow, dispatches = portal
    body = _test_body(system, flow)
    if change == "provider": body["provider"] = "azure_openai"
    if change == "model": body["model"] = "different-model"
    if change == "stale": body["expected_flow_sha256"] = "0" * 64
    if change == "foreign": body["system_id"] = "other-workspace-system"
    if change == "ack": body["acknowledge_real_side_effects"] = 1
    before = db_session.query(Run).count()
    response = client.post("/models/test", json=body)
    assert response.status_code == expected, response.text
    assert dispatches == [] and db_session.query(Run).count() == before


def test_non_admin_sees_permission_and_cannot_test(portal):
    client, workspace, user, system, skill, flow, dispatches = portal
    user.role = "user"
    config = client.get("/models/config")
    assert config.status_code == 200
    assert config.json()["can_configure"] is False and config.json()["can_test"] is False
    assert client.post("/models/test", json=_test_body(system, flow)).status_code == 403
    assert client.put("/models/routing", json={"default_provider": "openai", "default_model": "gpt-5"}).status_code == 403
    assert dispatches == []


def test_disabled_workbench_explains_unavailable_test(portal):
    client, workspace, user, system, skill, flow, dispatches = portal
    workspace.settings = {**workspace.settings, "features": {"model_portal_beta": True}}
    config = client.get("/models/config").json()
    assert config["can_test"] is False
    assert config["test_blockers"][0]["code"] == "FLOW_WORKBENCH_DISABLED"
    targets = client.get("/models/test-targets", params={"provider": "openai", "model": "gpt-4o-mini"}).json()
    assert targets["targets"] == [] and targets["can_test"] is False


def test_connection_check_is_not_generation_and_keeps_public_metadata(portal, monkeypatch):
    client, workspace, user, system, skill, flow, dispatches = portal
    async def providers(**kwargs):
        assert kwargs["workspace"].id == workspace.id
        return [{"key": "openai", "status": "unreachable", "error": "HTTP 401", "models": []}]
    monkeypatch.setattr(model_portal.providers_service, "list_providers", providers)
    response = client.post("/models/providers/openai/test")
    assert response.status_code == 200
    assert response.json()["generation_verified"] is False
    assert response.json()["provider"]["status"] == "unreachable"
    assert dispatches == []


def test_catalogue_error_is_structured_instead_of_an_empty_success(portal, monkeypatch):
    client, *_ = portal
    async def fail(**kwargs):
        raise RuntimeError("fixture unavailable")
    monkeypatch.setattr(models.providers, "list_models", fail)
    response = client.get("/models")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "MODEL_CATALOG_UNAVAILABLE"


def test_status_uses_workspace_catalogue_and_supports_model_path(portal, monkeypatch):
    client, workspace, *_ = portal
    async def catalog(**kwargs):
        assert kwargs["workspace"] is workspace
        return [{"id": "openai:org/custom-model", "provider": "openai", "model": "org/custom-model",
                 "status": "unreachable", "runtime_available": True, "compatibility": "unknown"}]
    monkeypatch.setattr(models.providers, "list_models", catalog)
    response = client.get("/models/openai:org/custom-model/status")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unreachable"
    assert response.json()["provider"] == "openai" and response.json()["generation_verified"] is False
    assert client.get("/models/not-present/status").json()["detail"]["code"] == "MODEL_NOT_FOUND"


def test_status_requires_provider_when_bare_model_is_ambiguous(portal, monkeypatch):
    client, *_ = portal
    async def catalog(**kwargs):
        return [{"id": provider + ":shared", "provider": provider, "model": "shared"}
                for provider in ("openai", "azure_openai")]
    monkeypatch.setattr(models.providers, "list_models", catalog)
    response = client.get("/models/shared/status")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MODEL_AMBIGUOUS"


def test_routing_reads_actual_skill_configuration_and_respects_system_read(portal, monkeypatch):
    from app.api.v1.endpoints import systems
    client, workspace, user, system, skill, *_ = portal
    async def nodes(**kwargs):
        assert kwargs["workspace"] is workspace
        return {"nodes": []}
    async def providers(**kwargs):
        assert kwargs["workspace"] is workspace
        return [{"key": "azure_openai", "configured": True, "runtime_available": True}]
    monkeypatch.setattr(model_portal.serving_nodes_service, "list_nodes", nodes)
    monkeypatch.setattr(model_portal.providers_service, "list_providers", providers)
    system.default_model = "system-default-that-is-not-used"
    response = client.get("/models/routing")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["registered_clients"] == ["azure_openai"]
    usage = payload["model_usage"][0]
    assert usage["system_id"] == system.id and usage["node_id"] == "llm"
    assert usage["model"] == "gpt-4o-mini" and usage["model_source"] == "executor"
    assert usage["source"] == "current_flow"
    def deny(*args, **kwargs):
        raise HTTPException(status_code=404)
    monkeypatch.setattr(systems, "_enforce_system_read", deny)
    denied = client.get("/models/routing").json()
    assert denied["systems"] == [] and denied["model_usage"] == []


def test_distribution_excludes_other_users_private_run_and_evidence(portal, db_session):
    client, workspace, user, system, *_ = portal
    user.role = "user"
    runs = [Run(id=str(uuid4()), workspace_id=workspace.id, system_id=system.id, status="completed",
                trigger=trigger, initiated_by_user_id=owner, started_at=datetime.utcnow())
            for trigger, owner in [("manual", user.id), ("chat_agentic", "another-user")]]
    db_session.add_all(runs)
    db_session.flush()
    invocations = [SkillInvocation(id=str(uuid4()), run_id=run.id, started_at=datetime.utcnow(),
                                  status="completed", trace={"model_execution": {
                                      "provider": "openai", "model": "gpt-4o-mini"}})
                   for run in runs]
    db_session.add_all(invocations)
    db_session.commit()
    response = client.get("/models/distribution")
    assert response.status_code == 200, response.text
    totals = response.json()["totals"]
    assert totals["invocations"] == 1
    assert totals["run_ids"] == [runs[0].id] and totals["invocation_ids"] == [invocations[0].id]
    assert runs[1].id not in str(response.json()) and invocations[1].id not in str(response.json())
