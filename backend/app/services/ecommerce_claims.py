"""Evidence-driven claim tools for the canonical AgentLoop and HITL runtime.

The planner chooses tools. The server validates proofs, amounts and approval;
no model output or caller-supplied observation authorizes a refund.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
    WORKSPACE_REVIEWER,
    normalize_role_template,
)
from app.models.claim_action import ClaimAction
from app.models.decision import Decision
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace, WorkspaceMember
from app.services.collection_access import require_named_collection_read
from app.services.connectors.generic import postgresql_claims as pg

SKILLS = {
    "snapshot": "postgresql_claim_snapshot_v1",
    "policy": "ecommerce_policy_evidence_v1",
    "delivery": "ecommerce_delivery_evidence_v1",
    "refund": "ecommerce_refund_evidence_v1",
    "propose": "ecommerce_resolution_propose_v1",
    "simulate": "ecommerce_resolution_simulate_v1",
}


def _config(workspace):
    settings = workspace.settings or {}
    if (settings.get("features") or {}).get("ecommerce_claims_v1") is not True:
        raise ValueError("ECOMMERCE_CLAIMS_DISABLED")
    config = settings.get("ecommerce_claims") or {}
    if (
        not config.get("allowed_claim_ids")
        or not config.get("policy_sha256")
        or not config.get("allowed_collection_slugs")
    ):
        raise ValueError("ECOMMERCE_CLAIMS_NOT_CONFIGURED")
    return config


def _run(db, ctx):
    workspace = db.query(Workspace).filter(Workspace.id == ctx.get("workspace_id")).one_or_none()
    run = (
        db.query(Run)
        .filter(Run.id == ctx.get("run_id"), Run.workspace_id == ctx.get("workspace_id"))
        .one_or_none()
    )
    if workspace is None or run is None:
        raise ValueError("CLAIM_RUN_REQUIRED")
    config = _config(workspace)
    claim_id = pg.validate_claim_id((run.input_ref or {}).get("claim_id"))
    if claim_id not in config["allowed_claim_ids"]:
        raise ValueError("CLAIM_OUTSIDE_DEMO_COHORT")
    return workspace, run, config, claim_id


def _recorded(db, run, mode):
    row = (
        db.query(SkillInvocation)
        .filter(
            SkillInvocation.run_id == run.id,
            SkillInvocation.skill_slug == SKILLS[mode],
            SkillInvocation.status == "completed",
        )
        .order_by(SkillInvocation.started_at.desc())
        .first()
    )
    return dict(row.output_ref or {}) if row else None


def _sources(db, workspace, run, snapshot, modes):
    refs = snapshot["data"]["documents"]
    wanted = {
        "policy": {"policy", "decision_guide", "procedure", "contract"},
        "delivery": {"customer_claim", "delivery_receipt", "carrier_loss_confirmation"},
        "refund": {"customer_claim", "refund_receipt"},
    }
    types = set().union(*(wanted[mode] for mode in modes))
    sources = []
    for ref in refs:
        if ref["document_type"] not in types:
            continue
        source = (
            db.query(KnowledgeCollectionSource)
            .filter(
                KnowledgeCollectionSource.id == ref["knowledge_source_id"],
                KnowledgeCollectionSource.workspace_id == workspace.id,
            )
            .one_or_none()
        )
        if source is None or source.status != "ready":
            continue
        meta = source.source_metadata or {}
        if source.filename != ref["source_filename"] or meta.get("content_sha256") != ref["sha256"]:
            raise ValueError("CLAIM_SOURCE_REVISION_CHANGED")
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id == source.collection_id,
                KnowledgeCollection.workspace_id == workspace.id,
            )
            .one()
        )
        if collection.slug not in _config(workspace)["allowed_collection_slugs"]:
            raise ValueError("CLAIM_SOURCE_OUTSIDE_CONTRACT")
        require_named_collection_read(
            db,
            workspace=workspace,
            user_id=run.initiated_by_user_id,
            collection_ref=collection.slug,
        )
        sources.append((ref, source, collection))
    return sources


async def _evidence(db, workspace, run, config, snapshot, mode, ctx):
    from app.services.evaluation.judge import (
        contractual_zero_token_usage,
        new_provider_usage_accumulator,
        provider_usage_evidence,
        record_provider_usage,
    )
    from app.services.skills_registry.wrappers import _semantic_search_v1

    results, citations, refs_seen = [], [], set()
    usage = new_provider_usage_accumulator()
    collection_sources = [
        source for source in ctx.get("_flow_data_sources", []) if source.get("collection_slug")
    ]
    flow = getattr(run, "flow_snapshot", None) or {}
    explicit_sources = (flow.get("runtime_contract") or {}).get(
        "requires_postgresql_source"
    ) is True
    explicit_sources = explicit_sources or any(
        node.get("kind") == "asset" and (node.get("config") or {}).get("collection_slug")
        for node in flow.get("nodes", [])
    )
    used_sources = []
    for ref, source, collection in _sources(db, workspace, run, snapshot, (mode,)):
        if collection_sources or explicit_sources:
            matches = [
                item for item in collection_sources if item["collection_slug"] == collection.slug
            ]
            if not matches:
                raise ValueError("CLAIM_SOURCE_OUTSIDE_FLOW_BINDING")
            for item in matches:
                if item not in used_sources:
                    used_sources.append(item)
        doc_id = (source.source_metadata or {}).get("document_id")
        if not doc_id:
            continue
        frozen_scope = ctx.get("retrieval_contract") or {}
        if frozen_scope.get("asset_binding") == "authoritative":
            declared = frozen_scope.get("collection") or frozen_scope.get("context_collection")
            if declared != collection.slug:
                raise ValueError("CLAIM_SOURCE_OUTSIDE_RETRIEVAL_CONTRACT")
        retrieval_ctx = {
            **ctx,
            "workspace_slug": workspace.slug,
            "user_id": run.initiated_by_user_id,
            "retrieval_contract": {
                "asset_binding": "authoritative",
                "collection": collection.slug,
                "empty_bound_collection": "abstain",
                "allow_workspace_fallback": False,
            },
        }
        found = await _semantic_search_v1(
            {
                "query": f"{snapshot['data']['context'][0]['order_id']} {ref['source_filename']} règles faits justificatifs",
                "context_collection": collection.slug,
                "top_k": 12,
                "retrieval_filters": {"document_id": doc_id},
            },
            retrieval_ctx,
        )
        # Preserve provider usage of every nested retrieval, including retries.
        reported = found.get("usage") or {}
        if reported.get("measurement_coverage") == "complete" and (
            reported.get("calls") or reported.get("provider_calls") == 0
        ):
            for call in reported.get("calls") or []:
                record_provider_usage(
                    usage, call, provider=call.get("provider"), model=call.get("model")
                )
        else:
            # An incomplete nested call cannot become a measured zero.
            usage["calls"].append({"provider": "retrieval", "model": "unknown", "reported": False})
        for item in found.get("results") or []:
            meta = item.get("metadata") or {}
            if meta.get("document_id") != doc_id or meta.get("content_sha256") != ref["sha256"]:
                continue
            refs_seen.add(ref["document_key"])
            results.append(
                {"reference": ref["document_key"], "content": item["content"], "metadata": meta}
            )
            citations.append(
                {
                    "title": ref["source_filename"],
                    "source": collection.slug,
                    "document_id": doc_id,
                    "page": meta.get("page"),
                    "collection": collection.slug,
                    "filename": ref["source_filename"],
                    "content": item["content"],
                    "chunk_index": meta.get("chunk_index"),
                    "sha256": ref["sha256"],
                }
            )
    accounting = (
        provider_usage_evidence(usage)
        if usage["calls"]
        else (
            contractual_zero_token_usage("ecommerce:scoped_retrieval_without_provider_call")
            if results
            else provider_usage_evidence(usage)
        )
    )
    return {
        "results": results,
        "citations": citations,
        "references": sorted(refs_seen),
        "data_sources": used_sources,
        "snapshot_sha256": snapshot["provenance"]["snapshot_sha256"],
        "evidence_kind": "synthetic_demo",
        **accounting,
    }


def propose(snapshot, evidence, config):
    """Independent, deterministic guard over the actual retrieved passages."""
    data, provenance = snapshot["data"], snapshot["provenance"]
    order = data["context"][0]
    passages = [p for group in evidence for p in (group or {}).get("results", [])]
    refs = {p["reference"] for p in passages}
    policy = next((r for r in data["documents"] if r["document_key"] == "refund-policy-v2"), None)
    required = {"refund-policy-v2"}
    if not policy or policy["sha256"] != config["policy_sha256"] or policy["version"] != "2":
        raise ValueError("CLAIM_POLICY_REVISION_INVALID")
    if order["ordered_at"][:10] < policy["effective_from"]:
        raise ValueError("CLAIM_POLICY_NOT_APPLICABLE")
    if any(
        group and group.get("snapshot_sha256") != provenance["snapshot_sha256"]
        for group in evidence
    ):
        raise ValueError("CLAIM_EVIDENCE_SNAPSHOT_MISMATCH")
    paid = Decimal(order["paid_amount"])
    executed = [r for r in data["refunds"] if r["status"] == "executed"]
    if order["currency"] != "EUR" or any(r["currency"] != "EUR" for r in data["refunds"]):
        raise ValueError("CLAIM_CURRENCY_UNSUPPORTED")
    amounts = [Decimal(r["amount"]) for r in executed]
    if any(not a.is_finite() or a < 0 for a in amounts):
        raise ValueError("CLAIM_AMOUNT_INVALID")
    refunded = sum(amounts, Decimal(0))
    if (
        not paid.is_finite()
        or not refunded.is_finite()
        or paid < 0
        or refunded < 0
        or refunded > paid
    ):
        raise ValueError("CLAIM_AMOUNT_INVALID")
    action, reason, amount = "request_information", "missing_evidence", Decimal(0)
    case_refs = [r for r in data["documents"] if r["order_id"] == order["order_id"]]
    if executed:
        required.update(
            r["document_key"] for r in case_refs if r["document_type"] == "refund_receipt"
        )
        if not any(r["document_type"] == "refund_receipt" for r in case_refs):
            required.add("missing_refund_receipt")
        receipt_text = " ".join(
            p["content"]
            for p in passages
            if any(
                r["document_key"] == p["reference"] and r["document_type"] == "refund_receipt"
                for r in case_refs
            )
        )
        if order["order_id"] not in receipt_text or any(
            r["refund_id"] not in receipt_text for r in executed
        ):
            required.add("missing_matching_refund_receipt")
        if paid == refunded:
            action, reason = "close_duplicate", "already_refunded"
    elif order["payment_status"] == "paid":
        shipment = data["shipments"][0] if data["shipments"] else None
        if shipment and shipment["status"] == "lost":
            required.update(
                r["document_key"]
                for r in case_refs
                if r["document_type"] == "carrier_loss_confirmation"
            )
            loss = " ".join(
                p["content"]
                for p in passages
                if any(
                    r["document_key"] == p["reference"]
                    and r["document_type"] == "carrier_loss_confirmation"
                    for r in case_refs
                )
            )
            if (
                shipment["tracking_id"] in loss
                and order["order_id"] in loss
                and ("perte" in loss.lower() or "colis perdu" in loss.lower())
            ):
                action, reason, amount = "refund", "carrier_loss_confirmed", paid - refunded
            else:
                required.add("missing_loss_confirmation")
        elif shipment and shipment["status"] == "delivered":
            receipts = [r for r in case_refs if r["document_type"] == "delivery_receipt"]
            required.update(r["document_key"] for r in receipts)
            if not receipts:
                required.add("missing_delivery_receipt")
            receipt_text = " ".join(
                p["content"]
                for p in passages
                if p["reference"] in {r["document_key"] for r in receipts}
            )
            import re

            postcodes = set(re.findall(r"code postal\s+(\d{5})", receipt_text, re.I))
            if len(postcodes) == 1 and order["shipping_postcode"] not in postcodes:
                action, reason = "carrier_investigation", "delivery_address_mismatch"
    missing = sorted(required - refs)
    if missing:
        action, reason, amount = "request_information", "missing_evidence", Decimal(0)
    return {
        "claim_id": order["claim_id"],
        "order_id": order["order_id"],
        "action": action,
        "summary": "waiting_information" if action == "request_information" else "resolution_ready",
        "reason": reason,
        "amount": str(amount),
        "currency": "EUR",
        "requires_human": True,
        "requires_sav_manager": amount > Decimal(300),
        "missing_references": missing,
        "snapshot_sha256": provenance["snapshot_sha256"],
        "evidence_sha256": pg.digest(passages),
        "citations": [c for group in evidence for c in (group or {}).get("citations", [])],
        "evidence_kind": "synthetic_demo",
        "financial_execution": "simulated",
    }


def _approved_human(db, workspace, run, proposal):
    decisions = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.scope == "run",
            Decision.target_id == run.id,
            Decision.kind == "hitl_approval",
        )
        .all()
    )
    candidates = [
        d
        for d in decisions
        if (d.rationale or {}).get("node_id") == "hitl.review"
        and d.status in {"accepted", "applied"}
        and d.human_confirmed_by
        and d.human_confirmed_at
    ]
    if len(candidates) != 1:
        raise ValueError("CLAIM_HUMAN_APPROVAL_REQUIRED")
    decision = candidates[0]
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == decision.human_confirmed_by,
        )
        .one_or_none()
    )
    if not member:
        raise ValueError("CLAIM_APPROVER_NOT_MEMBER")
    role = normalize_role_template(member.role_template, member.role)
    allowed = {WORKSPACE_REVIEWER, WORKSPACE_ADMIN, WORKSPACE_OWNER}
    if role not in allowed:
        raise ValueError("CLAIM_APPROVER_PERMISSION_DENIED")
    if proposal["requires_sav_manager"] and role not in {WORKSPACE_ADMIN, WORKSPACE_OWNER}:
        raise ValueError("CLAIM_MANAGER_APPROVAL_REQUIRED")
    return decision


def _simulate(db, workspace, run, config, claim_id, proposal, *, data_source=None):
    if proposal["action"] == "request_information":
        raise ValueError("CLAIM_RESOLUTION_NOT_READY")
    # Serialize per-workspace writes. A DB unique constraint is the final guard.
    db.query(Workspace).filter(Workspace.id == workspace.id).with_for_update().one()
    existing = (
        db.query(ClaimAction)
        .filter(ClaimAction.workspace_id == workspace.id, ClaimAction.run_id == run.id)
        .one_or_none()
    )
    if existing:
        return existing.receipt
    decision = _approved_human(db, workspace, run, proposal)
    current = pg.snapshot(workspace, claim_id)
    if current["provenance"]["snapshot_sha256"] != proposal["snapshot_sha256"]:
        raise ValueError("CLAIM_EVIDENCE_STALE")
    sources = _sources(db, workspace, run, current, ("policy", "delivery", "refund"))
    present_ids = {(source.source_metadata or {}).get("document_id") for _, source, _ in sources}
    if any(c["document_id"] not in present_ids for c in proposal["citations"]):
        raise ValueError("CLAIM_EVIDENCE_STALE")
    duplicate = (
        db.query(ClaimAction)
        .filter(
            ClaimAction.workspace_id == workspace.id,
            ClaimAction.order_id == proposal["order_id"],
            ClaimAction.action == proposal["action"],
        )
        .first()
    )
    if duplicate:
        # A new investigation must obtain its own approval and pass the live
        # evidence checks above. An identical business action then retrieves
        # the original simulated receipt rather than performing another write.
        receipt = duplicate.receipt or {}
        try:
            same_amount = Decimal(str(receipt.get("amount"))) == Decimal(proposal["amount"])
        except (ValueError, ArithmeticError):
            same_amount = False
        if not (
            duplicate.claim_id == claim_id
            and receipt.get("receipt_id") == duplicate.id
            and receipt.get("status") == "simulated"
            and receipt.get("evidence_kind") == "synthetic_demo"
            and receipt.get("external_payment_called") is False
            and receipt.get("claim_id") == proposal.get("claim_id") == claim_id
            and receipt.get("order_id") == proposal["order_id"]
            and receipt.get("action") == proposal["action"]
            and receipt.get("currency") == proposal["currency"]
            and receipt.get("snapshot_sha256") == proposal["snapshot_sha256"]
            and same_amount
        ):
            raise ValueError("CLAIM_ACTION_ALREADY_RECORDED")
        return {
            **receipt,
            "idempotent_replay": True,
            "reused_for_run_id": run.id,
            "reused_for_decision_id": decision.id,
        }
    receipt_id = str(uuid4())
    receipt = {
        **proposal,
        "receipt_id": receipt_id,
        "status": "simulated",
        "run_id": run.id,
        "decision_id": decision.id,
        "approved_by_user_id": decision.human_confirmed_by,
        "executed_at": datetime.utcnow().isoformat(),
        "external_payment_called": False,
    }
    if data_source:
        receipt["flow_data_source"] = data_source
    db.add(
        ClaimAction(
            id=receipt_id,
            workspace_id=workspace.id,
            order_id=proposal["order_id"],
            claim_id=claim_id,
            action=proposal["action"],
            run_id=run.id,
            decision_id=decision.id,
            actor_user_id=decision.human_confirmed_by,
            receipt=receipt,
        )
    )
    db.flush()
    return receipt


async def invoke(mode, payload, ctx):
    from app.db.base import SessionLocal
    from app.services.evaluation.judge import contractual_zero_token_usage

    ctx = ctx or {}
    owns_db = ctx.get("db") is None
    db = ctx.get("db") or SessionLocal()
    try:
        workspace, run, config, claim_id = _run(db, ctx)
        from app.services.flow_data_sources import require_postgresql_binding

        source = (
            require_postgresql_binding(
                run, ctx.get("_flow_data_sources", []), resources=pg.CLAIM_RESOURCES
            )
            if mode in {"snapshot", "simulate"}
            else None
        )
        if mode == "snapshot":
            snapshot = pg.snapshot(workspace, claim_id)
            if source:
                snapshot["provenance"]["flow_data_source"] = source
            return {**snapshot, **contractual_zero_token_usage("postgresql:bounded_read")}
        snapshot = _recorded(db, run, "snapshot")
        if snapshot is None:
            raise ValueError("CLAIM_SNAPSHOT_REQUIRED")
        if mode in {"policy", "delivery", "refund"}:
            return await _evidence(db, workspace, run, config, snapshot, mode, ctx)
        evidence = [_recorded(db, run, m) for m in ("policy", "delivery", "refund")]
        evidence = [
            e
            if e and e.get("snapshot_sha256") == snapshot["provenance"]["snapshot_sha256"]
            else None
            for e in evidence
        ]
        proposal = propose(snapshot, evidence, config)
        if mode == "propose":
            return {**proposal, **contractual_zero_token_usage("ecommerce:deterministic_guard")}
        if mode == "simulate":
            recorded = _recorded(db, run, "propose")
            if recorded is None or any(recorded.get(k) != proposal.get(k) for k in proposal):
                raise ValueError("CLAIM_PROPOSAL_CHANGED")
            result = _simulate(db, workspace, run, config, claim_id, proposal, data_source=source)
            if owns_db:
                db.commit()
            return {**result, **contractual_zero_token_usage("ecommerce:simulated_action")}
        raise ValueError("CLAIM_TOOL_UNKNOWN")
    finally:
        if owns_db:
            db.close()
