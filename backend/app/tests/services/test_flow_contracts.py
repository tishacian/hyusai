"""Executable ingress/output contracts compiled at Publish time."""

from __future__ import annotations

import pytest

from app.models.skill import Skill
from app.services.flow_contracts import (
    FlowContractError,
    canonical_sha256,
    compile_execution_contract,
    contract_ingress,
    validate_execution_contract,
    validate_payload,
    validate_schema_definition,
)


def _minimal_execution_contract() -> dict:
    body = {
        "schema_version": 1,
        "runtime_mode": "dag_overlay",
        "validation_mode": "observe",
        "ingresses": [],
        "nodes": {},
        "outputs": [],
    }
    return {**body, "contract_sha256": canonical_sha256(body)}


def _rehash_execution_contract(contract: dict) -> None:
    body = {key: value for key, value in contract.items() if key != "contract_sha256"}
    contract["contract_sha256"] = canonical_sha256(body)


def test_validate_execution_contract_accepts_canonical_frozen_shape() -> None:
    contract = _minimal_execution_contract()

    assert validate_execution_contract(contract) == contract


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("ingresses", "not-an-array"),
        ("nodes", []),
        ("outputs", {}),
        ("runtime_mode", []),
    ],
)
def test_validate_execution_contract_rejects_self_hashed_shape_corruption(
    field: str,
    invalid_value,
) -> None:
    contract = _minimal_execution_contract()
    contract[field] = invalid_value
    _rehash_execution_contract(contract)

    with pytest.raises(FlowContractError) as exc_info:
        validate_execution_contract(contract)

    assert exc_info.value.code == "execution_contract_invalid"
    assert exc_info.value.path == f"/{field}"


def test_validate_execution_contract_rejects_digest_corruption() -> None:
    contract = _minimal_execution_contract()
    contract["contract_sha256"] = "0" * 64

    with pytest.raises(FlowContractError) as exc_info:
        validate_execution_contract(contract)

    assert exc_info.value.code == "execution_contract_invalid"
    assert exc_info.value.path == "/contract_sha256"


def test_validate_execution_contract_rejects_self_hashed_mode_contradiction() -> None:
    contract = _minimal_execution_contract()
    contract["runtime_mode"] = "dag_strict"
    _rehash_execution_contract(contract)

    with pytest.raises(FlowContractError) as exc_info:
        validate_execution_contract(contract)

    assert exc_info.value.path == "/validation_mode"


def test_schema_rejects_remote_ref_and_accepts_local_defs() -> None:
    local = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"name": {"type": "string"}},
        "type": "object",
        "properties": {"name": {"$ref": "#/$defs/name"}},
    }
    assert validate_schema_definition(local, field="schema") == local

    with pytest.raises(FlowContractError) as exc_info:
        validate_schema_definition(
            {"$ref": "https://schemas.example.invalid/person.json"},
            field="schema",
        )
    assert exc_info.value.code == "schema_remote_ref_forbidden"


def test_schema_depth_is_bounded() -> None:
    schema: dict = {"type": "string"}
    for _ in range(40):
        schema = {"allOf": [schema]}
    with pytest.raises(FlowContractError) as exc_info:
        validate_schema_definition(schema, field="schema")
    assert exc_info.value.code == "schema_too_deep"


def test_payload_error_is_sanitised_and_path_bound() -> None:
    schema = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    with pytest.raises(FlowContractError) as exc_info:
        validate_payload(
            {"count": "secret raw value"},
            schema,
            code="ingress_schema_violation",
            subject="Ingress payload",
        )
    assert exc_info.value.to_dict() == {
        "code": "ingress_schema_violation",
        "message": "Ingress payload does not satisfy its executable schema.",
        "path": "/count",
    }
    assert "secret" not in str(exc_info.value)


