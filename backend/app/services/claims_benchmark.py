"""Observed human sessions and paired demo ROI; no fabricated baseline.

Client durations, prices, run lists and quality verdicts are never trusted.
All attempts in the session window are included, including failed runs.
"""
from datetime import datetime
from decimal import Decimal
from statistics import median
from types import SimpleNamespace

from app.core.iam.roles import normalize_role_template, WORKSPACE_ADMIN, WORKSPACE_OWNER, WORKSPACE_REVIEWER
from app.models.claim_trial import ClaimTrial
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace, WorkspaceMember
from app.services import ecommerce_claims as claims
from app.services.connectors.generic import postgresql_claims as pg


def protocol(workspace):
    config = claims._config(workspace).get("benchmark")
    if not isinstance(config, dict) or not config.get("pairs") or config.get("hourly_eur") != "40.00":
        raise ValueError("BENCHMARK_NOT_CONFIGURED")
    return config


def _lock(db, workspace):
    db.query(Workspace).filter(Workspace.id == workspace.id).with_for_update().one()


def start(db, workspace, user, pair_id, condition):
    _lock(db, workspace)
    config = protocol(workspace)
    pair = next((p for p in config["pairs"] if p["pair_id"] == pair_id), None)
    if pair is None or condition not in {"manual", "assisted"}:
        raise ValueError("BENCHMARK_CASE_INVALID")
    config_sha = pg.digest(config)
    if db.query(ClaimTrial).filter(ClaimTrial.workspace_id == workspace.id, ClaimTrial.operator_id == user.id,
                                 ClaimTrial.state.in_(["active", "paused"])).first():
        raise ValueError("BENCHMARK_SESSION_ALREADY_ACTIVE")
    previous = db.query(ClaimTrial).filter(ClaimTrial.workspace_id == workspace.id,
        ClaimTrial.protocol_sha256 == config_sha, ClaimTrial.pair_id == pair_id).all()
    if any(t.condition == condition for t in previous):
        raise ValueError("BENCHMARK_CASE_ALREADY_USED")
    if not previous and condition != pair["first_condition"]:
        raise ValueError("BENCHMARK_ORDER_INVALID")
    if previous and any(t.state != "finished" or t.operator_id != user.id for t in previous):
        raise ValueError("BENCHMARK_PAIR_OPERATOR_MISMATCH")
    claim_id = pair[condition + "_claim_id"]
    snapshot = pg.snapshot(workspace, claim_id)
    if (config.get("snapshot_sha256") or {}).get(claim_id) != snapshot["provenance"]["snapshot_sha256"]:
        raise ValueError("BENCHMARK_SNAPSHOT_CHANGED")
    reader = SimpleNamespace(initiated_by_user_id=user.id)
    sources = claims._sources(db, workspace, reader, snapshot, ("policy", "delivery", "refund"))
    refs = {s.id for _, s, _ in sources}
    if any(r["knowledge_source_id"] not in refs for r in snapshot["data"]["documents"]):
        raise ValueError("BENCHMARK_SOURCES_NOT_READY")
    now = datetime.utcnow()
    row = ClaimTrial(workspace_id=workspace.id, operator_id=user.id, protocol_sha256=config_sha,
        pair_id=pair_id, condition=condition, claim_id=claim_id, state="active", started_at=now,
        evidence={"snapshot": snapshot, "protocol": config, "expected": pair[condition + "_expected"],
                  "evidence_kind": "synthetic_demo_benchmark", "production_baseline_eligible": False},
        events=[{"sequence": 1, "action": "start", "at": now.isoformat(), "actor_id": user.id}])
    db.add(row); db.flush()
    return row


def session_runs(db, row):
    # Closed native Experience binding, same tenant, case, operator and window.
    runs = db.query(Run).filter(Run.workspace_id == row.workspace_id, Run.initiated_by_user_id == row.operator_id,
                               Run.started_at >= row.started_at).all()
    return [r for r in runs if (r.input_ref or {}).get("claim_id") == row.claim_id
            and (r.input_ref or {}).get("_ingress", {}).get("adapter", {}).get("binding_key") == "showcase.claims.investigate"
            and (row.finished_at is None or r.started_at <= row.finished_at)]


