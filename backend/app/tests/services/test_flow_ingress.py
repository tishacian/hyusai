from datetime import datetime

import pytest

from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services import flow_contracts
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_ingress, flow_publication


def _seed_published(db_session):
    workspace = Workspace(
        id="ws-ingress",
        name="Ingress",
        slug="ingress",
        settings={
            "features": {
                "flow_publication_v1": True,
                "flow_v3_dag_authoritative": True,
            }
        },
    )
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual.input",
                "kind": "source",
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {"query": {"type": "string"}},
                        "additionalProperties": False,
                    },
                },
            },
            {"id": "result", "kind": "sink"},
        ],
        "edges": [{"from": "manual.input", "to": "result", "kind": "data"}],
    }
    system = System(
        id="system-ingress",
        workspace_id=workspace.id,
        name="Ingress System",
        objective="test",
        flow_definition=flow,
        status="active",
    )
    db_session.add_all([workspace, system])
    db_session.flush()
    contract = flow_publication.compile_execution_contract(db_session, flow, workspace)
    version = SystemVersion(
        id="version-ingress",
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=contract,
        message="published",
        created_by="test",
    )
    db_session.add(version)
    db_session.flush()
    system.published_flow_version_id = version.id
    system.published_by = "test"
    system.published_at = datetime.utcnow()
    db_session.commit()
    return workspace, system, version, flow


def _seed_sequential_published(db_session):
    workspace, system, version, flow = _seed_published(db_session)
    skill = Skill(
        id="skill-answer-required",
        workspace_id=None,
        slug="eval_radar_v1",
        name="Evaluation Radar",
        input_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        output_schema={"type": "object"},
    )
    db_session.add(skill)
    system.skill_ids = [skill.id]
    flow["io_mode"] = "observe"
    flow["nodes"][0]["config"]["input_schema"] = {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "answer": {"type": "string"},
        },
        "additionalProperties": True,
    }
    digest = canonical_flow_sha256(flow)
    system.flow_definition = flow
    version.flow_definition = flow
    version.flow_sha256 = digest
    version.execution_contract = flow_contracts.compile_execution_contract(
        db_session,
        flow=flow,
        workspace_id=workspace.id,
        runtime_mode="sequential_legacy",
    )
    db_session.commit()
    return workspace, system, version, flow


def test_published_ingress_freezes_version_contract_and_payload(db_session) -> None:
    workspace, system, version, flow = _seed_published(db_session)
    run = flow_ingress.create_published_ingress_run(
        db_session,
        system_id=system.id,
        workspace=workspace,
        ingress_id="manual.input",
        kind="manual",
        payload={"query": "reset password"},
        initiated_by_user_id=None,
        expected_published_version_id=version.id,
        expected_flow_sha256=canonical_flow_sha256(flow),
        adapter_evidence={"surface": "test"},
    )
    db_session.commit()

    assert run.published_flow_version_id == version.id
    assert run.flow_snapshot == flow
    assert run.execution_contract == version.execution_contract
    assert run.execution_surface == "published_manual"
    assert run.input_ref["_ingress"]["ingress_id"] == "manual.input"
    assert run.input_ref["execution"]["flow_sha256"] == canonical_flow_sha256(flow)


def test_invalid_ingress_payload_creates_zero_run(db_session) -> None:
    workspace, system, _version, _flow = _seed_published(db_session)
    before = db_session.query(Run).count()

    with pytest.raises(flow_ingress.FlowIngressError) as exc_info:
        flow_ingress.create_published_ingress_run(
            db_session,
            system_id=system.id,
            workspace=workspace,
            ingress_id="manual.input",
            kind="manual",
            payload={"query": 42},
        )

    assert exc_info.value.code == "INGRESS_PAYLOAD_INVALID"
    assert db_session.query(Run).count() == before


