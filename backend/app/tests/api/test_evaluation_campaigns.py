"""Comparisons retain authority, immutable baselines and explicit test verdicts."""
import copy
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.api.v1.endpoints import evaluation_campaigns as api
from app.tests.api.test_flow_workbench_api import _seed
from app.services.systems import flow_workbench
from app.services.evaluation import campaigns
from app.models.run import Run
from app.models.system_flow_draft import SystemFlowDraft
from app.models.knowledge_collection import KnowledgeCollection


@pytest.fixture(autouse=True)
def reset_comparison_test_policy(db_session):
    from app.models.policy import ControlPolicy
    db_session.query(ControlPolicy).filter_by(workspace_id="ws-flow-workbench").delete()
    db_session.commit()


def client(db, workspace, user, monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/evaluation")
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[api.get_current_workspace] = lambda: workspace
    app.dependency_overrides[api.get_current_user] = lambda: user
    monkeypatch.setattr(api, "dispatch_workspace_job", lambda *args, **kwargs: "test-task")
    return TestClient(app)


def setup_campaign(db, monkeypatch, *, assertions=None):
    workspace, user, system, _ = _seed(db)
    http = client(db, workspace, user, monkeypatch)
    suite = http.post("/evaluation/suites", json={"system_id": system.id, "name": "pressure", "reviewed": True,
        "cases": [{"id": "direct", "input_ref": {"case": "pressure"}, "assertions": assertions or []}]} )
    assert suite.status_code == 201, suite.text
    draft = db.get(SystemFlowDraft, system.id)
    prepared = flow_workbench.prepare_preview(db, system_id=system.id, workspace=workspace,
        flow_definition=draft.flow_definition, expected_flow_sha256=draft.flow_sha256, ingress_id=None, ingress_kind=None)
    baseline = flow_workbench.create_run(db, prepared=prepared, workspace=workspace, user_id=user.id, surface="golden_preview", input_ref={"case": "pressure"})
    baseline.status = "completed"
    db.commit()
    body = {"suite_id": suite.json()["id"], "baseline_run_id": baseline.id,
            "expected_draft_revision": draft.revision, "request_key": "comparison-1"}
    return http, body, baseline, workspace, user, system


def test_no_oracle_is_unevaluated_and_baseline_is_frozen(db_session, monkeypatch):
    http, body, baseline, *_ = setup_campaign(db_session, monkeypatch)
    frozen = copy.deepcopy(baseline.execution_contract)
    response = http.post("/evaluation/campaigns", json=body)
    assert response.status_code == 201, response.text
    campaign = response.json()
    for side in ("baseline", "candidate"):
        run = db_session.get(Run, campaign["results"][0][side]["run_id"])
        run.status, run.output_ref = "completed", {"value": 6}
        if side == "baseline":
            assert run.execution_contract == frozen
    db_session.commit()
    result = http.get(f"/evaluation/campaigns/{campaign['id']}").json()
    assert result["status"] == "completed"
    assert result["results"][0]["change"] == "unevaluated"
    assert result["snapshot"]["comparability"] == "limited"


def test_server_verdict_detects_regression_and_deduplicates(db_session, monkeypatch):
    http, body, *_ = setup_campaign(db_session, monkeypatch, assertions=[{"id": "pressure", "path": ["pressure"], "operator": "equals", "value": 6}])
    first = http.post("/evaluation/campaigns", json=body)
    assert first.status_code == 201, first.text
    assert http.post("/evaluation/campaigns", json=body).json()["id"] == first.json()["id"]
    assert db_session.query(Run).count() == 3
    assert http.post("/evaluation/campaigns", json={**body, "expected_draft_revision": 99}).status_code == 409
    for side, value in (("baseline", 6), ("candidate", 8)):
        run = db_session.get(Run, first.json()["results"][0][side]["run_id"])
        run.status, run.output_ref = "completed", {"pressure": value}
    db_session.commit()
    result = http.get(f"/evaluation/campaigns/{first.json()['id']}").json()
    assert result["results"][0]["change"] == "regressed"
    assert result["results"][0]["candidate"]["assertions"][0]["passed"] is False


def test_draft_conflict_creates_no_runs(db_session, monkeypatch):
    http, body, *_ = setup_campaign(db_session, monkeypatch)
    assert http.post("/evaluation/campaigns", json={**body, "expected_draft_revision": 99}).status_code == 409
    assert db_session.query(Run).count() == 1


def test_review_requires_actual_boolean(db_session, monkeypatch):
    workspace, user, system, _ = _seed(db_session)
    http = client(db_session, workspace, user, monkeypatch)
    response = http.post("/evaluation/suites", json={"system_id": system.id, "name": "invalid", "reviewed": 1, "cases": [{"id": "a", "input_ref": {}}]})
    assert response.status_code == 422


@pytest.mark.parametrize("executor", ["http", "python", "mcp", "unknown"])
def test_unqualified_executor_rejected_even_when_claiming_read(executor):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        campaigns.assert_read_only({"nodes": [{"id": "a", "kind": "skill", "config": {"effect": "read"}}]},
            {"nodes": {"a": {"executor": {"kind": executor, "params": {}}}}})


def test_assertions_distinguish_absence_zero_null_and_false():
    def check(value, expected):
        return campaigns.assertion_results(value, [{"id": "v", "path": ["value"], "operator": "equals", "value": expected}])["verdict"]
    assert check({}, None) == "failed"
    assert check({"value": None}, None) == "passed"
    assert check({"value": 0}, False) == "failed"
    assert check({"value": 0}, 0) == "passed"
    assert check({"value": {"nested": 0}}, {"nested": False}) == "failed"


def test_authored_prompt_task_is_supported():
    campaigns.assert_read_only({"nodes": [{"id": "summarize", "kind": "task"}]},
        {"nodes": {"summarize": {"executor": {"kind": "prompt_template", "params": {"template": "Summarize {text}"}}}}})


def test_collection_drift_suppresses_improvement(db_session, monkeypatch):
    http, body, baseline, workspace, user, system = setup_campaign(db_session, monkeypatch)
    collection = KnowledgeCollection(id="pressure-doc", workspace_id=workspace.id, slug="pressure", name="Pressure",
        vector_collection_name="pressure", artifact_prefix="pressure/", status="ready", document_names=["manual.pdf"])
    db_session.add(collection)
    db_session.commit()
    from app.models.evaluation_campaign import EvaluationSuite
    suite = db_session.get(EvaluationSuite, body["suite_id"])
    suite.corpus_manifest = campaigns.corpus_manifest(db_session, workspace.id, [collection.id])
    db_session.commit()
    created = http.post("/evaluation/campaigns", json=body)
    assert created.status_code == 201, created.text
    collection.document_names = ["changed.pdf"]
    db_session.commit()
    result = http.get(f"/evaluation/campaigns/{created.json()['id']}").json()
    assert result["snapshot"]["comparability"] == "not_comparable"
    assert result["results"][0]["change"] == "not_comparable"


def test_withdrawn_run_access_hides_campaign_and_listing(db_session, monkeypatch):
    from fastapi import HTTPException
    http, body, *_ = setup_campaign(db_session, monkeypatch)
    created = http.post("/evaluation/campaigns", json=body).json()
    def deny(*args, **kwargs):
        raise HTTPException(404, "Run not found")
    monkeypatch.setattr(api, "_visible_run_or_404", deny)
    assert http.get(f"/evaluation/campaigns/{created['id']}").status_code == 404
    assert http.get('/evaluation/campaigns', params={"system_id": created["system_id"]}).json() == []


def test_missing_worker_is_terminal_and_cancels_unexecuted_cases(db_session, monkeypatch):
    http, body, *_ = setup_campaign(db_session, monkeypatch)
    monkeypatch.setattr(api, "dispatch_workspace_job", lambda *args, **kwargs: None)
    created = http.post("/evaluation/campaigns", json=body)
    assert created.status_code == 201
    assert created.json()["status"] == "failed"
    refreshed = http.get(f"/evaluation/campaigns/{created.json()['id']}").json()
    assert refreshed["status"] == "failed"
    assert refreshed["results"][0]["candidate"]["status"] == "cancelled"
    assert refreshed["results"][0]["candidate"]["verdict"] == "unevaluated"


def test_giskard_requires_reviewed_text_reference_before_dispatch(db_session, monkeypatch):
    http, body, *_ = setup_campaign(db_session, monkeypatch)
    created = http.post("/evaluation/campaigns", json=body).json()
    for side in ("baseline", "candidate"):
        run = db_session.get(Run, created["results"][0][side]["run_id"])
        run.status, run.output_ref = "completed", {"answer": "6 bar"}
    db_session.commit()
    assert http.post(f"/evaluation/campaigns/{created['id']}/raget", json={"request_key": "raget-one"}).status_code == 422


def test_generation_is_idempotent_and_never_persists_credentials(db_session, monkeypatch):
    from types import SimpleNamespace
    from app.models.workspace_job import WorkspaceJob
    workspace, user, system, _ = _seed(db_session)
    collection = KnowledgeCollection(id="generation-doc", workspace_id=workspace.id, slug="generation", name="Generation",
        vector_collection_name="generation", artifact_prefix="generation/", status="ready")
    db_session.add(collection)
    db_session.commit()
    http = client(db_session, workspace, user, monkeypatch)
    monkeypatch.setattr("app.services.model_plane.execution.resolve_model_execution", lambda *args, **kwargs: SimpleNamespace(provider="openai", model="gpt-4o-mini", _api_key="secret-only-in-memory"))
    payload = {"system_id": system.id, "collection_ids": [collection.id], "request_key": "generation-one"}
    # SQLite ignores locks: compile the actual endpoint query for PostgreSQL.
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql
    locks = []
    def capture_lock(state):
        if state.is_select and getattr(state.statement, "_for_update_arg", None) is not None:
            locks.append(str(state.statement.compile(dialect=postgresql.dialect())))
    event.listen(db_session, "do_orm_execute", capture_lock)
    try:
        first = http.post('/evaluation/generations', json=payload)
    finally:
        event.remove(db_session, "do_orm_execute", capture_lock)
    assert first.status_code == 201, first.text
    assert any("FOR UPDATE OF systems" in sql for sql in locks)
    second = http.post('/evaluation/generations', json=payload)
    assert second.json()["id"] == first.json()["id"]
    assert db_session.query(WorkspaceJob).filter_by(kind="evaluation_generation").count() == 1
    assert "secret-only-in-memory" not in first.text
    assert http.post('/evaluation/generations', json={**payload, "num_questions": 4}).status_code == 409


def test_giskard_unconfigured_provider_refuses_before_creating_job(db_session, monkeypatch):
    from types import SimpleNamespace
    from app.models.workspace_job import WorkspaceJob
    workspace, user, system, _ = _seed(db_session)
    http = client(db_session, workspace, user, monkeypatch)
    monkeypatch.setattr("app.services.model_plane.execution.resolve_model_execution", lambda *args, **kwargs: SimpleNamespace(provider="ollama", _api_key=None))
    response = http.post('/evaluation/generations', json={"system_id": system.id, "collection_ids": ["missing"], "request_key": "generation-one"})
    assert response.status_code == 409
    assert db_session.query(WorkspaceJob).filter_by(kind="evaluation_generation").count() == 0


def test_campaign_worker_dispatches_canonical_runs_once_and_persists_verdict(db_session, monkeypatch):
    http, body, *_ = setup_campaign(db_session, monkeypatch, assertions=[{"id": "pressure", "path": ["answer"], "operator": "contains", "value": "6 bar"}])
    created = http.post('/evaluation/campaigns', json=body).json()
    calls = []
    def execute(run_id):
        calls.append(run_id)
        run = db_session.get(Run, run_id)
        run.status, run.output_ref = "completed", {"answer": "6 bar"}
        db_session.commit()
    monkeypatch.setattr("app.db.base.SessionLocal", lambda: db_session)
    monkeypatch.setattr("app.services.run_engine.schedule_run", execute)
    result = campaigns.run_campaign_job(created["job_id"])
    assert result["campaign_status"] == "completed"
    assert len(calls) == 2
    campaigns.run_campaign_job(created["job_id"])
    assert len(calls) == 2
    from app.models.evaluation_campaign import EvaluationCampaign
    refreshed = db_session.get(EvaluationCampaign, created["id"])
    assert refreshed.results[0]["candidate"]["verdict"] == "passed"


@pytest.mark.parametrize("ledger,expected,coverage", [
    ([], None, "unavailable"), ([(0, None)], None, "unavailable"),
    ([(10, False)], None, "unavailable"), ([(0, True)], 0, "complete"),
    ([(0.01, True), (0, False)], None, "partial"),
    ([(0.01, True), (0.02, True)], 0.03, "complete"),
])
def test_cost_uses_complete_invocation_measurements_only(db_session, ledger, expected, coverage):
    from app.models.run import SkillInvocation
    workspace, user, system, _ = _seed(db_session)
    run = Run(workspace_id=workspace.id, system_id=system.id, status="completed", cost_internal=999)
    db_session.add(run)
    db_session.flush()
    for cost, measured in ledger:
        db_session.add(SkillInvocation(run_id=run.id, cost=cost, cost_measured=measured, status="completed"))
    db_session.commit()
    evidence = campaigns.execution_cost_evidence(db_session, run)
    assert evidence["execution_cost"] == expected
    assert evidence["execution_cost_coverage"] == coverage
    assert evidence["execution_cost_measurements"] == sum(flag is True for _, flag in ledger)


def test_worker_failure_preserves_completed_run_and_cancels_pending_retry_is_new_attempt(db_session, monkeypatch):
    from app.models.evaluation_campaign import EvaluationCampaign
    from app.models.workspace import Workspace
    from app.models.user import User
    http, body, _, workspace, user, _ = setup_campaign(db_session, monkeypatch)
    workspace_id, user_id = workspace.id, user.id
    created = http.post('/evaluation/campaigns', json=body).json()
    calls = []
    def execute(run_id):
        calls.append(run_id)
        if len(calls) == 2:
            raise RuntimeError("worker interrupted")
        run = db_session.get(Run, run_id)
        run.status, run.output_ref = "completed", {"answer": "6 bar"}
        db_session.commit()
    monkeypatch.setattr("app.db.base.SessionLocal", lambda: db_session)
    monkeypatch.setattr("app.services.run_engine.schedule_run", execute)
    assert campaigns.run_campaign_job(created["job_id"])["status"] == "failed"
    result = db_session.get(EvaluationCampaign, created["id"])
    assert result.status == "failed"
    assert result.results[0]["baseline"]["status"] == "completed"
    assert result.results[0]["candidate"]["status"] == "cancelled"
    campaigns.run_campaign_job(created["job_id"])
    assert len(calls) == 2
    http = client(db_session, db_session.get(Workspace, workspace_id), db_session.get(User, user_id), monkeypatch)
    retry = http.post('/evaluation/campaigns', json={**body, "request_key": "explicit-retry"})
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] != created["id"]
    assert retry.json()["results"][0]["baseline"]["run_id"] != created["results"][0]["baseline"]["run_id"]


