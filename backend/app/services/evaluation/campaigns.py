"""Golden comparisons use the canonical Workbench and Run worker, never a second runner."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from app.models.evaluation_campaign import EvaluationCampaign, EvaluationSuite
from app.models.knowledge_collection import KnowledgeCollection
from app.models.run import Run
from app.models.system_flow_draft import SystemFlowDraft
from app.services.systems import flow_workbench
from app.services.workspace_jobs import create_workspace_job


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def corpus_manifest(db, workspace_id: str, collection_ids: list[str]) -> list[dict]:
    rows = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace_id,
            KnowledgeCollection.id.in_(collection_ids),
        )
        .all()
    )
    if {row.id for row in rows} != set(collection_ids):
        raise HTTPException(404, "Collection not found")
    if any(row.status != "ready" for row in rows):
        raise HTTPException(409, "All evaluation collections must be ready")
    # This is a ledger fingerprint, not a claim to hash every Qdrant byte.
    return [
        {
            "id": row.id,
            "updated_at": row.updated_at.isoformat(),
            "document_count": row.document_count,
            "chunk_count": row.chunk_count,
            "embedding_model": row.embedding_model,
            "document_names_sha256": digest(row.document_names),
            "verification": "collection_ledger",
        }
        for row in sorted(rows, key=lambda item: item.id)
    ]


def contract_collection_ids(db, *, workspace_id, contract):
    """Capture only retrieval collections pinned in the compiled executors."""
    from app.services.knowledge_collections import get_collection_or_404

    collection_ids = set()
    contracts = [contract]
    while contracts:
        for node in contracts.pop()["nodes"].values():
            if "tool_contract" in node:
                contracts.append(node["tool_contract"])
            executor = node.get("executor") or {}
            params = executor.get("params") or {}
            if (
                executor.get("kind") != "registry_call"
                or params.get("skill_slug") != "semantic_search_v1"
            ):
                continue
            frozen = params.get("frozen_input") or {}
            references = {
                str(frozen[key]).strip()
                for key in ("collection", "collection_name", "context_collection")
                if frozen.get(key)
            }
            if len(references) > 1:
                raise HTTPException(422, "Frozen retrieval collection aliases must agree")
            for reference in references:
                collection = get_collection_or_404(
                    db, workspace_id=workspace_id, collection_ref=reference
                )
                collection_ids.add(collection.id)
    return sorted(collection_ids)


def validate_brd_corpus_bindings(db, *, workspace_id, suite, contract):
    """BRD manifests describe compiled tools; manual suites may describe case inputs."""
    provenance = suite.provenance or {}
    if not provenance.get("brd_proposal_id"):
        return []
    compiled_ids = set(contract_collection_ids(db, workspace_id=workspace_id, contract=contract))
    if not suite.corpus_manifest and provenance.get("corpus_snapshot") != "compiled_v1":
        return (
            [
                "The BRD suite has no reviewed corpus manifest; corpus identity and drift are unverified."
            ]
            if compiled_ids
            else []
        )
    if compiled_ids != {item["id"] for item in suite.corpus_manifest}:
        raise HTTPException(
            409, "BRD execution corpus changed; create and review a new suite revision"
        )
    return []


def validate_generation_policy(
    db, *, system_id: str, workspace_id: str, inputs: dict, executing: bool = False
):
    """Use current canonical model/source controls also when reading cached reports."""
    from app.models.system import System
    from app.services.membrane.enforcement import enforce_inbound_collections, evaluate_capability
    from app.services.run_engine.engine import _load_control_policy, _safe_membrane

    system = db.query(System).filter_by(id=system_id, workspace_id=workspace_id).one_or_none()
    if system is None:
        raise HTTPException(404, "System not found")
    membrane = _safe_membrane(_load_control_policy(db, system))
    model = inputs.get("model_execution") or {}
    allowed_models = membrane.capabilities.allowed_models
    raw_model = str(model.get("model") or "")
    model_name = (
        raw_model if raw_model in allowed_models else f"{model.get('provider')}:{raw_model}"
    )
    if not evaluate_capability(membrane, model=model_name, action="evaluate").allowed:
        raise HTTPException(403, "Evaluation model or action denied by System policy")
    embedding = inputs.get("embedding_model")
    if (
        membrane.enforcement_active
        and allowed_models
        and embedding not in allowed_models
        and f"openai:{embedding}" not in allowed_models
    ):
        raise HTTPException(403, "Evaluation embedding model denied by System policy")
    corpus_manifest(db, workspace_id, inputs["collection_ids"])
    collections = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace_id,
            KnowledgeCollection.id.in_(inputs["collection_ids"]),
        )
        .all()
    )
    slugs = [collection.slug for collection in collections]
    allowed = enforce_inbound_collections(membrane, slugs)
    if allowed.blocked or set(allowed.collections) != set(slugs):
        raise HTTPException(403, "Evaluation corpus denied by System policy")
    if membrane.enforcement_active and (
        membrane.inbound.reference_type_filters or membrane.inbound.reject_cross_project_sources
    ):
        raise HTTPException(403, "This corpus policy requires source-filtered evaluation")
    if (
        executing
        and membrane.enforcement_active
        and membrane.valves.max_cost_per_decision is not None
    ):
        raise HTTPException(
            409, "Giskard cannot reserve this monetary budget; no provider call was made"
        )
    return membrane


def freeze_generation_models(db, workspace, system_id: str, inputs: dict) -> None:
    from app.core.config import settings
    from app.services.model_plane.execution import resolve_model_execution

    execution = resolve_model_execution(workspace, provider="workspace")
    if execution.provider != "openai" or not execution._api_key:
        raise HTTPException(409, "Giskard requires the configured OpenAI provider")
    inputs["model_execution"] = {
        "provider": execution.provider,
        "model": execution.model,
        "selection_basis": "workspace_routing_at_enqueue",
    }
    inputs["embedding_model"] = settings.embedding_model
    inputs["embedding_selection_basis"] = "platform_configuration_at_enqueue"
    validate_generation_policy(
        db, system_id=system_id, workspace_id=workspace.id, inputs=inputs, executing=True
    )


def assert_read_only(flow: dict, contract: dict) -> None:
    """Fail closed for unqualified exectors, even if a node declares effect=read."""
    safe_builtins = {"llm_rag_answer_v1", "semantic_search_v1", "claim_audit_v1", "audit_log_v1"}
    safe_nodes = {"source", "sink", "skill", "task", "transform", "condition", "join", "hitl"}
    for node in flow.get("nodes", []):
        kind = node.get("kind") or node.get("type")
        config = node.get("config") or {}
        if kind not in safe_nodes or config.get("effect") in {"write", "notification", "ingestion"}:
            raise HTTPException(422, "Comparison supports qualified read-only nodes only")
    for node in (contract.get("nodes") or {}).values():
        executor = node.get("executor")
        if executor:
            if executor.get("kind") != "prompt_template":
                raise HTTPException(
                    422, "Comparison executor is not qualified for read-only replay"
                )
        elif node.get("skill_slug") not in safe_builtins:
            raise HTTPException(422, "Comparison Skill is not qualified for read-only replay")


def assertion_results(output: Any, assertions: list[dict], *, run: Run | None = None) -> dict:
    if not assertions:
        return {"verdict": "unevaluated", "assertions": []}
    result = []
    for assertion in assertions:
        value, present = output, True
        for part in assertion.get("path", []):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                present = False
                break
        operator = assertion["operator"]
        expected = assertion.get("value")
        details = {}
        if operator == "invocation_succeeded":
            # Model output and copied observations are never invocation evidence.
            present = run is not None and (
                run.status == "completed"
                or any(cp.get("kind") == "evaluation_boundary" for cp in run.checkpoints or [])
            )
            ids = (
                [
                    item.id
                    for item in run.invocations
                    if item.run_id == run.id
                    and item.skill_slug == expected
                    and item.status == "completed"
                    and not item.error
                ]
                if present
                else []
            )
            passed = bool(ids) if present else None
            details = {"evidence_basis": "invocation_ledger", "invocation_ids": ids}
        elif operator == "exists":
            passed = present
        elif operator == "equals":
            passed = present and digest(value) == digest(expected)
        elif operator == "contains":
            passed = (
                present
                and isinstance(value, str)
                and isinstance(expected, str)
                and expected in value
            )
        elif operator == "not_contains":
            passed = (
                present
                and isinstance(value, str)
                and isinstance(expected, str)
                and expected not in value
            )
        elif operator == "quotes_in_source":
            # Exact substring provenance only; no claim of semantic entailment.
            quotes = (
                [
                    next(part for part in match if part).strip()
                    for match in re.findall(r'"([^"\n]+)"|“([^”\n]+)”|«([^»\n]+)»', value)
                ]
                if present and isinstance(value, str)
                else []
            )
            missing = [
                quote for quote in quotes if not isinstance(expected, str) or quote not in expected
            ]
            passed = bool(quotes) and all(quotes) and not missing
            details = {"quotes_examined": len(quotes), "quotes_not_found": len(missing)}
        else:
            raise ValueError("Unsupported assertion operator")
        result.append({"id": assertion["id"], "passed": passed, "path_found": present, **details})
    verdict = (
        "failed"
        if any(item["passed"] is False for item in result)
        else "unevaluated"
        if any(item["passed"] is None for item in result)
        else "passed"
    )
    return {"verdict": verdict, "assertions": result}


def matches_expected_subset(expected: Any, actual: Any) -> bool:
    """Object subsets, exact ordered arrays and JSON primitives; bool is not a number."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches_expected_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(matches_expected_subset(left, right) for left, right in zip(expected, actual))
        )
    if type(expected) in (int, float) and type(actual) in (int, float):
        return expected == actual
    return type(expected) is type(actual) and expected == actual


