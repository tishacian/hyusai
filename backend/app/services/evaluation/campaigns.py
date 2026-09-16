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
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def corpus_manifest(db, workspace_id: str, collection_ids: list[str]) -> list[dict]:
    rows = db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace_id, KnowledgeCollection.id.in_(collection_ids)).all()
    if {row.id for row in rows} != set(collection_ids):
        raise HTTPException(404, "Collection not found")
    if any(row.status != "ready" for row in rows):
        raise HTTPException(409, "All evaluation collections must be ready")
    # This is a ledger fingerprint, not a claim to hash every Qdrant byte.
    return [{"id": row.id, "updated_at": row.updated_at.isoformat(), "document_count": row.document_count,
             "chunk_count": row.chunk_count, "embedding_model": row.embedding_model,
             "document_names_sha256": digest(row.document_names), "verification": "collection_ledger"}
            for row in sorted(rows, key=lambda item: item.id)]


def validate_generation_policy(db, *, system_id: str, workspace_id: str, inputs: dict,
                               executing: bool = False):
    """Use current canonical model/source controls also when reading cached reports."""
    from app.models.system import System
    from app.services.run_engine.engine import _load_control_policy, _safe_membrane
    from app.services.membrane.enforcement import evaluate_capability, enforce_inbound_collections
    system = db.query(System).filter_by(id=system_id, workspace_id=workspace_id).one_or_none()
    if system is None:
        raise HTTPException(404, "System not found")
    membrane = _safe_membrane(_load_control_policy(db, system))
    model = inputs.get("model_execution") or {}
    allowed_models = membrane.capabilities.allowed_models
    raw_model = str(model.get("model") or "")
    model_name = raw_model if raw_model in allowed_models else f"{model.get('provider')}:{raw_model}"
    if not evaluate_capability(membrane, model=model_name, action="evaluate").allowed:
        raise HTTPException(403, "Evaluation model or action denied by System policy")
    embedding = inputs.get("embedding_model")
    if membrane.enforcement_active and allowed_models and embedding not in allowed_models and f"openai:{embedding}" not in allowed_models:
        raise HTTPException(403, "Evaluation embedding model denied by System policy")
    corpus_manifest(db, workspace_id, inputs["collection_ids"])
    collections = db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == workspace_id,
                                                       KnowledgeCollection.id.in_(inputs["collection_ids"])).all()
    slugs = [collection.slug for collection in collections]
    allowed = enforce_inbound_collections(membrane, slugs)
    if allowed.blocked or set(allowed.collections) != set(slugs):
        raise HTTPException(403, "Evaluation corpus denied by System policy")
    if membrane.enforcement_active and (membrane.inbound.reference_type_filters or membrane.inbound.reject_cross_project_sources):
        raise HTTPException(403, "This corpus policy requires source-filtered evaluation")
    if executing and membrane.enforcement_active and membrane.valves.max_cost_per_decision is not None:
        raise HTTPException(409, "Giskard cannot reserve this monetary budget; no provider call was made")
    return membrane


def freeze_generation_models(db, workspace, system_id: str, inputs: dict) -> None:
    from app.core.config import settings
    from app.services.model_plane.execution import resolve_model_execution
    execution = resolve_model_execution(workspace, provider="workspace")
    if execution.provider != "openai" or not execution._api_key:
        raise HTTPException(409, "Giskard requires the configured OpenAI provider")
    inputs["model_execution"] = {"provider": execution.provider, "model": execution.model,
                                 "selection_basis": "workspace_routing_at_enqueue"}
    inputs["embedding_model"] = settings.embedding_model
    inputs["embedding_selection_basis"] = "platform_configuration_at_enqueue"
    validate_generation_policy(db, system_id=system_id, workspace_id=workspace.id, inputs=inputs, executing=True)


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
                raise HTTPException(422, "Comparison executor is not qualified for read-only replay")
        elif node.get("skill_slug") not in safe_builtins:
            raise HTTPException(422, "Comparison Skill is not qualified for read-only replay")


