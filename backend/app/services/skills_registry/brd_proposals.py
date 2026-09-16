"""Server-owned proposal snapshots; mappings never imply successful tests."""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.brd_proposal import BrdProposal
from app.services.flow_contracts import canonical_sha256
from app.services.flow_skill_binding import resolve_flow_skill_binding


def coverage(extraction, mappings, *, node_ids, case_ids):
    """Use source positions, not potentially duplicate BRD reference labels."""
    sources = {
        (item["table"], item["row"]): item
        for item in extraction.get("provenance", [])
        if item["section"] in {"business outcomes", "functional requirements", "business rules", "prohibitions", "decisions"}
    }
    selected = {}
    for mapping in mappings:
        key = (mapping["table"], mapping["row"])
        if key not in sources or key in selected:
            raise HTTPException(422, "Unknown or duplicate BRD source mapping")
        if not set(mapping["node_ids"]).issubset(node_ids):
            raise HTTPException(422, "A requirement maps to an unknown operation")
        if not set(mapping["case_ids"]).issubset(case_ids):
            raise HTTPException(422, "A requirement maps to an unknown test case")
        selected[key] = mapping
    result = []
    for key, source in sources.items():
        mapping = selected.get(key, {})
        nodes, cases = mapping.get("node_ids", []), mapping.get("case_ids", [])
        result.append({
            **source, "node_ids": nodes, "case_ids": cases,
            "status": "proposed" if nodes and cases else "uncovered",
            "reason": mapping.get("reason", ""),
            "test_verdict": "not_run",
        })
    return result


def validate_case_output_paths(flow, cases):
    """BRD tests must address declared result fields, never a trace envelope.

    Only inspect a single explicitly shaped sink. Complex/undeclared output
    contracts still need execution and review; this is not an oracle.
    """
    for case in cases:
        for assertion in case.assertions:
            if assertion.operator == "quotes_in_source" and not any(
                isinstance(value, str) and value == assertion.value for value in case.input_ref.values()
            ):
                raise HTTPException(422, "Quote provenance must use an original case input text")
        required_text = [item for item in case.assertions
                         if item.operator in {"contains", "equals"} and isinstance(item.value, str)]
        for exclusion in case.assertions:
            if exclusion.operator != "not_contains":
                continue
            for requirement in required_text:
                if exclusion.path == requirement.path and exclusion.value in requirement.value:
                    raise HTTPException(422, {
                        "code": "brd_case_assertions_contradict", "case_id": case.id,
                        "assertion_ids": [requirement.id, exclusion.id],
                        "message": "The same result cannot contain required text and exclude part of that text.",
                    })
    sources = [node for node in flow.get("nodes", []) if node.get("kind") == "source"]
    if len(sources) == 1:
        from app.services.flow_contracts import validate_schema_definition, validate_payload, FlowContractError
        schema = (sources[0].get("config") or {}).get("input_schema")
        if schema is not None:
            try:
                schema = validate_schema_definition(schema, field="input_schema")
                for case in cases:
                    validate_payload(case.input_ref, schema, code="brd_case_input_invalid", subject=f"Case {case.id}")
            except FlowContractError as exc:
                raise HTTPException(422, {"code": exc.code, "message": str(exc),
                    "hint": "Case input_ref must satisfy the source input_schema; do not add routing fields."}) from exc
    sinks = [node for node in flow.get("nodes", []) if node.get("kind") == "sink"]
    if len(sinks) != 1:
        return
    schema = (sinks[0].get("config") or {}).get("output_schema") or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return
    for case in cases:
        paths = [case.answer_path, *(item.path for item in case.assertions)]
        for path in paths:
            if path and path[0] not in properties:
                raise HTTPException(422, {
                    "code": "brd_case_output_path_invalid", "case_id": case.id,
                    "path": path, "declared_output_fields": sorted(properties),
                    "message": "Test paths are relative to the sink result. Declare the output field before testing it; do not prefix with nodes or the sink ID.",
                })