def suite_run_result(run: Run) -> dict | None:
    """Evaluate only the criteria frozen by server-owned Golden Runs."""
    if run.execution_surface != "golden_preview":
        return None
    if run.evaluation_campaign_id:
        checkpoint = next(
            (cp for cp in run.checkpoints or [] if cp.get("kind") == "evaluation_case_queued"), None
        )
        if checkpoint:
            result = case_result(run, checkpoint["case"], qualified=True)
            # Run metadata is also exposed to payload-restricted readers. Keep
            # selected answers solely on the authorized campaign detail route.
            result.pop("output_ref", None)
            result.pop("source_snapshots", None)
            return {
                "suite_id": checkpoint["suite_id"],
                "suite_revision": checkpoint["suite_revision"],
                "case_id": checkpoint["case"]["id"],
                "method": "qualified_campaign_assertions",
                **result,
            }
    checkpoint = next(
        (
            cp
            for cp in run.checkpoints or []
            if cp.get("kind") == "golden_case_queued"
            and (
                cp.get("suite_id")
                or cp.get("evaluation_method") in {"expected_subset_v1", "no_oracle_v1"}
            )
        ),
        None,
    )
    if checkpoint is None:
        return None
    if not checkpoint.get("suite_id"):
        # Only new, explicitly marked checkpoints are evaluated. Older previews
        # could not distinguish an omitted oracle from explicit null.
        checks = []
        verdict = "pending"
        if run.status in {"completed", "failed", "cancelled"}:
            verdict = "unevaluated"
            if (
                run.status == "completed"
                and checkpoint["evaluation_method"] == "expected_subset_v1"
                and "expected" in checkpoint
            ):
                passed = matches_expected_subset(checkpoint["expected"], run.output_ref)
                checks = [{"id": "expected", "passed": passed}]
                verdict = "passed" if passed else "failed"
        return {
            "case_id": checkpoint["case_id"],
            "batch_id": checkpoint["batch_id"],
            "method": checkpoint["evaluation_method"],
            "verdict": verdict,
            "assertions": checks,
        }
    verdict = (
        assertion_results(run.output_ref, checkpoint.get("assertions", []), run=run)
        if run.status == "completed"
        else {
            "verdict": "unevaluated" if run.status in {"failed", "cancelled"} else "pending",
            "assertions": [],
        }
    )
    return {
        "suite_id": checkpoint["suite_id"],
        "suite_revision": checkpoint["suite_revision"],
        "case_id": checkpoint["case_id"],
        "batch_id": checkpoint["batch_id"],
        "brd_proposal_id": checkpoint.get("brd_proposal_id"),
        "brd_proposal_sha256": checkpoint.get("brd_proposal_sha256"),
        **(
            {"corpus_limitations": checkpoint["corpus_limitations"]}
            if checkpoint.get("corpus_limitations")
            else {}
        ),
        "method": "server_assertions",
        **verdict,
    }


