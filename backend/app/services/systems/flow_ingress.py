"""Normalized, published-only ingress boundary for executable Flows."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.system import System
from app.services.flow_contracts import canonical_sha256
from app.services.run_engine.debug_contract import (
    DebugContractError,
    normalize_input_debug,
)
from app.services.run_engine.run_contracts import (
    RuntimeContractError,
    validate_ingress_payload,
)
from app.services.system_catalog_bindings import (
    SystemCatalogBindingError,
    resolve_persisted_system_catalog_bindings,
)
from app.services.systems import flow_publication


# Not frozen: exception propagation assigns ``__traceback__``.
@dataclass(slots=True)
class FlowIngressError(ValueError):
    code: str
    message: str
    status_code: int = 409
    details: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "error": self.code.lower(),
            "code": self.code,
            "message": self.message,
            **copy.deepcopy(self.details or {}),
        }


def _translate_publication(exc: flow_publication.FlowPublicationError) -> FlowIngressError:
    return FlowIngressError(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=copy.deepcopy(exc.details),
    )


def _published_evidence(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    require_active: bool,
    lock_system: bool,
) -> tuple[System, Any, dict[str, Any], str, dict[str, Any]]:
    try:
        flow_publication.require_flow_publication(workspace)
    except flow_publication.FlowPublicationError as exc:
        raise _translate_publication(exc) from exc
    query = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .populate_existing()
    )
    if lock_system:
        query = query.with_for_update(of=System)
    system = query.one_or_none()
    if system is None:
        raise FlowIngressError("SYSTEM_NOT_FOUND", "System not found.", 404)
    if require_active and system.status != "active":
        raise FlowIngressError(
            "FLOW_INGRESS_SYSTEM_INACTIVE",
            "Published ingresses accept Runs only while the System is active.",
            409,
            {"status": system.status},
        )
    try:
        flow_publication.assert_system_skills_ready(
            db,
            system=system,
            workspace=workspace,
        )
        version, flow, flow_sha256, contract = flow_publication.published_run_evidence(
            db,
            system=system,
            workspace=workspace,
        )
    except flow_publication.FlowPublicationError as exc:
        raise _translate_publication(exc) from exc
    return system, version, flow, flow_sha256, contract


def sequential_runtime_input_contract(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
    runtime_mode: str,
) -> dict[str, Any] | None:
    """Describe the payload consumed by the first legacy sequential Skill.

    A legacy sequential Flow walks the System's ordered Skill binding rather
    than task nodes in the visual graph.  Its published ingress schema can
    therefore be intentionally broad while the first Skill still requires a
    concrete field such as ``answer``.  Surface that effective boundary to
    operators and enforce it before a Run row exists.
    """

    if runtime_mode != "sequential_legacy":
        return None
    try:
        bindings = resolve_persisted_system_catalog_bindings(
            db,
            workspace=workspace,
            system=system,
        )
    except SystemCatalogBindingError as exc:
        raise FlowIngressError(
            code=exc.code.upper(),
            message=str(exc),
            status_code=422,
            details={"field": exc.field},
        ) from exc
    if not bindings.skills:
        return None
    skill = bindings.skills[0]
    if not isinstance(skill.input_schema, Mapping):
        raise FlowIngressError(
            code="RUN_INPUT_CONTRACT_INVALID",
            message="The first Skill has an invalid input contract and cannot be run.",
            status_code=422,
            details={"runtime_input_skill": {"id": skill.id, "slug": skill.slug}},
        )
    schema = copy.deepcopy(dict(skill.input_schema))
    if not schema:
        return None
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise FlowIngressError(
            code="RUN_INPUT_CONTRACT_INVALID",
            message="The first Skill has an invalid input contract and cannot be run.",
            status_code=422,
            details={"runtime_input_skill": {"id": skill.id, "slug": skill.slug}},
        ) from exc
    required = schema.get("required")
    required_fields = (
        [str(item) for item in required if isinstance(item, str) and item]
        if isinstance(required, list)
        else []
    )
    return {
        "schema": schema,
        "schema_sha256": canonical_sha256(schema),
        "required_fields": required_fields,
        "skill": {
            "id": skill.id,
            "slug": skill.slug,
            "name": skill.name,
        },
    }


def validate_sequential_runtime_input(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
    runtime_mode: str,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Reject an unusable first-Skill payload without creating a Run."""

    runtime_contract = sequential_runtime_input_contract(
        db,
        system=system,
        workspace=workspace,
        runtime_mode=runtime_mode,
    )
    if runtime_contract is None:
        return None
    schema = runtime_contract["schema"]
    required_fields = runtime_contract["required_fields"]
    candidate = {
        key: value
        for key, value in payload.items()
        if key not in {"_debug", "_ingress", "execution"}
    }
    missing_fields = [
        field
        for field in required_fields
        if field not in candidate
        or candidate[field] is None
        or (isinstance(candidate[field], str) and not candidate[field].strip())
    ]
    details = {
        "required_fields": required_fields,
        "missing_fields": missing_fields,
        "runtime_input_schema": copy.deepcopy(schema),
        "runtime_input_skill": copy.deepcopy(runtime_contract["skill"]),
    }
    if missing_fields:
        fields = ", ".join(f"\u201c{field}\u201d" for field in missing_fields)
        noun = "input" if len(missing_fields) == 1 else "inputs"
        raise FlowIngressError(
            code="RUN_INPUT_REQUIRED",
            message=f"Complete the required {noun} {fields} before starting this Run.",
            status_code=422,
            details=details,
        )

    errors = sorted(
        Draft202012Validator(schema).iter_errors(candidate),
        key=lambda error: [str(item) for item in error.absolute_path],
    )
    if errors:
        error = errors[0]
        path = "/" + "/".join(str(item) for item in error.absolute_path)
        raise FlowIngressError(
            code="RUN_INPUT_INVALID",
            message="The Run input does not match the first Skill's required contract.",
            status_code=422,
            details={**details, "path": path or "/"},
        )
    return runtime_contract


