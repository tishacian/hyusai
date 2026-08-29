"""Structural and behavioural proof for the NAWA PR→PO MCP witness."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

import pytest

from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.chains.dag_validator import validate_flow
from app.services.connectors.mcp.flow import PR_TO_PO_SKILL_SLUGS, pr_to_po_flow
from app.services.connectors.mcp.poc import majority_supplier_format, select_next_pr
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