def assertion_results(output: Any, assertions: list[dict]) -> dict:
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
        if operator == "exists":
            passed = present
        elif operator == "equals":
            passed = present and digest(value) == digest(expected)
        elif operator == "contains":
            passed = present and isinstance(value, str) and isinstance(expected, str) and expected in value
        elif operator == "not_contains":
            passed = present and isinstance(value, str) and isinstance(expected, str) and expected not in value
        elif operator == "quotes_in_source":
            # Exact substring provenance only; no claim of semantic entailment.
            quotes = [next(part for part in match if part).strip() for match in
                      re.findall(r'"([^"\n]+)"|“([^”\n]+)”|«([^»\n]+)»', value)
                      ] if present and isinstance(value, str) else []
            missing = [quote for quote in quotes if not isinstance(expected, str) or quote not in expected]
            passed = bool(quotes) and all(quotes) and not missing
            details = {"quotes_examined": len(quotes), "quotes_not_found": len(missing)}
        else:
            raise ValueError("Unsupported assertion operator")
        result.append({"id": assertion["id"], "passed": passed, "path_found": present, **details})
    return {"verdict": "passed" if all(item["passed"] for item in result) else "failed", "assertions": result}


def suite_run_result(run: Run) -> dict | None:
    """Evaluate only the criteria frozen by server-owned Golden Runs."""
    if run.execution_surface != "golden_preview":
        return None
    checkpoint = next((cp for cp in run.checkpoints or []
        if cp.get("kind") == "golden_case_queued" and cp.get("suite_id")), None)
    if checkpoint is None:
        return None
    verdict = (assertion_results(run.output_ref, checkpoint.get("assertions", []))
        if run.status == "completed" else {"verdict": "unevaluated"
        if run.status in {"failed", "cancelled"} else "pending", "assertions": []})
    return {"suite_id": checkpoint["suite_id"], "suite_revision": checkpoint["suite_revision"],
        "case_id": checkpoint["case_id"], "batch_id": checkpoint["batch_id"],
        "brd_proposal_id": checkpoint.get("brd_proposal_id"),
        "brd_proposal_sha256": checkpoint.get("brd_proposal_sha256"),
        "method": "server_assertions", **verdict}


def execution_cost_evidence(db, run: Run) -> dict:
    from app.services.run_engine.engine import _valve_invocation_ledger
    from app.services.membrane.enforcement import collect_valve_usage
    invocations, gaps = _valve_invocation_ledger(db, run)
    usage = collect_valve_usage(invocations, measurement_gaps=gaps)
    coverage = usage.cost_coverage.value
    if run.status not in {"completed", "failed", "cancelled"} and coverage == "complete":
        coverage = "partial"
    return {"execution_cost": usage.cost if coverage == "complete" else None,
            "execution_cost_coverage": coverage, "execution_cost_basis": "invocation_ledger",
            "execution_cost_measurements": usage.cost_measurement_count,
            "execution_cost_subjects": usage.invocation_count + usage.measurement_gap_count}


def cancel_pending_cases(db, campaign: EvaluationCampaign, reason: str) -> None:
    """Only unstarted cases are cancelled; an executing Run keeps its evidence."""
    ids = [item[side]["run_id"] for item in campaign.results for side in ("baseline", "candidate")]
    for run in db.query(Run).filter(Run.id.in_(ids), Run.workspace_id == campaign.workspace_id,
                                   Run.status == "pending").with_for_update().all():
        run.status, run.error, run.completed_at = "cancelled", reason, datetime.utcnow()


