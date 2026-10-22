"""Native authorities behind the optional Temporal candidate.

Every Activity reconstructs context from the persisted, authorized Run. Temporal
receives identifiers/status only. A Skill ledger row is committed before effects;
an uncertain attempt is observed or reconciled, never automatically invoked again.
"""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from .native_profile import COMPOSITIONS, request_for_run


class NativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: str = Field(min_length=1, max_length=36)
    run_id: str = Field(min_length=1, max_length=36)
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_revision: str = Field(min_length=1, max_length=80)


def invocation_id(run, node_id):
    return str(
        uuid5(
            NAMESPACE_URL,
            f"agentium-native:v1:{run.workspace_id}:{run.id}:{run.execution_policy['native_profile_digest']}:{node_id}:1",
        )
    )


def authorize(db, request, *, allow_terminal=False, enforce_revision=True):
    from app.api.v1.endpoints.systems import _enforce_system_run_authority
    from app.core.config import settings
    from app.models.run import Run
    from app.models.system import System
    from app.models.system_version import SystemVersion
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.activity_observability.queries import require_membership
    from app.services.execution.contracts import ExecutionPolicy
    from app.services.run_engine import engine
    from app.services.run_engine.dag import DagGraph, validate_graph_skill_bindings
    from app.services.system_catalog_bindings import resolve_run_system_catalog_bindings

    value = NativeRequest.model_validate(request).model_dump()
    run = db.get(Run, value["run_id"], populate_existing=True)
    if run is None or run.workspace_id != value["workspace_id"]:
        raise ValueError("NATIVE_RUN_SCOPE_MISMATCH")
    if request_for_run(db, run) != value:
        raise ValueError("NATIVE_REQUEST_MISMATCH")
    policy = ExecutionPolicy.model_validate(run.execution_policy)
    if enforce_revision and policy.runtime_revision != settings.agentium_image_revision:
        raise ValueError("EXECUTION_VERSION_UNAVAILABLE")
    if run.cancel_requested or run.status in {"cancelled", "failed"}:
        raise ValueError("EXECUTION_CANCELLED")
    if not allow_terminal and (run.status == "completed" or policy.remaining_seconds() <= 0):
        raise ValueError("EXECUTION_DEADLINE_OR_TERMINAL")
    workspace = db.get(Workspace, run.workspace_id, populate_existing=True)
    actor = (
        db.get(User, run.initiated_by_user_id, populate_existing=True)
        if run.initiated_by_user_id
        else None
    )
    require_membership(db, workspace, actor)
    system = db.get(System, run.system_id, populate_existing=True)
    version = db.get(SystemVersion, run.published_flow_version_id, populate_existing=True)
    if (
        system is None
        or system.workspace_id != run.workspace_id
        or version is None
        or version.system_id != system.id
    ):
        raise ValueError("NATIVE_SYSTEM_VERSION_MISMATCH")
    if version.flow_sha256 != run.flow_sha256:
        raise ValueError("NATIVE_SYSTEM_VERSION_MISMATCH")
    _enforce_system_run_authority(
        db,
        user=actor,
        workspace=workspace,
        system=system,
        execution_source="native_temporal",
        execution_contract=run.execution_contract,
        flow_snapshot=run.flow_snapshot,
    )
    bindings = resolve_run_system_catalog_bindings(db, workspace=workspace, system=system, run=run)
    graph = DagGraph.from_flow_definition(run.flow_snapshot)
    graph.strict_authoritative = run.execution_contract.get("runtime_mode") == "dag_strict"
    validate_graph_skill_bindings(graph, bindings)
    control = engine._load_control_policy(db, system, run=run)
    if not engine._evaluate_run_capability(control, system, db=db, run=run).allowed:
        raise ValueError("NATIVE_MEMBRANE_BLOCKED")
    if engine._runtime_valves_blocked(db, run, control):
        raise ValueError("NATIVE_RUNTIME_VALVE_BLOCKED")
    return run, system, bindings, graph, control


