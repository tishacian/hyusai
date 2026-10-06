"""Read-only Luma activity. Demo projections never become observed human value."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

from sqlalchemy.orm import selectinload

from app.models.run import Run
from app.services import ecommerce_claims as claims
from app.services.run_access import readable_runs

LIMIT = 200
BINDING = "showcase.claims.investigate"
ASSUMPTIONS = {
    "nature": "declared_demo_assumptions",
    "manual_minutes": 8,
    "assisted_minutes": 2,
    "hourly_eur": "40.00",
    "incremental_eur_per_case": "0.50",
}


def _amount(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def _seconds(value):
    result = _amount(value)
    return float(result / 1000) if result is not None else None


def _rule_match(run, config):
    """Compare the native guarded proposal to the frozen demo rubric.

    This is an automatic rule check, never an independent human review. The
    immutable snapshot maps document references to the citations actually used.
    """
    claim_id = (run.input_ref or {}).get("claim_id")
    expected = next(
        (
            pair.get(condition + "_expected")
            for pair in (config.get("benchmark") or {}).get("pairs", [])
            for condition in ("manual", "assisted")
            if pair.get(condition + "_claim_id") == claim_id
        ),
        None,
    )
    if expected is None:
        return None
    outputs = {
        call.skill_slug: call.output_ref or {}
        for call in run.invocations
        if call.status == "completed"
    }
    proposal = outputs.get(claims.SKILLS["propose"], {})
    snapshot = outputs.get(claims.SKILLS["snapshot"], {})
    if not proposal:
        return None
    docs = (snapshot.get("data") or {}).get("documents", [])
    # Citations use the Document Center identity, not the KnowledgeSource id.
    references = set()
    for mode in ("policy", "delivery", "refund"):
        evidence = outputs.get(claims.SKILLS[mode], {})
        cited = {c.get("document_id") for c in proposal.get("citations", [])}
        references.update(
            passage.get("reference")
            for passage in evidence.get("results", [])
            if (passage.get("metadata") or {}).get("document_id") in cited
        )
    return bool(
        proposal.get("evidence_kind") == "synthetic_demo"
        and proposal.get("claim_id") == claim_id
        and proposal.get("snapshot_sha256")
        == (snapshot.get("provenance") or {}).get("snapshot_sha256")
        and proposal.get("snapshot_sha256")
        and proposal.get("action") == expected["action"]
        and _amount(proposal.get("amount")) == _amount(expected["amount"])
        and _amount(proposal.get("amount")) is not None
        and set(expected["references"]) <= references
        and set(expected["references"]) <= {d.get("document_key") for d in docs}
    )


def summarize_runs(runs, config):
    """All attempts remain in the ledger; repeated claims do not create volume."""
    entries, totals = [], defaultdict(Decimal)
    priced_calls = unpriced_calls = 0
    latest = {}
    receipts = set()
    tool_seconds = []
    for run in runs:
        calls = run.invocations
        for call in calls:
            receipt = call.output_ref or {}
            if (
                call.skill_slug == claims.SKILLS["simulate"]
                and call.status == "completed"
                and receipt.get("status") == "simulated"
                and receipt.get("evidence_kind") == "synthetic_demo"
                and receipt.get("external_payment_called") is False
                and receipt.get("receipt_id")
            ):
                receipts.add(receipt["receipt_id"])
        costs = defaultdict(Decimal)
        missing = 0
        durations = [_seconds(c.latency_ms) for c in calls]
        duration = sum(v for v in durations if v is not None)
        if calls and all(v is not None for v in durations):
            tool_seconds.append(duration)
        else:
            duration = None
        for call in calls:
            evidence = (call.metrics or {}).get("cost_evidence") or {}
            currency = evidence.get("currency")
            amount = _amount(call.cost)
            if (
                call.status in {"completed", "failed", "cancelled"}
                and call.cost_measured is True
                and evidence.get("state") in {"calculated", "measured"}
                and currency in {"EUR", "USD"}
                and amount is not None
            ):
                costs[currency] += amount
                totals[currency] += amount
                priced_calls += 1
            else:
                missing += 1
                unpriced_calls += 1
        proposal = next(
            (
                c.output_ref or {}
                for c in reversed(calls)
                if c.skill_slug == claims.SKILLS["propose"] and c.status == "completed"
            ),
            {},
        )
        claim_id = (run.input_ref or {}).get("claim_id")
        match = _rule_match(run, config)
        elapsed = (
            max(0, (run.completed_at - run.started_at).total_seconds())
            if run.completed_at and run.started_at
            else None
        )
        entry = {
            "run_id": run.id,
            "claim_id": claim_id,
            "status": run.status,
            "reason": "duplicate_action"
            if getattr(run, "error", None) == "CLAIM_ACTION_ALREADY_RECORDED"
            else "missing_information"
            if proposal.get("action") == "request_information"
            else None,
            "started_at": run.started_at.isoformat(),
            "action": proposal.get("action"),
            "amount": proposal.get("amount"),
            "automatic_rule_match": match,
            "invocations": len(calls),
            "technical_seconds": duration,
            "elapsed_seconds": elapsed,
            "priced_subtotals": {k: str(v) for k, v in costs.items()},
            "unpriced_invocations": missing,
            "flow_version_id": run.published_flow_version_id,
            "flow_sha256": run.flow_sha256,
        }
        entries.append(entry)
        if claim_id and (claim_id not in latest or run.started_at > latest[claim_id][0]):
            latest[claim_id] = (run.started_at, entry)
    statuses = Counter(entry["status"] for entry in entries)
    return {
        "evidence_kind": "synthetic_demo_activity",
        "production_baseline_eligible": False,
        "assumptions": dict(ASSUMPTIONS),
        "counts": {
            "attempts": len(runs),
            "completed": statuses["completed"],
            "failed": statuses["failed"] + statuses["cancelled"],
            "duplicate_blocked": sum(e["reason"] == "duplicate_action" for e in entries),
            "pending": sum(
                v for k, v in statuses.items() if k not in {"completed", "failed", "cancelled"}
            ),
            "unique_cases": len(latest),
            "rule_matched_cases": sum(
                e["automatic_rule_match"] is True for _, e in latest.values()
            ),
            "simulated_receipts": len(receipts),
            "waiting_information_cases": sum(
                e["action"] == "request_information" for _, e in latest.values()
            ),
            "invocations": priced_calls + unpriced_calls,
        },
        "catalog_costs": {
            "state": "partial" if unpriced_calls or not priced_calls else "catalog_priced",
            "by_currency": {k: str(v) for k, v in totals.items()},
            "priced_invocations": priced_calls,
            "unpriced_invocations": unpriced_calls,
            "includes_infrastructure_licence_integration": False,
        },
        "median_technical_seconds": median(tool_seconds) if tool_seconds else None,
        "runs": entries,
    }


def activity(db, workspace, user, *, experience_id, system_id, since=None):
    config = claims._config(workspace)
    now = datetime.utcnow()
    since = since or now - timedelta(days=7)
    candidates = (
        db.query(Run)
        .options(selectinload(Run.invocations))
        .filter(
            Run.workspace_id == workspace.id,
            Run.system_id == system_id,
            Run.started_at >= since,
            Run.input_ref["_ingress"]["adapter"]["experience_id"].as_string() == experience_id,
            Run.input_ref["_ingress"]["adapter"]["binding_key"].as_string() == BINDING,
            Run.input_ref["claim_id"].as_string().in_(config["allowed_claim_ids"]),
        )
        .order_by(Run.started_at.desc(), Run.id.asc())
        .limit(LIMIT + 1)
        .all()
    )
    visible = readable_runs(db, runs=candidates, user=user, workspace=workspace)
    result = summarize_runs(visible[:LIMIT], config)
    result["period"] = {
        "since": since.isoformat(),
        "until": now.isoformat(),
        "limited": len(candidates) > LIMIT,
    }
    result["system_id"] = system_id
    return result