def execution_cost_evidence(db, run: Run) -> dict:
    from app.services.membrane.enforcement import collect_valve_usage
    from app.services.run_engine.engine import _valve_invocation_ledger

    invocations, gaps = _valve_invocation_ledger(db, run)
    usage = collect_valve_usage(invocations, measurement_gaps=gaps)
    coverage = usage.cost_coverage.value
    if run.status not in {"completed", "failed", "cancelled"} and coverage == "complete":
        coverage = "partial"
    return {
        "execution_cost": usage.cost if coverage == "complete" else None,
        "execution_cost_coverage": coverage,
        "execution_cost_basis": "invocation_ledger",
        "execution_cost_measurements": usage.cost_measurement_count,
        "execution_cost_subjects": usage.invocation_count + usage.measurement_gap_count,
    }


def cancel_pending_cases(db, campaign: EvaluationCampaign, reason: str) -> None:
    """Only unstarted cases are cancelled; an executing Run keeps its evidence."""
    ids = [item[side]["run_id"] for item in campaign.results for side in ("baseline", "candidate")]
    for run in (
        db.query(Run)
        .filter(Run.id.in_(ids), Run.workspace_id == campaign.workspace_id, Run.status == "pending")
        .with_for_update()
        .all()
    ):
        run.status, run.error, run.completed_at = "cancelled", reason, datetime.utcnow()