def test_generation_rechecks_source_policy_and_embedding_allowlist(db_session, monkeypatch):
    from types import SimpleNamespace
    from app.models.policy import ControlPolicy
    workspace, user, system, _ = _seed(db_session)
    collection = KnowledgeCollection(id="policy-doc", workspace_id=workspace.id, slug="policy-doc", name="Policy",
        vector_collection_name="policy-doc", artifact_prefix="policy/", status="ready")
    db_session.add(collection)
    db_session.commit()
    http = client(db_session, workspace, user, monkeypatch)
    monkeypatch.setattr("app.services.model_plane.execution.resolve_model_execution", lambda *args, **kwargs: SimpleNamespace(provider="openai", model="gpt-4o-mini", _api_key="private"))
    created = http.post('/evaluation/generations', json={"system_id":system.id,"collection_ids":[collection.id],"request_key":"policy-one"})
    assert created.status_code == 201, created.text
    inputs = created.json()["input_ref"]
    assert inputs["model_execution"]["model"] == "gpt-4o-mini"
    assert inputs["embedding_selection_basis"] == "platform_configuration_at_enqueue"
    policy = ControlPolicy(workspace_id=workspace.id, scope="system", target_id=system.id,
        extra={"membrane_spec":{"version":2,"enforcement_mode":"enforce","capabilities":{"allowed_models":["gpt-4o-mini"]}}})
    db_session.add(policy)
    db_session.commit()
    denied = http.get(f"/evaluation/generations/{created.json()['id']}")
    assert denied.status_code == 403
    assert "embedding" in denied.text
    policy.extra = {"membrane_spec":{"version":2,"enforcement_mode":"enforce","inbound":{"collection_allowlist":["another-corpus"]}}}
    db_session.commit()
    denied = http.get(f"/evaluation/generations/{created.json()['id']}")
    assert denied.status_code == 403
    assert "corpus" in denied.text