def create_campaign(db, *, suite: EvaluationSuite, baseline: Run, workspace, user, body: dict) -> EvaluationCampaign:
    request_hash = digest(body)
    previous = db.query(EvaluationCampaign).filter_by(workspace_id=workspace.id, created_by_user_id=user.id, request_key=body["request_key"]).first()
    if previous:
        if previous.request_sha256 != request_hash:
            raise HTTPException(409, "Request key already used for another comparison")
        return previous
    if baseline.system_id != suite.system_id or baseline.status != "completed":
        raise HTTPException(422, "Baseline must be a completed Run of this System")
    if not baseline.execution_contract or not baseline.flow_snapshot or not baseline.flow_sha256:
        raise HTTPException(409, "Historical Run has no frozen execution contract")
    draft = db.query(SystemFlowDraft).filter_by(system_id=suite.system_id, workspace_id=workspace.id).with_for_update().one_or_none()
    previous = db.query(EvaluationCampaign).filter_by(workspace_id=workspace.id, created_by_user_id=user.id, request_key=body["request_key"]).first()
    if previous:
        if previous.request_sha256 != request_hash:
            raise HTTPException(409, "Request key already used for another comparison")
        return previous
    if not draft or draft.revision != body["expected_draft_revision"]:
        raise HTTPException(409, "Draft changed; review it again")
    collection_ids = [item["id"] for item in suite.corpus_manifest]
    current_manifest = corpus_manifest(db, workspace.id, collection_ids)
    if current_manifest != suite.corpus_manifest:
        raise HTTPException(409, "Corpus changed; create and review a new suite revision")
    candidate = flow_workbench.prepare_preview(db, system_id=suite.system_id, workspace=workspace,
        flow_definition=draft.flow_definition, expected_flow_sha256=draft.flow_sha256,
        ingress_id=body.get("ingress_id"), ingress_kind=body.get("kind"))
    frozen = copy.deepcopy(baseline.execution_contract)
    baseline_prepared = flow_workbench.PreparedPreview(system=candidate.system, flow=copy.deepcopy(baseline.flow_snapshot),
        flow_sha256=baseline.flow_sha256, source_flow_sha256=baseline.flow_sha256, contract=frozen,
        runtime_reason="evaluation_frozen_baseline", ingress=flow_workbench._select_ingress(frozen,
            ingress_id=body.get("ingress_id"), ingress_kind=body.get("kind")))
    for prepared in (baseline_prepared, candidate):
        assert_read_only(prepared.flow, prepared.contract)
    campaign = EvaluationCampaign(workspace_id=workspace.id, system_id=suite.system_id, suite_id=suite.id,
        baseline_run_id=baseline.id, request_key=body["request_key"], request_sha256=request_hash,
        created_by_user_id=user.id, snapshot={"suite_revision": suite.revision, "cases": copy.deepcopy(suite.cases),
        "corpus_manifest": current_manifest, "candidate_draft_revision": draft.revision,
        "baseline_contract_sha256": digest(frozen), "candidate_contract_sha256": digest(candidate.contract),
        "comparability": "limited", "limitations": ["Collection ledger fingerprint; external model revisions and live retrieval are not immutable."]})
    db.add(campaign)
    db.flush()
    results = []
    for case in suite.cases:
        item = {"case_id": case["id"], "change": "pending"}
        for side, prepared in (("baseline", baseline_prepared), ("candidate", candidate)):
            run = flow_workbench.create_run(db, prepared=prepared, workspace=workspace, user_id=user.id,
                surface="golden_preview", input_ref=case["input_ref"], metadata={"evaluation_campaign_id": campaign.id,
                    "golden_case_id": case["id"], "comparison_side": side, "readonly_comparison": True})
            item[side] = {"run_id": run.id, "status": run.status, "verdict": "pending"}
        results.append(item)
    campaign.results = results
    job = create_workspace_job(db, workspace, user, kind="evaluation_campaign", title=suite.name,
        system_id=suite.system_id, status="queued", input_ref={"campaign_id": campaign.id})
    campaign.job_id = job.id
    db.flush()
    return campaign


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
            verdict = assertion_results(run.output_ref, cases[item["case_id"]].get("assertions", [])) if run.status == "completed" else {"verdict": "unevaluated" if run.status in {"failed", "cancelled"} else "pending"}
            item[side] = {"run_id": run.id, "status": run.status, **verdict,
                "output_ref": copy.deepcopy(run.output_ref), "duration_ms": run.duration_ms,
                **execution_cost_evidence(db, run), "evaluation_cost": None, "test_generation_cost": None,
                "flow_sha256": run.flow_sha256,
                "awaiting_decision_id": next((cp.get("decision_id") for cp in reversed(run.checkpoints or [])
                    if cp.get("kind") == "hitl_pause"), None) if run.status == "hitl_pending" else None}
            finished += run.status in {"completed", "failed", "cancelled"}
        before, after = item["baseline"]["verdict"], item["candidate"]["verdict"]
        item["change"] = ("pending" if "pending" in (before, after) else "unevaluated" if "unevaluated" in (before, after)
            else "improved" if (before, after) == ("failed", "passed") else "regressed" if (before, after) == ("passed", "failed") else "unchanged")
    snapshot = copy.deepcopy(campaign.snapshot)
    try:
        current = corpus_manifest(db, campaign.workspace_id, [item["id"] for item in snapshot["corpus_manifest"]])
        drift = current != snapshot["corpus_manifest"]
    except HTTPException:
        drift = True
    if drift:
        snapshot["comparability"] = "not_comparable"
        if "Corpus changed or became unavailable during the campaign." not in snapshot["limitations"]:
            snapshot["limitations"].append("Corpus changed or became unavailable during the campaign.")
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
        campaign = db.get(EvaluationCampaign, (job.input_ref or {}).get("campaign_id")) if job else None
        if not campaign or campaign.workspace_id != job.workspace_id:
            return {"status": "unavailable"}
        if job.status in {"completed", "failed", "cancelled"}:
            return job.result or {"campaign_id": campaign.id, "campaign_status": campaign.status}
        from app.models.workspace import Workspace
        from app.models.user import User
        from app.api.v1.endpoints.evaluation_campaigns import authorize_campaign
        workspace, user = db.get(Workspace, job.workspace_id), db.get(User, job.created_by_user_id)
        authorize_campaign(db, campaign, workspace, user)
        job.status, job.stage, job.started_at = "running", "canonical_runs", datetime.utcnow()
        db.commit()
        for item in campaign.results:
            for side in ("baseline", "candidate"):
                run = db.get(Run, item[side]["run_id"])
                if run and run.status == "pending":
                    schedule_run(run.id)
                db.expire_all()
                refresh_campaign(db, campaign)
                terminal = sum(side_row["status"] in {"completed", "failed", "cancelled", "unavailable"} for result in campaign.results for side_row in (result["baseline"], result["candidate"]))
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
                cancel_pending_cases(db, campaign, "Comparison worker failed before this case started. Start a new comparison attempt.")
                refresh_campaign(db, campaign)
                job.result = {"campaign_id": campaign.id, "campaign_status": "failed"}
            db.commit()
        return {"job_id": job_id, "status": "failed"}
    finally:
        db.close()