def preflight_campaign(db, *, suite, baseline, workspace, body):
    baseline_boundary = baseline.status == "hitl_pending" or any(
        cp.get("kind") == "evaluation_boundary" for cp in baseline.checkpoints or []
    )
    if baseline.system_id != suite.system_id or (
        baseline.status != "completed" and not baseline_boundary
    ):
        raise HTTPException(
            422, "Baseline must be a completed Run or a recorded human boundary of this System"
        )
    if not baseline.execution_contract or not baseline.flow_snapshot or not baseline.flow_sha256:
        raise HTTPException(409, "Historical Run has no frozen execution contract")
    draft = (
        db.query(SystemFlowDraft)
        .filter_by(system_id=suite.system_id, workspace_id=workspace.id)
        .with_for_update()
        .one_or_none()
    )
    if not draft or draft.revision != body["expected_draft_revision"]:
        raise HTTPException(409, "Draft changed; review it again")
    collection_ids = [item["id"] for item in suite.corpus_manifest]
    current_manifest = corpus_manifest(db, workspace.id, collection_ids)
    if current_manifest != suite.corpus_manifest:
        raise HTTPException(409, "Corpus changed; create and review a new suite revision")
    candidate = flow_workbench.prepare_preview(
        db,
        system_id=suite.system_id,
        workspace=workspace,
        flow_definition=draft.flow_definition,
        expected_flow_sha256=draft.flow_sha256,
        ingress_id=body.get("ingress_id"),
        ingress_kind=body.get("kind"),
    )
    frozen = copy.deepcopy(baseline.execution_contract)
    baseline_prepared = flow_workbench.PreparedPreview(
        system=candidate.system,
        flow=copy.deepcopy(baseline.flow_snapshot),
        flow_sha256=baseline.flow_sha256,
        source_flow_sha256=baseline.flow_sha256,
        contract=frozen,
        runtime_reason="evaluation_frozen_baseline",
        ingress=flow_workbench._select_ingress(
            frozen, ingress_id=body.get("ingress_id"), ingress_kind=body.get("kind")
        ),
    )
    corpus_limitations = sorted(
        {
            limitation
            for prepared in (baseline_prepared, candidate)
            for limitation in validate_brd_corpus_bindings(
                db, workspace_id=workspace.id, suite=suite, contract=prepared.contract
            )
        }
    )
    from app.services.evaluation.qualification import profile

    profiles = {
        side: profile(prepared.flow, prepared.contract, prepared.ingress)
        for side, prepared in (("baseline", baseline_prepared), ("candidate", candidate))
    }
    issues = []
    if body.get("execution_mode", "legacy_readonly") == "qualified_prefix":
        issues = [
            {**issue, "side": side} for side, spec in profiles.items() for issue in spec["issues"]
        ]
    else:
        for prepared in (baseline_prepared, candidate):
            try:
                assert_read_only(prepared.flow, prepared.contract)
            except HTTPException as exc:
                issues.append(
                    {"code": "EVALUATION_READONLY_UNQUALIFIED", "message": str(exc.detail)}
                )
    result = {
        "schema_version": 2,
        "eligible": not issues,
        "issues": issues,
        "execution_mode": body.get("execution_mode", "legacy_readonly"),
        "repeat_count": body.get("repeat_count", 1),
        "planned_runs": len(suite.cases) * 2 * body.get("repeat_count", 1),
        "comparability": "not_comparable" if corpus_limitations else "limited",
        "limitations": [
            "External model revisions and live retrieval are not immutable.",
            *corpus_limitations,
        ],
        "profiles": profiles,
        "suite_revision": suite.revision,
        "candidate_draft_revision": draft.revision,
        "corpus_manifest": current_manifest,
    }
    source_bindings = {}
    if body.get("execution_mode", "legacy_readonly") == "qualified_prefix":
        from app.services.flow_data_sources import bound_data_sources
        from app.services.knowledge_collections import get_collection_or_404

        reviewed_ids = {item["id"] for item in current_manifest}
        for side, prepared in (("baseline", baseline_prepared), ("candidate", candidate)):
            reachable = {node["node_id"] for node in profiles[side]["nodes"]}
            bindings = []
            for node_id in sorted(reachable):
                for source in bound_data_sources(prepared.flow, node_id):
                    source = {**source, "consumer_node_id": node_id}
                    if source.get("collection_slug"):
                        collection = get_collection_or_404(
                            db, workspace_id=workspace.id, collection_ref=source["collection_slug"]
                        )
                        source["collection_id"] = collection.id
                        if collection.id not in reviewed_ids:
                            issues.append(
                                {
                                    "code": "EVALUATION_CORPUS_MANIFEST_INCOMPLETE",
                                    "side": side,
                                    "node_id": node_id,
                                    "collection_id": collection.id,
                                    "message": "Add this bound collection to a reviewed suite revision.",
                                }
                            )
                    bindings.append(source)
            side_contract = {
                **prepared.contract,
                "nodes": {
                    key: value
                    for key, value in (prepared.contract.get("nodes") or {}).items()
                    if key in reachable
                },
            }
            for collection_id in contract_collection_ids(
                db, workspace_id=workspace.id, contract=side_contract
            ):
                if collection_id not in reviewed_ids:
                    issues.append(
                        {
                            "code": "EVALUATION_CORPUS_MANIFEST_INCOMPLETE",
                            "side": side,
                            "collection_id": collection_id,
                            "message": "Add this frozen tool collection to the reviewed suite.",
                        }
                    )
            source_bindings[side] = bindings
    result["source_bindings"] = source_bindings
    from app.models.tabular import MLModel

    model_manifest = []
    for side, prepared in (("baseline", baseline_prepared), ("candidate", candidate)):
        reachable = {node["node_id"] for node in profiles[side]["nodes"]}
        for node in prepared.flow.get("nodes", []):
            cfg = node.get("config") or {}
            if node["id"] not in reachable or cfg.get("skill_slug") != "ml_batch_score_v1":
                continue
            params = cfg.get("params") or {}
            model = db.get(MLModel, params.get("model_id")) if params.get("model_id") else None
            if (
                model is None
                or model.workspace_id != workspace.id
                or model.version != params.get("pinned_version")
                or model.status != "ready"
            ):
                issues.append(
                    {
                        "code": "EVALUATION_MODEL_UNAVAILABLE",
                        "side": side,
                        "node_id": node["id"],
                        "message": "The pinned model is unavailable.",
                    }
                )
                continue
            model_manifest.append(
                {
                    "side": side,
                    "node_id": node["id"],
                    "model_id": model.id,
                    "version": model.version,
                    "artifact": model.model_uri,
                    "signature_sha256": digest(model.signature_json),
                    "artifact_metadata_sha256": digest((model.metrics_json or {}).get("artifact")),
                }
            )
    result["model_manifest"] = model_manifest
    result["eligible"] = not issues
    result["preflight_sha256"] = digest(result)
    return result, baseline_prepared, candidate