def event(db, workspace, user, trial_id, action, expected_sequence, result=None):
    _lock(db, workspace)
    row = db.query(ClaimTrial).filter(ClaimTrial.id == trial_id, ClaimTrial.workspace_id == workspace.id,
                                    ClaimTrial.operator_id == user.id).one_or_none()
    if row is None:
        raise ValueError("BENCHMARK_SESSION_NOT_FOUND")
    if len(row.events) != expected_sequence:
        raise ValueError("BENCHMARK_EVENT_CONFLICT")
    reopening = row.state == "finished" and action == "resume" and row.review is not None and row.review["passed"] is False
    if not (reopening or (row.state == "active" and action in {"pause", "finish"})
            or (row.state == "paused" and action in {"resume", "finish"})):
        raise ValueError("BENCHMARK_TRANSITION_INVALID")
    if action == "resume" and db.query(ClaimTrial).filter(ClaimTrial.workspace_id == workspace.id,
        ClaimTrial.operator_id == user.id, ClaimTrial.id != row.id, ClaimTrial.state.in_(["active", "paused"])).first():
        raise ValueError("BENCHMARK_SESSION_ALREADY_ACTIVE")
    if action == "finish":
        if not result or result.get("action") not in {"refund", "carrier_investigation", "close_duplicate", "request_information", "failed"}:
            raise ValueError("BENCHMARK_RESULT_REQUIRED")
        amount = Decimal(result.get("amount", ""))
        if not amount.is_finite() or amount < 0:
            raise ValueError("BENCHMARK_AMOUNT_INVALID")
        available = {r["document_key"] for r in row.evidence["snapshot"]["data"]["documents"]}
        if (result["action"] != "failed" and not result.get("references")) or not set(result["references"]) <= available:
            raise ValueError("BENCHMARK_REFERENCES_INVALID")
        runs = session_runs(db, row)
        if row.condition == "manual" and runs:
            raise ValueError("BENCHMARK_MANUAL_CONDITION_CONTAMINATED")
        if row.condition == "assisted" and ((not runs and result["action"] != "failed") or any(r.status not in {"completed", "failed", "cancelled"} for r in runs)):
            raise ValueError("BENCHMARK_ASSISTED_RUNS_UNSETTLED")
        if pg.snapshot(workspace, row.claim_id)["provenance"]["snapshot_sha256"] != row.evidence["snapshot"]["provenance"]["snapshot_sha256"]:
            raise ValueError("BENCHMARK_SNAPSHOT_CHANGED")
        row.result = {**result, "run_ids": [r.id for r in runs]}
    now = datetime.utcnow()
    if reopening:
        row.events = [*row.events, {"sequence": len(row.events) + 1, "action": "quality_review", "at": now.isoformat(), "review": row.review}]
        row.review = None; row.finished_at = None
    row.events = [*row.events, {"sequence": len(row.events) + 1, "action": action, "at": now.isoformat(), "actor_id": user.id, **({"result": row.result} if action == "finish" else {})}]
    row.state = {"pause": "paused", "resume": "active", "finish": "finished"}[action]
    if action == "finish": row.finished_at = now
    db.flush()
    return row


def review(db, workspace, user, trial_id, passed, note):
    _lock(db, workspace)
    row = db.query(ClaimTrial).filter(ClaimTrial.workspace_id == workspace.id, ClaimTrial.id == trial_id).one_or_none()
    member = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id).one_or_none()
    if not member or normalize_role_template(member.role_template, member.role) not in {WORKSPACE_REVIEWER, WORKSPACE_ADMIN, WORKSPACE_OWNER}:
        raise ValueError("BENCHMARK_REVIEWER_REQUIRED")
    if not row or row.state != "finished" or row.operator_id == user.id or row.review is not None:
        raise ValueError("BENCHMARK_INDEPENDENT_REVIEW_REQUIRED")
    expected, actual = row.evidence["expected"], row.result
    matches = actual["action"] == expected["action"] and Decimal(actual["amount"]) == Decimal(expected["amount"])
    matches = matches and set(expected["references"]) <= set(actual["references"])
    row.review = {"passed": bool(passed and matches), "reviewer_id": user.id, "note": note,
                  "at": datetime.utcnow().isoformat(), "rule_match": matches}
    db.flush(); return row


def seconds(row):
    active, started, total = False, None, 0.0
    for event in row.events:
        at = datetime.fromisoformat(event["at"])
        if active: total += (at - started).total_seconds()
        active = event["action"] in {"start", "resume"}
        started = at
    return total if row.state == "finished" else None


def cost_eur(db, rows, config):
    total = Decimal(0)
    for row in rows:
        if row.condition != "assisted": continue
        for run in session_runs(db, row):
            calls = db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()
            if not calls: return None
            for call in calls:
                metric = (call.metrics or {}).get("cost_evidence") or {}
                currency = metric.get("currency")
                if call.cost_measured is not True or currency != "EUR" or call.cost is None:
                    return None
                value = Decimal(str(call.cost))
                if not value.is_finite() or value < 0: return None
                total += value
    allocation = config.get("allocation")
    if not allocation or allocation.get("coverage") != "complete" or not allocation.get("evidence_ref"):
        return None
    value = Decimal(str(allocation.get("total_eur", "")))
    return total + value if value.is_finite() and value >= 0 else None


