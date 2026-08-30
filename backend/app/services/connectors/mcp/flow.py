"""PR to PO DAG. Skills stay Skills; the walker does not learn MCP."""

from __future__ import annotations

from typing import Any

from app.services.connectors.mcp.poc import (
    FORMAT_CODE,
    FORMAT_REQUIREMENTS,
    FORMAT_TEST_INPUT,
    MAJORITY_CODE,
    SELECT_PR_CODE,
)

PR_TO_PO_SKILL_SLUGS: tuple[str, ...] = (
    "sap_list_approved_prs_v1",
    "sap_check_budget_v1",
    "sap_get_justification_v1",
    "sap_reject_pr_v1",
    "hikma_list_pos_by_type_v1",
    "sap_create_po_v1",
    "sap_handle_rejection_v1",
    "azure_llm_v1",
    "python_recipe_v1",
    "audit_log_v1",
)


def _task(
    node_id: str,
    label: str,
    slug: str,
    *,
    description: str,
    params: dict[str, Any] | None = None,
    inputs_map: dict[str, Any] | None = None,
    extra_data: dict[str, Any] | None = None,
    x: int = 0,
    y: int = 200,
) -> dict[str, Any]:
    config: dict[str, Any] = {"skill_slug": slug}
    if params is not None:
        config["params"] = params
    if inputs_map is not None:
        config["inputs_map"] = inputs_map
    data: dict[str, Any] = {"description": description}
    if extra_data:
        data.update(extra_data)
    return {
        "id": node_id,
        "kind": "task",
        "type": "task",
        "label": label,
        "position": {"x": x, "y": y},
        "config": config,
        "data": data,
    }