def create_campaign(
    db, *, suite: EvaluationSuite, baseline: Run, workspace, user, body: dict
) -> EvaluationCampaign:
    request_hash = digest(body)
    previous = (
        db.query(EvaluationCampaign)
        .filter_by(
            workspace_id=workspace.id, created_by_user_id=user.id, request_key=body["request_key"]
        )
        .first()
    )
    if previous:
        if previous.request_sha256 != request_hash:
            raise HTTPException(409, "Request key already used for another comparison")
        return previous
    preflight, baseline_prepared, candidate = preflight_campaign(
        db, suite=suite, baseline=baseline, workspace=workspace, body=body
    )
    # The draft lock serializes concurrent requests for this System.
    previous = (
        db.query(EvaluationCampaign)
        .filter_by(
            workspace_id=workspace.id, created_by_user_id=user.id, request_key=body["request_key"]
        )
        .first()
    )
    if previous:
        if previous.request_sha256 != request_hash:
            raise HTTPException(409, "Request key already used for another comparison")
        return previous
    if not preflight["eligible"]:
        raise HTTPException(
            422, {"code": "EVALUATION_PREFLIGHT_FAILED", "issues": preflight["issues"]}
        )
    qualified = body.get("execution_mode", "legacy_readonly") == "qualified_prefix"
    if qualified and body.get("preflight_sha256") != preflight["preflight_sha256"]:
        raise HTTPException(
            409, "Execution plan changed or was not reviewed; refresh the preflight"
        )
    frozen = baseline_prepared.contract
    current_manifest = preflight["corpus_manifest"]
    corpus_limitations = preflight["limitations"][1:]
    campaign = EvaluationCampaign(
        workspace_id=workspace.id,
        system_id=suite.system_id,
        suite_id=suite.id,
        baseline_run_id=baseline.id,
        request_key=body["request_key"],
        request_sha256=request_hash,
        created_by_user_id=user.id,
        snapshot={
            "suite_revision": suite.revision,
            "cases": copy.deepcopy(suite.cases),
            "corpus_manifest": current_manifest,
            "candidate_draft_revision": preflight["candidate_draft_revision"],
            "schema_version": 2,
            "execution_mode": preflight["execution_mode"],
            "repeat_count": preflight["repeat_count"],
            "preflight_sha256": preflight["preflight_sha256"],
            "execution_profiles": preflight["profiles"] if qualified else {},
            "model_manifest": preflight["model_manifest"],
            "source_bindings": preflight["source_bindings"],
            "baseline_contract_sha256": digest(frozen),
            "candidate_contract_sha256": digest(candidate.contract),
            "comparability": "not_comparable" if corpus_limitations else "limited",
            "limitations": [
                "Collection ledger fingerprint; external model revisions and live retrieval are not immutable.",
                *corpus_limitations,
            ],
        },
    )
    db.add(campaign)
    db.flush()
    results = []
    for repetition_index in range(preflight["repeat_count"]):
        for case in suite.cases:
            item = {
                "case_id": case["id"],
                "repetition_index": repetition_index,
                "result_key": f"{case['id']}:{repetition_index}",
                "change": "pending",
            }
            # Alternate dispatch order; retain every repetition, never pick a best attempt.
            sides = (("baseline", baseline_prepared), ("candidate", candidate))
            for side, prepared in sides if repetition_index % 2 == 0 else tuple(reversed(sides)):
                run = flow_workbench.create_run(
                    db,
                    prepared=prepared,
                    workspace=workspace,
                    user_id=user.id,
                    surface="golden_preview",
                    input_ref=case["input_ref"],
                    metadata={
                        "evaluation_campaign_id": campaign.id,
                        "golden_case_id": case["id"],
                        "comparison_side": side,
                        "readonly_comparison": not qualified,
                    },
                )
                if qualified:
                    run.evaluation_campaign_id = campaign.id
                    run.evaluation_binding = {
                        "schema_version": 1,
                        "case_id": case["id"],
                        "side": side,
                        "repetition_index": repetition_index,
                        "profile_sha256": digest(preflight["profiles"][side]),
                    }
                    run.checkpoints = [
                        *(run.checkpoints or []),
                        {
                            "kind": "evaluation_case_queued",
                            "suite_id": suite.id,
                            "suite_revision": suite.revision,
                            "case": copy.deepcopy(case),
                        },
                    ]
                item[side] = {"run_id": run.id, "status": run.status, "verdict": "pending"}
            results.append(item)
    campaign.results = results
    job = create_workspace_job(
        db,
        workspace,
        user,
        kind="evaluation_campaign",
        title=suite.name,
        system_id=suite.system_id,
        status="queued",
        input_ref={"campaign_id": campaign.id},
    )
    campaign.job_id = job.id
    db.flush()
    return campaign


