"""Structural and behavioural proof for the NAWA PR→PO MCP witness."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

import pytest

from app.core.config import settings
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chains.dag_validator import validate_flow
from app.services.connectors.mcp.flow import PR_TO_PO_SKILL_SLUGS, pr_to_po_flow
from app.services.connectors.mcp.poc import (
    FORMAT_CODE,
    FORMAT_REQUIREMENTS,
    FORMAT_TEST_INPUT,
    format_dossier,
    majority_supplier_format,
    select_next_pr,
)
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag, resume_run_dag, should_use_dag

FLOW = pr_to_po_flow()

PR_4401 = {
    "pr_id": "PR-4401",
    "pr_type": "IT_HARDWARE",
    "type": "IT_HARDWARE",
    "amount": 85_000,
    "currency": "QAR",
    "title": "Warehouse scanners",
}
PR_4402 = {
    "pr_id": "PR-4402",
    "pr_type": "IT_HARDWARE",
    "type": "IT_HARDWARE",
    "amount": 12_000,
    "currency": "QAR",
    "title": "Laptop replacements",
}

SkillFn = Callable[[Dict[str, Any], Dict[str, Any]], Any]


def _install_registry(monkeypatch: pytest.MonkeyPatch, skills: Dict[str, SkillFn]) -> None:
    def _resolve(slug: str) -> SkillFn:
        fn = skills.get(slug)
        if fn is None:
            raise NotImplementedError(f"flow reached an unexpected skill: {slug!r}")
        return fn

    monkeypatch.setattr(engine_module, "resolve_skill", _resolve)


def _mk_skill(db, slug: str) -> Skill:
    row = Skill(
        id=str(uuid.uuid4()),
        slug=slug,
        version="1",
        name=slug,
        description=f"stub {slug}",
        input_schema={},
        output_schema={},
        pricing={"unit_price": 0.0},
        execution={"mode": "sync", "timeout_ms": 5000, "retryable": True, "idempotent": True},
        certification_level="production",
    )
    db.add(row)
    db.commit()
    return row


def _mk_system(db) -> System:
    skills = [_mk_skill(db, slug) for slug in PR_TO_PO_SKILL_SLUGS]
    row = System(
        id=str(uuid.uuid4()),
        name="PR to PO",
        objective="PR to PO witness",
        skill_ids=[skill.id for skill in skills],
        flow_definition=FLOW,
        settings={"nawa_pr_to_po": True},
        execution_mode="human_augmented",
        coordination_pattern="graph",
        status="active",
        default_model="gpt-4o-mini",
    )
    db.add(row)
    db.commit()
    return row


def _mk_run(db, system: System, **extra: Any) -> Run:
    row = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        input_ref=dict(extra),
        status="pending",
    )
    db.add(row)
    db.commit()
    return row


def _reload(db, run: Run) -> Run:
    db.expire_all()
    return db.query(Run).filter(Run.id == run.id).one()


def _invocations(db, run: Run) -> List[SkillInvocation]:
    return db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()


def _slug_counts(db, run: Run) -> Counter:
    rows = _invocations(db, run)
    assert all(row.status == "completed" for row in rows), [
        (row.skill_slug, row.status, row.error) for row in rows
    ]
    return Counter(row.skill_slug for row in rows)


def _node_status(run: Run) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for cp in run.checkpoints or []:
        if cp.get("kind") == "node_end" and cp.get("node_id"):
            out[cp["node_id"]] = cp.get("status") or "completed"
    return out


def _pending_decision(db, summary: Dict[str, Any]) -> Decision:
    decision_id: Optional[str] = summary.get("awaiting_decision")
    assert decision_id, f"the HITL gate must expose its Decision: {summary}"
    return db.query(Decision).filter(Decision.id == decision_id).one()


def _registry(*, budget_ok: bool, listed: list[dict[str, Any]]) -> Dict[str, SkillFn]:
    writes: list[dict[str, Any]] = []

    async def list_prs(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "prs": listed,
            "count": len(listed),
            "server_id": "sap",
            "tool": "list_approved_prs",
            "contract_tool": "list_approved_prs",
            "credential_source": "workspace",
        }

    async def recipe(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        code = str((inp.get("_recipe") or {}).get("code") or "")
        if "tabulate" in code or "formatted" in code:
            return format_dossier(inp)
        if "pos" in inp:
            return majority_supplier_format(inp)
        return select_next_pr(inp)

    async def budget(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "pr_id": inp.get("pr_id"),
            "budget_ok": budget_ok,
            "reason": "ok" if budget_ok else "Requested amount exceeds remaining cost-center budget",
            "server_id": "sap",
            "tool": "check_budget",
            "contract_tool": "check_budget",
        }

    async def justification(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "pr_id": inp.get("pr_id"),
            "justification": "Finance laptops are past refresh.",
            "server_id": "sap",
            "tool": "get_justification",
            "contract_tool": "get_justification",
        }

    async def reject(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        writes.append({"slug": "sap_reject_pr_v1", **inp})
        return {
            "pr_id": inp.get("pr_id"),
            "rejected": True,
            "server_id": "sap",
            "tool": "reject_pr",
            "contract_tool": "reject_pr",
        }

    async def hikma(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "pos": [
                {"supplier": "ACME", "format": "XML"},
                {"supplier": "ACME", "format": "XML"},
                {"supplier": "BETA", "format": "EDI"},
            ],
            "pr_type": inp.get("pr_type"),
            "server_id": "hikma",
            "tool": "list_pos_by_type",
            "contract_tool": "list_pos_by_type",
        }

    async def summarise(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        assert inp.get("prompt"), "azure_llm_v1 must receive the summary prompt"
        return {"completion": "Refresh six finance laptops with a shared docking format."}

    async def create_po(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        writes.append({"slug": "sap_create_po_v1", **inp})
        return {
            "po_id": f"PO-{inp.get('pr_id')}",
            "created": True,
            "server_id": "sap",
            "tool": "create_po",
            "contract_tool": "create_po",
        }

    async def handle(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        writes.append({"slug": "sap_handle_rejection_v1", **inp})
        return {
            "pr_id": inp.get("pr_id"),
            "handled": True,
            "server_id": "sap",
            "tool": "handle_rejection",
            "contract_tool": "handle_rejection",
        }

    async def audit(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": "audit-pr-to-po", "status": "recorded"}

    return {
        "sap_list_approved_prs_v1": list_prs,
        "python_recipe_v1": recipe,
        "sap_check_budget_v1": budget,
        "sap_get_justification_v1": justification,
        "sap_reject_pr_v1": reject,
        "hikma_list_pos_by_type_v1": hikma,
        "azure_llm_v1": summarise,
        "sap_create_po_v1": create_po,
        "sap_handle_rejection_v1": handle,
        "audit_log_v1": audit,
        "_writes": writes,  # type: ignore[dict-item]
    }


def test_flow_has_no_validator_errors_and_routes_to_dag() -> None:
    errors = [issue.to_dict() for issue in validate_flow(FLOW) if issue.level == "error"]
    assert errors == [], errors
    assert FLOW["schema_version"] >= 3
    kinds = {node["kind"] for node in FLOW["nodes"]}
    assert {"decision", "hitl", "source"} <= kinds
    assert should_use_dag(System(flow_definition=FLOW)) is True
    slugs = {
        (node.get("config") or {}).get("skill_slug")
        for node in FLOW["nodes"]
        if (node.get("config") or {}).get("skill_slug")
    }
    assert "sap_hana_query_v1" not in slugs
    assert "rpa_dispatch_v1" not in slugs
    assert {"sap_list_approved_prs_v1", "sap_create_po_v1", "hikma_list_pos_by_type_v1"} <= slugs
    src = next(node for node in FLOW["nodes"] if node["id"] == "src")
    assert src["type"] == "source.schedule"
    assert src["config"]["cron"] == "0 */4 * * *"
    assert {node["id"] for node in FLOW["nodes"]} >= {
        "task.select_pr",
        "task.majority",
        "task.format_dossier",
    }
    assert len(FLOW["nodes"]) == 18
    assert len(FLOW["edges"]) == 20
    hikma = next(node for node in FLOW["nodes"] if node["id"] == "task.hikma")
    hikma_inputs = (hikma.get("config") or {}).get("inputs_map") or {}
    assert "MaterialGroup" in hikma_inputs
    assert "pr_type" in hikma_inputs
    create = next(node for node in FLOW["nodes"] if node["id"] == "task.create_po")
    description = str((create.get("data") or {}).get("description") or "").lower()
    assert "sealed" in description
    assert "write gate" in description
    # Every write node takes the run-level guardrail; a scheduled tick may omit it.
    for node_id in ("task.create_po", "task.reject", "task.handle_rejection"):
        node = next(item for item in FLOW["nodes"] if item["id"] == node_id)
        ref = node["config"]["inputs_map"]["disabled_tools"]
        assert ref["path"] == ["input", "disabled_tools"]
        assert ref["required"] is False
    hitl = next(node for node in FLOW["nodes"] if node["id"] == "hitl.approve_po")
    hitl_inputs = hitl["config"]["inputs_map"]
    assert {"candidates", "total_open", "price_missing", "payment_terms", "incoterms"} <= set(hitl_inputs)


def test_format_dossier_node_declares_a_managed_env() -> None:
    node = next(item for item in FLOW["nodes"] if item["id"] == "task.format_dossier")
    params = (node.get("config") or {}).get("params") or {}
    assert params["requirements_text"] == FORMAT_REQUIREMENTS
    assert "tabulate" in FORMAT_REQUIREMENTS
    assert "import tabulate" in FORMAT_CODE
    assert params["code"] == FORMAT_CODE
    assert params["timeout_s"] == 30
    assert (node.get("config") or {}).get("skill_slug") == "python_recipe_v1"
    assert (node.get("data") or {}).get("workshop_test_input") == FORMAT_TEST_INPUT
    assert '"supplier":"ACME"' in FORMAT_TEST_INPUT
    majority = next(item for item in FLOW["nodes"] if item["id"] == "task.majority")
    select = next(item for item in FLOW["nodes"] if item["id"] == "task.select_pr")
    assert "requirements_text" not in ((majority.get("config") or {}).get("params") or {})
    assert "requirements_text" not in ((select.get("config") or {}).get("params") or {})
    assert any(
        edge["from"] == "task.majority" and edge["to"] == "task.format_dossier"
        for edge in FLOW["edges"]
    )
    assert any(
        edge["from"] == "task.format_dossier" and edge["to"] == "task.summarise"
        for edge in FLOW["edges"]
    )


def test_format_dossier_helper_exposes_the_training_keys() -> None:
    compiled = majority_supplier_format(
        {
            "pos": [
                {"supplier": "ACME", "format": "XML"},
                {"supplier": "ACME", "format": "XML"},
                {"supplier": "BETA", "format": "EDI"},
            ],
            "pr": PR_4402,
            "pr_id": "PR-4402",
            "pr_type": "IT_HARDWARE",
            "justification": "Finance laptops are past refresh.",
        }
    )
    dossier = format_dossier(compiled)
    assert dossier["recipe_package"] == "tabulate"
    assert dossier["supplier"] == "ACME"
    assert dossier["format"] == "XML"
    assert dossier["pr_id"] == "PR-4402"
    assert "ACME" in dossier["formatted"]
    assert "PR-4402" in dossier["formatted"]
    assert dossier["summary_prompt"]


def test_znpr_uses_most_recent_plant_po_and_zlpo() -> None:
    compiled = majority_supplier_format(
        {
            "pos": [
                {
                    "Supplier": "1000000018",
                    "PurchaseOrderType": "ZSVO",
                    "PurchasingGroup": "013",
                    "PaymentTerms": "ZAPS",
                    "IncotermsClassification": "DDP",
                },
                {
                    "Supplier": "1000000661",
                    "PurchaseOrderType": "ZLPO",
                    "PurchasingGroup": "013",
                    "PaymentTerms": "ZAPS",
                    "IncotermsClassification": "DDP",
                },
                {
                    "Supplier": "1000000661",
                    "PurchaseOrderType": "ZLPO",
                    "PurchasingGroup": "013",
                    "PaymentTerms": "ZAPS",
                    "IncotermsClassification": "DDP",
                },
            ],
            "pr": {
                "PurchaseRequisition": "2000276449",
                "Plant": "1000",
                "PurReqnItemCurrency": "SYP",
                "PurchaseRequisitionType": "ZNPR",
            },
            "pr_id": "2000276449",
            "pr_type": "ZNPR",
        }
    )
    assert compiled["supplier"] == "1000000018"
    assert compiled["format"] == "ZLPO"
    assert compiled["proposed_po"]["currency"] == "SYP"
    assert compiled["proposed_po"]["plant"] == "1000"
    assert compiled["purch_group"] == "013"


@pytest.mark.asyncio
async def test_over_budget_rejects_without_hitl(db_session, monkeypatch):
    skills = _registry(budget_ok=False, listed=[PR_4401, PR_4402])
    writes = skills.pop("_writes")
    _install_registry(monkeypatch, skills)
    system = _mk_system(db_session)
    run = _mk_run(db_session, system, pr_id="PR-4401")
    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary
    run = _reload(db_session, run)
    counts = _slug_counts(db_session, run)
    assert counts["sap_reject_pr_v1"] == 1
    assert counts.get("sap_create_po_v1", 0) == 0
    assert counts.get("sap_handle_rejection_v1", 0) == 0
    assert counts.get("hikma_list_pos_by_type_v1", 0) == 0
    assert "hitl_pause" not in [cp.get("kind") for cp in (run.checkpoints or [])]
    assert writes[0]["slug"] == "sap_reject_pr_v1"
    assert writes[0]["pr_id"] == "PR-4401"
    statuses = _node_status(run)
    assert statuses["task.reject"] == "completed"
    assert statuses.get("hitl.approve_po") in (None, "skipped")
    assert statuses.get("task.create_po") in (None, "skipped")


@pytest.mark.asyncio
async def test_in_budget_pauses_then_create_po_on_approve(db_session, monkeypatch):
    skills = _registry(budget_ok=True, listed=[PR_4402])
    writes = skills.pop("_writes")
    _install_registry(monkeypatch, skills)
    system = _mk_system(db_session)
    run = _mk_run(db_session, system, pr_id="PR-4402")
    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending", paused
    run = _reload(db_session, run)
    decision = _pending_decision(db_session, paused)
    upstream = decision.rationale.get("upstream") if isinstance(decision.rationale, dict) else {}
    assert upstream.get("supplier") == "ACME"
    assert upstream.get("format") == "XML"
    assert upstream.get("recipe_package") == "tabulate"
    assert "ACME" in str(upstream.get("formatted") or "")
    assert "create_po" not in str(writes)
    decision.status = "accepted"
    db_session.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed", resumed
    run = _reload(db_session, run)
    counts = _slug_counts(db_session, run)
    assert counts["sap_create_po_v1"] == 1
    assert counts.get("sap_reject_pr_v1", 0) == 0
    assert counts.get("sap_handle_rejection_v1", 0) == 0
    create = next(item for item in writes if item["slug"] == "sap_create_po_v1")
    assert create["pr_id"] == "PR-4402"
    invocation = next(
        row for row in _invocations(db_session, run) if row.skill_slug == "sap_create_po_v1"
    )
    stored = invocation.output_ref if isinstance(invocation.output_ref, dict) else {}
    assert stored.get("server_id") == "sap"
    statuses = _node_status(run)
    assert statuses["task.create_po"] == "completed"
    assert statuses["task.handle_rejection"] == "skipped"


@pytest.mark.asyncio
async def test_human_reject_calls_handle_rejection(db_session, monkeypatch):
    skills = _registry(budget_ok=True, listed=[PR_4402])
    writes = skills.pop("_writes")
    _install_registry(monkeypatch, skills)
    system = _mk_system(db_session)
    run = _mk_run(db_session, system, pr_id="PR-4402")
    paused = await execute_run_dag(run.id)
    decision = _pending_decision(db_session, paused)
    decision.status = "rejected"
    db_session.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed", resumed
    run = _reload(db_session, run)
    counts = _slug_counts(db_session, run)
    assert counts["sap_handle_rejection_v1"] == 1
    assert counts.get("sap_create_po_v1", 0) == 0
    assert writes[-1]["slug"] == "sap_handle_rejection_v1"
    statuses = _node_status(run)
    assert statuses["task.handle_rejection"] == "completed"
    assert statuses["task.create_po"] == "skipped"


_FORMAT_INPUT = {
    "pr": PR_4402,
    "pr_id": "PR-4402",
    "supplier": "ACME",
    "format": "XML",
    "vote_count": 2,
    "proposed_po": {"pr_id": "PR-4402", "supplier": "ACME", "format": "XML"},
    "summary_prompt": "Summarise this purchase-requisition justification.",
    "justification": "Finance laptops are past refresh.",
}


def _workspace(db) -> Workspace:
    row = Workspace(
        id=str(uuid.uuid4()),
        name="Recipe training",
        slug=f"recipe-train-{uuid.uuid4().hex[:8]}",
        settings={},
    )
    db.add(row)
    db.commit()
    return row


def test_format_code_fails_closed_in_an_empty_managed_env(db_session, monkeypatch, tmp_path):
    """stdlib-only venv cannot import tabulate — that is the custom-env proof."""

    from app.models.recipe import RecipeExecution
    from app.services.recipe_envs import build_env, build_env_spec, resolve_env
    from app.services.recipe_executions import create_execution, run_recipe_execution

    monkeypatch.setattr(settings, "recipe_execution_enabled", True)
    monkeypatch.setattr(settings, "recipe_envs_path", str(tmp_path / "envs"))
    workspace = _workspace(db_session)
    env = resolve_env(db_session, workspace_id=workspace.id, spec=build_env_spec())
    db_session.commit()
    built = build_env(db_session, env.id)
    assert built.status == "ready"
    execution = create_execution(
        db_session,
        workspace_id=workspace.id,
        env=built,
        code=FORMAT_CODE,
        inputs=_FORMAT_INPUT,
        timeout_s=30,
        node_id="task.format_dossier",
    )
    db_session.commit()
    run_recipe_execution(execution.id, FORMAT_CODE)
    db_session.expire_all()
    settled = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert settled.status == "failed"
    evidence = f"{settled.error or ''}\n{settled.stderr_tail or ''}"
    assert "tabulate" in evidence.lower()


def test_format_code_runs_in_the_tabulate_managed_env(db_session, monkeypatch, tmp_path):
    """The training path: declare tabulate, the platform builds the venv, the script runs."""

    from app.models.recipe import RecipeExecution
    from app.services.recipe_envs import build_env, build_env_spec, resolve_env
    from app.services.recipe_executions import create_execution, run_recipe_execution

    monkeypatch.setattr(settings, "recipe_execution_enabled", True)
    monkeypatch.setattr(settings, "recipe_envs_path", str(tmp_path / "envs"))
    workspace = _workspace(db_session)
    spec = build_env_spec(requirements_text=FORMAT_REQUIREMENTS)
    assert "tabulate" in spec.requirements_text
    env = resolve_env(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    built = build_env(db_session, env.id)
    assert built.status == "ready", built.build_error or built.build_log_tail
    assert built.requirements_text
    execution = create_execution(
        db_session,
        workspace_id=workspace.id,
        env=built,
        code=FORMAT_CODE,
        inputs=_FORMAT_INPUT,
        timeout_s=30,
        node_id="task.format_dossier",
    )
    db_session.commit()
    run_recipe_execution(execution.id, FORMAT_CODE)
    db_session.expire_all()
    settled = db_session.query(RecipeExecution).filter_by(id=execution.id).one()
    assert settled.status == "succeeded", settled.error or settled.stderr_tail
    output = settled.output_json if isinstance(settled.output_json, dict) else {}
    assert output.get("recipe_package") == "tabulate"
    assert output.get("recipe_package_version")
    assert output.get("supplier") == "ACME"
    assert "ACME" in str(output.get("formatted") or "")
    assert "PR-4402" in str(output.get("formatted") or "")
