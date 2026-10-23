"""Required step inputs that nothing feeds, read with the engine's own rules.

Only certain gaps are reported: an undecidable step yields no warning.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.experience import lifecycle
from app.services.run_engine.input_coverage import unfed_required_inputs
from app.tests.api import test_work_api as helpers

INCIDENT_FORM = {"type": "object", "properties": {"incident_id": {"type": "string"}}}


def _workspace(db) -> Workspace:
    row = Workspace(id=str(uuid4()), name="Coverage", slug=f"coverage-{uuid4().hex[:8]}", settings={})
    db.add(row)
    db.flush()
    return row


def _skill(db, workspace, *, required=(), outputs=None, closed=True, executor=None) -> Skill:
    output_schema: dict = {"type": "object", "properties": {name: {"type": "string"} for name in outputs or []}}
    if closed and outputs is not None:
        output_schema["additionalProperties"] = False
    row = Skill(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"step-{uuid4().hex[:8]}",
        name="Step",
        version="1",
        input_schema={"type": "object", "required": list(required), "properties": {}},
        output_schema=output_schema,
        execution={"mode": "sync"},
        pricing={"unit_price": 0.0},
        executor=executor,
    )
    db.add(row)
    db.flush()
    return row


def _system(db, workspace, skills, flow=None) -> System:
    row = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Coverage system",
        skill_ids=[skill.id for skill in skills],
        flow_definition=flow or {},
    )
    db.add(row)
    db.flush()
    return row


def _gaps(db, workspace, system, *, form=INCIDENT_FORM, flow=None):
    return [
        (gap["step"], gap["node_id"], gap["field"])
        for gap in unfed_required_inputs(
            db, workspace=workspace, system=system, flow=flow or {}, input_schema=form
        )
    ]


def test_the_recette_case_an_llm_step_without_prompt_is_reported(db_session):
    """incident_id only reaches a step that requires prompt: the Run will fail."""
    workspace = _workspace(db_session)
    llm = _skill(db_session, workspace, required=["prompt"])
    system = _system(db_session, workspace, [llm])

    assert _gaps(db_session, workspace, system) == [(1, None, "prompt")]


def test_a_field_fed_by_the_form_or_by_the_previous_step_is_not_reported(db_session):
    workspace = _workspace(db_session)
    llm = _skill(db_session, workspace, required=["prompt"])
    fed_by_form = {"type": "object", "properties": {"prompt": {"type": "string"}}}
    assert _gaps(db_session, workspace, _system(db_session, workspace, [llm]), form=fed_by_form) == []

    writer = _skill(db_session, workspace, outputs=["prompt"])
    assert _gaps(db_session, workspace, _system(db_session, workspace, [writer, llm])) == []
    # Server-owned Run input keys feed a step too.
    audited = _skill(db_session, workspace, required=["run_id", "workspace_slug"])
    assert _gaps(db_session, workspace, _system(db_session, workspace, [audited])) == []


def test_an_undecidable_step_is_never_reported(db_session):
    workspace = _workspace(db_session)
    llm = _skill(db_session, workspace, required=["prompt"])
    # The previous step's output may carry any key: nothing can be said.
    open_writer = _skill(db_session, workspace, outputs=["summary"], closed=False)
    assert _gaps(db_session, workspace, _system(db_session, workspace, [open_writer, llm])) == []
    # An authored executor may pin the field itself.
    authored = _skill(
        db_session,
        workspace,
        required=["prompt"],
        executor={"kind": "registry_call", "params": {"skill_slug": "workspace_llm_v1", "frozen_input": {"prompt": "x"}}},
    )
    assert _gaps(db_session, workspace, _system(db_session, workspace, [authored])) == []
    # No ingress contract: the Run input is unknown.
    assert _gaps(db_session, workspace, _system(db_session, workspace, [llm]), form=None) == []
    # A closed previous output without the field is certain again.
    closed_writer = _skill(db_session, workspace, outputs=["summary"])
    assert _gaps(db_session, workspace, _system(db_session, workspace, [closed_writer, llm])) == [(2, None, "prompt")]


def _dag_flow(task_config: dict) -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "manual.input", "kind": "source", "config": {"ingress_kind": "manual", "input_schema": INCIDENT_FORM}},
            {"id": "ask", "kind": "task", "label": "Ask the model", "config": task_config},
            {"id": "result", "kind": "sink"},
        ],
        "edges": [
            {"from": "manual.input", "to": "ask", "kind": "data"},
            {"from": "ask", "to": "result", "kind": "data"},
        ],
    }


def test_a_dag_step_reads_its_mapping(db_session):
    workspace = _workspace(db_session)
    llm = _skill(db_session, workspace, required=["prompt"])
    system = _system(db_session, workspace, [llm])
    mapped = {"skill_slug": llm.slug, "input_mode": "mapped"}

    assert _gaps(db_session, workspace, system, flow=_dag_flow(mapped)) == [(2, "ask", "prompt")]
    for fed in (
        {"inputs_map": {"prompt": {"node_id": "manual.input", "path": "incident_id"}}},
        {"passthrough_inputs": ["prompt"]},
        {"params": {"prompt": "Summarise the incident"}},
    ):
        assert _gaps(db_session, workspace, system, flow=_dag_flow({**mapped, **fed})) == []
    # Alone, an inheriting task runs sequentially, where the gap is certain…
    inherit = {"skill_slug": llm.slug, "input_mode": "inherit"}
    assert _gaps(db_session, workspace, system, flow=_dag_flow(inherit)) == [(1, None, "prompt")]
    # …but inside a DAG it receives its predecessors' merge: undecidable.
    flow = _dag_flow({**mapped, "params": {"prompt": "x"}})
    flow["nodes"].insert(2, {"id": "follow", "kind": "task", "config": inherit})
    flow["edges"] = [
        {"from": "manual.input", "to": "ask", "kind": "data"},
        {"from": "ask", "to": "follow", "kind": "data"},
        {"from": "follow", "to": "result", "kind": "data"},
    ]
    assert _gaps(db_session, workspace, system, flow=flow) == []


def test_the_ready_check_warns_and_never_blocks(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)
    gap = {"step": 1, "node_id": None, "skill_slug": "workspace_llm_v1", "skill_name": "LLM", "field": "prompt"}
    monkeypatch.setattr(
        "app.services.run_engine.input_coverage.unfed_required_inputs", lambda *a, **k: [gap]
    )
    studio = helpers._experiences_client(db_session, workspace, user)
    experience_id, _release_id = helpers._publish(studio, binding_key="work.reset")

    check = studio.get(f"/experiences/{experience_id}/ready-check").json()
    unfed = [item for item in check["warnings"] if item["code"] == "STEP_INPUT_UNFED"]
    assert unfed == [
        {
            "code": "STEP_INPUT_UNFED",
            "message": "A step requires a field that no form field or previous step provides.",
            "binding_key": "work.reset",
            "step": 1,
            "node_id": None,
            "skill": "LLM",
            "field": "prompt",
        }
    ]
    assert not any(item["code"] == "STEP_INPUT_UNFED" for item in check["blockers"])


def test_a_coverage_failure_yields_no_warning(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)

    def boom(*_args, **_kwargs):
        raise RuntimeError("unreadable")

    monkeypatch.setattr("app.services.run_engine.input_coverage.unfed_required_inputs", boom)
    resolved = {"work.reset": {"status": "ok", "binding": {"system_id": "work-bound-system", "published_flow_version_id": "work-bound-v1"}}}
    assert lifecycle._unfed_step_input_warnings(db_session, workspace=workspace, resolved_by_key=resolved) == []