def summary(db, workspace):
    config = protocol(workspace); config_sha = pg.digest(config)
    rows = db.query(ClaimTrial).filter(ClaimTrial.workspace_id == workspace.id, ClaimTrial.protocol_sha256 == config_sha).order_by(ClaimTrial.started_at).all()
    paired = []
    for pair in config["pairs"]:
        two = [r for r in rows if r.pair_id == pair["pair_id"]]
        if len(two) == 2 and all(r.state == "finished" and (r.review or {}).get("passed") for r in two):
            manual = next(r for r in two if r.condition == "manual")
            assisted = next(r for r in two if r.condition == "assisted")
            paired.append({"pair_id": pair["pair_id"], "manual_seconds": seconds(manual), "assisted_seconds": seconds(assisted),
                           "difference_seconds": seconds(manual) - seconds(assisted), "trial_ids": [manual.id, assisted.id]})
    complete = len(paired) == len(config["pairs"]) and len(paired) >= 10
    capacity = sum(Decimal(str(p["difference_seconds"])) for p in paired) / Decimal(3600) * Decimal(config["hourly_eur"]) if complete else None
    cost_receipt = approved_costs(db, workspace, rows, config_sha) if complete else None
    cost = Decimal(cost_receipt.rationale["total_eur"]) if cost_receipt else cost_eur(db, rows, config) if complete else None
    net = capacity - cost if capacity is not None and cost is not None else None
    return {"evidence_kind": "synthetic_demo_benchmark", "production_baseline_eligible": False,
            "protocol_sha256": config_sha, "hourly_eur": config["hourly_eur"], "hourly_nature": "declared_demo_assumption",
            "planned_pairs": len(config["pairs"]), "completed_quality_pairs": len(paired), "complete": complete,
            "cost_review_id": cost_receipt.id if cost_receipt else None, "cost_nature": "human_approved_billing_and_allocation" if cost_receipt else "runtime_tariff_and_allocation",
            "cost_ledger_sha256": ledger_sha(db, rows),
            "state": "measured" if net is not None else "awaiting_costs" if complete else "experiment_not_complete",
            "capacity_value_eur": str(capacity) if capacity is not None else None,
            "incremental_cost_eur": str(cost) if cost is not None else None, "net_benefit_eur": str(net) if net is not None else None,
            "roi": str(net / cost) if net is not None and cost > 0 else None,
            "median_difference_seconds": median(p["difference_seconds"] for p in paired) if paired else None,
            "pairs": paired, "trials": [serialize(r) for r in rows],
            "protocol": {"version": config["version"], "pairs": [{k: v for k, v in p.items() if not k.endswith("_expected")} for p in config["pairs"]]}}


def serialize(row):
    return {"id": row.id, "claim_id": row.claim_id, "pair_id": row.pair_id, "condition": row.condition, "operator_id": row.operator_id,
            "state": row.state, "events": row.events, "active_human_seconds": seconds(row), "result": row.result, "review": row.review,
            "started_at": row.started_at.isoformat(), "finished_at": row.finished_at.isoformat() if row.finished_at else None}


def ledger_sha(db, rows):
    evidence = []
    for row in rows:
        if row.state != "finished": return None
        for run in session_runs(db, row):
            calls = db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).order_by(SkillInvocation.id).all()
            evidence.append({"trial_id": row.id, "run_id": run.id, "status": run.status,
                "calls": [{"id": c.id, "status": c.status, "cost": c.cost, "cost_measured": c.cost_measured, "metrics": c.metrics} for c in calls]})
    return pg.digest(sorted(evidence, key=lambda e: (e["trial_id"], e["run_id"]))) if rows else None


def approved_costs(db, workspace, rows, protocol_sha):
    evidence_sha = ledger_sha(db, rows)
    reviews = db.query(Decision).filter(Decision.workspace_id == workspace.id, Decision.scope == "workspace",
        Decision.target_id == workspace.id, Decision.kind == "benchmark_cost_approval", Decision.status == "accepted").order_by(Decision.created_at.desc()).all()
    return next((d for d in reviews if d.human_confirmed_by and d.human_confirmed_at
                 and d.rationale.get("protocol_sha256") == protocol_sha
                 and d.rationale.get("ledger_sha256") == evidence_sha), None)


def approve_costs(db, workspace, user, body):
    _lock(db, workspace)
    member = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id).one_or_none()
    if not member or normalize_role_template(member.role_template, member.role) not in {WORKSPACE_ADMIN, WORKSPACE_OWNER}:
        raise ValueError("BENCHMARK_COST_APPROVER_REQUIRED")
    result = summary(db, workspace)
    if not result["complete"] or result["cost_ledger_sha256"] != body["ledger_sha256"]:
        raise ValueError("BENCHMARK_COST_REVIEW_STALE")
    # This is explicitly a human-approved billing/allocation convention, never
    # inferred from an absent runtime cost. All four components need evidence.
    amounts = [Decimal(body[k]) for k in ("provider_eur", "infrastructure_eur", "licence_eur", "integration_eur")]
    if any(not a.is_finite() or a < 0 for a in amounts): raise ValueError("BENCHMARK_COST_INVALID")
    now = datetime.utcnow()
    row = Decision(workspace_id=workspace.id, scope="workspace", target_id=workspace.id, kind="benchmark_cost_approval",
        status="accepted", title="Luma Maison benchmark cost coverage", approved_by=user.email, approved_at=now,
        human_confirmed_by=user.id, human_confirmed_at=now,
        rationale={**body, "total_eur": str(sum(amounts, Decimal(0))), "protocol_sha256": result["protocol_sha256"],
                   "nature": "human_approved_billing_and_allocation", "currency": "EUR", "coverage": "all_attempts_and_allocations"})
    db.add(row); db.flush(); return {"decision_id": row.id}