def case_result(run, case, *, qualified=False):
    from app.services.evaluation.qualification import selected_output, trajectory_results

    output, source_invocation_id = selected_output(run, case)
    boundary = next(
        (cp for cp in reversed(run.checkpoints or []) if cp.get("kind") == "evaluation_boundary"),
        None,
    )
    termination = (
        boundary.get("boundary", "human_gate")
        if boundary
        else "completed"
        if run.status == "completed"
        else run.status
    )
    terminal = run.status in {"completed", "failed", "cancelled"}
    usable = run.status == "completed" or bool(
        boundary and boundary.get("boundary") == "human_gate" and run.status == "cancelled"
    )
    business = (
        assertion_results(output, case.get("assertions", []), run=run)
        if usable
        else {"verdict": "unevaluated" if terminal else "pending"}
    )
    trajectory = trajectory_results(run, case.get("trajectory_assertions", [])) if usable else []
    checks = [row["passed"] for row in business.get("assertions", []) + trajectory]
    if qualified and terminal:
        expected = case.get("expected_termination", "completed")
        checks.append(usable and (expected == "either" or termination == expected))
    verdict = (
        "pending"
        if not terminal
        else "unevaluated"
        if not usable
        else "failed"
        if False in checks
        else "unevaluated"
        if not (case.get("assertions") or case.get("trajectory_assertions")) or None in checks
        else "passed"
    )
    source_hashes = {}
    controls = []
    for invocation in run.invocations:
        if invocation.skill_slug == "evaluate_v2":
            payload = invocation.output_ref if isinstance(invocation.output_ref, dict) else {}
            controls.append(
                {
                    "invocation_id": invocation.id,
                    "evaluation_id": payload.get("evaluation_id"),
                    "execution_status": payload.get("status", invocation.status),
                    "quality_status": payload.get("quality_status", "unassessed"),
                }
            )
        if (
            invocation.status != "completed"
            or invocation.error
            or not isinstance(invocation.output_ref, dict)
        ):
            continue
        provenance = invocation.output_ref.get("provenance") or {}
        if isinstance(provenance, dict) and provenance.get("snapshot_sha256"):
            key = f"{(invocation.trace or {}).get('node_id', '')}:{invocation.skill_slug}"
            source_hashes.setdefault(key, set()).add(provenance["snapshot_sha256"])
    qualities = [control["quality_status"] for control in controls]
    quality_status = (
        "not_applicable"
        if not qualities
        else "failed"
        if "failed" in qualities
        else "unassessed"
        if any(q != "passed" for q in qualities)
        else "passed"
    )
    return {
        "verdict": verdict,
        "assertions": business.get("assertions", []),
        "quality_status": quality_status,
        "controls": controls,
        "trajectory_assertions": trajectory,
        "termination": termination,
        "output_ref": copy.deepcopy(output),
        "output_invocation_id": source_invocation_id,
        "source_snapshots": {key: sorted(value) for key, value in source_hashes.items()},
    }


def refresh_campaign(db, campaign: EvaluationCampaign) -> EvaluationCampaign:
    results = copy.deepcopy(campaign.results)
    cases = {case["id"]: case for case in campaign.snapshot["cases"]}
    finished = 0
    for item in results:
        for side in ("baseline", "candidate"):
            run = db.get(Run, item[side]["run_id"])
            if run is None or run.workspace_id != campaign.workspace_id:
                item[side] = {**item[side], "status": "unavailable", "verdict": "unevaluated"}
                finished += 1
                continue
            verdict = case_result(
                run,
                cases[item["case_id"]],
                qualified=campaign.snapshot.get("execution_mode") == "qualified_prefix",
            )
            item[side] = {
                "run_id": run.id,
                "status": run.status,
                "execution_status": run.status,
                **verdict,
                "duration_ms": run.duration_ms,
                **execution_cost_evidence(db, run),
                "evaluation_cost": None,
                "test_generation_cost": None,
                "flow_sha256": run.flow_sha256,
                "awaiting_decision_id": next(
                    (
                        cp.get("decision_id")
                        for cp in reversed(run.checkpoints or [])
                        if cp.get("kind") == "hitl_pause"
                    ),
                    None,
                )
                if run.status == "hitl_pending"
                else None,
            }
            finished += run.status in {"completed", "failed", "cancelled"}
        before, after = item["baseline"]["verdict"], item["candidate"]["verdict"]
        item["change"] = (
            "pending"
            if "pending" in (before, after)
            else "unevaluated"
            if "unevaluated" in (before, after)
            else "improved"
            if (before, after) == ("failed", "passed")
            else "regressed"
            if (before, after) == ("passed", "failed")
            else "unchanged"
        )
        before_sources, after_sources = (
            item["baseline"].get("source_snapshots", {}),
            item["candidate"].get("source_snapshots", {}),
        )
        if (
            before not in {"pending"}
            and after not in {"pending"}
            and before_sources != after_sources
        ):
            item["change"] = "not_comparable"
            item["comparability_reason"] = "live_source_snapshot_changed"
    snapshot = copy.deepcopy(campaign.snapshot)
    try:
        current = corpus_manifest(
            db, campaign.workspace_id, [item["id"] for item in snapshot["corpus_manifest"]]
        )
        drift = current != snapshot["corpus_manifest"]
    except HTTPException:
        drift = True
    if drift:
        snapshot["comparability"] = "not_comparable"
        if (
            "Corpus changed or became unavailable during the campaign."
            not in snapshot["limitations"]
        ):
            snapshot["limitations"].append(
                "Corpus changed or became unavailable during the campaign."
            )
    if snapshot["comparability"] == "not_comparable":
        for item in results:
            item["change"] = "not_comparable"
    campaign.snapshot, campaign.results = snapshot, results
    campaign.status = "completed" if finished == len(results) * 2 else "running"
    from app.models.workspace_job import WorkspaceJob

    job = db.get(WorkspaceJob, campaign.job_id) if campaign.job_id else None
    if job and job.status == "failed":
        campaign.status = "failed"
        failure = job.error or "Comparison worker failed; inspect the canonical Runs."
        if failure not in snapshot["limitations"]:
            snapshot["limitations"].append(failure)
        campaign.snapshot = snapshot
    if campaign.status == "completed" and campaign.completed_at is None:
        campaign.completed_at = datetime.utcnow()
    return campaign