def test_raget_repeated_request_returns_same_job(db_session, monkeypatch):
    from types import SimpleNamespace
    from app.models.evaluation_campaign import EvaluationSuite
    from app.models.workspace_job import WorkspaceJob
    http, body, _, workspace, _, _ = setup_campaign(db_session, monkeypatch)
    collection = KnowledgeCollection(id="raget-doc", workspace_id=workspace.id, slug="raget-doc", name="RAGET",
        vector_collection_name="raget-doc", artifact_prefix="raget/", status="ready")
    db_session.add(collection)
    db_session.flush()
    suite = db_session.get(EvaluationSuite, body["suite_id"])
    suite.corpus_manifest = campaigns.corpus_manifest(db_session, workspace.id, [collection.id])
    suite.cases = [{**suite.cases[0], "question":"Pressure?", "reference_answer":"6 bar", "answer_path":["answer"]}]
    db_session.commit()
    created = http.post('/evaluation/campaigns', json=body).json()
    for side in ("baseline", "candidate"):
        run = db_session.get(Run, created["results"][0][side]["run_id"])
        run.status, run.output_ref = "completed", {"answer":"6 bar"}
    db_session.commit()
    monkeypatch.setattr("app.services.model_plane.execution.resolve_model_execution", lambda *args, **kwargs: SimpleNamespace(provider="openai", model="gpt-4o-mini", _api_key="private"))
    first = http.post(f"/evaluation/campaigns/{created['id']}/raget",json={"request_key":"raget-one"})
    assert first.status_code == 201, first.text
    second = http.post(f"/evaluation/campaigns/{created['id']}/raget",json={"request_key":"raget-one"})
    assert second.json()["id"] == first.json()["id"]
    assert db_session.query(WorkspaceJob).filter_by(kind="evaluation_raget").count() == 1