def retain_proposal(db, *, document, user, request_key, proposal):
    snapshot = {**deepcopy(proposal), "document_id": document.id, "document_sha256": document.sha256}
    digest = canonical_sha256(snapshot)
    query = db.query(BrdProposal).filter_by(
        workspace_id=document.workspace_id, created_by_user_id=user.id, request_key=request_key
    )
    def replay(row):
        if row.sha256 != digest:
            raise HTTPException(409, "Request key already used for a different BRD proposal")
        return row
    previous = query.first()
    if previous:
        return replay(previous)
    row = BrdProposal(
        workspace_id=document.workspace_id, document_id=document.id,
        created_by_user_id=user.id, request_key=request_key, sha256=digest,
        proposal=snapshot,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        previous = query.first()
        if previous is None:
            raise
        return replay(previous)
    db.commit()
    return row


def proposal_payload(row):
    return {"id": row.id, "sha256": row.sha256, "status": row.status,
            "system_id": row.system_id, "proposal": deepcopy(row.proposal)}


def apply_proposal(db, *, document, proposal_id, expected_sha256, user, workspace):
    """Apply exactly the reviewed snapshot in one transaction, never publish it."""
    from app.api.v1.endpoints.skills import SkillCreate, _create_skill_record
    from app.api.v1.endpoints.systems import SystemCreate, _create_system_record
    from app.models.skill import Skill
    from app.models.system import System
    from app.services.systems import flow_publication
    from app.services.iam.decision_plane import enforce_action
    from app.services.iam.legacy_authority import legacy_object_action_allowed

    enforce_action(db, user=user, workspace=workspace, resource_kind="system", action="admin",
        legacy_allowed=legacy_object_action_allowed(db, user=user, workspace=workspace,
                                                   resource_kind="system", action="admin"))
    row = db.query(BrdProposal).filter_by(id=proposal_id, workspace_id=workspace.id,
                                        document_id=document.id).with_for_update().first()
    if row is None:
        raise HTTPException(404, "BRD proposal not found")
    if row.sha256 != expected_sha256:
        raise HTTPException(409, "Review the current proposal before applying it")
    if row.status == "applied":
        system = db.query(System).filter_by(id=row.system_id, workspace_id=workspace.id).first()
        if system is None:
            raise HTTPException(409, "The applied System is no longer available")
        from app.api.v1.endpoints.systems import _enforce_system_read
        _enforce_system_read(db, user=user, workspace=workspace, system=system)
        return proposal_payload(row)
    flow_publication.require_flow_publication(workspace)
    snapshot = row.proposal
    flow = deepcopy(snapshot["flow_definition"])
    aliases = {}
    for index, raw in enumerate(snapshot["skills"]):
        spec = SkillCreate.model_validate(raw)
        if spec.capability_id:
            raise HTTPException(422, "Review Capability attachment separately from BRD draft creation")
        original_name = spec.local_name
        # Each proposal owns its Skills. Applying another proposal cannot mutate
        # a shared executor or the version used by an earlier System.
        spec.local_name = f"brd_{row.id.replace('-', '')}_{index}"
        skill = _create_skill_record(spec, workspace=workspace, user=user, db=db)
        aliases["@" + original_name] = skill.slug

    referenced = set()
    def resolve(value, key=None):
        if isinstance(value, dict):
            return {k: resolve(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [resolve(v, key) for v in value]
        if key in {"skill_slug", "decide_skill", "skill_allowlist"} and isinstance(value, str):
            if value.startswith("@") and value not in aliases:
                raise HTTPException(422, "Unknown proposed Skill reference")
            slug = aliases.get(value, value)
            referenced.add(slug)
            return slug
        return value
    flow = resolve(flow)
    for node in flow.get("nodes", []):
        if node.get("kind") == "agent_loop":
            referenced.add(resolve_flow_skill_binding(node).skill_slug)
    skill_ids = []
    for slug in sorted(referenced):
        skill = db.query(Skill).filter_by(slug=slug).first()
        if skill is None:
            raise HTTPException(422, "A proposed Skill is not available")
        skill_ids.append(skill.id)
    evidence = {"document_id": document.id, "document_sha256": document.sha256,
                "proposal_id": row.id, "proposal_sha256": row.sha256,
                "coverage": deepcopy(snapshot["coverage"])}
    # Seed only the empty initial state through canonical creation, then save
    # the proposal through the draft API. The candidate is never the live graph.
    created = _create_system_record(SystemCreate(
        name=snapshot["name"], objective=snapshot["objective"], skill_ids=skill_ids,
        settings={"brd_provenance": evidence}, flow_definition={},
    ), workspace=workspace, user=user, db=db)
    system = db.get(System, created["id"])
    actor = str(getattr(user, "username", None) or user.id)
    flow_publication.compile_execution_contract(db, flow, workspace, system=system)
    flow_publication.save_draft(db, system_id=system.id, workspace=workspace,
        flow_definition=flow, expected_revision=1, actor=actor)
    if snapshot["cases"]:
        from app.api.v1.endpoints.evaluation_campaigns import SuiteBody, _create_suite_record
        suite = _create_suite_record(SuiteBody(
            system_id=system.id, name="BRD acceptance", cases=snapshot["cases"], reviewed=True,
        ), workspace=workspace, user=user, db=db)
        suite.provenance = {**suite.provenance, "brd_document_id": document.id,
                            "brd_proposal_id": row.id, "brd_proposal_sha256": row.sha256}
        system.settings = {**system.settings, "brd_provenance": {**evidence, "suite_id": suite.id}}
    row.system_id = system.id
    row.status = "applied"
    db.flush()
    return proposal_payload(row)