def test_compile_contract_freezes_skill_ingress_and_sink_schemas(db_session) -> None:
    skill = Skill(
        id="skill-contract",
        workspace_id=None,
        slug="contract-skill",
        version="7",
        name="Contract skill",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        execution={"capabilities": ["provider_json_schema"]},
    )
    db_session.add(skill)
    db_session.commit()
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual",
                "kind": "source",
                "type": "source",
                "outputs": [{"name": "query", "schema": "string", "required": True}],
            },
            {
                "id": "task",
                "kind": "task",
                "config": {"skill_slug": skill.slug},
            },
            {
                "id": "result",
                "kind": "sink",
                "inputs": [{"name": "answer", "schema": "string", "required": True}],
            },
        ],
        "edges": [
            {"from": "manual", "to": "task", "kind": "data"},
            {"from": "task", "to": "result", "kind": "data"},
        ],
    }

    contract = compile_execution_contract(
        db_session,
        flow=flow,
        workspace_id="workspace-contract",
        runtime_mode="dag_strict",
    )

    assert contract["validation_mode"] == "enforce"
    assert contract["nodes"]["task"]["skill_version"] == "7"
    assert contract["nodes"]["task"]["provider_json_schema"] is True
    assert contract_ingress(contract, "manual")["kind"] == "manual"
    assert contract["outputs"][0]["node_id"] == "result"
    assert len(contract["contract_sha256"]) == 64
    assert validate_execution_contract(contract) == contract

    with pytest.raises(FlowContractError) as unbound:
        compile_execution_contract(
            db_session,
            flow=flow,
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
            allowed_skill_ids=set(),
        )
    assert unbound.value.code == "skill_not_bound_to_system"


@pytest.mark.parametrize(
    ("sinks", "code"),
    [
        ([], "flow_output_sink_required"),
        (
            [
                {"id": "first", "kind": "sink"},
                {"id": "second", "kind": "sink"},
            ],
            "flow_output_sink_ambiguous",
        ),
    ],
)
def test_compile_strict_flow_requires_exactly_one_explicit_sink(
    db_session,
    sinks,
    code,
) -> None:
    with pytest.raises(FlowContractError) as exc_info:
        compile_execution_contract(
            db_session,
            flow={
                "schema_version": 3,
                "io_mode": "strict",
                "nodes": [{"id": "source", "kind": "source"}, *sinks],
                "edges": [],
            },
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
        )

    assert exc_info.value.code == code
    assert exc_info.value.path == "outputs"


def test_compile_contract_freezes_control_node_output_adapters(db_session) -> None:
    invocation_schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    skill = Skill(
        id="skill-control-contract",
        workspace_id=None,
        slug="control-contract-skill",
        version="2",
        name="Control contract skill",
        input_schema={"type": "object"},
        output_schema=invocation_schema,
        execution={},
    )
    db_session.add(skill)
    db_session.commit()

    contract = compile_execution_contract(
        db_session,
        flow={
            "nodes": [
                {
                    "id": "retry",
                    "kind": "retry",
                    "config": {"skill_slug": skill.slug, "max_attempts": 3},
                },
                {
                    "id": "loop",
                    "kind": "loop",
                    "config": {"skill_slug": skill.slug, "max_iterations": 5},
                },
            ]
        },
        workspace_id="workspace-contract",
        runtime_mode="dag_overlay",
        allowed_skill_ids={skill.id},
    )

    assert validate_execution_contract(contract) == contract

    retry_contract = contract["nodes"]["retry"]
    assert retry_contract["output_adapter"] == "retry.v1"
    assert retry_contract["invocation_output_schema"] == invocation_schema
    assert retry_contract["output_schema"] != invocation_schema
    assert retry_contract["output_schema"]["required"] == [
        "_retry_attempts",
        "_status",
    ]
    assert len(retry_contract["invocation_output_schema_sha256"]) == 64

    loop_contract = contract["nodes"]["loop"]
    assert loop_contract["output_adapter"] == "loop.v1"
    assert loop_contract["invocation_output_schema"] == invocation_schema
    assert loop_contract["output_schema"]["required"] == ["iterations", "count"]
    assert loop_contract["output_schema"]["properties"]["iterations"]["maxItems"] == 5

    validate_payload(
        {"answer": "ok"},
        retry_contract["invocation_output_schema"],
        code="invalid",
        subject="Raw output",
    )
    validate_payload(
        {"answer": "ok", "_retry_attempts": 1, "_status": "completed"},
        retry_contract["output_schema"],
        code="invalid",
        subject="Retry output",
    )
    validate_payload(
        {
            "iterations": [{"index": 0, "status": "completed", "output": {"answer": "ok"}}],
            "count": 1,
        },
        loop_contract["output_schema"],
        code="invalid",
        subject="Loop output",
    )


def test_declarative_source_typed_asset_is_not_an_external_ingress(db_session) -> None:
    contract = compile_execution_contract(
        db_session,
        flow={
            "nodes": [
                {
                    "id": "manual",
                    "kind": "source",
                },
                {
                    "id": "knowledge.asset",
                    "kind": "asset",
                    "type": "source.collection",
                },
            ],
            "edges": [],
        },
        workspace_id="workspace-contract",
        runtime_mode="dag_strict",
    )

    assert [item["ingress_id"] for item in contract["ingresses"]] == ["manual"]