def test_changed_model_refused_before_loading_corpus(db_session, monkeypatch):
    from types import SimpleNamespace
    from app.models.workspace_job import WorkspaceJob
    workspace, user, system, _ = _seed(db_session)
    collection = KnowledgeCollection(id="model-doc",workspace_id=workspace.id,slug="model-doc",name="Model",
        vector_collection_name="model-doc",artifact_prefix="model/",status="ready")
    db_session.add(collection)
    db_session.commit()
    http = client(db_session, workspace, user, monkeypatch)
    monkeypatch.setattr("app.services.model_plane.execution.resolve_model_execution", lambda *args, **kwargs: SimpleNamespace(provider="openai", model="gpt-4o-mini", _api_key="private"))
    created = http.post('/evaluation/generations',json={"system_id":system.id,"collection_ids":[collection.id],"request_key":"model-one"}).json()
    monkeypatch.setattr("app.services.model_plane.execution.resolve_model_execution", lambda *args, **kwargs: SimpleNamespace(provider="openai", model="another-model", _api_key="private"))
    monkeypatch.setattr("app.db.base.SessionLocal", lambda: db_session)
    def forbid(*args, **kwargs):
        pytest.fail("A changed model must be rejected before corpus loading")
    monkeypatch.setattr("app.services.vector_db.factory.VectorDBFactory.get_db",forbid)
    assert campaigns.run_generation_job(created["id"])["status"] == "failed"
    job = db_session.get(WorkspaceJob, created["id"])
    assert "Model routing changed" in job.error


