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