def test_canonical_chat_request_source_compiles_as_chat_ingress(db_session) -> None:
    contract = compile_execution_contract(
        db_session,
        flow={
            "nodes": [
                {
                    "id": "source.request",
                    "type": "input",
                    "kind": "source",
                    "outputs": [
                        {"name": "query", "schema": "string", "required": True},
                        {"name": "conversation_history", "schema": "array"},
                    ],
                },
                {"id": "sink.answer", "kind": "sink"},
            ],
            "edges": [{"from": "source.request", "to": "sink.answer"}],
        },
        workspace_id="workspace-contract",
        runtime_mode="dag_strict",
    )

    assert [(item["ingress_id"], item["kind"]) for item in contract["ingresses"]] == [
        ("source.request", "chat")
    ]
    assert contract["ingresses"][0]["input_schema"]["required"] == ["query"]


def test_seeded_chat_request_port_compiles_as_chat_ingress(db_session) -> None:
    """The seeded chat System names its port ``chat.request``, not ``source.request``.

    Keying the chat surface on the ``type=input`` role rather than on one node
    id is what makes the seeded template dispatchable; before this, every
    workspace's chat System compiled a ``manual`` ingress and the chat adapter
    was refused with ``FLOW_INGRESS_KIND_UNAVAILABLE``.
    """

    contract = compile_execution_contract(
        db_session,
        flow={
            "nodes": [
                {"id": "chat.request", "kind": "source", "type": "input"},
                {"id": "sink.answer", "kind": "sink"},
            ],
            "edges": [{"from": "chat.request", "to": "sink.answer"}],
        },
        workspace_id="workspace-contract",
        runtime_mode="dag_strict",
    )

    assert [(item["ingress_id"], item["kind"]) for item in contract["ingresses"]] == [
        ("chat.request", "chat")
    ]


@pytest.mark.parametrize(
    ("node", "expected_kind"),
    [
        # Canonical spelling.
        ({"id": "root", "kind": "source"}, "manual"),
        # Legacy spelling: the role is named in ``type`` and ``kind`` is absent.
        ({"id": "root", "type": "source"}, "manual"),
        # Both fields, agreeing.
        ({"id": "root", "kind": "source", "type": "source"}, "manual"),
    ],
)
def test_source_role_is_read_in_both_graph_dialects(
    db_session, node, expected_kind
) -> None:
    contract = compile_execution_contract(
        db_session,
        flow={"nodes": [node], "edges": []},
        workspace_id="workspace-contract",
        runtime_mode="sequential_legacy",
    )

    assert [(item["ingress_id"], item["kind"]) for item in contract["ingresses"]] == [
        ("root", expected_kind)
    ]


@pytest.mark.parametrize(
    ("node", "expected_ingresses"),
    [
        # ``kind`` is canonical, so it decides even when ``type`` contradicts it:
        # a task stays a task and freezes no ingress.
        ({"id": "root", "kind": "task", "type": "source"}, []),
        # ...and a declared source stays a source even when ``type`` says
        # otherwise. Resolution never depends on mapping order.
        ({"id": "root", "kind": "source", "type": "task"}, [("root", "manual")]),
    ],
)
def test_conflicting_kind_and_type_resolve_from_kind(
    db_session, node, expected_ingresses
) -> None:
    contract = compile_execution_contract(
        db_session,
        flow={"nodes": [node], "edges": []},
        workspace_id="workspace-contract",
        runtime_mode="sequential_legacy",
    )

    assert [
        (item["ingress_id"], item["kind"]) for item in contract["ingresses"]
    ] == expected_ingresses


def test_legacy_typed_source_asset_is_still_not_an_ingress(db_session) -> None:
    """The legacy fallback is the bare ``type: "source"`` literal only.

    A dotted ``source.*`` type is a sub-discriminator of an explicit ``kind``;
    widening the fallback to the prefix would promote declarative assets to
    externally invokable ingresses.
    """

    contract = compile_execution_contract(
        db_session,
        flow={
            "nodes": [
                {"id": "knowledge.asset", "type": "source.collection"},
                {"id": "feeds", "type": "source"},
            ],
            "edges": [],
        },
        workspace_id="workspace-contract",
        runtime_mode="sequential_legacy",
    )

    assert [item["ingress_id"] for item in contract["ingresses"]] == ["feeds"]