def list_published_ingresses(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
) -> dict[str, Any]:
    system, version, _flow, flow_sha256, contract = _published_evidence(
        db,
        system_id=system_id,
        workspace=workspace,
        require_active=False,
        lock_system=False,
    )
    raw = contract.get("ingresses")
    ingresses = (
        [copy.deepcopy(dict(item)) for item in raw if isinstance(item, Mapping)]
        if isinstance(raw, list)
        else []
    )
    runtime_input = sequential_runtime_input_contract(
        db,
        system=system,
        workspace=workspace,
        runtime_mode=str(contract.get("runtime_mode") or ""),
    )
    if runtime_input is not None:
        for ingress in ingresses:
            ingress["runtime_input_schema"] = copy.deepcopy(runtime_input["schema"])
            ingress["runtime_input_schema_sha256"] = runtime_input["schema_sha256"]
            ingress["required_input_fields"] = list(runtime_input["required_fields"])
            ingress["runtime_input_skill"] = copy.deepcopy(runtime_input["skill"])
    outputs = contract.get("outputs")
    output_schema = None
    if (
        isinstance(outputs, list)
        and len(outputs) == 1
        and isinstance(outputs[0], Mapping)
        and isinstance(outputs[0].get("schema"), Mapping)
    ):
        output_schema = copy.deepcopy(dict(outputs[0]["schema"]))
    return {
        "system_id": system.id,
        "system_status": system.status,
        "published_flow_version_id": getattr(version, "id", None),
        "flow_sha256": flow_sha256,
        "runtime_mode": contract.get("runtime_mode"),
        "validation_mode": contract.get("validation_mode"),
        "output_schema": output_schema,
        "ingresses": sorted(ingresses, key=lambda item: str(item.get("ingress_id") or "")),
    }


def assert_dispatchable(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
) -> dict[str, Any]:
    """Raise :class:`FlowIngressError` unless an adapter would be served a Run.

    The gate :func:`create_published_ingress_run` applies before it builds
    anything, evaluated on its own so a read model can ask the question without
    inserting a Run or locking the System row.
    """
    _system, version, flow, flow_sha256, contract = _published_evidence(
        db,
        system_id=system_id,
        workspace=workspace,
        require_active=True,
        lock_system=False,
    )
    return {
        "published_flow_version_id": getattr(version, "id", None),
        "flow_sha256": flow_sha256,
        "flow": flow,
        "execution_contract": contract,
    }


def resolve_published_ingress_id(
    execution_contract: Mapping[str, Any],
    *,
    kind: str,
    requested_ingress_id: str | None,
) -> str:
    raw = execution_contract.get("ingresses")
    candidates = (
        [
            str(item.get("ingress_id"))
            for item in raw
            if isinstance(item, Mapping)
            and item.get("kind") == kind
            and isinstance(item.get("ingress_id"), str)
            and item.get("ingress_id")
        ]
        if isinstance(raw, list)
        else []
    )
    if requested_ingress_id:
        if requested_ingress_id not in candidates:
            raise FlowIngressError(
                "FLOW_INGRESS_NOT_PUBLISHED",
                "The requested ingress is not part of the published Flow contract.",
                422,
                {"ingress_id": requested_ingress_id, "kind": kind},
            )
        return requested_ingress_id
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FlowIngressError(
            "FLOW_INGRESS_KIND_UNAVAILABLE",
            "The published Flow has no ingress for this adapter kind.",
            422,
            {"kind": kind},
        )
    raise FlowIngressError(
        "FLOW_INGRESS_AMBIGUOUS",
        "This adapter must name one of the published ingresses explicitly.",
        422,
        {"kind": kind, "candidate_ingress_ids": sorted(candidates)},
    )