def run_campaign_job(job_id: str):
    """Dispatch existing canonical Runs. Redelivery never creates another Run."""
    from app.db.base import SessionLocal
    from app.models.workspace_job import WorkspaceJob
    from app.services.run_engine import schedule_run

    db = SessionLocal()
    try:
        job = db.get(WorkspaceJob, job_id)
        campaign = (
            db.get(EvaluationCampaign, (job.input_ref or {}).get("campaign_id")) if job else None
        )
        if not campaign or campaign.workspace_id != job.workspace_id:
            return {"status": "unavailable"}
        if job.status in {"completed", "failed", "cancelled"}:
            return job.result or {"campaign_id": campaign.id, "campaign_status": campaign.status}
        from app.api.v1.endpoints.evaluation_campaigns import authorize_campaign
        from app.models.user import User
        from app.models.workspace import Workspace

        workspace, user = db.get(Workspace, job.workspace_id), db.get(User, job.created_by_user_id)
        authorize_campaign(db, campaign, workspace, user)
        job.status, job.stage, job.started_at = "running", "canonical_runs", datetime.utcnow()
        db.commit()
        for item in campaign.results:
            for side in (
                ("baseline", "candidate")
                if item.get("repetition_index", 0) % 2 == 0
                else ("candidate", "baseline")
            ):
                run = db.get(Run, item[side]["run_id"])
                if run and run.status == "pending":
                    schedule_run(run.id)
                db.expire_all()
                refresh_campaign(db, campaign)
                terminal = sum(
                    side_row["status"] in {"completed", "failed", "cancelled", "unavailable"}
                    for result in campaign.results
                    for side_row in (result["baseline"], result["candidate"])
                )
                job.progress = int(100 * terminal / max(1, len(campaign.results) * 2))
                db.commit()
        db.expire_all()
        refresh_campaign(db, campaign)
        job.status, job.stage = "completed", "runs_dispatched"
        job.progress, job.completed_at = 100, datetime.utcnow()
        job.result = {"campaign_id": campaign.id, "campaign_status": campaign.status}
        db.commit()
        return job.result
    except Exception:
        db.rollback()
        job = db.get(WorkspaceJob, job_id)
        if job:
            job.status, job.stage = "failed", "comparison_unavailable"
            job.error = "Comparison could not continue. Review access and canonical Run status before retrying."
            job.completed_at = datetime.utcnow()
            campaign = db.get(EvaluationCampaign, (job.input_ref or {}).get("campaign_id"))
            if campaign and campaign.workspace_id == job.workspace_id:
                cancel_pending_cases(
                    db,
                    campaign,
                    "Comparison worker failed before this case started. Start a new comparison attempt.",
                )
                refresh_campaign(db, campaign)
                job.result = {"campaign_id": campaign.id, "campaign_status": "failed"}
            db.commit()
        return {"job_id": job_id, "status": "failed"}
    finally:
        db.close()


def serialize_suite(suite):
    return {
        name: getattr(suite, name)
        for name in (
            "id",
            "system_id",
            "name",
            "revision",
            "cases",
            "corpus_manifest",
            "provenance",
            "created_at",
        )
    }