@pytest.mark.parametrize(
    ("nodes", "edges", "code"),
    [
        (
            [
                {
                    "id": "webhook",
                    "kind": "source",
                    "type": "source.webhook",
                    "config": {"ingress_kind": "htp"},
                }
            ],
            [],
            "ingress_kind_invalid",
        ),
        (
            # The legacy dialect reaches the same root-only rule as the
            # canonical one, rather than silently compiling no ingress.
            [
                {"id": "upstream", "type": "source"},
                {"id": "nested", "type": "source"},
            ],
            [{"from": "upstream", "to": "nested"}],
            "ingress_source_not_root",
        ),
        (
            [
                {"id": "upstream", "kind": "source"},
                {"id": "nested", "kind": "source"},
            ],
            [{"from": "upstream", "to": "nested"}],
            "ingress_source_not_root",
        ),
    ],
)
def test_compile_rejects_ingress_that_cannot_be_selected_safely(
    db_session,
    nodes,
    edges,
    code,
) -> None:
    with pytest.raises(FlowContractError) as exc_info:
        compile_execution_contract(
            db_session,
            flow={"nodes": nodes, "edges": edges},
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
        )

    assert exc_info.value.code == code


def test_compile_rejects_disagreeing_skill_id_and_slug(db_session) -> None:
    first = Skill(
        id="skill-contract-first",
        workspace_id=None,
        slug="contract-first",
        version="1",
        name="First",
        input_schema={},
        output_schema={},
        execution={},
    )
    second = Skill(
        id="skill-contract-second",
        workspace_id=None,
        slug="contract-second",
        version="1",
        name="Second",
        input_schema={},
        output_schema={},
        execution={},
    )
    db_session.add_all([first, second])
    db_session.commit()

    with pytest.raises(FlowContractError) as exc_info:
        compile_execution_contract(
            db_session,
            flow={
                "nodes": [
                    {
                        "id": "task",
                        "kind": "task",
                        "config": {
                            "skill_id": first.id,
                            "skill_slug": second.slug,
                        },
                    }
                ]
            },
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
        )
    assert exc_info.value.code == "skill_contract_mismatch"


def test_compile_missing_skill_fails_closed(db_session) -> None:
    with pytest.raises(FlowContractError) as exc_info:
        compile_execution_contract(
            db_session,
            flow={
                "nodes": [
                    {
                        "id": "task",
                        "kind": "task",
                        "config": {"skill_slug": "missing-skill"},
                    }
                ]
            },
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
        )
    assert exc_info.value.code == "skill_contract_missing"


@pytest.mark.parametrize(
    "binding",
    [
        {"config": {"skill": {"slug": "legacy-contract-skill"}}},
        {"data": {"bound_skill_slug": "legacy-contract-skill"}},
        {"data": {"skill_slug": "legacy-contract-skill"}},
    ],
)
def test_compile_resolves_legacy_skill_slug_locations(db_session, binding) -> None:
    skill = Skill(
        id="skill-legacy-contract",
        workspace_id=None,
        slug="legacy-contract-skill",
        version="3",
        name="Legacy contract skill",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        execution={},
    )
    db_session.add(skill)
    db_session.commit()

    contract = compile_execution_contract(
        db_session,
        flow={"nodes": [{"id": "task", "kind": "task", **binding}]},
        workspace_id="workspace-contract",
        runtime_mode="dag_strict",
        allowed_skill_ids={skill.id},
    )

    assert contract["nodes"]["task"]["skill_id"] == skill.id
    assert contract["nodes"]["task"]["skill_slug"] == skill.slug


def test_compile_applies_system_allowlist_to_data_only_binding(db_session) -> None:
    skill = Skill(
        id="skill-data-only-contract",
        workspace_id=None,
        slug="data-only-contract-skill",
        version="1",
        name="Data-only contract skill",
        input_schema={},
        output_schema={},
        execution={},
    )
    db_session.add(skill)
    db_session.commit()

    with pytest.raises(FlowContractError) as exc_info:
        compile_execution_contract(
            db_session,
            flow={
                "nodes": [
                    {
                        "id": "task",
                        "kind": "task",
                        "data": {"bound_skill_slug": skill.slug},
                    }
                ]
            },
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
            allowed_skill_ids=set(),
        )

    assert exc_info.value.code == "skill_not_bound_to_system"


def test_compile_rejects_skill_id_without_slug() -> None:
    with pytest.raises(FlowContractError) as exc_info:
        compile_execution_contract(
            object(),
            flow={
                "nodes": [
                    {
                        "id": "task",
                        "kind": "task",
                        "config": {"skill_id": "skill-id-only"},
                    }
                ]
            },
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
        )

    assert exc_info.value.code == "skill_slug_required"