def _window(db, run):
    from app.models.service_contract import ServiceAttempt
    from app.services.service_engine import window_for_run

    window = window_for_run(db, run.id, run.workspace_id)
    if window is None or window.system_id != run.system_id:
        raise ValueError("NATIVE_SERVICE_WINDOW_REQUIRED")
    attempt = (
        db.query(ServiceAttempt)
        .filter_by(
            workspace_id=run.workspace_id, window_id=window.id, run_id=run.id, fence=window.fence
        )
        .first()
    )
    if attempt is None or attempt.lease_token != window.lease_token:
        raise ValueError("NATIVE_SERVICE_ATTEMPT_REPLACED")
    if window.status not in {"running", "awaiting_review", "delivered"}:
        raise ValueError("NATIVE_SERVICE_WINDOW_CLOSED")
    return window, attempt


def _reference(kind, identifier, status):
    return {"reference": {"kind": kind, "id": identifier}, "status": status}


def _outputs(db, run, profile, graph, *, before):
    from app.models.run import SkillInvocation
    from app.services.run_engine.variable_pool import VariablePool, apply_outputs_map

    pool = VariablePool(
        {"input": run.input_ref or {}, "ctx": {}, "node": {}, "sys": {"run_id": run.id}}
    )
    outputs = {
        key: dict(run.input_ref or {}) for key, node in graph.nodes.items() if node.kind == "source"
    }
    for key, output in outputs.items():
        pool.set_namespace(key, output)
    for role in COMPOSITIONS[profile["composition"]]:
        if role == before or role in {"review", "delivery"}:
            break
        node_id = profile["role_nodes"][role]
        inv = db.get(SkillInvocation, invocation_id(run, node_id), populate_existing=True)
        if not inv or inv.status != "completed":
            raise ValueError("NATIVE_PREDECESSOR_INCOMPLETE")
        output = inv.output_ref
        if not isinstance(output, dict):
            raise ValueError("NATIVE_OBJECT_OUTPUT_REQUIRED")
        outputs[node_id] = output
        pool.set_namespace(node_id, output)
        apply_outputs_map(graph.nodes[node_id].config, output, pool)
    return outputs, pool


def _inputs(db, run, profile, graph, role):
    from app.services.flow_contracts import validate_payload
    from app.services.run_engine.dag import (
        _GRAPH_OWNED_BLOCKS,
        WalkerState,
        _apply_graph_owned_config,
        _apply_retrieval_node_scope,
        _merge_predecessor_outputs,
        _without_secret_values,
    )
    from app.services.run_engine.variable_pool import apply_inputs_map

    outputs, pool = _outputs(db, run, profile, graph, before=role)
    node = graph.nodes[profile["role_nodes"][role]]
    merged = _merge_predecessor_outputs(graph, WalkerState(node_outputs=outputs), node.id)
    value = apply_inputs_map(
        node.config, pool, merged, io_mode="strict" if graph.strict_authoritative else "overlay"
    )
    if graph.strict_authoritative:
        for key, item in _without_secret_values(node.config.get("params") or {}).items():
            value.setdefault(key, item)
    _apply_retrieval_node_scope(node, value)
    for key, slugs, params in _GRAPH_OWNED_BLOCKS:
        _apply_graph_owned_config(node, value, key=key, slugs=slugs, param_keys=params)
    if node.skill_slug == "data_prep_v1":
        config = value["_data_prep"]["data_prep"]
        pins = dict(config.get("inputs") or {})
        for edge in graph.in_edges[node.id]:
            if edge.kind != "data":
                continue
            upstream = outputs.get(edge.source, {})
            if "outputs" in upstream:
                options = upstream["outputs"]
                port = edge.from_port or (next(iter(options)) if len(options) == 1 else None)
                upstream = options.get(port)
            if not isinstance(upstream, dict) or not upstream.get("dataset_id"):
                # An agent may produce a plan while the graph pins data inputs.
                if pins:
                    continue
                raise ValueError("DATAPREP_DATASET_REQUIRED")
            port = edge.to_port or "in"
            if port in pins and pins[port].get("dataset_id") != upstream.get("dataset_id"):
                raise ValueError("DATAPREP_INPUT_PORT_DUPLICATE")
            pins[port] = upstream
        value["_data_prep"]["inputs"] = pins
    contract = run.execution_contract["nodes"][node.id]
    validate_payload(
        value, contract["input_schema"], code="node_input_invalid", subject="Native node input"
    )
    return value


