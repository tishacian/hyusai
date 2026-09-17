"""Mandate edits share the existing Flow draft, revision and publish boundary."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.models.policy import ControlPolicy
from app.models.knowledge_collection import KnowledgeCollection
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.catalog_visibility import workspace_catalog_policy
from app.services.control_policy_snapshot import freeze_control_policy, thaw_control_policy, validate_frozen_control_policy
from app.services.membrane.spec import MembraneSpec, resolve_membrane_spec
from app.services.projection_integrity import scrub_projection_mapping
from app.services.chains import dag_validator
from app.services.systems import flow_publication as publication


CHECKS = ("mandate_schema", "workspace_resources", "flow_contract", "provider_availability", "runtime_tests")


def configured_models(system: System, workspace: Workspace | None, *, flow: dict | None = None) -> set[str]:
    """Configured names only; this is not a provider availability probe."""
    from app.services.model_plane.workspace_config import get_routing
    models = {system.default_model} if system.default_model else set()
    if workspace is not None:
        model = get_routing(workspace).get("default_model")
        if model:
            models.add(model)
    # Existing explicit model bindings are meaningful configured references.
    for node in (flow if flow is not None else system.flow_definition or {}).get("nodes", []):
        config = node.get("config") if isinstance(node, dict) else None
        if isinstance(config, dict) and isinstance(config.get("model"), str) and config["model"]:
            models.add(config["model"])
    return models


def editable_spec(snapshot: dict) -> dict:
    policy = thaw_control_policy(snapshot, workspace_id=snapshot["workspace_id"], system_id=snapshot["system_id"])
    _assert_no_credentials(policy)
    spec = resolve_membrane_spec(control=policy)
    payload = spec.to_dict()
    payload["provenance"].pop("object_store_prefix", None)
    if not spec.authoritative:
        # The compatibility resolver's review=True is a capture default, not
        # an enforced System gate. Do not activate it when authoring a mandate.
        payload.update(version=2, enforcement_mode="shadow")
        payload["outbound"]["expert_review_required"] = False
    return payload


def spec_is_seed(snapshot: dict) -> bool:
    policy = thaw_control_policy(snapshot, workspace_id=snapshot["workspace_id"], system_id=snapshot["system_id"])
    return not resolve_membrane_spec(control=policy).authoritative


def _reject(code: str, message: str, *, field: str | None = None, status: int = 422):
    raise publication.FlowPublicationError(code, message, status, {"field": field} if field else None)


def _assert_no_credentials(policy: ControlPolicy | None) -> None:
    # A redacted editable schema could be saved back as a changed contract.
    # Refuse unsafe legacy content instead of exposing or rewriting it.
    if policy is not None and scrub_projection_mapping(policy.extra or {}) != (policy.extra or {}):
        _reject("MANDATE_POLICY_CONTAINS_CREDENTIALS", "Move credentials out of the policy before freezing it.")


def normalize_spec(raw: dict, *, base_snapshot: dict) -> dict:
    default = MembraneSpec().to_dict()
    allowed = set(default) | {"enforcement_mode"}
    if set(raw) - allowed or type(raw.get("version")) is not int or raw["version"] not in {1, 2}:
        _reject("MANDATE_SPEC_INVALID", "Unknown mandate field or version.")
    if raw.get("enforcement_mode", "compat") not in {"compat", "shadow", "enforce"}:
        _reject("MANDATE_SPEC_INVALID", "Unsupported mandate mode.", field="enforcement_mode")
    if raw["version"] == 1 and raw.get("enforcement_mode", "compat") != "compat":
        _reject("MANDATE_SPEC_INVALID", "Shadow or enforce requires mandate version 2.", field="enforcement_mode")
    for facet in ("inbound", "outbound", "capabilities", "provenance", "valves"):
        value = raw.get(facet, {})
        if not isinstance(value, dict) or set(value) - set(default[facet]):
            _reject("MANDATE_SPEC_INVALID", "Unsupported mandate field.", field=facet)
        for key, item in value.items():
            expected = default[facet][key]
            if isinstance(expected, bool) and not isinstance(item, bool):
                _reject("MANDATE_SPEC_INVALID", "A mandate switch must be a boolean.", field=f"{facet}.{key}")
            if isinstance(expected, list) and not isinstance(item, list):
                _reject("MANDATE_SPEC_INVALID", "A scope must be a list.", field=f"{facet}.{key}")
            if expected is None and key not in {"object_store_prefix", "circuit_breaker"} and item is not None:
                if type(item) not in {int, float} or (key == "token_budget" and type(item) is not int):
                    _reject("MANDATE_SPEC_INVALID", "A limit must be a number (token budget an integer).", field=f"{facet}.{key}")
    # Validate limits even for v1, whose read-compatible parser is permissive.
    try:
        checked = deepcopy(raw)
        checked["version"] = 2
        if raw["version"] == 1:
            checked.setdefault("capabilities", {})["allowed_delegations"] = []
        MembraneSpec.from_dict(checked)
    except (ValueError, TypeError, OverflowError) as exc:
        _reject("MANDATE_SPEC_INVALID", str(exc))
    payload = MembraneSpec.from_dict(raw).to_dict()
    base_policy = thaw_control_policy(base_snapshot, workspace_id=base_snapshot["workspace_id"], system_id=base_snapshot["system_id"])
    base_spec = resolve_membrane_spec(control=base_policy).to_dict()
    storage_prefix = base_spec["provenance"].get("object_store_prefix")
    supplied_prefix = raw.get("provenance", {}).get("object_store_prefix")
    if supplied_prefix is not None and supplied_prefix != storage_prefix:
        _reject("MANDATE_REFERENCE_NOT_ALLOWED", "Provenance storage is managed by the platform.", field="provenance.object_store_prefix")
    payload["provenance"]["object_store_prefix"] = storage_prefix
    if payload["capabilities"]["allowed_actions"] != base_spec["capabilities"]["allowed_actions"]:
        _reject("MANDATE_REFERENCE_NOT_ALLOWED", "Action permissions are managed by the existing policy.", field="capabilities.allowed_actions")
    # Legacy operational flags are preserved, not newly enabled by this form.
    for field in ("reference_type_filters", "preserve_reference_types", "expert_fiche_correction_enabled", "industrial_grounding"):
        if payload["inbound"][field] != base_spec["inbound"][field]:
            _reject("MANDATE_REFERENCE_NOT_ALLOWED", "This runtime option is not editable here.", field=f"inbound.{field}")
    if payload["valves"]["circuit_breaker"] != base_spec["valves"]["circuit_breaker"]:
        _reject("MANDATE_REFERENCE_NOT_ALLOWED", "Circuit-breaker policy is managed in the existing controls.", field="valves.circuit_breaker")
    return payload


def validate_options(spec: dict, *, options: dict, base_snapshot: dict) -> None:
    base = editable_spec(base_snapshot)
    for facet, field, kind in (("inbound", "collection_allowlist", "collections"),
                               ("capabilities", "allowed_skills", "skills"),
                               ("capabilities", "allowed_models", "models")):
        allowed = {item["id"] for item in options[kind]} | set(base[facet][field])
        if any(ref not in allowed for ref in spec[facet][field]):
            _reject("MANDATE_REFERENCE_NOT_ALLOWED", "The selected resource is outside the authorized options.", field=f"{facet}.{field}")
    # Preserving a hidden existing reference is not a new grant. Changing its
    # child input/output contract or adding a target is never implicit.
    allowed_delegations = base["capabilities"]["allowed_delegations"]
    if any(rule not in allowed_delegations for rule in spec["capabilities"]["allowed_delegations"]):
        _reject("MANDATE_REFERENCE_NOT_ALLOWED", "Delegation contracts must already belong to this mandate.", field="capabilities.allowed_delegations")


def validate_resources(db, *, snapshot: dict, system: System, allow_missing: bool = False, flow: dict | None = None) -> None:
    snapshot = validate_frozen_control_policy(snapshot, workspace_id=system.workspace_id, system_id=system.id)
    policy = thaw_control_policy(snapshot, workspace_id=system.workspace_id, system_id=system.id)
    # Published executable contracts are visible to System readers. Credentials
    # belong in provider/integration storage, never in a ControlPolicy body.
    _assert_no_credentials(policy)
    spec = resolve_membrane_spec(control=policy)
    # References introduced into a frozen mandate must never resolve to an
    # identically named object belonging to another workspace.
    workspace = db.get(Workspace, system.workspace_id) if system.workspace_id else None
    hidden_skills = workspace_catalog_policy(workspace).hidden_skills if workspace is not None else set()
    for ref in spec.capabilities.allowed_skills:
        rows = db.query(Skill).filter((Skill.slug == ref) | (Skill.id == ref)).all()
        if not allow_missing and any({str(row.id).lower(), str(row.slug).lower()} & hidden_skills for row in rows):
            _reject("MANDATE_REFERENCE_NOT_ALLOWED", "A declared Skill was disabled in this workspace.", field="capabilities.allowed_skills")
        if rows and not any(row.workspace_id in {None, system.workspace_id} for row in rows):
            _reject("MANDATE_REFERENCE_NOT_ALLOWED", "A Skill belongs to another workspace.", field="capabilities.allowed_skills")
        if not rows and not allow_missing:
            _reject("MANDATE_REFERENCE_UNAVAILABLE", "A declared Skill is no longer in the authorized catalog.", field="capabilities.allowed_skills")
    for ref in spec.inbound.collection_allowlist:
        local = db.query(KnowledgeCollection.id).filter(KnowledgeCollection.workspace_id == system.workspace_id,
                (KnowledgeCollection.slug == ref) | (KnowledgeCollection.id == ref)).first()
        if not local and db.query(KnowledgeCollection.id).filter(
                (KnowledgeCollection.slug == ref) | (KnowledgeCollection.id == ref)).first():
            _reject("MANDATE_REFERENCE_NOT_ALLOWED", "A collection is unavailable in this workspace.", field="inbound.collection_allowlist")
        if not local and not allow_missing:
            _reject("MANDATE_REFERENCE_UNAVAILABLE", "A declared collection is absent from this workspace catalog.", field="inbound.collection_allowlist")
    models = configured_models(system, workspace, flow=flow)
    if not allow_missing and any(ref not in models for ref in spec.capabilities.allowed_models):
        _reject("MANDATE_REFERENCE_UNAVAILABLE", "A model is not configured in this System or the workspace routing.", field="capabilities.allowed_models")
    for rule in spec.capabilities.allowed_delegations:
        target_id = rule.get("system_id") if isinstance(rule, dict) else rule
        if db.query(System.id).filter(System.id == target_id, System.workspace_id == system.workspace_id).first() is None and not allow_missing:
            _reject("MANDATE_REFERENCE_NOT_ALLOWED", "A delegation target is unavailable in this workspace.", field="capabilities.allowed_delegations")


def save(db, *, system: System, workspace: Any, expected_revision: int,
         expected_snapshot_sha256: str, spec: dict, options: dict, actor: str):
    publication.require_flow_publication(workspace)
    system = publication._lock_system(db, system_id=system.id, workspace_id=workspace.id)
    draft = publication._locked_draft(db, system)
    publication._assert_draft_precondition(draft, expected_revision=expected_revision)
    base = publication.resolved_control_policy_snapshot(db, system=system, draft=draft)
    if base["sha256"] != expected_snapshot_sha256:
        _reject("MANDATE_SNAPSHOT_MISMATCH", "The mandate changed; reload it before saving.", status=409)
    normalized = normalize_spec(spec, base_snapshot=base)
    validate_options(normalized, options=options, base_snapshot=base)
    policy = thaw_control_policy(base, workspace_id=workspace.id, system_id=system.id)
    if policy is None:
        policy = ControlPolicy(id=str(uuid5(NAMESPACE_URL, f"agentium:mandate:{workspace.id}:{system.id}")),
                               workspace_id=workspace.id, scope="system", target_id=system.id)
    policy.extra = {**deepcopy(policy.extra or {}), "membrane_spec": normalized}
    policy.allowed_skills = normalized["capabilities"]["allowed_skills"]
    policy.allowed_models = normalized["capabilities"]["allowed_models"]
    for field in ("max_cost_per_decision", "max_latency_ms", "mandatory_hitl_if_confidence_below"):
        setattr(policy, field, normalized["valves"][field])
    candidate = freeze_control_policy(policy, workspace_id=workspace.id, system_id=system.id)
    validate_resources(db, snapshot=candidate, system=system, allow_missing=True, flow=draft.flow_definition)
    if candidate == base and draft.control_policy_snapshot is not None:
        return draft, True
    draft.control_policy_snapshot = candidate
    draft.revision += 1
    draft.updated_by = actor
    draft.updated_at = datetime.utcnow()
    emit_audit_event(db=db, workspace_id=workspace.id, event_type="flow.mandate.draft.saved", actor=actor,
                     agent_id=system.id, details={"system_id": system.id, "draft_revision": draft.revision,
                                                  "control_policy_snapshot_sha256": candidate["sha256"]})
    db.flush()
    return draft, False


def validate(db, *, system: System, workspace: Any, expected_revision: int,
             expected_snapshot_sha256: str | None = None) -> dict:
    system = publication._lock_system(db, system_id=system.id, workspace_id=workspace.id)
    draft = publication._locked_draft(db, system)
    publication._assert_draft_precondition(draft, expected_revision=expected_revision)
    snapshot = publication.resolved_control_policy_snapshot(db, system=system, draft=draft)
    if expected_snapshot_sha256 is not None and snapshot["sha256"] != expected_snapshot_sha256:
        _reject("MANDATE_SNAPSHOT_MISMATCH", "The mandate changed; reload it before validation.", status=409)
    def compile_flow():
        issues = dag_validator.validate_flow(draft.flow_definition)
        if dag_validator.has_errors(issues):
            raise publication.FlowPublicationError("FLOW_PUBLISH_VALIDATION_FAILED", "The Flow has blocking diagnostics.",
                                                    422, {"issues": dag_validator.issues_to_payload(issues)})
        return publication.compile_execution_contract(db, draft.flow_definition, workspace, system=system)
    checks = []
    for code, action in (
        ("mandate_schema", lambda: validate_frozen_control_policy(snapshot, workspace_id=workspace.id, system_id=system.id)),
        ("workspace_resources", lambda: validate_resources(db, snapshot=snapshot, system=system, flow=draft.flow_definition)),
        ("flow_contract", compile_flow),
    ):
        try:
            action()
            checks.append({"code": code, "status": "passed"})
        except (ValueError, publication.FlowPublicationError) as exc:
            checks.append({"code": code, "status": "failed", "field": getattr(exc, "code", "invalid"),
                           "reason_code": getattr(exc, "code", "invalid"),
                           "message": getattr(exc, "message", str(exc)), "details": getattr(exc, "details", None)})
    checks.extend({"code": code, "status": "not_run"} for code in ("provider_availability", "runtime_tests"))
    return {"valid": not any(check["status"] == "failed" for check in checks), "checks": checks}
