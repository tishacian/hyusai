"""The BRD import endpoint: who may read a document, and what reading yields.

The endpoint parses and returns. It is behind the authoring boundary because
its only use is drafting a Skill, and retention is opt-in. It creates no executable objects.
"""
from __future__ import annotations

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.models.skill import Skill
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

docx = pytest.importorskip("docx")


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(skills.router, prefix="/skills")
    app.dependency_overrides[skills.get_current_workspace] = lambda: workspace
    app.dependency_overrides[skills.get_current_user] = lambda: user
    app.dependency_overrides[skills.get_db] = lambda: db
    return TestClient(app)


def _seed(db, *, role_template: str = "workspace_admin"):
    workspace = Workspace(id="ws-brd", slug="brd", name="Brd", settings={})
    user = User(id="brd-user", username="brd-user")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template=role_template,
    )
    db.add_all([workspace, user, member])
    db.commit()
    return workspace, user


def _brd() -> bytes:
    document = docx.Document()
    table = document.add_table(rows=2, cols=4)
    for column, text in enumerate(["ID", "Requirement", "Priority (M/S/C/W)", "Maps to capability"]):
        table.cell(0, column).text = text
    for column, text in enumerate(["FR-1", "Draft a reply", "M", "Ticket triage"]):
        table.cell(1, column).text = text
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _upload(client, data: bytes, name: str = "brd.docx"):
    return client.post(
        "/skills/import/business-requirements",
        files={"file": (name, data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )


def test_an_admin_reads_the_requirements_and_nothing_is_created(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = _upload(client, _brd())

    assert response.status_code == 200
    body = response.json()
    assert body["requirements"] == [
        {
            "id": "FR-1",
            "requirement": "Draft a reply",
            "priority": "M",
            "capability": "Ticket triage",
        }
    ]
    assert db_session.query(Skill).count() == 0


def test_a_member_who_cannot_author_cannot_read_either(db_session):
    workspace, user = _seed(db_session, role_template="workspace_viewer")
    client = _client(db_session, workspace, user)

    assert _upload(client, _brd()).status_code == 403


def test_a_file_that_is_not_a_document_is_refused_with_a_reason(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = _upload(client, b"not a docx at all", name="notes.txt")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "brd_document_unreadable"


def test_an_oversized_upload_is_refused_before_it_is_parsed(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = _upload(client, b"0" * (5 * 1024 * 1024 + 1))

    assert response.status_code == 413


def test_retained_original_round_trip_replay_and_workspace_boundary(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.brd_document import BrdDocument
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    data = _brd()
    def upload():
        return client.post("/skills/import/business-requirements?retain=true",
                           files={"file": ("../requirements.docx", data)})
    first = upload()
    assert first.status_code == 200
    document = first.json()["document"]
    assert document["filename"] == "requirements.docx"
    document_id = document["id"]
    assert upload().json()["document"]["id"] == document_id
    assert db_session.query(BrdDocument).count() == 1
    assert db_session.query(Skill).count() == 0
    path = f"/skills/imports/business-requirements/{document_id}"
    assert client.get(path).json()["requirements"] == first.json()["requirements"]
    assert client.get(path + "/original").content == data

    other = Workspace(id="other-brd", slug="other-brd", name="Other", settings={})
    db_session.add(other)
    db_session.add(WorkspaceMember(workspace_id=other.id, user_id=user.id,
                                   role="member", role_template="workspace_admin"))
    db_session.commit()
    other_client = _client(db_session, other, user)
    assert other_client.get(path).status_code == 404
    assert other_client.get(path + "/original").status_code == 404

    member = db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).one()
    member.role_template = "workspace_viewer"
    db_session.commit()
    assert client.get(path).status_code == 403
    assert client.get(path + "/original").status_code == 403
    assert upload().status_code == 403


def test_retained_original_missing_or_modified_is_not_presented_as_evidence(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.brd_document import BrdDocument
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    response = client.post("/skills/import/business-requirements?retain=true",
                           files={"file": ("requirements.docx", _brd())})
    assert response.status_code == 200
    row = db_session.query(BrdDocument).one()
    path = f"/skills/imports/business-requirements/{row.id}/original"
    original = tmp_path / row.storage_key
    original.write_bytes(b"changed")
    assert client.get(path).json()["detail"]["code"] == "brd_original_integrity_error"
    original.unlink()
    assert client.get(path).status_code == 410


def test_proposal_preserves_uncovered_requirements_and_never_creates_system(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.system import System
    from app.models.brd_proposal import BrdProposal
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    document_id = client.post("/skills/import/business-requirements?retain=true",
                             files={"file": ("brd.docx", _brd())}).json()["document"]["id"]
    path = f"/skills/imports/business-requirements/{document_id}/proposals"
    body = {
        "request_key": "first-proposal", "name": "Ticket draft",
        "flow_definition": {"schema_version": 3, "nodes": [
            {"id": "input", "type": "source", "kind": "source"},
            {"id": "result", "type": "sink", "kind": "sink"},
        ], "edges": [{"from": "input", "to": "result", "kind": "data"}]},
    }
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["proposal"]["coverage"][0]["status"] == "uncovered"
    assert first["proposal"]["coverage"][0]["test_verdict"] == "not_run"
    assert first["proposal"]["execution_readiness"] == "not_validated"
    assert client.post(path, json=body).json()["id"] == first["id"]
    assert client.get(path + "/" + first["id"]).json() == first
    assert db_session.query(BrdProposal).count() == 1
    assert db_session.query(System).count() == 0
    assert db_session.query(Skill).count() == 0
    assert client.post(path, json={**body, "name": "Changed"}).status_code == 409

    mapped = {**body, "request_key": "second-proposal", "mappings": [
        {"table": 1, "row": 2, "node_ids": ["result"], "case_ids": ["t1"]}],
        "cases": [{"id": "t1", "input_ref": {}, "assertions": []}]}
    second = client.post(path, json=mapped)
    assert second.status_code == 200, second.text
    assert second.json()["proposal"]["coverage"][0]["status"] == "proposed"
    assert second.json()["proposal"]["coverage"][0]["test_verdict"] == "not_run"
    mapped["mappings"][0]["node_ids"] = ["invented"]
    assert client.post(path, json=mapped).status_code == 422
    mapped["mappings"][0]["node_ids"] = ["result"]
    mapped["mappings"][0]["row"] = 99
    assert client.post(path, json=mapped).status_code == 422


    # Reject the actual provider failure before retaining any proposal: the
    # evaluator reads Run.output_ref, not a node/trace envelope.
    from copy import deepcopy
    invalid = deepcopy(body)
    invalid["request_key"] = "invalid-output-path"
    invalid["flow_definition"]["nodes"][1]["config"] = {
        "output_schema": {"type": "object", "properties": {"completion": {"type": "string"}}}}
    invalid["cases"] = [{"id": "normal", "input_ref": {}, "assertions": [{
        "id": "title", "path": ["nodes", "result", "completion"],
        "operator": "contains", "value": "Senior Data Analyst"}]}]
    count = db_session.query(BrdProposal).count()
    rejected = client.post(path, json=invalid)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["code"] == "brd_case_output_path_invalid"
    assert db_session.query(BrdProposal).count() == count
    invalid["cases"][0]["assertions"][0]["path"] = ["completion"]
    assert client.post(path, json=invalid).status_code == 200


def test_reviewed_proposal_applies_once_to_draft_only(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.system import System
    from app.models.system_flow_draft import SystemFlowDraft
    from app.models.system_version import SystemVersion
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    workspace.settings = {"features": {"flow_workbench_v1": True}}
    db_session.commit()
    client = _client(db_session, workspace, user)
    document_id = client.post("/skills/import/business-requirements?retain=true",
                             files={"file": ("brd.docx", _brd())}).json()["document"]["id"]
    path = f"/skills/imports/business-requirements/{document_id}/proposals"
    flow = {"schema_version": 3, "nodes": [
        {"id": "input", "type": "source", "kind": "source"},
        {"id": "result", "type": "sink", "kind": "sink"},
    ], "edges": [{"from": "input", "to": "result", "kind": "data"}]}
    proposal = client.post(path, json={"request_key": "apply-test", "name": "Draft only",
                                      "flow_definition": flow, "cases": [{"id": "case-1", "input_ref": {}, "assertions": []}]}).json()
    apply_path = path + "/" + proposal["id"] + "/apply"
    assert client.post(apply_path, json={"expected_sha256": proposal["sha256"], "reviewed": False}).status_code == 422
    assert client.post(apply_path, json={"expected_sha256": "0" * 64, "reviewed": True}).status_code == 409
    body = {"expected_sha256": proposal["sha256"], "reviewed": True}
    applied = client.post(apply_path, json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert client.post(apply_path, json=body).json() == applied.json()
    system = db_session.query(System).one()
    assert system.status == "draft"
    assert not system.flow_definition.get("nodes")
    draft = db_session.query(SystemFlowDraft).one()
    assert len(draft.flow_definition["nodes"]) == 2
    assert draft.revision == 2
    published = db_session.get(SystemVersion, system.published_flow_version_id)
    assert not published.flow_definition.get("nodes")
    assert system.settings["brd_provenance"]["proposal_sha256"] == proposal["sha256"]
    from app.models.evaluation_campaign import EvaluationSuite
    suite = db_session.query(EvaluationSuite).one()
    assert suite.system_id == system.id
    assert suite.cases[0]["id"] == "case-1"
    assert suite.provenance["brd_proposal_sha256"] == proposal["sha256"]
    assert system.settings["brd_provenance"]["suite_id"] == suite.id

    # Draft tests and publication carry server-owned origins, never a mutable
    # System setting. Later edits cannot relabel an earlier execution.
    from app.services.systems import flow_publication
    from app.services.flow_contracts import validate_execution_contract, FlowContractError, canonical_sha256
    from copy import deepcopy
    run = flow_publication.create_draft_test_run(db_session, system_id=system.id,
        workspace=workspace, user_id=user.id, input_ref={},
        expected_draft_revision=draft.revision, expected_flow_sha256=draft.flow_sha256)
    version, _, _ = flow_publication.publish_draft(db_session, system_id=system.id,
        workspace=workspace, expected_draft_revision=draft.revision,
        expected_published_version_id=system.published_flow_version_id,
        message="Reviewed BRD draft", breaking_change_intent=None, actor=user.id)
    expected_origin = {"document_id": document_id,
        "document_sha256": proposal["proposal"]["document_sha256"],
        "proposal_id": proposal["id"], "proposal_sha256": proposal["sha256"]}
    assert run.execution_contract["brd_origin"] == expected_origin
    assert validate_execution_contract(version.execution_contract)["brd_origin"] == expected_origin
    system.settings = {"brd_provenance": {"document_id": "forged"}}
    db_session.flush()
    assert flow_publication.compile_execution_contract(db_session, flow, workspace,
        system=system)["brd_origin"] == expected_origin
    assert run.execution_contract["brd_origin"] == expected_origin
    from app.services.systems import flow_ingress
    system.status = "active"
    db_session.flush()
    published_run = flow_ingress.create_published_ingress_run(db_session,
        system_id=system.id, workspace=workspace, ingress_id="input", kind="manual",
        payload={}, initiated_by_user_id=user.id)
    assert published_run.execution_contract["brd_origin"] == expected_origin
    assert published_run.published_flow_version_id == version.id
    tampered = deepcopy(version.execution_contract)
    tampered["brd_origin"]["document_id"] = "forged"
    tampered.pop("contract_sha256")
    tampered["contract_sha256"] = canonical_sha256(tampered)
    with pytest.raises(FlowContractError):
        validate_execution_contract(tampered)

    # Failure after an authored Skill has been inserted must roll it back.
    bad_flow = {"schema_version": 3, "nodes": [
        {"id": "input", "type": "source", "kind": "source"},
        {"id": "task", "type": "skill", "kind": "task", "config": {"skill_slug": "@missing"}},
        {"id": "result", "type": "sink", "kind": "sink"},
    ], "edges": [{"from": "input", "to": "task", "kind": "data"},
                 {"from": "task", "to": "result", "kind": "data"}]}
    bad_response = client.post(path, json={"request_key": "rollback-test", "name": "Invalid binding",
        "flow_definition": bad_flow, "skills": [{"local_name": "summary", "name": "Summary",
        "executor": {"kind": "prompt_template", "params": {"provider": "workspace", "template": "Summarize {text}"}}}]})
    assert bad_response.status_code == 200, bad_response.text
    bad = bad_response.json()
    failed = client.post(path + "/" + bad["id"] + "/apply", json={"expected_sha256": bad["sha256"], "reviewed": True})
    assert failed.status_code == 422, failed.text
    assert db_session.query(Skill).count() == 0
    assert db_session.query(System).count() == 1
    from app.models.brd_proposal import BrdProposal
    assert db_session.get(BrdProposal, bad["id"]).status == "proposed"

    # A resolvable authored executor is cloned for this proposal and frozen by
    # the canonical compiler, without changing the earlier System's draft.
    bad_flow["nodes"][1]["config"]["skill_slug"] = "@summary"
    good_response = client.post(path, json={"request_key": "authored-test", "name": "Authored summary",
        "flow_definition": bad_flow, "skills": [{"local_name": "summary", "name": "Summary",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        "output_schema": {"type": "object", "properties": {"completion": {"type": "string"}}},
        "executor": {"kind": "prompt_template", "params": {"provider": "workspace", "template": "Summarize {text}"}}}]})
    assert good_response.status_code == 200, good_response.text
    good = good_response.json()
    successful = client.post(path + "/" + good["id"] + "/apply", json={"expected_sha256": good["sha256"], "reviewed": True})
    assert successful.status_code == 200, successful.text
    assert db_session.query(System).count() == 2
    authored = db_session.query(Skill).one()
    new_draft = db_session.query(SystemFlowDraft).filter_by(system_id=successful.json()["system_id"]).one()
    assert new_draft.flow_definition["nodes"][1]["config"]["skill_slug"] == authored.slug
    assert db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one().revision == 2


def test_proposal_apply_binds_default_agent_loop_planner(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.system import System
    from app.models.system_flow_draft import SystemFlowDraft
    from app.services.systems import flow_publication

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    planner = Skill(slug="decide_next_v1", name="Planner")
    tool = Skill(slug="semantic_search_v1", name="Search")
    workspace.settings = {"features": {"flow_workbench_v1": True},
                          "catalog": {"enabled_skills": [planner.slug, tool.slug]}}
    db_session.add_all([planner, tool])
    db_session.commit()
    client = _client(db_session, workspace, user)
    imported = client.post("/skills/import/business-requirements?retain=true",
                           files={"file": ("brd.docx", _brd())})
    assert imported.status_code == 200, imported.text
    document_id = imported.json()["document"]["id"]
    path = f"/skills/imports/business-requirements/{document_id}/proposals"
    flow = {"schema_version": 3, "nodes": [
        {"id": "input", "kind": "source"},
        {"id": "investigate", "kind": "agent_loop", "config": {
            "max_turns": 2, "skill_allowlist": [tool.slug], "privilege_tier": "recommend"}},
        {"id": "result", "kind": "sink"},
    ], "edges": [{"from": "input", "to": "investigate", "kind": "data"},
                 {"from": "investigate", "to": "result", "kind": "data"}]}
    proposed = client.post(path, json={"request_key": "implicit-planner", "name": "Investigation",
        "flow_definition": flow, "cases": [{"id": "case-1", "input_ref": {}, "assertions": []}],
        "mappings": [{"table": 1, "row": 2, "node_ids": ["investigate"], "case_ids": ["case-1"]}]})
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()

    applied = client.post(path + "/" + proposal["id"] + "/apply",
                          json={"expected_sha256": proposal["sha256"], "reviewed": True})

    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    system = db_session.get(System, applied.json()["system_id"])
    assert set(system.skill_ids) == {planner.id, tool.id}
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    assert draft.flow_definition == flow
    assert applied.json()["proposal"] == proposal["proposal"]
    assert system.settings["brd_provenance"]["coverage"] == proposal["proposal"]["coverage"]
    assert system.settings["brd_provenance"]["proposal_sha256"] == proposal["sha256"]
    contract = flow_publication.compile_execution_contract(db_session, flow, workspace, system=system)
    assert contract["nodes"]["investigate"]["skill_slug"] == planner.slug
    assert set(contract["nodes"]["investigate"]["tool_contract"]["nodes"]) == {tool.slug}


def _pinned_corpus_proposal(db, tmp_path, monkeypatch, *, retrieval=True):
    from app.core.config import settings
    from app.models.knowledge_collection import KnowledgeCollection

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db)
    planner = Skill(slug="decide_next_v1", name="Planner")
    workspace.settings = {"features": {"flow_workbench_v1": True, "flow_v3_dag_authoritative": True},
                          "catalog": {"enabled_skills": [planner.slug]}}
    collections = [KnowledgeCollection(id="collection-" + name, workspace_id=workspace.id, slug=name, name=name,
        vector_collection_name=name, artifact_prefix=name + "/", status="ready",
        document_names=[name + ".pdf"], document_count=1, chunk_count=3,
        embedding_model="test-embedding") for name in ("notices", "history", "unreferenced")]
    db.add_all([planner, *collections])
    db.commit()
    client = _client(db, workspace, user)
    imported = client.post("/skills/import/business-requirements?retain=true",
                           files={"file": ("brd.docx", _brd())})
    assert imported.status_code == 200, imported.text
    path = f"/skills/imports/business-requirements/{imported.json()['document']['id']}/proposals"
    flow = {"schema_version": 3, "io_mode": "strict", "nodes": [
        {"id": "input", "kind": "source"},
        {"id": "investigate", "kind": "agent_loop", "config": {"max_turns": 2,
            "skill_allowlist": ["@notices", "@history"], "privilege_tier": "recommend"}},
        {"id": "result", "kind": "sink"},
    ], "edges": [{"from": "input", "to": "investigate", "kind": "data"},
                 {"from": "investigate", "to": "result", "kind": "data"}]}
    if not retrieval:
        flow["nodes"] = [flow["nodes"][0], flow["nodes"][2]]
        flow["edges"] = [{"from": "input", "to": "result", "kind": "data"}]
    specs = [{"local_name": collection.slug, "name": collection.name,
        "executor": {"kind": "registry_call", "params": {"skill_slug": "semantic_search_v1",
            "frozen_input": {"context_collection": collection.slug}}}} for collection in collections]
    proposed = client.post(path, json={"request_key": "pinned-corpus", "name": "Corpus investigation",
        "flow_definition": flow, "skills": specs,
        "cases": [{"id": "case-1", "input_ref": {}, "assertions": []}]})
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    return client, workspace, user, collections, proposal, path + "/" + proposal["id"] + "/apply"


@pytest.mark.parametrize("drift", ["ledger", "candidate_binding", "baseline_binding"])
def test_brd_suite_freezes_only_compiled_tool_corpus_and_refuses_drift(db_session, tmp_path, monkeypatch, drift):
    from copy import deepcopy
    from app.api.v1.endpoints import flow_workbench, evaluation_campaigns
    from app.models.evaluation_campaign import EvaluationCampaign, EvaluationSuite
    from app.models.run import Run
    from app.models.run_dispatch_outbox import RunDispatchOutbox
    from app.models.system_flow_draft import SystemFlowDraft
    from app.services.evaluation.campaigns import corpus_manifest

    client, workspace, user, collections, proposal, path = _pinned_corpus_proposal(db_session, tmp_path, monkeypatch)
    apply_body = {"expected_sha256": proposal["sha256"], "reviewed": True}
    applied = client.post(path, json=apply_body)
    assert applied.status_code == 200, applied.text
    system_id = applied.json()["system_id"]
    suite = db_session.query(EvaluationSuite).one()
    expected_manifest = corpus_manifest(db_session, workspace.id, [collection.id for collection in collections[:2]])
    assert suite.corpus_manifest == expected_manifest
    assert len(suite.corpus_manifest) == 2  # The unused authored Skill adds no corpus.
    assert suite.provenance["corpus_snapshot"] == "compiled_v1"
    assert suite.provenance["brd_proposal_sha256"] == proposal["sha256"]
    frozen_cases, frozen_manifest = deepcopy(suite.cases), deepcopy(suite.corpus_manifest)

    client.app.include_router(flow_workbench.router, prefix="/systems")
    client.app.include_router(evaluation_campaigns.router, prefix="/evaluation")
    monkeypatch.setattr(flow_workbench, "reconcile_dispatch_outbox", lambda: None)
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system_id).one()
    golden_body = {"acknowledge_real_side_effects": True, "flow_definition": draft.flow_definition,
        "expected_flow_sha256": draft.flow_sha256, "suite_id": suite.id, "request_key": "before-drift"}
    golden_path = f"/systems/{system_id}/flow-workbench/golden-runs"
    first = client.post(golden_path, json=golden_body)
    assert first.status_code == 201, first.text
    run = db_session.get(Run, first.json()["runs"][0]["id"])
    run.status = "completed"
    original_contract = deepcopy(run.execution_contract)
    if drift == "ledger":
        collections[1].document_names = ["changed-history.pdf"]
    else:
        history_tool = db_session.query(Skill).filter_by(workspace_id=workspace.id, name="history").one()
        original_executor = deepcopy(history_tool.executor)
        history_tool.executor = {"kind": "registry_call", "params": {"skill_slug": "semantic_search_v1",
            "frozen_input": {"context_collection": collections[2].slug}}}
        db_session.flush()
        if drift == "baseline_binding":
            # Model an earlier baseline whose frozen binding differs from the
            # candidate's current catalog, without executing either comparison.
            from app.models.system import System
            from app.services.systems.flow_publication import compile_execution_contract
            run.execution_contract = compile_execution_contract(db_session, draft.flow_definition,
                workspace, system=db_session.get(System, system_id))
            original_contract = deepcopy(run.execution_contract)
            history_tool.executor = original_executor
    db_session.commit()

    if drift != "ledger":
        assert corpus_manifest(db_session, workspace.id,
            [item["id"] for item in frozen_manifest]) == frozen_manifest
    if drift != "baseline_binding":
        rejected = client.post(golden_path, json={**golden_body, "request_key": "after-drift"})
        assert rejected.status_code == 409, rejected.text
        assert "corpus changed" in rejected.json()["detail"].lower()
    comparison = client.post("/evaluation/campaigns", json={"suite_id": suite.id,
        "baseline_run_id": run.id, "expected_draft_revision": draft.revision, "request_key": "drift-comparison"})
    assert comparison.status_code == 409, comparison.text
    assert "corpus changed" in comparison.json()["detail"].lower()
    assert db_session.query(Run).count() == 1
    assert db_session.query(RunDispatchOutbox).count() == 1
    assert db_session.query(EvaluationCampaign).count() == 0
    # Replaying an applied proposal never backfills or rewrites historical evidence.
    assert client.post(path, json=apply_body).json() == applied.json()
    db_session.refresh(suite)
    db_session.refresh(run)
    assert suite.cases == frozen_cases and suite.corpus_manifest == frozen_manifest
    assert run.execution_contract == original_contract
    assert db_session.query(EvaluationSuite).count() == 1


def test_legacy_brd_suite_keeps_missing_manifest_explicit_without_qualifying_agentloop_comparison(db_session, tmp_path, monkeypatch):
    from app.api.v1.endpoints import flow_workbench, evaluation_campaigns
    from app.models.evaluation_campaign import EvaluationCampaign, EvaluationSuite
    from app.models.run import Run
    from app.models.system_flow_draft import SystemFlowDraft
    from app.services.evaluation.campaigns import suite_run_result

    client, workspace, user, _, proposal, path = _pinned_corpus_proposal(db_session, tmp_path, monkeypatch)
    applied = client.post(path, json={"expected_sha256": proposal["sha256"], "reviewed": True})
    assert applied.status_code == 200, applied.text
    suite = db_session.query(EvaluationSuite).one()
    suite.corpus_manifest = []  # Simulate a suite retained before corpus capture.
    suite.provenance = {key: value for key, value in suite.provenance.items() if key != "corpus_snapshot"}
    db_session.commit()
    client.app.include_router(flow_workbench.router, prefix="/systems")
    client.app.include_router(evaluation_campaigns.router, prefix="/evaluation")
    monkeypatch.setattr(flow_workbench, "reconcile_dispatch_outbox", lambda: None)
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=suite.system_id).one()
    response = client.post(f"/systems/{suite.system_id}/flow-workbench/golden-runs", json={
        "acknowledge_real_side_effects": True, "flow_definition": draft.flow_definition,
        "expected_flow_sha256": draft.flow_sha256, "suite_id": suite.id, "request_key": "legacy-corpus"})
    assert response.status_code == 201, response.text
    run = db_session.get(Run, response.json()["runs"][0]["id"])
    assert "unverified" in suite_run_result(run)["corpus_limitations"][0]
    assert suite.corpus_manifest == []
    run.status = "completed"
    db_session.commit()
    comparison = client.post("/evaluation/campaigns", json={"suite_id": suite.id,
        "baseline_run_id": run.id, "expected_draft_revision": draft.revision, "request_key": "unsupported-agentloop"})
    assert comparison.status_code == 422, comparison.text
    assert "qualified read-only nodes" in comparison.json()["detail"]
    assert db_session.query(EvaluationCampaign).count() == 0
    assert db_session.query(Run).count() == 1


def test_new_brd_empty_corpus_snapshot_refuses_added_retrieval_pins(db_session, tmp_path, monkeypatch):
    from copy import deepcopy
    from app.api.v1.endpoints import flow_workbench, evaluation_campaigns
    from app.models.evaluation_campaign import EvaluationCampaign, EvaluationSuite
    from app.models.run import Run
    from app.models.system import System
    from app.models.system_flow_draft import SystemFlowDraft
    from app.services.systems.flow_publication import save_draft

    client, workspace, user, _, proposal, path = _pinned_corpus_proposal(db_session, tmp_path, monkeypatch, retrieval=False)
    applied = client.post(path, json={"expected_sha256": proposal["sha256"], "reviewed": True})
    assert applied.status_code == 200, applied.text
    suite = db_session.query(EvaluationSuite).one()
    assert suite.corpus_manifest == []
    assert suite.provenance["corpus_snapshot"] == "compiled_v1"
    system = db_session.get(System, suite.system_id)
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    client.app.include_router(flow_workbench.router, prefix="/systems")
    client.app.include_router(evaluation_campaigns.router, prefix="/evaluation")
    monkeypatch.setattr(flow_workbench, "reconcile_dispatch_outbox", lambda: None)
    golden_path = f"/systems/{system.id}/flow-workbench/golden-runs"
    before = client.post(golden_path, json={"acknowledge_real_side_effects": True,
        "flow_definition": draft.flow_definition, "expected_flow_sha256": draft.flow_sha256,
        "suite_id": suite.id, "request_key": "text-only"})
    assert before.status_code == 201, before.text
    baseline = db_session.get(Run, before.json()["runs"][0]["id"])
    baseline.status = "completed"
    tool = db_session.query(Skill).filter_by(workspace_id=workspace.id, name="history").one()
    system.skill_ids = [tool.id]
    changed_flow = deepcopy(draft.flow_definition)
    changed_flow["nodes"].insert(1, {"id": "search", "kind": "task", "config": {"skill_slug": tool.slug}})
    changed_flow["edges"] = [{"from": "input", "to": "search", "kind": "data"},
                             {"from": "search", "to": "result", "kind": "data"}]
    db_session.flush()
    save_draft(db_session, system_id=system.id, workspace=workspace, flow_definition=changed_flow,
        expected_revision=draft.revision, actor=user.id)
    db_session.commit()
    db_session.refresh(draft)
    response = client.post(golden_path, json={"acknowledge_real_side_effects": True,
        "flow_definition": draft.flow_definition, "expected_flow_sha256": draft.flow_sha256,
        "suite_id": suite.id, "request_key": "new-pins"})
    assert response.status_code == 409, response.text
    assert "BRD execution corpus changed" in response.json()["detail"]
    comparison = client.post("/evaluation/campaigns", json={"suite_id": suite.id,
        "baseline_run_id": baseline.id, "expected_draft_revision": draft.revision, "request_key": "new-pins-comparison"})
    assert comparison.status_code == 409, comparison.text
    assert "BRD execution corpus changed" in comparison.json()["detail"]
    assert db_session.query(EvaluationCampaign).count() == 0
    assert db_session.query(Run).count() == 1
    assert suite.corpus_manifest == []


@pytest.mark.parametrize("unavailable", ["outside_workspace", "absent", "not_ready"])
def test_brd_pinned_corpus_must_be_ready_in_the_workspace(db_session, tmp_path, monkeypatch, unavailable):
    from app.models.brd_proposal import BrdProposal
    from app.models.evaluation_campaign import EvaluationSuite
    from app.models.system import System

    client, workspace, user, collections, proposal, path = _pinned_corpus_proposal(db_session, tmp_path, monkeypatch)
    history = collections[1]
    if unavailable == "outside_workspace":
        other = Workspace(id="foreign-corpus", slug="foreign-corpus", name="Other")
        db_session.add(other)
        history.workspace_id = other.id
    elif unavailable == "absent":
        db_session.delete(history)
    else:
        history.status = "queued"
    db_session.commit()
    response = client.post(path, json={"expected_sha256": proposal["sha256"], "reviewed": True})
    assert response.status_code == (409 if unavailable == "not_ready" else 404), response.text
    assert db_session.query(EvaluationSuite).count() == 0
    assert db_session.query(System).count() == 0
    assert db_session.query(Skill).filter_by(workspace_id=workspace.id).count() == 0
    assert db_session.get(BrdProposal, proposal["id"]).status == "proposed"


def test_brd_generation_is_durable_idempotent_and_validated(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.db import base
    from app.models.workspace_job import WorkspaceJob
    from app.models.brd_proposal import BrdProposal
    from app.services import workspace_jobs
    from app.services.skills_registry import brd_generation
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    monkeypatch.setattr(workspace_jobs, "dispatch_workspace_job", lambda *a, **k: "task")
    from contextlib import nullcontext
    monkeypatch.setattr(base, "SessionLocal", lambda: nullcontext(db_session))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    document_id = client.post("/skills/import/business-requirements?retain=true",
                             files={"file": ("brd.docx", _brd())}).json()["document"]["id"]
    path = f"/skills/imports/business-requirements/{document_id}/generations"
    request = {"request_key": "gen-1", "family": "document_summary", "name": "PIH"}
    response = client.post(path, json=request)
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    assert client.post(path, json=request).json()["id"] == job_id
    assert client.post(path, json={**request, "name": "changed"}).status_code == 409
    calls = []
    async def generate(*args, **kwargs):
        calls.append(True)
        return {"request_key": "model-invented", "name": "PIH", "flow_definition": {
            "schema_version": 3, "nodes": [{"id": "in", "kind": "source", "type": "source"},
            {"id": "out", "kind": "sink", "type": "sink"}],
            "edges": [{"from": "in", "to": "out", "kind": "data"}]}}, {"method": "test_stub"}
    monkeypatch.setattr(brd_generation, "generate_material", generate)
    assert brd_generation.run_generation_job(job_id)["status"] == "completed"
    assert brd_generation.run_generation_job(job_id)["status"] == "completed"
    assert len(calls) == 1
    proposal = db_session.query(BrdProposal).one()
    assert proposal.request_key == job_id
    assert proposal.proposal["generation"]["job_id"] == job_id
    assert db_session.query(WorkspaceJob).one().result["id"] == proposal.id
    assert db_session.query(Skill).count() == 0

    async def invalid(*args, **kwargs):
        material, generation = await generate(*args, **kwargs)
        material["flow_definition"]["nodes"][0]["config"] = {"skill_slug": "foreign_tool"}
        return material, generation
    monkeypatch.setattr(brd_generation, "generate_material", invalid)
    second = client.post(path, json={**request, "request_key": "gen-2"}).json()["id"]
    assert brd_generation.run_generation_job(second)["status"] == "failed"
    db_session.expire_all()
    assert db_session.get(WorkspaceJob, second).result["reason"] == "proposal_validation_failed"
    assert "generation" in db_session.get(WorkspaceJob, second).result
    assert db_session.query(BrdProposal).count() == 1

    assert len(calls) == 4  # one success plus exactly three refused candidates
    assert len(db_session.get(WorkspaceJob, second).result["generation_attempts"]) == 3

    repairs = []
    async def repair(*args, **kwargs):
        repairs.append(kwargs.get("feedback"))
        material, generation = await generate(*args, **kwargs)
        generation["usage"] = {"total_tokens": 10}
        if kwargs.get("feedback") is None:
            material["flow_definition"]["edges"] = []
        else:
            assert kwargs["feedback"]["issues"]["code"] == "brd_proposal_flow_invalid"
            assert kwargs["feedback"]["previous_proposal"]["flow_definition"]["edges"] == []
        return material, generation
    monkeypatch.setattr(brd_generation, "generate_material", repair)
    third = client.post(path, json={**request, "request_key": "gen-3"}).json()["id"]
    assert brd_generation.run_generation_job(third)["status"] == "completed"
    assert len(repairs) == 2
    corrected = db_session.query(BrdProposal).filter_by(request_key=third).one()
    attempts = corrected.proposal["generation"]["attempts"]
    assert [attempt["attempt"] for attempt in attempts] == [1, 2]
    assert sum(attempt["usage"]["total_tokens"] for attempt in attempts) == 20
    assert db_session.query(Skill).count() == 0

    json_attempts = []
    async def repair_json(*args, **kwargs):
        json_attempts.append(kwargs.get("feedback"))
        if len(json_attempts) == 1:
            raise brd_generation.BrdGenerationOutputError("invalid_proposal_json", {"usage": {"total_tokens": 7}})
        assert "valid JSON object" in kwargs["feedback"]["issues"]
        return await generate(*args, **kwargs)
    monkeypatch.setattr(brd_generation, "generate_material", repair_json)
    json_job = client.post(path, json={**request, "request_key": "json-repair"}).json()["id"]
    assert brd_generation.run_generation_job(json_job)["status"] == "completed"
    assert len(json_attempts) == 2
    repaired = db_session.query(BrdProposal).filter_by(request_key=json_job).one()
    assert repaired.proposal["generation"]["attempts"][0]["usage"]["total_tokens"] == 7

    invalid_json_calls = []
    async def invalid_json(*args, **kwargs):
        invalid_json_calls.append(True)
        raise brd_generation.BrdGenerationOutputError("invalid_proposal_json", {"usage": {"total_tokens": 3}})
    monkeypatch.setattr(brd_generation, "generate_material", invalid_json)
    invalid_json_job = client.post(path, json={**request, "request_key": "json-exhausted"}).json()["id"]
    assert brd_generation.run_generation_job(invalid_json_job)["status"] == "failed"
    assert len(invalid_json_calls) == 3
    failed_attempts = db_session.get(WorkspaceJob, invalid_json_job).result["generation_attempts"]
    assert len(failed_attempts) == 3
    assert sum(attempt["usage"]["total_tokens"] for attempt in failed_attempts) == 9

    duplicate_attempts = []
    async def duplicate_templates(*args, **kwargs):
        material, generation = await generate(*args, **kwargs)
        duplicate_attempts.append(kwargs.get("feedback"))
        if kwargs.get("feedback") is None:
            material["skills"] = [{"local_name": name, "name": name,
                "executor": {"kind": "prompt_template", "params": {
                    "provider": "workspace", "template": "Summarize {text}"}}}
                for name in ("extract", "select", "synthesize")]
        else:
            assert "distinct task-specific template" in kwargs["feedback"]["issues"]
        return material, generation
    monkeypatch.setattr(brd_generation, "generate_material", duplicate_templates)
    duplicate_job = client.post(path, json={**request, "request_key": "gen-duplicates"}).json()["id"]
    assert brd_generation.run_generation_job(duplicate_job)["status"] == "completed"
    assert len(duplicate_attempts) == 2

    outages = []
    async def outage(*args, **kwargs):
        outages.append(True)
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(brd_generation, "generate_material", outage)
    fourth = client.post(path, json={**request, "request_key": "gen-4"}).json()["id"]
    assert brd_generation.run_generation_job(fourth)["status"] == "failed"
    assert len(outages) == 1  # uncertain network calls are not retried as corrections

    from app.api.v1.endpoints import workspace_jobs as jobs_api
    client.app.include_router(jobs_api.router, prefix="/workspace-jobs")
    assert client.post("/workspace-jobs/", json={"kind": "brd_generation", "title": "forged"}).status_code == 403
    assert client.post(f"/workspace-jobs/{job_id}/transition", json={"status": "completed", "result": {"forged": True}}).status_code == 403
    assert client.get(f"/workspace-jobs/{job_id}").status_code == 200
    member = db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).one()
    member.role_template = "workspace_viewer"
    db_session.commit()
    assert client.get(f"/workspace-jobs/{job_id}").status_code == 404
    assert client.get(path + "/" + job_id).status_code == 403