def begin(db, request):
    run, system, _, _, control = authorize(db, request)
    from app.models.run import Run

    run = db.query(Run).filter_by(id=run.id).with_for_update().populate_existing().one()
    authorize(db, request)
    _window(db, run)
    if run.status == "pending":
        from app.services.run_engine.engine import _snapshot_run_flow

        _snapshot_run_flow(db, run, system, first_start=True, control=control)
        run.status = "running"
        run.checkpoints = [
            *(run.checkpoints or []),
            {
                "kind": "native_start",
                "profile_digest": request["profile_digest"],
                "runtime_revision": request["runtime_revision"],
            },
        ]
        db.commit()
    profile = run.execution_policy["native_profile"]
    return {
        "roles": list(COMPOSITIONS[profile["composition"]]),
        "poll_interval_s": profile["poll_interval_s"],
    }


async def submit(db, request, role):
    from app.services.run_engine import engine

    run, system, bindings, graph, control = authorize(db, request)
    profile = run.execution_policy["native_profile"]
    if role not in COMPOSITIONS[profile["composition"]]:
        raise ValueError("NATIVE_ROLE_UNKNOWN")
    if role == "review":
        return prepare_review(db, run, profile, graph)
    if role == "delivery":
        return deliver(db, run)
    value = _inputs(db, run, profile, graph, role)
    node = graph.nodes[profile["role_nodes"][role]]
    ctx = engine._build_initial_ctx(db, run, system, bindings.capability)
    engine._attach_authoritative_membrane(ctx, control)
    import asyncio

    from app.services.execution.contracts import ExecutionPolicy

    invocation = await asyncio.wait_for(
        engine._execute_task_node(
            db,
            run,
            ctx,
            node.skill_slug,
            control=control,
            last_output=value,
            resolved_input=value,
            node_id=node.id,
            attempt_kind="native",
            attempt_index=1,
            native_invocation_id=invocation_id(run, node.id),
        ),
        timeout=min(290, ExecutionPolicy.model_validate(run.execution_policy).remaining_seconds()),
    )
    if invocation is None:
        raise ValueError("NATIVE_SKILL_BLOCKED")
    return _observe_invocation(db, run, invocation, node.id)