def create_published_ingress_run(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
    ingress_id: str | None,
    kind: str,
    payload: Mapping[str, Any],
    initiated_by_user_id: str | None = None,
    runner_session_id: str | None = None,
    expected_published_version_id: str | None = None,
    expected_flow_sha256: str | None = None,
    adapter_evidence: Mapping[str, Any] | None = None,
    trigger: str | None = None,
    trigger_dedup_key: str | None = None,
    experience_idempotency_key: str | None = None,
    allow_debug: bool = False,
    authority_version_id: str | None = None,
) -> Run:
    """Validate an ingress and freeze all evidence before inserting one Run."""
    if authority_version_id is None:
        system, version, flow, flow_sha256, contract = _published_evidence(
            db,
            system_id=system_id,
            workspace=workspace,
            require_active=True,
            lock_system=True,
        )
    else:
        system = (
            db.query(System)
            .filter(System.id == system_id, System.workspace_id == workspace.id)
            .populate_existing()
            .with_for_update(of=System)
            .one_or_none()
        )
        if system is None:
            raise FlowIngressError("SYSTEM_NOT_FOUND", "System not found.", 404)
        if system.status != "active":
            raise FlowIngressError(
                "FLOW_INGRESS_SYSTEM_INACTIVE",
                "Published ingresses accept Runs only while the System is active.",
                409,
                {"status": system.status},
            )
        try:
            version, flow, flow_sha256, contract = flow_publication.version_run_evidence(
                db,
                system=system,
                workspace=workspace,
                version_id=authority_version_id,
            )
        except flow_publication.FlowPublicationError as exc:
            raise _translate_publication(exc) from exc
    version_id = getattr(version, "id", None)
    if expected_published_version_id is not None and version_id != expected_published_version_id:
        raise FlowIngressError(
            "PUBLISHED_FLOW_VERSION_MISMATCH",
            "Reload the published Flow before executing this ingress.",
            409,
            {
                "expected_published_version_id": expected_published_version_id,
                "authority_version_id": version_id,
            },
        )
    if expected_flow_sha256 is not None and expected_flow_sha256 != flow_sha256:
        raise FlowIngressError(
            "RUN_FLOW_SHA256_MISMATCH",
            "Reload the published Flow before executing this ingress.",
            409,
            {
                "expected_flow_sha256": expected_flow_sha256,
                "current_flow_sha256": flow_sha256,
            },
        )

    resolved_id = resolve_published_ingress_id(
        contract,
        kind=kind,
        requested_ingress_id=ingress_id,
    )
    runtime_mode = str(contract.get("runtime_mode") or "")
    if "_debug" in payload and (not allow_debug or kind != "manual"):
        raise FlowIngressError(
            "RUN_DEBUG_SURFACE_FORBIDDEN",
            "Debugger controls are accepted only by the explicit Flow Builder run surface.",
            422,
            {"path": "_debug", "kind": kind},
        )
    try:
        accepted_payload = normalize_input_debug(
            payload,
            runtime_mode=runtime_mode,
        )
    except DebugContractError as exc:
        raise FlowIngressError(
            exc.code,
            exc.message,
            422,
            {"path": exc.path},
        ) from exc
    contract_payload = {key: value for key, value in accepted_payload.items() if key != "_debug"}
    try:
        ingress = validate_ingress_payload(
            contract,
            ingress_id=resolved_id,
            kind=kind,
            payload=contract_payload,
        )
    except RuntimeContractError as exc:
        raise FlowIngressError(
            exc.code.upper(),
            exc.message,
            422,
            {
                "path": exc.path,
                "ingress_id": resolved_id,
                "kind": kind,
            },
        ) from exc
    validate_sequential_runtime_input(
        db,
        system=system,
        workspace=workspace,
        runtime_mode=runtime_mode,
        payload=accepted_payload,
    )

    # Both namespaces are server-owned.  Adapter metadata is deliberately
    # restricted to non-secret evidence supplied by the trusted caller.
    accepted_payload.pop("execution", None)
    accepted_payload.pop("_ingress", None)
    accepted_payload["execution"] = {
        "flow_sha256": flow_sha256,
        "runtime_mode": runtime_mode,
        "runtime_mode_reason": contract.get("runtime_mode_reason"),
        "execution_surface": f"published_{kind}",
        "published_flow_version_id": version_id,
        "ingress_id": resolved_id,
        "ingress_selection_version": 1,
    }
    accepted_payload["_ingress"] = {
        "ingress_id": resolved_id,
        "source_node_id": ingress.get("source_node_id") or resolved_id,
        "kind": kind,
        "adapter": copy.deepcopy(dict(adapter_evidence or {})),
    }
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=system.capability_id,
        initiated_by_user_id=initiated_by_user_id,
        input_ref=accepted_payload,
        flow_snapshot=copy.deepcopy(flow),
        flow_version_id=version_id,
        published_flow_version_id=version_id,
        flow_sha256=flow_sha256,
        execution_contract=copy.deepcopy(contract),
        execution_surface=f"published_{kind}",
        runner_session_id=runner_session_id,
        status="pending",
        started_at=datetime.utcnow(),
        trigger=trigger or {"schedule": "scheduler", "http": "webhook"}.get(kind, kind),
        trigger_dedup_key=trigger_dedup_key,
        experience_idempotency_key=experience_idempotency_key,
        checkpoints=[
            {
                "kind": "ingress_accepted",
                "t": datetime.utcnow().isoformat(),
                "ingress_id": resolved_id,
                "ingress_kind": kind,
                "published_flow_version_id": version_id,
                "flow_sha256": flow_sha256,
            }
        ],
    )
    db.add(run)
    db.flush()
    return run