def test_compile_rejects_conflicting_skill_slug_locations() -> None:
    with pytest.raises(FlowContractError) as exc_info:
        compile_execution_contract(
            object(),
            flow={
                "nodes": [
                    {
                        "id": "task",
                        "kind": "task",
                        "config": {"skill_slug": "first"},
                        "data": {"bound_skill_slug": "second"},
                    }
                ]
            },
            workspace_id="workspace-contract",
            runtime_mode="dag_strict",
        )

    assert exc_info.value.code == "skill_binding_conflict"


def _authored_schema_flow(node_kind: str, config_extra: dict) -> dict:
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "manual",
                "kind": "source",
                "type": "source",
                "outputs": [{"name": "query", "schema": "string", "required": True}],
            },
            {
                "id": "task",
                "kind": node_kind,
                "config": {"skill_slug": "contract-skill", **config_extra},
            },
            {
                "id": "result",
                "kind": "sink",
                "inputs": [{"name": "answer", "schema": "string", "required": True}],
            },
        ],
        "edges": [
            {"from": "manual", "to": "task", "kind": "data"},
            {"from": "task", "to": "result", "kind": "data"},
        ],
    }


def _contract_skill(db_session) -> Skill:
    skill = Skill(
        id="skill-authored",
        workspace_id=None,
        slug="contract-skill",
        version="7",
        name="Contract skill",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )
    db_session.add(skill)
    db_session.commit()
    return skill


def test_authored_node_output_schema_overrides_the_mutable_catalogue(db_session) -> None:
    """The Flow, not the Skill row, decides what a node is allowed to publish.

    A prose "answer in JSON" prompt is unenforceable; an authored schema is the
    surface that makes a malformed answer fail at its own node instead of at
    whatever reads it next.
    """

    _contract_skill(db_session)
    authored = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "line_manager_approved": {"type": "boolean"},
        },
        "required": ["answer", "line_manager_approved"],
        "additionalProperties": False,
    }

    contract = compile_execution_contract(
        db_session,
        flow=_authored_schema_flow("task", {"output_schema": authored}),
        workspace_id="workspace-authored",
        runtime_mode="dag_strict",
    )

    node = contract["nodes"]["task"]
    assert node["output_schema"]["required"] == ["answer", "line_manager_approved"]
    assert node["output_schema_sha256"] != canonical_sha256(
        {"type": "object", "properties": {"answer": {"type": "string"}}}
    )
    assert validate_execution_contract(contract) == contract


@pytest.mark.parametrize("node_kind", ["retry", "loop"])
def test_a_control_envelope_output_schema_cannot_be_authored(db_session, node_kind) -> None:
    """Retry and Loop publish an adapter envelope, not the Skill's own output,
    so an authored schema would describe a payload the node never emits."""

    _contract_skill(db_session)

    with pytest.raises(FlowContractError) as rejected:
        compile_execution_contract(
            db_session,
            flow=_authored_schema_flow(
                node_kind,
                {
                    "max_attempts": 2,
                    "max_iterations": 2,
                    "output_schema": {"type": "object"},
                },
            ),
            workspace_id="workspace-authored",
            runtime_mode="dag_strict",
        )

    assert rejected.value.code == "node_output_schema_not_overridable"
    assert rejected.value.path == "nodes/task/config/output_schema"


def test_agent_loop_compiled_contract_can_be_read_after_publication(db_session):
    planner = Skill(
        id="loop-planner-contract", workspace_id=None, slug="decide_next_v1",
        version="1", name="Planner", input_schema={"type": "object"},
        output_schema={"type": "object"}, execution={},
    )
    db_session.add(planner)
    db_session.commit()
    contract = compile_execution_contract(
        db_session, workspace_id="workspace-contract", runtime_mode="dag_overlay",
        flow={"nodes": [{"id": "investigate", "kind": "agent_loop", "config": {
            "skill_slug": planner.slug, "skill_allowlist": ["read_notices", "read_history"],
        }}], "edges": []},
    )
    assert validate_execution_contract(contract) == contract
    assert contract["nodes"]["investigate"]["skill_allowlist"] == ["read_notices", "read_history"]
    for invalid in (None, "read_notices", [], [""], [3], [" padded "], ["tool"] * 9):
        contract["nodes"]["investigate"]["skill_allowlist"] = invalid
        _rehash_execution_contract(contract)
        with pytest.raises(FlowContractError) as exc:
            validate_execution_contract(contract)
        assert exc.value.path == "/nodes/investigate/skill_allowlist"