def _observe_invocation(db, run, invocation, node_id):
    from app.models.recipe import RecipeExecution
    from app.models.run import Run, SkillInvocation
    from app.services.run_engine.run_contracts import validate_node_output

    # Serialize final publication with cancellation/unknown settlement, then
    # re-read actor and contract authority in that same native transaction.
    run = db.query(Run).filter_by(id=run.id).with_for_update().populate_existing().one()
    authorize(db, request_for_run(db, run))
    invocation = (
        db.query(SkillInvocation)
        .filter_by(id=invocation.id, run_id=run.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if invocation.status == "waiting":
        reference = (invocation.trace or {}).get("native_reference") or {}
        if reference.get("kind") != "recipe_execution":
            raise ValueError("NATIVE_CHILD_KIND_UNSUPPORTED")
        child = db.get(RecipeExecution, reference.get("id"), populate_existing=True)
        if child is None or (child.workspace_id, child.run_id, child.node_id) != (
            run.workspace_id,
            run.id,
            node_id,
        ):
            raise ValueError("NATIVE_CHILD_LINEAGE_MISMATCH")
        if child.status == "succeeded":
            invocation.output_ref = child.output_json
            invocation.status, invocation.completed_at = "completed", datetime.utcnow()
            invocation.trace = {
                **invocation.trace,
                "native_receipt": {"kind": "recipe_execution", "id": child.id},
            }
        elif child.status in {"failed", "cancelled", "timed_out", "lost"}:
            invocation.status, invocation.error = "failed", "NATIVE_COMPUTE_FAILED"
            invocation.completed_at = datetime.utcnow()
        else:
            return _reference("skill_invocation", invocation.id, "waiting")
    if invocation.status == "completed":
        violation = validate_node_output(run, node_id=node_id, payload=invocation.output_ref)
        if violation:
            invocation.status, invocation.error = "failed", violation.terminal_error()
    db.commit()
    status = {"completed": "succeeded", "running": "running", "waiting": "waiting"}.get(
        invocation.status, "failed"
    )
    return _reference("skill_invocation", invocation.id, status)


def prepare_review(db, run, profile, graph):
    from app.models.run import Run
    from app.services import service_promises as promises
    from app.services.governed_assets import asset_ref, current_qualification, record_qualification
    from app.services.service_engine import _dataset_asset

    run = db.query(Run).filter_by(id=run.id).with_for_update().populate_existing().one()
    authorize(db, request_for_run(db, run))
    outputs, _ = _outputs(db, run, profile, graph, before="review")
    window, attempt = _window(db, run)
    if window.status == "running":
        # One native transaction contains candidate registration and the window
        # transition. A retry observes the same candidate instead of copying it.
        window = promises.get_window(db, run.workspace_id, window.id, lock=True)
        if window.status == "running":
            output = outputs[profile["role_nodes"][profile["output_role"]]]
            if profile.get("output_port") is not None:
                output = (output.get("outputs") or {}).get(profile["output_port"])
                if not isinstance(output, dict):
                    raise ValueError("NATIVE_OUTPUT_PORT_UNAVAILABLE")
            elif "outputs" in output:
                if len(output["outputs"]) != 1:
                    raise ValueError("NATIVE_OUTPUT_PORT_REQUIRED")
                output = next(iter(output["outputs"].values()))
            run.output_ref = output
            candidate = _dataset_asset(db, window, run)
            if current_qualification(db, run.workspace_id, candidate.id) is None:
                record_qualification(
                    db,
                    run.workspace_id,
                    asset_ref(candidate),
                    status="review_required",
                    policy={
                        "authority": "service_producer",
                        "contract_digest": promises.get_contract(
                            db, run.workspace_id, window.contract_id
                        ).digest,
                    },
                    evidence={
                        "run_id": run.id,
                        "technical_status": "completed",
                        "human_required": True,
                    },
                )
            from app.services.window_budget import summary

            budget = summary(db, run.workspace_id, window.id, run_id=run.id)
            if budget and (budget.get("over_budget") or budget.get("measurement_conflict")):
                raise ValueError("NATIVE_SERVICE_BUDGET_EXCEEDED")
            cost, tokens = _provider_totals(db, run, profile)
            run.provider_cost_usd = cost
            promises.complete_attempt(
                db,
                run.workspace_id,
                window.id,
                fence=attempt.fence,
                lease_token=attempt.lease_token,
                candidate_ref=asset_ref(candidate),
                cost=cost,
                tokens=tokens,
                seconds=(datetime.utcnow() - run.started_at).total_seconds(),
            )
            run.status = "hitl_pending"
            run.checkpoints = [
                *(run.checkpoints or []),
                {
                    "kind": "native_service_review",
                    "node_id": profile["role_nodes"]["review"],
                    "window_id": window.id,
                    "fence": window.fence,
                    "candidate_ref": window.candidate_ref,
                    "profile_digest": run.execution_policy["native_profile_digest"],
                },
            ]
            db.commit()
    _validate_review_binding(run, window)
    return _reference("service_window", window.id, "waiting")


def _provider_totals(db, run, profile):
    """A judge subtotal is not complete measurement of every agent call."""
    from app.models.run import SkillInvocation
    from app.services.membrane.enforcement import token_measurement_from_payload

    rows = [
        db.get(SkillInvocation, invocation_id(run, profile["role_nodes"][role]))
        for role in COMPOSITIONS[profile["composition"]]
        if role not in {"data_prepare", "review", "delivery"}
    ]
    cost = (
        sum(row.provider_cost_usd for row in rows)
        if rows
        and all(
            row and row.cost_measured is True and row.provider_cost_usd is not None for row in rows
        )
        else None
    )
    tokens = [
        token_measurement_from_payload(row.metrics or {}) if row else (0, False) for row in rows
    ]
    return cost, sum(value for value, _ in tokens) if tokens and all(
        reported for _, reported in tokens
    ) else None


def _validate_review_binding(run, window):
    if not any(
        item.get("kind") == "native_service_review"
        and item.get("window_id") == window.id
        and item.get("fence") == window.fence
        and item.get("candidate_ref") == window.candidate_ref
        and item.get("profile_digest") == run.execution_policy["native_profile_digest"]
        for item in run.checkpoints or []
    ):
        raise ValueError("NATIVE_REVIEW_BINDING_CHANGED")


def _review_decision(db, run, window):
    from app.models.decision import Decision

    # A human-created service decision carries exact asset/qualification binding.
    # Signals and generic HITL approvals are not delivery authority.
    rows = (
        db.query(Decision)
        .filter_by(
            workspace_id=run.workspace_id,
            scope="system",
            target_id=run.system_id,
            kind="service_delivery",
            status="accepted",
        )
        .order_by(Decision.created_at.desc())
        .all()
    )
    from app.services.service_promises import _delivery_facts

    try:
        *_, binding = _delivery_facts(db, window)
    except Exception:
        return None
    return next(
        (
            row
            for row in rows
            if (row.rationale or {}).get("window_id") == window.id
            and (row.rationale or {}).get("binding_digest") == binding
        ),
        None,
    )


def observe(db, request, role):
    from app.models.run import SkillInvocation

    run, _, _, graph, _ = authorize(db, request)
    profile = run.execution_policy["native_profile"]
    node_id = profile["role_nodes"].get(role)
    if not node_id:
        raise ValueError("NATIVE_ROLE_UNKNOWN")
    if role == "review":
        window, _ = _window(db, run)
        _validate_review_binding(run, window)
        decision = _review_decision(db, run, window)
        return (
            _reference("decision", decision.id, "succeeded")
            if decision
            else _reference("service_window", window.id, "waiting")
        )
    if role == "delivery":
        return deliver(db, run)
    row = db.get(SkillInvocation, invocation_id(run, node_id), populate_existing=True)
    if row is None:
        raise ValueError("NATIVE_INVOCATION_MISSING")
    return _observe_invocation(db, run, row, node_id)


def deliver(db, run):
    from app.models.run import Run
    from app.services.service_promises import publish_delivery

    run = db.query(Run).filter_by(id=run.id).with_for_update().populate_existing().one()
    _, _, _, graph, _ = authorize(db, request_for_run(db, run))
    _outputs(db, run, run.execution_policy["native_profile"], graph, before="delivery")
    window, attempt = _window(db, run)
    _validate_review_binding(run, window)
    decision = _review_decision(db, run, window)
    if decision is None:
        raise ValueError("NATIVE_DELIVERY_DECISION_REQUIRED")
    receipt = publish_delivery(
        db,
        run.workspace_id,
        window.id,
        decision_id=decision.id,
        fence=attempt.fence,
        lease_token=attempt.lease_token,
    )
    run.status, run.completed_at = "completed", datetime.utcnow()
    run.output_ref = {**(run.output_ref or {}), "delivery_receipt_id": receipt.id}
    run.duration_ms = (run.completed_at - run.started_at).total_seconds() * 1000
    db.commit()
    return _reference("delivery_receipt", receipt.id, "succeeded")


def uncertain(db, request, role):
    """An Activity timeout is not proof an external provider did nothing."""
    from app.models.run import Run, SkillInvocation

    run, _, _, _, _ = authorize(db, request, allow_terminal=True)
    run = db.query(Run).filter_by(id=run.id).with_for_update().populate_existing().one()
    if role == "delivery" and run.status == "completed":
        from app.models.service_contract import DeliveryReceipt

        window, _ = _window(db, run)
        receipt = (
            db.query(DeliveryReceipt)
            .filter_by(
                window_id=window.id,
                workspace_id=run.workspace_id,
                id=(run.output_ref or {}).get("delivery_receipt_id"),
            )
            .first()
        )
        if receipt:
            return _reference("delivery_receipt", receipt.id, "succeeded")
    if role == "review":
        window, _ = _window(db, run)
        if window.status == "awaiting_review":
            _validate_review_binding(run, window)
            return _reference("service_window", window.id, "waiting")
    node_id = run.execution_policy["native_profile"]["role_nodes"].get(role)
    row = (
        db.query(SkillInvocation)
        .filter_by(id=invocation_id(run, node_id))
        .with_for_update()
        .populate_existing()
        .first()
        if node_id
        else None
    )
    if row and row.status in {"completed", "waiting"}:
        return _observe_invocation(db, run, row, node_id)
    from app.services.execution.control import request_run_cancel

    request_run_cancel(db, run, commit=False)
    if row:
        row.status, row.error, row.completed_at = (
            "lost",
            "NATIVE_OUTCOME_REQUIRES_RECONCILIATION",
            datetime.utcnow(),
        )
    run.status, run.error, run.completed_at = (
        "failed",
        "NATIVE_OUTCOME_REQUIRES_RECONCILIATION",
        datetime.utcnow(),
    )
    db.commit()
    return _reference("run", run.id, "failed")


def fail(db, request):
    """Close a failed/cancelled Workflow without copying sensitive exceptions."""
    from app.models.run import Run

    value = NativeRequest.model_validate(request)
    run = (
        db.query(Run)
        .filter_by(id=value.run_id, workspace_id=value.workspace_id)
        .with_for_update()
        .first()
    )
    if run is None or request_for_run(db, run) != value.model_dump():
        raise ValueError("NATIVE_REQUEST_MISMATCH")
    settle_failed_run(db, run, error_code="NATIVE_WORKFLOW_STOPPED")
    db.commit()
    return _reference("run", run.id, "succeeded" if run.status == "completed" else "failed")


def settle_failed_run(db, run, *, error_code="NATIVE_OUTCOME_REQUIRES_RECONCILIATION"):
    """Metadata-only drain for an older image/closed Workflow, no effect replay.

    The caller commits. Native children keep their own physical stop evidence;
    the invocation ledger merely records that its caller no longer owns it.
    """
    from app.models.run import Run, SkillInvocation
    from app.services.execution.control import request_run_cancel

    run = (
        db.query(Run)
        .filter_by(id=run.id, workspace_id=run.workspace_id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if run.status == "completed":
        return run
    was_terminal = run.status in {"failed", "cancelled"}
    invocations = (
        db.query(SkillInvocation)
        .filter_by(run_id=run.id)
        .filter(SkillInvocation.status.in_(["running", "waiting"]))
        .order_by(SkillInvocation.id)
        .with_for_update()
        .populate_existing()
        .all()
    )
    request_run_cancel(db, run, commit=False)
    for row in invocations:
        if not (row.trace or {}).get("native_binding"):
            continue
        row.status = "lost" if row.status == "running" else "cancelled"
        row.error, row.completed_at = error_code, datetime.utcnow()
    if not was_terminal:
        run.status, run.error, run.completed_at = "failed", error_code, datetime.utcnow()
    return run
