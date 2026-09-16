"""Flow Builder workbench execution authority and durability contracts."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import flow_workbench as endpoint
from app.api.v1.endpoints import runs as runs_endpoint
from app.models.audit import AuditLog
from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.services.run_access import run_is_visible
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.run_outcome_provenance import baseline_run_exclusion_reason
from app.services.systems import flow_publication, flow_workbench


def _flow(label: str, *, task: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {
            "id": "manual",
            "kind": "source",
            "config": {
                "ingress_kind": "manual",
                "input_schema": {
                    "type": "object",
                    "properties": {"case": {"type": "string"}},
                    "required": ["case"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    edges: list[dict[str, Any]] = []
    if task is not None:
        nodes.append(copy.deepcopy(task))
        edges.append({"from": "manual", "to": task["id"], "kind": "data"})
        tail = task["id"]
    else:
        tail = "manual"
    nodes.append({"id": "result", "kind": "sink"})
    edges.append({"from": tail, "to": "result", "kind": "data"})
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "label": label,
        "nodes": nodes,
        "edges": edges,
    }


def _seed(db_session):
    workspace = Workspace(
        id="ws-flow-workbench",
        slug="flow-workbench",
        name="Flow workbench",
        settings={
            "features": {
                "flow_publication_v1": True,
                "flow_workbench_v1": True,
                "flow_v3_dag_authoritative": True,
            }
        },
    )
    user = User(
        id="user-flow-workbench",
        username="workbench@example.invalid",
        email="workbench@example.invalid",
        role="admin",
    )
    skill = Skill(
        id="skill-flow-workbench",
        workspace_id=workspace.id,
        slug="workbench_echo_v1",
        version="1",
        name="Workbench echo",
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        execution={"mode": "sync"},
    )
    system = System(
        id="system-flow-workbench",
        workspace_id=workspace.id,
        name="Flow workbench system",
        objective="Exercise local graphs without mutating publication authority",
        status="active",
        settings={},
        skill_ids=[skill.id],
        flow_definition=_flow("published-v1"),
        created_by=user.email,
    )
    db_session.add_all([workspace, user, skill, system])
    db_session.commit()
    flow_publication.initialize_publication_state(
        db_session,
        system=system,
        workspace=workspace,
        actor=user.email,
    )
    db_session.commit()
    db_session.refresh(system)
    return workspace, user, system, skill


def _client(
    db_session,
    workspace: Workspace,
    user: User,
    monkeypatch,
    dispatches: list[str] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/systems")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session

    def _schedule_run(run_id: str) -> None:
        if dispatches is not None:
            dispatches.append(run_id)

    monkeypatch.setattr(endpoint, "schedule_run", _schedule_run)
    return TestClient(app)


def _workbench_requests(system: System, skill: Skill) -> list[tuple[str, dict[str, Any]]]:
    preview_flow = _flow("workbench-authority-preview")
    node_flow = _flow(
        "workbench-authority-node",
        task={
            "id": "echo",
            "kind": "task",
            "config": {"skill_slug": skill.slug},
        },
    )
    return [
        (
            f"/systems/{system.id}/flow-workbench/preview-runs",
            {
                "acknowledge_real_side_effects": True,
                "flow_definition": preview_flow,
                "expected_flow_sha256": canonical_flow_sha256(preview_flow),
                "input_ref": {"case": "preview"},
            },
        ),
        (
            f"/systems/{system.id}/flow-workbench/node-runs",
            {
                "acknowledge_real_side_effects": True,
                "flow_definition": node_flow,
                "expected_flow_sha256": canonical_flow_sha256(node_flow),
                "node_id": "echo",
                "input_ref": {"prompt": "node"},
            },
        ),
        (
            f"/systems/{system.id}/flow-workbench/golden-runs",
            {
                "acknowledge_real_side_effects": True,
                "flow_definition": preview_flow,
                "expected_flow_sha256": canonical_flow_sha256(preview_flow),
                "cases": [{"id": "golden", "input_ref": {"case": "golden"}}],
            },
        ),
    ]


@pytest.mark.parametrize("feature_value", [None, False], ids=["missing", "false"])
def test_workbench_feature_is_fail_closed_before_run_or_dispatch(
    db_session,
    monkeypatch,
    feature_value,
) -> None:
    workspace, user, system, skill = _seed(db_session)
    settings = copy.deepcopy(workspace.settings)
    features = copy.deepcopy(settings["features"])
    if feature_value is None:
        features.pop(flow_workbench.FEATURE_KEY)
    else:
        features[flow_workbench.FEATURE_KEY] = feature_value
    settings["features"] = features
    workspace.settings = settings
    db_session.commit()

    dispatches: list[str] = []
    client = _client(db_session, workspace, user, monkeypatch, dispatches)

    for path, payload in _workbench_requests(system, skill):
        response = client.post(path, json=payload)
        assert response.status_code == 404, response.text
        assert response.json()["detail"]["code"] == "FLOW_WORKBENCH_DISABLED"

    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0
    assert dispatches == []


@pytest.mark.parametrize("mode", ["compat", "shadow", "enforce"])
def test_non_admin_cannot_execute_workbench_in_any_iam_mode(
    db_session,
    monkeypatch,
    attest_authorization_v2,
    mode,
) -> None:
    workspace, user, system, skill = _seed(db_session)
    user.role = "user"
    db_session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role="member",
            role_template="workspace_viewer",
        )
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=1,
        role_flags={},
        capability_overrides={
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "modes": {"system.admin": mode},
            }
        },
        updated_by_user_id=user.id,
    )
    db_session.add(config)
    db_session.commit()
    if mode == "enforce":
        attest_authorization_v2(config, ["system.admin"])
        db_session.commit()

    dispatches: list[str] = []
    client = _client(db_session, workspace, user, monkeypatch, dispatches)

    for path, payload in _workbench_requests(system, skill):
        response = client.post(path, json=payload)
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "FLOW_WORKBENCH_ADMIN_REQUIRED"

    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0
    assert dispatches == []


@pytest.mark.parametrize(
    "authority",
    ["global_admin", "workspace_admin", "workspace_owner"],
)
def test_admin_and_owner_can_execute_all_workbench_surfaces(
    db_session,
    monkeypatch,
    authority,
) -> None:
    workspace, user, system, skill = _seed(db_session)
    if authority != "global_admin":
        user.role = "user"
        legacy_role = "admin" if authority == "workspace_admin" else "owner"
        db_session.add(
            WorkspaceMember(
                user_id=user.id,
                workspace_id=workspace.id,
                role=legacy_role,
                role_template=authority,
            )
        )
        db_session.commit()

    dispatches: list[str] = []
    client = _client(db_session, workspace, user, monkeypatch, dispatches)

    for path, payload in _workbench_requests(system, skill):
        response = client.post(path, json=payload)
        assert response.status_code == 201, response.text

    runs = db_session.query(Run).filter_by(system_id=system.id).all()
    assert len(runs) == 3
    assert len(dispatches) == 3
    assert {run.execution_surface for run in runs} == {
        "builder_preview",
        "node_preview",
        "golden_preview",
    }
    assert set(dispatches) == {run.id for run in runs}


def test_all_workbench_surfaces_require_explicit_real_side_effect_ack(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, skill = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    task = {
        "id": "echo",
        "kind": "task",
        "config": {"skill_slug": skill.slug},
    }
    node_flow = _flow("missing-ack-node", task=task)
    preview_flow = _flow("missing-ack-preview")
    requests = [
        (
            f"/systems/{system.id}/flow-workbench/preview-runs",
            {
                "flow_definition": preview_flow,
                "expected_flow_sha256": canonical_flow_sha256(preview_flow),
                "input_ref": {"case": "preview"},
            },
        ),
        (
            f"/systems/{system.id}/flow-workbench/node-runs",
            {
                "flow_definition": node_flow,
                "expected_flow_sha256": canonical_flow_sha256(node_flow),
                "node_id": "echo",
                "input_ref": {"prompt": "node"},
            },
        ),
        (
            f"/systems/{system.id}/flow-workbench/golden-runs",
            {
                "flow_definition": preview_flow,
                "expected_flow_sha256": canonical_flow_sha256(preview_flow),
                "cases": [{"id": "golden", "input_ref": {"case": "golden"}}],
            },
        ),
    ]

    for path, payload in requests:
        response = client.post(path, json=payload)
        assert response.status_code == 422, response.text
        assert any(
            error["loc"][-1] == "acknowledge_real_side_effects"
            for error in response.json()["detail"]
        )

    for rejected_ack in (False, 1, "true"):
        response = client.post(
            f"/systems/{system.id}/flow-workbench/preview-runs",
            json={
                **requests[0][1],
                "acknowledge_real_side_effects": rejected_ack,
            },
        )
        assert response.status_code == 422, response.text
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0


def test_workbench_system_lock_refreshes_identity_and_targets_system_row(
    db_session,
    monkeypatch,
) -> None:
    workspace, _, system, _ = _seed(db_session)
    real_query = db_session.query
    observed: dict[str, object] = {}

    class _LockQuery:
        def filter(self, *_criteria):
            return self

        def populate_existing(self):
            observed["populate_existing"] = True
            return self

        def with_for_update(self, **kwargs):
            observed.update(kwargs)
            return self

        def one_or_none(self):
            return system

    def _query(entity):
        if entity is System:
            return _LockQuery()
        return real_query(entity)

    monkeypatch.setattr(db_session, "query", _query)

    locked = flow_workbench._locked_system(
        db_session,
        system_id=system.id,
        workspace=workspace,
    )

    assert locked is system
    assert observed == {"populate_existing": True, "of": System}


def test_dirty_preview_creates_only_a_durable_run(db_session, monkeypatch) -> None:
    workspace, user, system, _ = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    dirty_flow = _flow("unsaved-local-edit")
    initial_pointer = system.published_flow_version_id
    initial_system_flow = copy.deepcopy(system.flow_definition)
    initial_draft = db_session.get(SystemFlowDraft, system.id)
    assert initial_draft is not None
    initial_draft_state = (
        initial_draft.revision,
        initial_draft.flow_sha256,
        copy.deepcopy(initial_draft.flow_definition),
        initial_draft.base_published_version_id,
    )
    initial_version_count = (
        db_session.query(SystemVersion).filter_by(system_id=system.id).count()
    )

    response = client.post(
        f"/systems/{system.id}/flow-workbench/preview-runs",
        json={
            "acknowledge_real_side_effects": True,
            "flow_definition": dirty_flow,
            "expected_flow_sha256": canonical_flow_sha256(dirty_flow),
            "input_ref": {"case": "dirty"},
        },
    )

    assert response.status_code == 201, response.text
    run = db_session.get(Run, response.json()["id"])
    assert run is not None
    assert run.execution_surface == "builder_preview"
    assert run.flow_version_id is None
    assert run.published_flow_version_id is None
    assert run.flow_snapshot == dirty_flow
    assert run.flow_sha256 == canonical_flow_sha256(dirty_flow)
    assert run.input_ref["execution"]["source_flow_sha256"] == run.flow_sha256
    assert run.input_ref["execution"]["real_side_effects_acknowledged"] is True
    audit = (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="flow.workbench.builder_preview.queued",
        )
        .one()
    )
    assert audit.details["run_id"] == run.id
    assert audit.details["real_side_effects_acknowledged"] is True

    db_session.expire_all()
    persisted_system = db_session.get(System, system.id)
    persisted_draft = db_session.get(SystemFlowDraft, system.id)
    assert persisted_system is not None
    assert persisted_draft is not None
    assert persisted_system.published_flow_version_id == initial_pointer
    assert persisted_system.flow_definition == initial_system_flow
    assert (
        persisted_draft.revision,
        persisted_draft.flow_sha256,
        persisted_draft.flow_definition,
        persisted_draft.base_published_version_id,
    ) == initial_draft_state
    assert (
        db_session.query(SystemVersion).filter_by(system_id=system.id).count()
        == initial_version_count
    )


def test_preview_rejects_a_stale_validated_hash_without_side_effects(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, _ = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    dirty_flow = _flow("changed-after-validation")

    response = client.post(
        f"/systems/{system.id}/flow-workbench/preview-runs",
        json={
            "acknowledge_real_side_effects": True,
            "flow_definition": dirty_flow,
            "expected_flow_sha256": canonical_flow_sha256(_flow("validated-before-edit")),
            "input_ref": {"case": "stale"},
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "WORKBENCH_FLOW_HASH_MISMATCH"
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 1


def test_builder_and_golden_preview_refuse_sequential_legacy_runtime(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, _ = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    legacy_flow = _flow("legacy-workbench")
    legacy_flow["io_mode"] = "overlay"
    common = {
        "acknowledge_real_side_effects": True,
        "flow_definition": legacy_flow,
        "expected_flow_sha256": canonical_flow_sha256(legacy_flow),
    }

    responses = [
        client.post(
            f"/systems/{system.id}/flow-workbench/preview-runs",
            json={**common, "input_ref": {"case": "preview"}},
        ),
        client.post(
            f"/systems/{system.id}/flow-workbench/golden-runs",
            json={
                **common,
                "cases": [{"id": "golden", "input_ref": {"case": "golden"}}],
            },
        ),
    ]

    for response in responses:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "WORKBENCH_DAG_REQUIRED"
        assert response.json()["detail"]["runtime_mode"] == "sequential_legacy"
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0


def test_node_preview_builds_an_isolated_bound_skill_snapshot(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, skill = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    task = {
        "id": "echo",
        "kind": "task",
        "config": {"skill_slug": skill.slug, "temperature": 0},
    }
    local_flow = _flow("node-preview", task=task)

    response = client.post(
        f"/systems/{system.id}/flow-workbench/node-runs",
        json={
            "acknowledge_real_side_effects": True,
            "flow_definition": local_flow,
            "expected_flow_sha256": canonical_flow_sha256(local_flow),
            "node_id": "echo",
            "input_ref": {"prompt": "hello", "context": {"tenant": "demo"}},
        },
    )

    assert response.status_code == 201, response.text
    run = db_session.get(Run, response.json()["id"])
    assert run is not None
    assert run.execution_surface == "node_preview"
    assert run.input_ref["execution"]["node_id"] == "echo"
    assert run.input_ref["execution"]["source_flow_sha256"] == canonical_flow_sha256(
        local_flow
    )
    assert run.flow_sha256 != run.input_ref["execution"]["source_flow_sha256"]
    assert {node["kind"] for node in run.flow_snapshot["nodes"]} == {
        "source",
        "task",
        "sink",
    }
    assert [
        node["id"] for node in run.flow_snapshot["nodes"] if node["kind"] == "task"
    ] == ["echo"]
    isolated_task = next(
        node for node in run.flow_snapshot["nodes"] if node["id"] == "echo"
    )
    assert isolated_task["config"]["inputs_map"] == {
        "context": {"node_id": "run", "path": ["context"], "required": True},
        "prompt": {"node_id": "run", "path": ["prompt"], "required": True},
    }
    assert run.flow_version_id is None
    assert run.published_flow_version_id is None


def test_node_preview_rebuilds_server_owned_execution_evidence(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, skill = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    task = {
        "id": "echo",
        "kind": "task",
        "config": {"skill_slug": skill.slug},
    }
    local_flow = _flow("node-preview-evidence", task=task)

    response = client.post(
        f"/systems/{system.id}/flow-workbench/node-runs",
        json={
            "acknowledge_real_side_effects": True,
            "flow_definition": local_flow,
            "expected_flow_sha256": canonical_flow_sha256(local_flow),
            "node_id": "echo",
            "input_ref": {
                "prompt": "hello",
                "execution": {
                    "system_id": "attacker-system",
                    "published_flow_version_id": "attacker-version",
                    "golden_batch_id": "attacker-batch",
                    "golden_case_id": "attacker-case",
                    "execution_surface": "published_http",
                    "flow_sha256": "0" * 64,
                    "source_flow_sha256": "0" * 64,
                    "runtime_mode": "sequential_legacy",
                },
            },
        },
    )

    assert response.status_code == 201, response.text
    run = db_session.get(Run, response.json()["id"])
    assert run is not None
    assert run.input_ref["execution"] == {
        "flow_sha256": run.flow_sha256,
        "source_flow_sha256": canonical_flow_sha256(local_flow),
        "runtime_mode": "dag_strict",
        "runtime_mode_reason": "flow_v3_strict_workspace_authoritative",
        "execution_surface": "node_preview",
        "node_id": "echo",
        "real_side_effects_acknowledged": True,
        "ingress_id": "__workbench_input__",
        "ingress_selection_version": 1,
    }


def test_node_preview_refuses_control_and_unbound_tasks(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, _ = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    cases = [
        (
            {
                "schema_version": 3,
                "nodes": [{"id": "decision", "kind": "control", "type": "decision"}],
                "edges": [],
            },
            "decision",
            "WORKBENCH_NODE_KIND_UNSUPPORTED",
        ),
        (
            {
                "schema_version": 3,
                "nodes": [{"id": "unbound", "kind": "task", "config": {}}],
                "edges": [],
            },
            "unbound",
            "WORKBENCH_NODE_SKILL_REQUIRED",
        ),
    ]

    for flow, node_id, expected_code in cases:
        response = client.post(
            f"/systems/{system.id}/flow-workbench/node-runs",
            json={
                "acknowledge_real_side_effects": True,
                "flow_definition": flow,
                "expected_flow_sha256": canonical_flow_sha256(flow),
                "node_id": node_id,
                "input_ref": {"prompt": "hello"},
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == expected_code

    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0


def test_golden_batch_is_bounded_and_persists_one_run_per_case(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, _ = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    local_flow = _flow("golden-local-flow")
    request = {
        "acknowledge_real_side_effects": True,
        "flow_definition": local_flow,
        "expected_flow_sha256": canonical_flow_sha256(local_flow),
        "cases": [
            {"id": "case-a", "input_ref": {"case": "A"}, "expected": {"ok": True}},
            {"id": "case-b", "input_ref": {"case": "B"}, "expected": {"ok": False}},
        ],
    }

    response = client.post(
        f"/systems/{system.id}/flow-workbench/golden-runs",
        json=request,
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert len(payload["runs"]) == 2
    runs = (
        db_session.query(Run)
        .filter_by(system_id=system.id, execution_surface="golden_preview")
        .order_by(Run.id.asc())
        .all()
    )
    assert len(runs) == 2
    assert {run.input_ref["execution"]["golden_batch_id"] for run in runs} == {
        payload["batch_id"]
    }
    assert {run.input_ref["execution"]["golden_case_id"] for run in runs} == {
        "case-a",
        "case-b",
    }
    assert all("expected" not in run.input_ref for run in runs)
    assert {run.checkpoints[0]["expected"]["ok"] for run in runs} == {True, False}
    assert all(run.flow_version_id is None for run in runs)
    assert all(run.published_flow_version_id is None for run in runs)

    too_many = client.post(
        f"/systems/{system.id}/flow-workbench/golden-runs",
        json={
            **request,
            "cases": [
                {"id": f"case-{index}", "input_ref": {"case": str(index)}}
                for index in range(21)
            ],
        },
    )
    assert too_many.status_code == 422, too_many.text
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 2


def test_golden_expected_absent_is_distinct_from_explicit_null(
    db_session,
    monkeypatch,
) -> None:
    workspace, user, system, _ = _seed(db_session)
    client = _client(db_session, workspace, user, monkeypatch)
    local_flow = _flow("golden-expected-presence")

    response = client.post(
        f"/systems/{system.id}/flow-workbench/golden-runs",
        json={
            "acknowledge_real_side_effects": True,
            "flow_definition": local_flow,
            "expected_flow_sha256": canonical_flow_sha256(local_flow),
            "cases": [
                {"id": "absent", "input_ref": {"case": "A"}},
                {"id": "explicit-null", "input_ref": {"case": "B"}, "expected": None},
            ],
        },
    )

    assert response.status_code == 201, response.text
    runs = db_session.query(Run).filter_by(system_id=system.id).all()
    by_case = {
        run.input_ref["execution"]["golden_case_id"]: run
        for run in runs
    }
    assert "expected" not in by_case["absent"].checkpoints[0]
    assert "expected" in by_case["explicit-null"].checkpoints[0]
    assert by_case["explicit-null"].checkpoints[0]["expected"] is None


def test_workbench_runs_are_visible_only_to_owner_or_admin_and_not_baselines(
    db_session,
) -> None:
    workspace, admin, system, _ = _seed(db_session)
    owner = User(
        id="user-workbench-owner",
        username="workbench-owner@example.invalid",
        email="workbench-owner@example.invalid",
        role="user",
    )
    other = User(
        id="user-workbench-other",
        username="workbench-other@example.invalid",
        email="workbench-other@example.invalid",
        role="user",
    )
    run = Run(
        id="run-private-workbench",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=owner.id,
        status="completed",
        trigger="builder_preview",
        execution_surface="builder_preview",
        input_ref={},
    )
    db_session.add_all([owner, other, run])
    db_session.commit()

    assert run_is_visible(
        db_session, run=run, user=owner, workspace=workspace
    ) is True
    assert run_is_visible(
        db_session, run=run, user=admin, workspace=workspace
    ) is True
    assert run_is_visible(
        db_session, run=run, user=other, workspace=workspace
    ) is False
    assert baseline_run_exclusion_reason(run) == "baseline_run_is_flow_workbench"


@pytest.mark.asyncio
async def test_workbench_runs_cannot_use_generic_replay_or_rerun(
    db_session,
) -> None:
    workspace, _, system, _ = _seed(db_session)
    owner = User(
        id="user-workbench-reexecute-owner",
        username="workbench-reexecute-owner@example.invalid",
        email="workbench-reexecute-owner@example.invalid",
        role="user",
    )
    run = Run(
        id="run-workbench-reexecute",
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=owner.id,
        status="completed",
        trigger="node_preview",
        execution_surface="node_preview",
        input_ref={},
    )
    db_session.add_all([owner, run])
    db_session.commit()

    with pytest.raises(HTTPException) as replay_rejected:
        await runs_endpoint.replay_run(
            run.id,
            runs_endpoint.ReplayRequest(),
            workspace,
            owner,
            db_session,
        )
    assert replay_rejected.value.status_code == 409
    assert replay_rejected.value.detail["code"] == "WORKBENCH_RUN_REPLAY_FORBIDDEN"

    with pytest.raises(HTTPException) as rerun_rejected:
        await runs_endpoint.rerun_run(
            run.id,
            BackgroundTasks(),
            workspace,
            owner,
            db_session,
        )
    assert rerun_rejected.value.status_code == 409
    assert rerun_rejected.value.detail["code"] == "WORKBENCH_RUN_RERUN_FORBIDDEN"
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 1


def test_golden_runs_use_reviewed_suite_without_baseline(db_session, monkeypatch):
    from app.models.evaluation_campaign import EvaluationSuite
    workspace, user, system, _ = _seed(db_session)
    dispatches = []
    http = _client(db_session, workspace, user, monkeypatch, dispatches)
    assertions = [{"id": "fact", "path": ["completion"], "operator": "contains", "value": "source"}]
    suite = EvaluationSuite(workspace_id=workspace.id, system_id=system.id, name="BRD cases",
        revision=1, created_by_user_id=user.id, cases=[{"id": "first", "input_ref": {"case": "source"},
        "assertions": assertions}], corpus_manifest=[], provenance={"method": "brd_proposal"})
    db_session.add(suite)
    db_session.commit()
    flow = _flow("suite-run")
    body = {"acknowledge_real_side_effects": True, "flow_definition": flow,
            "expected_flow_sha256": canonical_flow_sha256(flow), "suite_id": suite.id, "request_key": "suite-first"}
    url = f"/systems/{system.id}/flow-workbench/golden-runs"
    assert http.post(url, json={**body, "cases": [{"id": "override", "input_ref": {}}]}).status_code == 422
    response = http.post(url, json=body)
    assert response.status_code == 201, response.text
    runs = db_session.query(Run).filter_by(system_id=system.id).all()
    assert len(runs) == 1
    assert runs[0].input_ref["case"] == "source"
    assert "override" not in runs[0].input_ref
    checkpoint = next(cp for cp in runs[0].checkpoints if cp["kind"] == "golden_case_queued")
    assert checkpoint["suite_id"] == suite.id
    assert checkpoint["suite_revision"] == 1
    assert checkpoint["assertions"] == assertions
    assert "expected" not in checkpoint  # No invented whole-output oracle.
    assert runs_endpoint._row(runs[0], db=db_session)["test_result"]["verdict"] == "pending"
    runs[0].status, runs[0].output_ref = "completed", {"completion": "source"}
    result = runs_endpoint._row(runs[0], db=db_session)["test_result"]
    assert result["verdict"] == "passed"
    assert result["suite_id"] == suite.id
    replay = http.post(url, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["batch_id"] == response.json()["batch_id"]
    assert replay.json()["runs"][0]["id"] == runs[0].id
    assert dispatches == [runs[0].id]
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 1
    changed = {**body, "flow_definition": _flow("changed-request")}
    assert http.post(url, json=changed).status_code == 409


def test_suite_run_verdict_uses_frozen_server_criteria():
    from types import SimpleNamespace
    from app.services.evaluation.campaigns import suite_run_result
    run = SimpleNamespace(execution_surface="golden_preview", status="hitl_pending",
        output_ref={"answer": "unreviewed"}, checkpoints=[{"kind": "golden_case_queued",
        "suite_id": "suite", "suite_revision": 2, "batch_id": "batch", "case_id": "case",
        "assertions": [{"id": "fact", "path": ["answer"], "operator": "equals", "value": "source"}]}])
    assert suite_run_result(run)["verdict"] == "pending"
    run.status = "completed"
    assert suite_run_result(run)["verdict"] == "failed"
    run.output_ref = {"answer": "source"}
    assert suite_run_result(run)["verdict"] == "passed"
    run.checkpoints[0]["assertions"] = []
    assert suite_run_result(run)["verdict"] == "unevaluated"
    run.execution_surface = "production"
    assert suite_run_result(run) is None