def test_sequential_ingress_requires_first_skill_input_before_run_creation(db_session) -> None:
    workspace, system, _version, _flow = _seed_sequential_published(db_session)

    summary = flow_ingress.list_published_ingresses(
        db_session,
        system_id=system.id,
        workspace=workspace,
    )
    assert summary["ingresses"][0]["required_input_fields"] == ["answer"]
    assert summary["ingresses"][0]["runtime_input_skill"]["slug"] == "eval_radar_v1"

    before = db_session.query(Run).count()
    with pytest.raises(flow_ingress.FlowIngressError) as exc_info:
        flow_ingress.create_published_ingress_run(
            db_session,
            system_id=system.id,
            workspace=workspace,
            ingress_id="manual.input",
            kind="manual",
            payload={"goal": "Audit this answer"},
        )

    assert exc_info.value.code == "RUN_INPUT_REQUIRED"
    assert exc_info.value.status_code == 422
    assert exc_info.value.details["missing_fields"] == ["answer"]
    assert db_session.query(Run).count() == before


def test_sequential_ingress_accepts_complete_first_skill_input(db_session) -> None:
    workspace, system, _version, _flow = _seed_sequential_published(db_session)

    run = flow_ingress.create_published_ingress_run(
        db_session,
        system_id=system.id,
        workspace=workspace,
        ingress_id="manual.input",
        kind="manual",
        payload={"answer": "The cited procedure supports the restart decision."},
    )

    assert run.status == "pending"
    assert run.input_ref["answer"].startswith("The cited procedure")


def test_non_builder_ingress_cannot_attach_debugger_controls(db_session) -> None:
    workspace, system, _version, _flow = _seed_published(db_session)

    with pytest.raises(flow_ingress.FlowIngressError) as exc_info:
        flow_ingress.create_published_ingress_run(
            db_session,
            system_id=system.id,
            workspace=workspace,
            ingress_id="manual.input",
            kind="manual",
            payload={"query": "reset", "_debug": {"mode": "step"}},
        )

    assert exc_info.value.code == "RUN_DEBUG_SURFACE_FORBIDDEN"
    assert db_session.query(Run).count() == 0


def test_explicit_builder_surface_normalizes_debugger_controls(db_session) -> None:
    workspace, system, _version, _flow = _seed_published(db_session)

    run = flow_ingress.create_published_ingress_run(
        db_session,
        system_id=system.id,
        workspace=workspace,
        ingress_id="manual.input",
        kind="manual",
        payload={
            "query": "reset",
            "_debug": {
                "mode": "breakpoints",
                "breakpoints": [" result ", "result"],
            },
        },
        allow_debug=True,
    )

    assert run.input_ref["_debug"] == {
        "mode": "breakpoints",
        "breakpoints": ["result"],
    }


def test_explicit_builder_surface_rejects_invalid_debugger_controls(db_session) -> None:
    workspace, system, _version, _flow = _seed_published(db_session)

    with pytest.raises(flow_ingress.FlowIngressError) as exc_info:
        flow_ingress.create_published_ingress_run(
            db_session,
            system_id=system.id,
            workspace=workspace,
            ingress_id="manual.input",
            kind="manual",
            payload={
                "query": "reset",
                "_debug": {"mode": "step", "unknown": True},
            },
            allow_debug=True,
        )

    assert exc_info.value.code == "RUN_DEBUG_INVALID"
    assert db_session.query(Run).count() == 0


def test_adapter_without_id_fails_closed_when_kind_is_ambiguous() -> None:
    contract = {
        "ingresses": [
            {"ingress_id": "a", "kind": "http"},
            {"ingress_id": "b", "kind": "http"},
        ]
    }
    with pytest.raises(flow_ingress.FlowIngressError) as exc_info:
        flow_ingress.resolve_published_ingress_id(
            contract,
            kind="http",
            requested_ingress_id=None,
        )
    assert exc_info.value.code == "FLOW_INGRESS_AMBIGUOUS"