def pr_to_po_flow() -> dict[str, Any]:
    """source.schedule → list → select one PR → budget path or HITL path → sink.

    One PR per tick: the existing ``loop`` kind only repeats a single skill,
    so a nested budget/HITL subgraph would be a new kind. The schedule
    (``0 */4 * * *``) picks the next remaining approved PR.
    """

    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "src",
                "kind": "source",
                "type": "source.schedule",
                "label": "Every 4 hours",
                "position": {"x": 40, "y": 220},
                "data": {
                    "description": (
                        "Cron 0 */4 * * * is table-driven via run_schedules. "
                        "Each fire processes the next approved PR."
                    )
                },
                "config": {"cron": "0 */4 * * *"},
            },
            _task(
                "task.list_prs",
                "List approved PRs (sap MCP)",
                "sap_list_approved_prs_v1",
                description="sap_list_approved_prs_v1 → sap MCP list_approved_prs. Not HANA.",
                x=280,
            ),
            _task(
                "task.select_pr",
                "Select next PR",
                "python_recipe_v1",
                description="Deterministic pick: run.input.pr_id or the first listed PR.",
                params={"code": SELECT_PR_CODE, "timeout_s": 15},
                inputs_map={
                    "prs": {"node_id": "task.list_prs", "path": ["prs"]},
                    "pr_id": {"node_id": "run", "path": ["input", "pr_id"]},
                },
                x=520,
            ),
            {
                "id": "decision.has_pr",
                "kind": "decision",
                "type": "decision",
                "label": "A PR remains",
                "position": {"x": 760, "y": 220},
                "data": {"description": "Empty list ends the tick without a write."},
                "config": {
                    "branches": [
                        {"label": "ready", "condition": "empty == False"},
                        {"label": "empty", "condition": "empty == True"},
                    ],
                    "inputs_map": {
                        "empty": {"node_id": "task.select_pr", "path": ["empty"]},
                        "pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]},
                    },
                },
            },
            _task(
                "task.budget",
                "Check budget (sap MCP)",
                "sap_check_budget_v1",
                description="sap_check_budget_v1 → sap MCP check_budget.",
                inputs_map={"pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]}},
                x=1000,
                y=80,
            ),
            _task(
                "task.justification",
                "Get justification (sap MCP)",
                "sap_get_justification_v1",
                description="sap_get_justification_v1 → sap MCP get_justification. Never auto-rejects.",
                inputs_map={"pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]}},
                x=1240,
                y=80,
            ),
            {
                "id": "decision.budget",
                "kind": "decision",
                "type": "decision",
                "label": "Budget",
                "position": {"x": 1480, "y": 80},
                "data": {
                    "description": "Only budget rejects without a human. Justification is summarised, never a reject."
                },
                "config": {
                    "branches": [
                        {"label": "ok", "condition": "budget_ok == True"},
                        {"label": "ko", "condition": "budget_ok == False"},
                    ],
                    "inputs_map": {
                        "budget_ok": {"node_id": "task.budget", "path": ["budget_ok"]}
                    },
                },
            },
            _task(
                "task.reject",
                "Reject PR (sap MCP write)",
                "sap_reject_pr_v1",
                description="sap_reject_pr_v1 → sap MCP reject_pr. Budget write, no HITL.",
                inputs_map={
                    "pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]},
                    "reason": {"node_id": "task.budget", "path": ["reason"]},
                },
                x=1720,
                y=320,
            ),
            _task(
                "task.hikma",
                "List POs by type (hikma MCP)",
                "hikma_list_pos_by_type_v1",
                description="hikma_list_pos_by_type_v1 → hikma MCP list_pos_by_type.",
                inputs_map={"pr_type": {"node_id": "task.select_pr", "path": ["pr_type"]}},
                x=1720,
                y=80,
            ),
            _task(
                "task.majority",
                "Majority supplier + format",
                "python_recipe_v1",
                description="Deterministic vote. The model does not invent a supplier.",
                params={"code": MAJORITY_CODE, "timeout_s": 15},
                inputs_map={
                    "pos": {"node_id": "task.hikma", "path": ["pos"]},
                    "pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]},
                    "pr": {"node_id": "task.select_pr", "path": ["pr"]},
                    "pr_type": {"node_id": "task.select_pr", "path": ["pr_type"]},
                    "justification": {"node_id": "task.justification", "path": ["justification"]},
                },
                x=1960,
                y=80,
            ),
            _task(
                "task.format_dossier",
                "Format dossier (custom env)",
                "python_recipe_v1",
                description=(
                    "Training node: python_recipe_v1 with a managed env "
                    f"({FORMAT_REQUIREMENTS}). Open the recipe workshop → "
                    "Environment → Prepare, then Test. Isolated Test does "
                    "not call SAP."
                ),
                extra_data={"workshop_test_input": FORMAT_TEST_INPUT},
                params={
                    "code": FORMAT_CODE,
                    "timeout_s": 30,
                    "requirements_text": FORMAT_REQUIREMENTS,
                },
                inputs_map={
                    "pr": {"node_id": "task.select_pr", "path": ["pr"]},
                    "pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]},
                    "supplier": {"node_id": "task.majority", "path": ["supplier"]},
                    "format": {"node_id": "task.majority", "path": ["format"]},
                    "vote_count": {"node_id": "task.majority", "path": ["vote_count"]},
                    "proposed_po": {"node_id": "task.majority", "path": ["proposed_po"]},
                    "summary_prompt": {"node_id": "task.majority", "path": ["summary_prompt"]},
                    "justification": {"node_id": "task.majority", "path": ["justification"]},
                },
                x=2200,
                y=80,
            ),
            _task(
                "task.summarise",
                "Summarise justification",
                "azure_llm_v1",
                description="azure_llm_v1 summarises. It does not reject.",
                inputs_map={
                    "prompt": {"node_id": "task.format_dossier", "path": ["summary_prompt"]}
                },
                x=2440,
                y=80,
            ),
            {
                "id": "hitl.approve_po",
                "kind": "hitl",
                "type": "policy",
                "label": "Approve PO in NAWA",
                "position": {"x": 2680, "y": 80},
                "data": {
                    "description": (
                        "Human gate in NAWA, not SAP. Upstream is the package. "
                        "Nothing is written to SAP until the next node."
                    )
                },
                "config": {
                    "prompt": (
                        "Approve creating this purchase order in SAP? "
                        "The package (PR, budget, justification summary, supplier, "
                        "format, formatted dossier) is in upstream."
                    ),
                    "prompt_kind": "approve_write",
                    "approvers": ["operator", "procurement"],
                    "expires_in_days": 1,
                    "expiry_action": "reject",
                    "inputs_map": {
                        "pr": {"node_id": "task.select_pr", "path": ["pr"]},
                        "pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]},
                        "budget": {"node_id": "task.budget", "path": ["budget_ok"]},
                        "justification": {"node_id": "task.justification", "path": ["justification"]},
                        "justification_summary": {"node_id": "task.summarise", "path": ["completion"]},
                        "supplier": {"node_id": "task.majority", "path": ["supplier"]},
                        "format": {"node_id": "task.majority", "path": ["format"]},
                        "proposed_po": {"node_id": "task.majority", "path": ["proposed_po"]},
                        "formatted": {"node_id": "task.format_dossier", "path": ["formatted"]},
                        "recipe_package": {
                            "node_id": "task.format_dossier",
                            "path": ["recipe_package"],
                        },
                    },
                },
            },
            {
                "id": "decision.hitl",
                "kind": "decision",
                "type": "decision",
                "label": "HITL verdict",
                "position": {"x": 2920, "y": 80},
                "data": {"description": "Approve writes a PO; reject calls handle_rejection."},
                "config": {
                    "branches": [
                        {"label": "approved", "condition": "hitl_approved == True"},
                        {"label": "rejected", "condition": "hitl_approved == False"},
                    ],
                    "inputs_map": {
                        "hitl_approved": {"node_id": "hitl.approve_po", "path": ["approved"]}
                    },
                },
            },
            _task(
                "task.create_po",
                "Create PO (sap MCP write)",
                "sap_create_po_v1",
                description="sap_create_po_v1 → sap MCP create_po. Trace server_id=sap.",
                inputs_map={
                    "pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]},
                    "supplier": {"node_id": "task.majority", "path": ["supplier"]},
                    "format": {"node_id": "task.majority", "path": ["format"]},
                    "amount": {"node_id": "task.select_pr", "path": ["pr", "amount"]},
                },
                x=3160,
                y=0,
            ),
            _task(
                "task.handle_rejection",
                "Handle rejection (sap MCP write)",
                "sap_handle_rejection_v1",
                description="sap_handle_rejection_v1 → sap MCP handle_rejection after human reject.",
                inputs_map={"pr_id": {"node_id": "task.select_pr", "path": ["pr_id"]}},
                x=3160,
                y=160,
            ),
            _task(
                "task.audit",
                "Audit ledger",
                "audit_log_v1",
                description="audit_log_v1 — NAWA ledger, not SAP.",
                params={"event_type": "procurement.pr_to_po", "details": {"source": "nawa_pr_to_po"}},
                x=3400,
                y=200,
            ),
            {
                "id": "sink.done",
                "kind": "sink",
                "label": "Done",
                "position": {"x": 3640, "y": 200},
                "data": {
                    "description": "Single strict sink. Empty ticks and completed ticks both land here."
                },
            },
        ],
        "edges": [
            {"from": "src", "to": "task.list_prs", "kind": "data"},
            {"from": "task.list_prs", "to": "task.select_pr", "kind": "data"},
            {"from": "task.select_pr", "to": "decision.has_pr", "kind": "data"},
            {"from": "decision.has_pr", "to": "sink.done", "kind": "branch", "branch_label": "empty"},
            {"from": "decision.has_pr", "to": "task.budget", "kind": "branch", "branch_label": "ready"},
            {"from": "task.budget", "to": "task.justification", "kind": "data"},
            {"from": "task.justification", "to": "decision.budget", "kind": "data"},
            {"from": "decision.budget", "to": "task.reject", "kind": "branch", "branch_label": "ko"},
            {"from": "decision.budget", "to": "task.hikma", "kind": "branch", "branch_label": "ok"},
            {"from": "task.reject", "to": "task.audit", "kind": "data"},
            {"from": "task.hikma", "to": "task.majority", "kind": "data"},
            {"from": "task.majority", "to": "task.format_dossier", "kind": "data"},
            {"from": "task.format_dossier", "to": "task.summarise", "kind": "data"},
            {"from": "task.summarise", "to": "hitl.approve_po", "kind": "data"},
            {"from": "hitl.approve_po", "to": "decision.hitl", "kind": "control"},
            {"from": "decision.hitl", "to": "task.create_po", "kind": "branch", "branch_label": "approved"},
            {"from": "decision.hitl", "to": "task.handle_rejection", "kind": "branch", "branch_label": "rejected"},
            {"from": "task.create_po", "to": "task.audit", "kind": "data"},
            {"from": "task.handle_rejection", "to": "task.audit", "kind": "data"},
            {"from": "task.audit", "to": "sink.done", "kind": "data"},
        ],
    }
