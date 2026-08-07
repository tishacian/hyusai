"""Builder-only execution surfaces for unsaved previews and focused tests.

These Runs are durable audit evidence, but the submitted graph is never written
to ``System.flow_definition``, ``SystemFlowDraft`` or ``SystemVersion``. The
three workbench surfaces remain distinct from ``draft_test`` and every published
ingress so relaxing authoring UX cannot weaken production execution authority.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.system import System
from app.services.audit_logger import emit_audit_event
from app.services.chains import dag_validator
from app.services.flow_skill_binding import (
    FlowSkillBindingError,
    resolve_flow_skill_binding,
)
from app.services.run_engine.debug_contract import (
    DebugContractError,
    normalize_input_debug,
)
from app.services.run_engine.execution_contract import (
    WORKBENCH_EXECUTION_SURFACES,
    canonical_flow,
    canonical_flow_sha256,
    resolve_flow_execution,
)
from app.services.run_engine.run_contracts import (
    RuntimeContractError,
    validate_ingress_payload,
)
from app.services.systems import flow_publication

MAX_FLOW_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 256 * 1024
MAX_GOLDEN_CASES = 20
MAX_GOLDEN_EXPECTED_BYTES = 64 * 1024
FEATURE_KEY = "flow_workbench_v1"


@dataclass(frozen=True, slots=True)
class FlowWorkbenchError(ValueError):
    code: str
    message: str
    status_code: int = 422
    details: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "error": self.code.lower(),
            "code": self.code,
            "message": self.message,
            **copy.deepcopy(self.details or {}),
        }


@dataclass(frozen=True, slots=True)
class PreparedPreview:
    system: System
    flow: dict[str, Any]
    flow_sha256: str
    source_flow_sha256: str
    contract: dict[str, Any]
    runtime_reason: str
    ingress: Mapping[str, Any] | None


def _json_size(value: Any, *, code: str, limit: int) -> None:
    try:
        size = len(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise FlowWorkbenchError(code, "Workbench payload must be JSON serialisable.") from exc
    if size > limit:
        raise FlowWorkbenchError(
            code,
            f"Workbench payload exceeds the {limit}-byte limit.",
            413,
            {"limit_bytes": limit, "actual_bytes": size},
        )


def _translate_publication(exc: flow_publication.FlowPublicationError) -> FlowWorkbenchError:
    return FlowWorkbenchError(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=copy.deepcopy(exc.details),
    )


def flow_workbench_enabled(workspace: Any) -> bool:
    settings = getattr(workspace, "settings", None)
    features = settings.get("features") if isinstance(settings, Mapping) else None
    return bool(isinstance(features, Mapping) and features.get(FEATURE_KEY) is True)


def require_flow_workbench(workspace: Any) -> None:
    if not flow_workbench_enabled(workspace):
        raise FlowWorkbenchError(
            code="FLOW_WORKBENCH_DISABLED",
            message="Flow Workbench is not enabled for this workspace.",
            status_code=404,
            details={"feature": FEATURE_KEY},
        )
    try:
        flow_publication.require_flow_publication(workspace)
    except flow_publication.FlowPublicationError as exc:
        raise _translate_publication(exc) from exc


def _locked_system(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
) -> System:
    require_flow_workbench(workspace)
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .populate_existing()
        .with_for_update(of=System)
        .one_or_none()
    )
    if system is None:
        raise FlowWorkbenchError("SYSTEM_NOT_FOUND", "System not found.", 404)
    return system


def _canonical_request_flow(
    flow_definition: Mapping[str, Any],
    *,
    expected_flow_sha256: str,
    require_executable: bool,
) -> tuple[dict[str, Any], str]:
    _json_size(flow_definition, code="WORKBENCH_FLOW_TOO_LARGE", limit=MAX_FLOW_BYTES)
    shape_issues = dag_validator.validate_flow_shape(flow_definition)
    if shape_issues:
        raise FlowWorkbenchError(
            "WORKBENCH_FLOW_SHAPE_INVALID",
            "The local Flow has a malformed graph shape.",
            422,
            {"issues": dag_validator.issues_to_payload(shape_issues)},
        )
    flow = copy.deepcopy(canonical_flow(flow_definition))
    digest = canonical_flow_sha256(flow)
    if digest != expected_flow_sha256:
        raise FlowWorkbenchError(
            "WORKBENCH_FLOW_HASH_MISMATCH",
            "The local Flow changed after validation. Validate the current snapshot again.",
            409,
            {"expected_flow_sha256": expected_flow_sha256, "current_flow_sha256": digest},
        )
    if require_executable:
        issues = dag_validator.validate_flow(flow)
        if dag_validator.has_errors(issues):
            raise FlowWorkbenchError(
                "WORKBENCH_FLOW_VALIDATION_FAILED",
                "The local Flow has blocking diagnostics.",
                422,
                {"issues": dag_validator.issues_to_payload(issues)},
            )
    return flow, digest


def _select_ingress(
    contract: Mapping[str, Any],
    *,
    ingress_id: str | None,
    ingress_kind: str | None,
) -> Mapping[str, Any] | None:
    if (ingress_id is None) != (ingress_kind is None):
        raise FlowWorkbenchError(
            "WORKBENCH_INGRESS_INCOMPLETE",
            "ingress_id and kind must be supplied together.",
        )
    raw = contract.get("ingresses")
    ingresses = [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []
    if ingress_id is not None and ingress_kind is not None:
        matches = [
            item
            for item in ingresses
            if item.get("ingress_id") == ingress_id and item.get("kind") == ingress_kind
        ]
        if len(matches) != 1:
            raise FlowWorkbenchError(
                "WORKBENCH_INGRESS_NOT_FOUND",
                "The requested ingress is not part of this local Flow contract.",
                422,
                {"ingress_id": ingress_id, "kind": ingress_kind},
            )
        return matches[0]
    if len(ingresses) == 1:
        return ingresses[0]
    if len(ingresses) > 1:
        raise FlowWorkbenchError(
            "WORKBENCH_INGRESS_AMBIGUOUS",
            "Choose exactly one local Flow ingress.",
            422,
            {
                "candidate_ingresses": sorted(
                    (
                        {
                            "ingress_id": str(item.get("ingress_id") or ""),
                            "kind": str(item.get("kind") or ""),
                        }
                        for item in ingresses
                    ),
                    key=lambda item: (item["kind"], item["ingress_id"]),
                )
            },
        )
    if contract.get("runtime_mode") != "sequential_legacy":
        raise FlowWorkbenchError(
            "WORKBENCH_INGRESS_REQUIRED",
            "An executable local DAG must expose one ingress.",
        )
    return None


def _compile(
    db: DBSession,
    *,
    flow: dict[str, Any],
    workspace: Any,
    system: System,
) -> tuple[dict[str, Any], str]:
    try:
        contract = flow_publication.compile_execution_contract(
            db,
            flow,
            workspace,
            system=system,
        )
    except flow_publication.FlowPublicationError as exc:
        raise _translate_publication(exc) from exc
    resolution = resolve_flow_execution(flow, workspace)
    return contract, resolution.reason


def prepare_preview(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    flow_definition: Mapping[str, Any],
    expected_flow_sha256: str,
    ingress_id: str | None,
    ingress_kind: str | None,
) -> PreparedPreview:
    system = _locked_system(db, system_id=system_id, workspace=workspace)
    flow, digest = _canonical_request_flow(
        flow_definition,
        expected_flow_sha256=expected_flow_sha256,
        require_executable=True,
    )
    contract, runtime_reason = _compile(db, flow=flow, workspace=workspace, system=system)
    if contract.get("runtime_mode") == "sequential_legacy":
        raise FlowWorkbenchError(
            "WORKBENCH_DAG_REQUIRED",
            "Flow Builder preview and golden execution require the DAG runtime.",
            409,
            {"runtime_mode": "sequential_legacy"},
        )
    ingress = _select_ingress(
        contract,
        ingress_id=ingress_id,
        ingress_kind=ingress_kind,
    )
    return PreparedPreview(
        system=system,
        flow=flow,
        flow_sha256=digest,
        source_flow_sha256=digest,
        contract=contract,
        runtime_reason=runtime_reason,
        ingress=ingress,
    )


def _accepted_input(
    prepared: PreparedPreview,
    *,
    surface: str,
    input_ref: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if surface not in WORKBENCH_EXECUTION_SURFACES:
        raise FlowWorkbenchError("WORKBENCH_SURFACE_INVALID", "Unknown workbench surface.")
    _json_size(input_ref, code="WORKBENCH_INPUT_TOO_LARGE", limit=MAX_INPUT_BYTES)
    try:
        accepted = normalize_input_debug(
            input_ref,
            runtime_mode=str(prepared.contract.get("runtime_mode") or ""),
        )
    except DebugContractError as exc:
        raise FlowWorkbenchError(
            exc.code,
            exc.message,
            422,
            {"path": exc.path},
        ) from exc
    # Both namespaces are reserved for evidence assembled from the compiled
    # contract below.  Remove caller-controlled values before validating the
    # business payload so they can neither forge evidence nor make an
    # otherwise valid ingress fail schema validation.
    accepted.pop("_ingress", None)
    accepted.pop("execution", None)
    selected = prepared.ingress
    if selected is not None:
        payload = {key: value for key, value in accepted.items() if key != "_debug"}
        try:
            validate_ingress_payload(
                prepared.contract,
                ingress_id=str(selected["ingress_id"]),
                kind=str(selected["kind"]),
                payload=payload,
            )
        except RuntimeContractError as exc:
            raise FlowWorkbenchError(
                exc.code.upper(),
                exc.message,
                422,
                {"path": exc.path} if exc.path else None,
            ) from exc
    # ``execution`` is a reserved, server-owned evidence namespace. Keeping
    # arbitrary caller fields here would let a preview manufacture misleading
    # system/version/case metadata which the worker otherwise preserves with
    # ``setdefault``. Business input belongs at the input_ref root; rebuild the
    # execution envelope from scratch for every workbench Run.
    execution: dict[str, Any] = {}
    execution.update(
        {
            "flow_sha256": prepared.flow_sha256,
            "source_flow_sha256": prepared.source_flow_sha256,
            "runtime_mode": prepared.contract["runtime_mode"],
            "runtime_mode_reason": prepared.runtime_reason,
            "execution_surface": surface,
            **copy.deepcopy(dict(metadata or {})),
            **(
                {
                    "ingress_id": selected["ingress_id"],
                    "ingress_selection_version": 1,
                }
                if selected is not None
                else {}
            ),
        }
    )
    accepted["execution"] = execution
    if selected is not None:
        accepted["_ingress"] = {
            "ingress_id": selected["ingress_id"],
            "source_node_id": selected["source_node_id"],
            "kind": selected["kind"],
            "adapter": {"surface": surface},
        }
    return accepted


def create_run(
    db: DBSession,
    *,
    prepared: PreparedPreview,
    workspace: Any,
    user_id: str | None,
    surface: str,
    input_ref: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    checkpoints: Sequence[Mapping[str, Any]] | None = None,
) -> Run:
    accepted = _accepted_input(
        prepared,
        surface=surface,
        input_ref=input_ref,
        metadata=metadata,
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=prepared.system.id,
        capability_id=prepared.system.capability_id,
        initiated_by_user_id=user_id,
        input_ref=accepted,
        flow_snapshot=copy.deepcopy(prepared.flow),
        flow_version_id=None,
        published_flow_version_id=None,
        flow_sha256=prepared.flow_sha256,
        execution_contract=copy.deepcopy(prepared.contract),
        execution_surface=surface,
        status="pending",
        started_at=datetime.utcnow(),
        trigger=surface,
        checkpoints=[copy.deepcopy(dict(item)) for item in checkpoints or []],
    )
    db.add(run)
    db.flush()
    emit_audit_event(
        workspace_id=workspace.id,
        event_type=f"flow.workbench.{surface}.queued",
        actor=user_id or "unknown",
        agent_id=prepared.system.id,
        details={
            "system_id": prepared.system.id,
            "run_id": run.id,
            "execution_surface": surface,
            "flow_sha256": prepared.flow_sha256,
            "source_flow_sha256": prepared.source_flow_sha256,
            **copy.deepcopy(dict(metadata or {})),
        },
        db=db,
    )
    return run


def _isolated_flow(
    source_flow: Mapping[str, Any],
    *,
    node_id: str,
    input_ref: Mapping[str, Any],
) -> dict[str, Any]:
    nodes = source_flow.get("nodes") if isinstance(source_flow.get("nodes"), list) else []
    matches = [node for node in nodes if isinstance(node, Mapping) and node.get("id") == node_id]
    if len(matches) != 1:
        raise FlowWorkbenchError(
            "WORKBENCH_NODE_NOT_FOUND",
            "The selected node is not uniquely present in the local Flow.",
            404,
            {"node_id": node_id},
        )
    target = copy.deepcopy(dict(matches[0]))
    if str(target.get("kind") or "task") != "task":
        raise FlowWorkbenchError(
            "WORKBENCH_NODE_KIND_UNSUPPORTED",
            "Only a Skill task can run in isolation.",
            422,
            {"node_id": node_id, "kind": target.get("kind")},
        )
    try:
        binding = resolve_flow_skill_binding(target)
    except FlowSkillBindingError as exc:
        raise FlowWorkbenchError(exc.code.upper(), exc.message, 422) from exc
    if not binding.skill_slug:
        raise FlowWorkbenchError(
            "WORKBENCH_NODE_SKILL_REQUIRED",
            "The selected node has no executable Skill binding.",
            422,
            {"node_id": node_id},
        )

    existing_ids = {
        str(node.get("id"))
        for node in nodes
        if isinstance(node, Mapping) and node.get("id") is not None
    }

    def fresh(base: str) -> str:
        candidate = base
        suffix = 1
        while candidate in existing_ids or candidate == node_id:
            suffix += 1
            candidate = f"{base}_{suffix}"
        existing_ids.add(candidate)
        return candidate

    source_id = fresh("__workbench_input__")
    sink_id = fresh("__workbench_output__")
    config = target.get("config") if isinstance(target.get("config"), Mapping) else {}
    mapped_keys = sorted(
        key
        for key in input_ref
        if isinstance(key, str) and key and not key.startswith("_") and key != "execution"
    )
    target["config"] = {
        **copy.deepcopy(dict(config)),
        "inputs_map": {
            key: {"node_id": "run", "path": [key], "required": True}
            for key in mapped_keys
        },
        "passthrough_inputs": [],
    }
    return {
        "source": "flow",
        "extended": True,
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": source_id,
                "type": "source",
                "kind": "source",
                "label": "Manual node input",
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
                "outputs": [],
            },
            target,
            {
                "id": sink_id,
                "type": "sink",
                "kind": "sink",
                "label": "Node result",
                "config": {"output_schema": {}},
                "inputs": [],
            },
        ],
        "edges": [
            {"from": source_id, "to": node_id, "kind": "data"},
            {"from": node_id, "to": sink_id, "kind": "data"},
        ],
    }


def prepare_node_preview(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    flow_definition: Mapping[str, Any],
    expected_flow_sha256: str,
    node_id: str,
    input_ref: Mapping[str, Any],
) -> PreparedPreview:
    system = _locked_system(db, system_id=system_id, workspace=workspace)
    source_flow, source_digest = _canonical_request_flow(
        flow_definition,
        expected_flow_sha256=expected_flow_sha256,
        require_executable=False,
    )
    isolated = _isolated_flow(source_flow, node_id=node_id, input_ref=input_ref)
    issues = dag_validator.validate_flow(isolated)
    if dag_validator.has_errors(issues):
        raise FlowWorkbenchError(
            "WORKBENCH_NODE_VALIDATION_FAILED",
            "The selected node cannot form a valid isolated execution graph.",
            422,
            {"node_id": node_id, "issues": dag_validator.issues_to_payload(issues)},
        )
    contract, runtime_reason = _compile(
        db,
        flow=isolated,
        workspace=workspace,
        system=system,
    )
    if contract.get("runtime_mode") == "sequential_legacy":
        raise FlowWorkbenchError(
            "WORKBENCH_NODE_DAG_REQUIRED",
            "Isolated node execution requires the DAG runtime for this workspace.",
            409,
            {"node_id": node_id, "runtime_mode": "sequential_legacy"},
        )
    ingress = _select_ingress(contract, ingress_id=None, ingress_kind=None)
    return PreparedPreview(
        system=system,
        flow=isolated,
        flow_sha256=canonical_flow_sha256(isolated),
        source_flow_sha256=source_digest,
        contract=contract,
        runtime_reason=runtime_reason,
        ingress=ingress,
    )


def validate_golden_cases(cases: Sequence[Mapping[str, Any]]) -> None:
    if not 1 <= len(cases) <= MAX_GOLDEN_CASES:
        raise FlowWorkbenchError(
            "WORKBENCH_GOLDEN_CASES_INVALID",
            f"A golden batch must contain between 1 and {MAX_GOLDEN_CASES} cases.",
        )
    seen: set[str] = set()
    for index, case in enumerate(cases):
        case_id = case.get("id")
        input_ref = case.get("input_ref")
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or case_id != case_id.strip()
            or len(case_id) > 160
            or case_id in seen
            or not isinstance(input_ref, Mapping)
        ):
            raise FlowWorkbenchError(
                "WORKBENCH_GOLDEN_CASE_INVALID",
                "Golden case ids must be unique, trimmed strings and input_ref must be an object.",
                422,
                {"case_index": index},
            )
        seen.add(case_id)
        _json_size(input_ref, code="WORKBENCH_INPUT_TOO_LARGE", limit=MAX_INPUT_BYTES)
        if "expected" in case:
            _json_size(
                case.get("expected"),
                code="WORKBENCH_GOLDEN_EXPECTED_TOO_LARGE",
                limit=MAX_GOLDEN_EXPECTED_BYTES,
            )