def run_generation_job(job_id: str):
    """Load authorized Qdrant chunks on the worker, then isolate Giskard globals."""
    import asyncio

    from app.api.v1.endpoints.flow_workbench import _authorize
    from app.db.base import SessionLocal
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.workspace_job import WorkspaceJob
    from app.services.evaluation.giskard_adapter import generate_isolated
    from app.services.model_plane.execution import resolve_model_execution
    from app.services.rag.index.factory import VectorDBFactory

    db = SessionLocal()
    try:
        job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update().one_or_none()
        if not job or job.status in {"completed", "cancelled"}:
            return {"status": "not_pending"}
        if (
            job.status == "running"
            and job.started_at
            and (datetime.utcnow() - job.started_at).total_seconds() < 1200
        ):
            return {"status": "already_running"}
        workspace, user = db.get(Workspace, job.workspace_id), db.get(User, job.created_by_user_id)
        _authorize(db, system_id=job.system_id, workspace=workspace, user=user)
        inputs = dict(job.input_ref or {})
        manifest = corpus_manifest(db, workspace.id, inputs["collection_ids"])
        if manifest != inputs["corpus_manifest"]:
            raise ValueError("Corpus changed before generation")
        routing = resolve_model_execution(workspace, provider="workspace")
        if routing.provider != "openai" or not routing._api_key:
            raise ValueError(
                "Giskard offline worker currently requires the configured OpenAI provider"
            )
        selected = inputs.get("model_execution") or {}
        if selected.get("provider") != routing.provider or selected.get("model") != routing.model:
            raise HTTPException(
                409, "Model routing changed after enqueue; start a new reviewed attempt"
            )
        membrane = validate_generation_policy(
            db, system_id=job.system_id, workspace_id=workspace.id, inputs=inputs, executing=True
        )
        if membrane.enforcement_active and membrane.valves.token_budget:
            inputs["max_tokens"] = min(inputs["max_tokens"], membrane.valves.token_budget)
        job.status, job.stage, job.started_at = "running", "loading_corpus", datetime.utcnow()
        db.commit()
        rows = []
        for collection_id in inputs["collection_ids"]:
            collection = db.get(KnowledgeCollection, collection_id)
            vectors = VectorDBFactory.get_db(
                collection.slug, db_type="qdrant", workspace_slug=workspace.slug
            )
            records = asyncio.run(vectors.list_payloads(limit=100))
            for record in records:
                text = str(record.get("content") or "").strip()
                if text:
                    rows.append(
                        {
                            "text": text[:8000],
                            "metadata": {
                                "collection_id": collection_id,
                                "point_id": record.get("point_id"),
                                "document_id": record.get("document_id"),
                            },
                        }
                    )
        if not 8 <= len(rows) <= 500:
            raise ValueError("Generation requires 8 to 500 usable source chunks")
        job.stage, job.progress = "generating_testset", 25
        db.commit()
        options = dict(
            rows=rows,
            model=routing.model,
            embedding_model=inputs["embedding_model"],
            api_key=routing._api_key,
            num_questions=inputs["num_questions"],
            language=inputs["language"],
            max_calls=inputs["max_calls"],
            max_tokens=inputs["max_tokens"],
            usage_context={
                "workspace_id": workspace.id,
                "system_id": job.system_id,
                "job_id": job.id,
                "campaign_id": inputs.get("campaign_id"),
                "request_key": f"{job.id}:generation",
            },
        )
        if job.kind == "evaluation_raget":
            from app.api.v1.endpoints.evaluation_campaigns import authorize_campaign

            campaign = authorize_campaign(
                db, db.get(EvaluationCampaign, inputs["campaign_id"]), workspace, user
            )
            report = {"method": "giskard_raget", "review_status": "evaluated", "sides": {}}
            from app.services.evaluation.qualification import selected_output

            cases_by_id = {case["id"]: case for case in campaign.snapshot["cases"]}
            repetitions = int(campaign.snapshot.get("repeat_count", 1))
            for side in ("baseline", "candidate"):
                batches = []
                for repetition_index in range(repetitions):
                    records = []
                    for outcome in campaign.results:
                        if outcome.get("repetition_index", 0) != repetition_index:
                            continue
                        case = cases_by_id[outcome["case_id"]]
                        run = db.get(Run, outcome[side]["run_id"])
                        boundary = any(
                            cp.get("kind") == "evaluation_boundary" for cp in run.checkpoints or []
                        )
                        if run.status != "completed" and not (
                            run.status == "cancelled" and boundary
                        ):
                            raise ValueError(
                                "RAGET requires a completed result or recorded human boundary"
                            )
                        answer, invocation_id = selected_output(run, case)
                        for part in case.get("answer_path", []):
                            answer = answer[part]
                        if case.get("answer_format") == "json" and answer is not None:
                            answer = json.dumps(answer, ensure_ascii=False, sort_keys=True)
                        if not isinstance(answer, str):
                            raise ValueError("Review the text output path before RAGET evaluation")
                        records.append(
                            {
                                "id": case["id"],
                                "question": case["question"],
                                "reference_answer": case["reference_answer"],
                                "reference_context": case.get("reference_context", ""),
                                "conversation_history": [],
                                "metadata": {
                                    "run_id": run.id,
                                    "invocation_id": invocation_id,
                                    "repetition_index": repetition_index,
                                    "question_type": "reviewed",
                                    "topic": "reviewed corpus",
                                },
                                "agent_answer": answer,
                            }
                        )
                    side_options = {
                        **options,
                        "usage_context": {
                            **options["usage_context"],
                            "request_key": f"{job.id}:{side}:{repetition_index}",
                        },
                        "max_calls": max(1, inputs["max_calls"] // (2 * repetitions)),
                        "max_tokens": inputs["max_tokens"] // (2 * repetitions),
                    }
                    batch = generate_isolated(**side_options, evaluation_cases=records)
                    batches.append({**batch, "repetition_index": repetition_index})
                    report["sides"][side] = (
                        batch
                        if repetitions == 1
                        else {"repetitions": copy.deepcopy(batches), "selection": "all_attempts"}
                    )
                    job.result = copy.deepcopy(report)
                    job.progress = 60 if side == "baseline" else 90
                    db.commit()
            report["campaign_id"] = campaign.id
        else:
            report = generate_isolated(**options)
        db.expire_all()
        _authorize(db, system_id=job.system_id, workspace=workspace, user=user)
        validate_generation_policy(
            db, system_id=job.system_id, workspace_id=workspace.id, inputs=inputs
        )
        if corpus_manifest(db, workspace.id, inputs["collection_ids"]) != manifest:
            raise ValueError("Corpus changed during generation")
        report["corpus_manifest"] = manifest
        report["corpus_sha256"] = digest(rows)
        report["coverage"] = {
            "chunks_examined": len(rows),
            "maximum_per_collection": 100,
            "maximum_characters_per_chunk": 8000,
            "exhaustive": False,
        }
        job.result, job.status, job.stage, job.progress = (
            report,
            "completed",
            "review_required",
            100,
        )
        job.completed_at = datetime.utcnow()
        db.commit()
        return {"job_id": job.id, "status": job.status}
    except Exception as exc:
        db.rollback()
        job = db.get(WorkspaceJob, job_id)
        if job:
            job.status, job.stage = "failed", "generation_unavailable"
            if getattr(exc, "usage", None):
                job.result = {
                    **(job.result or {}),
                    "failed_attempt_usage": exc.usage,
                    "review_status": "not_approved",
                }
            job.error = "Generation unavailable, corpus changed, authorization withdrawn or worker budget exhausted. No cases were approved."
            if isinstance(exc, HTTPException):
                job.error = str(exc.detail)
            job.completed_at = datetime.utcnow()
            db.commit()
        return {"job_id": job_id, "status": "failed"}
    finally:
        db.close()


def serialize_campaign(campaign):
    return {
        name: getattr(campaign, name)
        for name in (
            "id",
            "system_id",
            "suite_id",
            "baseline_run_id",
            "job_id",
            "status",
            "method",
            "snapshot",
            "results",
            "created_at",
            "completed_at",
        )
    }