def serialize_suite(suite):
    return {name: getattr(suite, name) for name in ("id", "system_id", "name", "revision", "cases", "corpus_manifest", "provenance", "created_at")}


def run_generation_job(job_id: str):
    """Load authorized Qdrant chunks on the worker, then isolate Giskard globals."""
    import asyncio
    from app.db.base import SessionLocal
    from app.models.workspace_job import WorkspaceJob
    from app.models.workspace import Workspace
    from app.models.user import User
    from app.services.model_plane.execution import resolve_model_execution
    from app.services.vector_db.factory import VectorDBFactory
    from app.services.evaluation.giskard_adapter import generate_isolated
    from app.api.v1.endpoints.flow_workbench import _authorize
    db = SessionLocal()
    try:
        job = db.query(WorkspaceJob).filter_by(id=job_id).with_for_update().one_or_none()
        if not job or job.status in {"completed", "cancelled"}:
            return {"status": "not_pending"}
        if job.status == "running" and job.started_at and (datetime.utcnow() - job.started_at).total_seconds() < 1200:
            return {"status": "already_running"}
        workspace, user = db.get(Workspace, job.workspace_id), db.get(User, job.created_by_user_id)
        _authorize(db, system_id=job.system_id, workspace=workspace, user=user)
        inputs = dict(job.input_ref or {})
        manifest = corpus_manifest(db, workspace.id, inputs["collection_ids"])
        if manifest != inputs["corpus_manifest"]:
            raise ValueError("Corpus changed before generation")
        routing = resolve_model_execution(workspace, provider="workspace")
        if routing.provider != "openai" or not routing._api_key:
            raise ValueError("Giskard offline worker currently requires the configured OpenAI provider")
        selected = inputs.get("model_execution") or {}
        if selected.get("provider") != routing.provider or selected.get("model") != routing.model:
            raise HTTPException(409, "Model routing changed after enqueue; start a new reviewed attempt")
        membrane = validate_generation_policy(db, system_id=job.system_id, workspace_id=workspace.id, inputs=inputs, executing=True)
        if membrane.enforcement_active and membrane.valves.token_budget:
            inputs["max_tokens"] = min(inputs["max_tokens"], membrane.valves.token_budget)
        job.status, job.stage, job.started_at = "running", "loading_corpus", datetime.utcnow()
        db.commit()
        rows = []
        for collection_id in inputs["collection_ids"]:
            collection = db.get(KnowledgeCollection, collection_id)
            vectors = VectorDBFactory.get_db(collection.slug, db_type="qdrant", workspace_slug=workspace.slug)
            records = asyncio.run(vectors.list_payloads(limit=100))
            for record in records:
                text = str(record.get("content") or "").strip()
                if text:
                    rows.append({"text": text[:8000], "metadata": {"collection_id": collection_id,
                        "point_id": record.get("point_id"), "document_id": record.get("document_id")}})
        if not 8 <= len(rows) <= 500:
            raise ValueError("Generation requires 8 to 500 usable source chunks")
        job.stage, job.progress = "generating_testset", 25
        db.commit()
        options = dict(rows=rows, model=routing.model, embedding_model=inputs["embedding_model"],
            api_key=routing._api_key, num_questions=inputs["num_questions"], language=inputs["language"],
            max_calls=inputs["max_calls"], max_tokens=inputs["max_tokens"])
        if job.kind == "evaluation_raget":
            from app.api.v1.endpoints.evaluation_campaigns import authorize_campaign
            campaign = authorize_campaign(db, db.get(EvaluationCampaign, inputs["campaign_id"]), workspace, user)
            report = {"method": "giskard_raget", "review_status": "evaluated", "sides": {}}
            for side in ("baseline", "candidate"):
                records = []
                for case, outcome in zip(campaign.snapshot["cases"], campaign.results):
                    run = db.get(Run, outcome[side]["run_id"])
                    if run.status != "completed":
                        raise ValueError("RAGET requires completed Runs")
                    answer = run.output_ref
                    for part in case.get("answer_path", []):
                        answer = answer[part]
                    if not isinstance(answer, str):
                        raise ValueError("Review the text output path before RAGET evaluation")
                    records.append({"id": case["id"], "question": case["question"],
                        "reference_answer": case["reference_answer"], "reference_context": case.get("reference_context", ""),
                        "conversation_history": [], "metadata": {"run_id": run.id,
                            "question_type": "reviewed", "topic": "reviewed corpus"}, "agent_answer": answer})
                side_options = {**options, "max_calls": max(1, inputs["max_calls"] // 2), "max_tokens": inputs["max_tokens"] // 2}
                report["sides"][side] = generate_isolated(**side_options, evaluation_cases=records)
                job.result = copy.deepcopy(report)
                job.progress = 60 if side == "baseline" else 90
                db.commit()
            report["campaign_id"] = campaign.id
        else:
            report = generate_isolated(**options)
        db.expire_all()
        _authorize(db, system_id=job.system_id, workspace=workspace, user=user)
        validate_generation_policy(db, system_id=job.system_id, workspace_id=workspace.id, inputs=inputs)
        if corpus_manifest(db, workspace.id, inputs["collection_ids"]) != manifest:
            raise ValueError("Corpus changed during generation")
        report["corpus_manifest"] = manifest
        report["corpus_sha256"] = digest(rows)
        report["coverage"] = {"chunks_examined": len(rows), "maximum_per_collection": 100,
                              "maximum_characters_per_chunk": 8000, "exhaustive": False}
        job.result, job.status, job.stage, job.progress = report, "completed", "review_required", 100
        job.completed_at = datetime.utcnow()
        db.commit()
        return {"job_id": job.id, "status": job.status}
    except Exception as exc:
        db.rollback()
        job = db.get(WorkspaceJob, job_id)
        if job:
            job.status, job.stage = "failed", "generation_unavailable"
            if getattr(exc, "usage", None):
                job.result = {**(job.result or {}), "failed_attempt_usage": exc.usage, "review_status": "not_approved"}
            job.error = "Generation unavailable, corpus changed, authorization withdrawn or worker budget exhausted. No cases were approved."
            if isinstance(exc, HTTPException):
                job.error = str(exc.detail)
            job.completed_at = datetime.utcnow()
            db.commit()
        return {"job_id": job_id, "status": "failed"}
    finally:
        db.close()


def serialize_campaign(campaign):
    return {name: getattr(campaign, name) for name in ("id", "system_id", "suite_id", "baseline_run_id", "job_id", "status", "method", "snapshot", "results", "created_at", "completed_at")}