def test_comparison_preserves_human_wait_and_reuses_run_after_review(db_session, monkeypatch):
    campaigns.assert_read_only({"nodes": [{"id": "review", "kind": "hitl"}]}, {"nodes": {}})
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        campaigns.assert_read_only({"nodes": [{"id": "review", "kind": "hitl", "config": {"effect": "write"}}]}, {"nodes": {}})
    http, body, *_ = setup_campaign(db_session, monkeypatch, assertions=[
        {"id": "fact", "path": ["pressure"], "operator": "equals", "value": 6}])
    created = http.post("/evaluation/campaigns", json=body)
    assert created.status_code == 201, created.text
    campaign = created.json()
    result = campaign["results"][0]
    for side in ("baseline", "candidate"):
        run = db_session.get(Run, result[side]["run_id"])
        run.status = "hitl_pending"
        run.checkpoints = [{"kind": "hitl_pause", "decision_id": "decision-" + side}]
    db_session.commit()
    refreshed = http.get(f"/evaluation/campaigns/{campaign['id']}").json()
    assert refreshed["status"] == "running"
    for side in ("baseline", "candidate"):
        assert refreshed["results"][0][side]["verdict"] == "pending"
        assert refreshed["results"][0][side]["awaiting_decision_id"] == "decision-" + side
        run = db_session.get(Run, result[side]["run_id"])
        assert run.status == "hitl_pending"  # Reading the campaign never decides.
        run.status, run.output_ref = "completed", {"pressure": 6}
    db_session.commit()
    final = http.get(f"/evaluation/campaigns/{campaign['id']}").json()
    assert final["status"] == "completed"
    assert final["results"][0]["change"] == "unchanged"
    for side in ("baseline", "candidate"):
        assert final["results"][0][side]["run_id"] == result[side]["run_id"]
        assert final["results"][0][side]["awaiting_decision_id"] is None


@pytest.mark.parametrize("answer, expected, examined", [
    ('Fact: "Current grade: P3."', "passed", 1),
    ('Fact: “Current grade: P3.” and « Current grade: P3. »', "passed", 2),
    ('Missing: "Current grade evidence: MISSING EVIDENCE"', "failed", 1),
    ('"Current grade: P3." and "MISSING EVIDENCE"', "failed", 2),
    ('No quotes supplied', "failed", 0),
    (None, "failed", 0),
])
def test_quote_provenance_rejects_intermediate_annotations(answer, expected, examined):
    from app.api.v1.endpoints.evaluation_campaigns import AssertionBody
    assertion = AssertionBody(id="source", path=["completion"], operator="quotes_in_source",
                              value="Current grade: P3.")
    result = campaigns.assertion_results({"completion": answer}, [assertion.model_dump()])
    assert result["verdict"] == expected
    assert result["assertions"][0]["quotes_examined"] == examined
