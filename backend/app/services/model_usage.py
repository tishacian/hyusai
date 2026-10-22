"""Durable provider accounting and atomic workspace/application admission.

The workspace row is the common lock for tariff/policy changes, reservation and
settlement. No network operation runs inside that transaction. Unknown outcomes
retain their reservation; configured tariffs are not a supplier invoice.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation, localcontext
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.audit import AuditLog
from app.models.model_usage import (
    ModelTariff,
    ModelUsageCall,
    UsageBudgetBucket,
    UsageBudgetPolicy,
    UsageReservation,
)
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob

TRAFFIC = {"business", "evaluation", "preview", "ingestion"}
PURPOSES = {
    "generation",
    "agent_decision",
    "judge",
    "embedding",
    "test_generation",
    "offline_evaluation",
    "other",
}
TERMINAL = {"completed", "failed", "cancelled", "unknown"}
RATE_KEYS = {
    "input_per_million",
    "output_per_million",
    "cached_input_per_million",
    "cache_write_per_million",
}
ROLLOUT_COMPONENTS = {"api", "cpu_worker", "dataops_worker", "connector_runner", "livekit_agent"}


class UsageError(ValueError):
    def __init__(self, code, status_code=409, details=None):
        super().__init__(code)
        self.code, self.status_code, self.details = code, status_code, details or {}


@dataclass(frozen=True)
class UsageContext:
    workspace_id: str
    system_id: str | None = None
    root_system_id: str | None = None
    run_id: str | None = None
    invocation_id: str | None = None
    job_id: str | None = None
    worker_job_id: str | None = None
    campaign_id: str | None = None
    evaluation_id: str | None = None
    actor_user_id: str | None = None
    purpose: str = "generation"
    traffic: str = "business"


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _decimal(value):
    if isinstance(value, bool):
        raise UsageError("USAGE_AMOUNT_INVALID", 422)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise UsageError("USAGE_AMOUNT_INVALID", 422) from None
    if not result.is_finite() or result < 0 or result > Decimal("100000000000"):
        raise UsageError("USAGE_AMOUNT_INVALID", 422)
    return result.quantize(Decimal("0.000000000001"))


def _count(value):
    return value if type(value) is int and 0 <= value <= 9_000_000_000_000_000 else None


def _workspace_lock(db, workspace_id):
    workspace = (
        db.query(Workspace).filter_by(id=workspace_id).populate_existing().with_for_update().first()
    )
    if not workspace or not workspace.is_active or workspace.deleted_at:
        raise UsageError("USAGE_WORKSPACE_INVALID", 403)
    return workspace


def _context(db, ctx):
    if (
        not isinstance(ctx, UsageContext)
        or ctx.traffic not in TRAFFIC
        or ctx.purpose not in PURPOSES
    ):
        raise UsageError("USAGE_CONTEXT_INVALID", 422)
    values = asdict(ctx)
    if ctx.worker_job_id:
        from app.models.knowledge_collection import WorkerJob

        worker_job = (
            db.query(WorkerJob)
            .filter_by(id=ctx.worker_job_id, workspace_id=ctx.workspace_id)
            .first()
        )
        if worker_job is None:
            raise UsageError("USAGE_WORKER_JOB_INVALID", 403)
    if ctx.job_id:
        job = db.query(WorkspaceJob).filter_by(id=ctx.job_id, workspace_id=ctx.workspace_id).first()
        if not job:
            raise UsageError("USAGE_JOB_INVALID", 403)
        multi_run_judge = (
            job.kind == "typed_evaluation_v2" and ctx.purpose == "judge" and bool(ctx.run_id)
        )
        if job.run_id and ctx.run_id and job.run_id != ctx.run_id and not multi_run_judge:
            raise UsageError("USAGE_JOB_RUN_MISMATCH", 403)
        # Typed batches deliberately retain their first Run pointer while each
        # later unit has its own canonical Run. The Judge already verifies its
        # batch contract/actor; the System equality is rechecked below.
        values["run_id"] = ctx.run_id if multi_run_judge else job.run_id or ctx.run_id
        values["system_id"] = job.system_id or ctx.system_id
    if values["run_id"]:
        run = db.query(Run).filter_by(id=values["run_id"], workspace_id=ctx.workspace_id).first()
        if not run or (values["system_id"] and values["system_id"] != run.system_id):
            raise UsageError("USAGE_RUN_INVALID", 403)
        values["system_id"] = run.system_id
        root, seen = run, set()
        while root.parent_run_id:
            if root.id in seen or len(seen) >= 32:
                raise UsageError("USAGE_RUN_LINEAGE_INVALID", 403)
            seen.add(root.id)
            parent = (
                db.query(Run)
                .filter_by(id=root.parent_run_id, workspace_id=ctx.workspace_id)
                .first()
            )
            if not parent:
                # Historical deleted parents cannot acquire a different budget.
                raise UsageError("USAGE_RUN_LINEAGE_UNAVAILABLE", 409)
            root = parent
        if ctx.root_system_id and ctx.root_system_id != root.system_id:
            raise UsageError("USAGE_ROOT_SYSTEM_MISMATCH", 403)
        values["root_system_id"] = root.system_id
        values["root_run_id"] = root.id
        campaign = getattr(run, "evaluation_campaign_id", None) or getattr(
            root, "evaluation_campaign_id", None
        )
        if campaign:
            values["campaign_id"], values["traffic"] = campaign, "evaluation"
        elif run.execution_surface in {"golden_preview", "draft_preview", "authoring_preview"}:
            values["traffic"] = "preview"
        values["actor_user_id"] = run.initiated_by_user_id or ctx.actor_user_id
        if (
            ctx.invocation_id
            and not db.query(SkillInvocation.id)
            .filter_by(id=ctx.invocation_id, run_id=run.id)
            .first()
        ):
            raise UsageError("USAGE_INVOCATION_INVALID", 403)
    else:
        if ctx.invocation_id:
            raise UsageError("USAGE_INVOCATION_RUN_REQUIRED", 403)
        values["root_system_id"] = values["system_id"]
        if ctx.root_system_id and ctx.root_system_id != values["system_id"]:
            raise UsageError("USAGE_ROOT_SYSTEM_MISMATCH", 403)
    for key in ("system_id", "root_system_id"):
        if (
            values[key]
            and not db.query(System.id)
            .filter_by(id=values[key], workspace_id=ctx.workspace_id)
            .first()
        ):
            raise UsageError("USAGE_SYSTEM_INVALID", 403)
    return values


def _capabilities():
    try:
        from app.services.model_usage_transport import QUALIFIED_TRANSPORTS

        return sorted(QUALIFIED_TRANSPORTS)
    except ImportError:
        return []


def budget_readiness(workspace):
    revision = str(settings.agentium_image_revision or "").lower()
    declared = (workspace.settings or {}).get("model_usage_rollout", {})
    capabilities = _capabilities()
    ready = bool(
        re.fullmatch(r"[0-9a-f]{40}", revision)
        and capabilities
        and declared.get("revision") == revision
        and declared.get("capabilities_sha256") == _hash(capabilities)
        and declared.get("all_workers_recreated") is True
        and declared.get("livekit_sessions_drained") is True
        and all(declared.get("components", {}).get(name) == revision for name in ROLLOUT_COMPONENTS)
    )
    return {
        "ready": ready,
        "code": "USAGE_ADMISSION_READY" if ready else "USAGE_ROLLOUT_UNVERIFIED",
        "revision": revision or None,
        "qualified_transports": capabilities,
        "missing_transports": [] if capabilities else ["provider_admission"],
        "attestation_basis": "operator_declaration" if declared else None,
        "attested_at": declared.get("at"),
        "required_components": sorted(ROLLOUT_COMPONENTS),
        "guarantee": "admission_at_configured_tariffs_and_bounds",
    }


def attest_rollout(
    db,
    workspace,
    user,
    *,
    revision,
    components,
    all_workers_recreated,
    livekit_sessions_drained=False,
):
    workspace = _workspace_lock(db, workspace.id)
    capabilities = _capabilities()
    if (
        not re.fullmatch(r"[0-9a-f]{40}", revision)
        or revision != settings.agentium_image_revision
        or not capabilities
        or all_workers_recreated is not True
        or livekit_sessions_drained is not True
        or any(components.get(name) != revision for name in ROLLOUT_COMPONENTS)
    ):
        raise UsageError("USAGE_ROLLOUT_UNVERIFIED", 409)
    entry = {
        "revision": revision,
        "components": {name: components[name] for name in sorted(ROLLOUT_COMPONENTS)},
        "all_workers_recreated": True,
        "livekit_sessions_drained": True,
        "capabilities_sha256": _hash(capabilities),
        "at": _now().isoformat() + "Z",
        "actor_user_id": user.id,
    }
    workspace.settings = {**(workspace.settings or {}), "model_usage_rollout": entry}
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=workspace.id,
            actor=user.id,
            event_type="model_usage.rollout_attested",
            details=entry,
        )
    )
    db.commit()
    return budget_readiness(workspace)


def _policies(db, workspace_id, root_system_id, *, include_disabled=False):
    keys = ["workspace", *(["system:" + root_system_id] if root_system_id else [])]
    query = db.query(UsageBudgetPolicy).filter(
        UsageBudgetPolicy.workspace_id == workspace_id, UsageBudgetPolicy.scope_key.in_(keys)
    )
    query = (
        query.filter(UsageBudgetPolicy.activated_at.isnot(None))
        if include_disabled
        else query.filter(UsageBudgetPolicy.enabled.is_(True))
    )
    return query.order_by(UsageBudgetPolicy.scope_key).all()


def active_budgets(workspace_id, root_system_id=None):
    with SessionLocal() as db:
        return bool(_policies(db, workspace_id, root_system_id))


def period_bounds(policy, now=None):
    now = now or _now()
    zone = ZoneInfo(policy.timezone)
    local = now.replace(tzinfo=UTC).astimezone(zone)
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_first = (
        first.replace(year=first.year + 1, month=1)
        if first.month == 12
        else first.replace(month=first.month + 1)
    )
    start = first.astimezone(UTC).replace(tzinfo=None)
    end = next_first.astimezone(UTC).replace(tzinfo=None)
    return max(start, policy.activated_at or start), end


def _bucket(db, policy, now):
    start, end = period_bounds(policy, now)
    row = db.query(UsageBudgetBucket).filter_by(policy_id=policy.id, period_start=start).first()
    if row is None:
        row = UsageBudgetBucket(
            id=str(uuid4()),
            policy_id=policy.id,
            period_start=start,
            period_end=end,
            consumed_tokens=0,
            reserved_tokens=0,
            consumed_amounts={},
            reserved_amounts={},
        )
        db.add(row)
    return row


def _tariff_snapshot(row):
    return (
        {
            "id": row.id,
            "revision": row.revision,
            "provider": row.provider,
            "model": row.model,
            "currency": row.currency,
            "rates": row.rates,
            "created_at": row.created_at.isoformat() + "Z",
        }
        if row
        else None
    )


def _price(snapshot, inputs, outputs, cached=None, cache_write=None, *, reserve=False):
    if not snapshot or inputs is None or outputs is None:
        return None
    rates = snapshot["rates"]
    inp, out = _decimal(rates["input_per_million"]), _decimal(rates["output_per_million"])
    if reserve:
        # A cache hit or discount cannot be assumed before the provider responds.
        inp = max(
            [
                inp,
                *[
                    _decimal(rates[k])
                    for k in ("cached_input_per_million", "cache_write_per_million")
                    if rates.get(k) is not None
                ],
            ]
        )
        with localcontext() as context:
            context.prec = 50
            amount = ((inp * inputs + out * outputs) / Decimal(1_000_000)).quantize(
                Decimal("0.000000000001"), rounding=ROUND_CEILING
            )
        if amount > Decimal("999999999999.999999999999"):
            raise UsageError("USAGE_MONETARY_BOUND_TOO_LARGE", 422)
        return amount
    # When a tariff distinguishes cache categories, their absence is not proof
    # of a zero cache hit. Keep the monetary reservation until those reported
    # counters arrive rather than showing a full-price estimate as measured.
    if (rates.get("cached_input_per_million") is not None and cached is None) or (
        rates.get("cache_write_per_million") is not None and cache_write is None
    ):
        return None
    cached, cache_write = cached or 0, cache_write or 0
    if cached + cache_write > inputs:
        return None
    amount = inp * (inputs - cached - cache_write) + out * outputs
    for count, key in (
        (cached, "cached_input_per_million"),
        (cache_write, "cache_write_per_million"),
    ):
        if count and rates.get(key) is None:
            return None
        amount += _decimal(rates[key]) * count if count else 0
    return (amount / Decimal(1_000_000)).quantize(Decimal("0.000000000001"))


def prepare_call(
    ctx,
    *,
    request_key,
    provider,
    model,
    operation="completion",
    input_token_bound=None,
    output_token_bound=None,
    tariff_id=None,
    request_sha256=None,
    admission_qualified=False,
    admission_hook: Callable | None = None,
):
    """Atomically reserve every applicable scope; never dispatch from this helper.

    admission_hook(db, call_dict) may reserve additional native ledgers in this
    SAME transaction. It must not commit or dispatch. Refusal rolls everything back.
    """
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200:
        raise UsageError("USAGE_REQUEST_KEY_INVALID", 422)
    for value in (input_token_bound, output_token_bound):
        if value is not None and _count(value) is None:
            raise UsageError("USAGE_BOUND_INVALID", 422)
    if not provider or len(provider) > 80 or not model or len(model) > 200 or len(operation) > 40:
        raise UsageError("USAGE_ROUTE_INVALID", 422)
    refusal = None
    with SessionLocal() as db:
        workspace = _workspace_lock(db, ctx.workspace_id)
        values = _context(db, ctx)
        fingerprint = _hash(
            {
                "context": values,
                "provider": provider,
                "model": model,
                "operation": operation,
                "inputs": input_token_bound,
                "outputs": output_token_bound,
                "tariff_id": tariff_id,
                "request": request_sha256,
            }
        )
        existing = (
            db.query(ModelUsageCall)
            .filter_by(workspace_id=ctx.workspace_id, request_key=request_key)
            .first()
        )
        if existing:
            if existing.request_sha256 != fingerprint:
                raise UsageError("USAGE_REQUEST_CHANGED", 409)
            result = public_call(existing)
            result["reused"] = True
            if existing.status == "blocked":
                raise UsageError(existing.diagnostic, 409, existing.details)
            return result
        query = db.query(ModelTariff).filter_by(
            workspace_id=ctx.workspace_id, provider=provider, model=model
        )
        tariff = (
            query.filter_by(id=tariff_id).first()
            if tariff_id
            else query.order_by(ModelTariff.revision.desc()).first()
        )
        if tariff_id and not tariff:
            raise UsageError("USAGE_TARIFF_NOT_FOUND", 404)
        snapshot = _tariff_snapshot(tariff)
        amount = _price(snapshot, input_token_bound, output_token_bound, reserve=True)
        tokens = (
            input_token_bound + output_token_bound
            if input_token_bound is not None and output_token_bound is not None
            else None
        )
        now = _now()
        call = ModelUsageCall(
            id=str(uuid4()),
            **values,
            request_key=request_key,
            request_sha256=fingerprint,
            provider=provider,
            model=model,
            operation=operation,
            status="prepared",
            started_at=now,
            reserved_tokens=tokens,
            reserved_amount=amount,
            currency=tariff.currency if tariff else None,
            tariff_id=tariff.id if tariff else None,
            tariff_snapshot=snapshot,
            usage_coverage="unavailable",
            details={},
        )
        db.add(call)
        policies = _policies(db, ctx.workspace_id, values["root_system_id"], include_disabled=True)
        allocations = []
        if any(policy.enabled for policy in policies):
            if not budget_readiness(workspace)["ready"]:
                refusal = UsageError("USAGE_ROLLOUT_UNVERIFIED")
            elif not admission_qualified:
                refusal = UsageError("USAGE_TRANSPORT_UNQUALIFIED")
        for policy in policies if not refusal else []:
            row = _bucket(db, policy, now)
            detail = {
                "policy_id": policy.id,
                "scope": policy.scope_key,
                "period_end": row.period_end.isoformat() + "Z",
            }
            if not policy.enabled:
                # Pausing a limit never resets accounting for the same period.
                allocations.append((row, policy))
                continue
            if policy.reconciliation_required:
                refusal = UsageError("USAGE_RECONCILIATION_REQUIRED", details=detail)
                break
            if policy.max_tokens is not None:
                if tokens is None:
                    refusal = UsageError("USAGE_BOUND_REQUIRED", details=detail)
                elif row.consumed_tokens + row.reserved_tokens + tokens > policy.max_tokens:
                    refusal = UsageError(
                        "USAGE_BUDGET_EXHAUSTED", details={**detail, "dimension": "tokens"}
                    )
            if not refusal and policy.currency_limits:
                if not snapshot:
                    refusal = UsageError("USAGE_TARIFF_REQUIRED", details=detail)
                elif call.currency not in policy.currency_limits:
                    refusal = UsageError("USAGE_CURRENCY_NOT_BUDGETED", details=detail)
                elif amount is None:
                    refusal = UsageError("USAGE_BOUND_REQUIRED", details=detail)
                elif Decimal(row.consumed_amounts.get(call.currency, "0")) + Decimal(
                    row.reserved_amounts.get(call.currency, "0")
                ) + amount > Decimal(policy.currency_limits[call.currency]):
                    refusal = UsageError(
                        "USAGE_BUDGET_EXHAUSTED",
                        details={**detail, "dimension": "cost", "currency": call.currency},
                    )
            if refusal:
                break
            allocations.append((row, policy))
        if refusal:
            call.status, call.diagnostic, call.details, call.completed_at = (
                "blocked",
                refusal.code,
                refusal.details,
                now,
            )
        else:
            db.flush()  # Native hooks and allocation FKs see the canonical call/buckets.
            for row, policy in allocations:
                # Both dimensions are tracked even when only one has a ceiling.
                rt, ra = tokens or 0, amount or Decimal(0)
                row.reserved_tokens += rt
                if call.currency:
                    row.reserved_amounts = {
                        **row.reserved_amounts,
                        call.currency: str(
                            Decimal(row.reserved_amounts.get(call.currency, "0")) + ra
                        ),
                    }
                db.add(
                    UsageReservation(
                        id=str(uuid4()),
                        call_id=call.id,
                        bucket_id=row.id,
                        reserved_tokens=rt,
                        reserved_amount=ra,
                        currency=call.currency,
                        released=False,
                    )
                )
            if admission_hook:
                admission_hook(db, public_call(call))
        db.commit()
        result = public_call(call)
        result["reused"] = False
    if refusal:
        raise refusal
    return result


def _locked_call(db, call_id):
    call = db.get(ModelUsageCall, call_id)
    if not call:
        raise UsageError("USAGE_CALL_NOT_FOUND", 404)
    _workspace_lock(db, call.workspace_id)
    return db.query(ModelUsageCall).filter_by(id=call_id).populate_existing().one()


def mark_dispatched(call_id):
    with SessionLocal() as db:
        call = _locked_call(db, call_id)
        if call.status != "prepared":
            return False
        call.status, call.dispatched_at = "dispatched", _now()
        db.commit()
        return True


def _adjust_amount(current, currency, delta):
    return {**current, currency: str(Decimal(current.get(currency, "0")) + delta)}


def _settle_allocations(db, call, *, release=False):
    for entry in db.query(UsageReservation).filter_by(call_id=call.id).all():
        if entry.released:
            continue
        bucket = db.get(UsageBudgetBucket, entry.bucket_id)
        if release:
            if entry.settled_tokens is None:
                bucket.reserved_tokens -= entry.reserved_tokens
            if entry.currency and entry.settled_amount is None:
                bucket.reserved_amounts = _adjust_amount(
                    bucket.reserved_amounts, entry.currency, -entry.reserved_amount
                )
            entry.released = True
            continue
        if call.total_tokens is not None:
            previous = entry.settled_tokens
            if previous is None:
                bucket.reserved_tokens -= entry.reserved_tokens
            bucket.consumed_tokens += call.total_tokens - (previous or 0)
            entry.settled_tokens = call.total_tokens
        if call.amount is not None and entry.currency:
            previous = entry.settled_amount
            if previous is None:
                bucket.reserved_amounts = _adjust_amount(
                    bucket.reserved_amounts, entry.currency, -entry.reserved_amount
                )
            bucket.consumed_amounts = _adjust_amount(
                bucket.consumed_amounts, entry.currency, call.amount - (previous or 0)
            )
            entry.settled_amount = call.amount


def cancel_before_dispatch(call_id):
    with SessionLocal() as db:
        call = _locked_call(db, call_id)
        if call.status != "prepared":
            return False
        call.status, call.completed_at = "cancelled", _now()
        call.diagnostic = "not_dispatched"
        call.input_tokens = call.output_tokens = call.total_tokens = 0
        call.usage_coverage = "complete"
        call.amount = Decimal(0) if call.currency else None
        _settle_allocations(db, call, release=True)
        db.commit()
        return True


def _usage(usage):
    source = usage if isinstance(usage, dict) else {}

    def pick(*keys):
        return next(
            (
                _count(source[key])
                for key in keys
                if key in source and _count(source[key]) is not None
            ),
            None,
        )

    inputs, outputs = (
        pick("input_tokens", "prompt_tokens"),
        pick("output_tokens", "completion_tokens"),
    )
    total = pick("total_tokens")
    if total is None and inputs is not None and outputs is not None:
        total = inputs + outputs
    if (
        total is not None
        and inputs is not None
        and outputs is not None
        and total != inputs + outputs
    ):
        raise UsageError("USAGE_COUNTERS_CONFLICT", 422)
    cached = pick("cached_input_tokens", "cached_tokens")
    cache_write, reasoning = pick("cache_write_tokens"), pick("reasoning_tokens")
    if inputs is not None and (cached or 0) + (cache_write or 0) > inputs:
        raise UsageError("USAGE_COUNTERS_CONFLICT", 422)
    if outputs is not None and reasoning is not None and reasoning > outputs:
        raise UsageError("USAGE_COUNTERS_CONFLICT", 422)
    return {
        "input_tokens": inputs,
        "output_tokens": outputs,
        "total_tokens": total,
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_write,
        "reasoning_tokens": reasoning,
    }


def settle_call(
    call_id,
    *,
    usage,
    returned_model=None,
    provider_request_id=None,
    status="completed",
    diagnostic=None,
):
    if status not in TERMINAL:
        raise UsageError("USAGE_STATUS_INVALID", 422)
    counters = _usage(usage)
    with SessionLocal() as db:
        call = _locked_call(db, call_id)
        if call.status in {"prepared", "blocked"} or not call.dispatched_at:
            raise UsageError("USAGE_CALL_NOT_DISPATCHED", 409)
        for key, value in counters.items():
            previous = getattr(call, key)
            if value is not None and previous is not None and value < previous:
                raise UsageError("USAGE_MEASUREMENT_CHANGED", 409)
            if value is not None:
                setattr(call, key, value)
        # Usage can arrive in several reconciliation messages. Validate the
        # merged report and derive total only once both parts are available.
        merged = _usage({key: getattr(call, key) for key in counters})
        for key, value in merged.items():
            if value is not None:
                setattr(call, key, value)
        if returned_model:
            call.returned_model = str(returned_model)[:200]
        if provider_request_id:
            call.provider_request_id = str(provider_request_id)[:200]
        call.status = status
        call.completed_at = call.completed_at or _now()
        if diagnostic:
            call.diagnostic = (
                str(diagnostic)
                if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", str(diagnostic))
                else "provider_error"
            )
        call.usage_coverage = (
            "complete"
            if call.input_tokens is not None and call.output_tokens is not None
            else "partial"
            if call.total_tokens is not None
            else "unavailable"
        )
        priced = _price(
            call.tariff_snapshot,
            call.input_tokens,
            call.output_tokens,
            call.cached_input_tokens,
            call.cache_write_tokens,
        )
        if priced is not None:
            if call.amount is not None and priced < call.amount:
                raise UsageError("USAGE_MEASUREMENT_CHANGED", 409)
            call.amount = priced
        if (
            call.total_tokens is not None
            and call.reserved_tokens is not None
            and call.total_tokens > call.reserved_tokens
        ) or (
            call.amount is not None
            and call.reserved_amount is not None
            and call.amount > call.reserved_amount
        ):
            call.details = {**call.details, "reservation_exceeded": True}
            for entry in db.query(UsageReservation).filter_by(call_id=call.id).all():
                bucket = db.get(UsageBudgetBucket, entry.bucket_id)
                db.get(UsageBudgetPolicy, bucket.policy_id).reconciliation_required = True
        _settle_allocations(db, call)
        db.commit()
        return public_call(call)


def public_call(row):
    result = {
        name: getattr(row, name)
        for name in (
            "id",
            "system_id",
            "root_system_id",
            "run_id",
            "root_run_id",
            "invocation_id",
            "job_id",
            "worker_job_id",
            "campaign_id",
            "evaluation_id",
            "purpose",
            "traffic",
            "provider",
            "model",
            "returned_model",
            "operation",
            "status",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "usage_coverage",
            "currency",
            "tariff_id",
            "reserved_tokens",
            "diagnostic",
            "details",
        )
    }
    for name in ("started_at", "dispatched_at", "completed_at"):
        value = getattr(row, name)
        result[name] = value.isoformat() + "Z" if value else None
    result["latency_ms"] = (
        (row.completed_at - row.dispatched_at).total_seconds() * 1000
        if row.completed_at and row.dispatched_at
        else None
    )
    result["amount"] = str(row.amount) if row.amount is not None else None
    result["reserved_amount"] = (
        str(row.reserved_amount) if row.reserved_amount is not None else None
    )
    result["cost_basis"] = (
        "provider_tokens_at_versioned_tariff" if row.amount is not None else "unknown"
    )
    result["billed_amount"] = None
    return result


def create_tariff(db, workspace, user, *, provider, model, currency, **rates):
    _workspace_lock(db, workspace.id)
    if not re.fullmatch(r"[A-Z]{3}", currency) or not provider or not model:
        raise UsageError("USAGE_TARIFF_INVALID", 422)
    if set(rates) - RATE_KEYS or any(
        rates.get(key) is None for key in ("input_per_million", "output_per_million")
    ):
        raise UsageError("USAGE_TARIFF_INVALID", 422)
    rates = {key: str(_decimal(value)) for key, value in rates.items() if value is not None}
    latest = (
        db.query(ModelTariff)
        .filter_by(workspace_id=workspace.id, provider=provider, model=model)
        .order_by(ModelTariff.revision.desc())
        .first()
    )
    row = ModelTariff(
        id=str(uuid4()),
        workspace_id=workspace.id,
        provider=provider,
        model=model,
        revision=latest.revision + 1 if latest else 1,
        currency=currency,
        rates=rates,
        created_by_user_id=user.id,
        created_at=_now(),
    )
    db.add(row)
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=workspace.id,
            actor=user.id,
            event_type="model_usage.tariff_created",
            details=_tariff_snapshot(row),
        )
    )
    db.commit()
    return _tariff_snapshot(row)


def save_budget(
    db,
    workspace,
    user,
    *,
    scope,
    system_id=None,
    enabled=False,
    timezone="UTC",
    max_tokens=None,
    currency_limits=None,
    expected_revision=0,
):
    workspace = _workspace_lock(db, workspace.id)
    if scope not in {"workspace", "system"} or (scope == "system") != bool(system_id):
        raise UsageError("USAGE_BUDGET_SCOPE_INVALID", 422)
    if (
        system_id
        and not db.query(System.id).filter_by(id=system_id, workspace_id=workspace.id).first()
    ):
        raise UsageError("USAGE_SYSTEM_INVALID", 404)
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise UsageError("USAGE_TIMEZONE_INVALID", 422) from None
    if max_tokens is not None and _count(max_tokens) is None:
        raise UsageError("USAGE_BUDGET_TOKENS_INVALID", 422)
    amounts = currency_limits or {}
    if (
        not isinstance(amounts, dict)
        or len(amounts) > 20
        or any(not re.fullmatch(r"[A-Z]{3}", key) for key in amounts)
    ):
        raise UsageError("USAGE_CURRENCY_INVALID", 422)
    amounts = {key: str(_decimal(value)) for key, value in amounts.items()}
    if enabled and max_tokens is None and not amounts:
        raise UsageError("USAGE_BUDGET_LIMIT_REQUIRED", 422)
    key = "workspace" if scope == "workspace" else "system:" + system_id
    row = db.query(UsageBudgetPolicy).filter_by(workspace_id=workspace.id, scope_key=key).first()
    if (row.revision if row else 0) != expected_revision:
        raise UsageError("USAGE_BUDGET_REVISION_CONFLICT", 409)
    if row and row.activated_at and timezone != row.timezone:
        raise UsageError("USAGE_BUDGET_TIMEZONE_LOCKED", 409)
    if enabled and not budget_readiness(workspace)["ready"]:
        raise UsageError("USAGE_ROLLOUT_UNVERIFIED", 409)
    if enabled and row and row.activated_at:
        start, _ = period_bounds(row)
        pending = (
            db.query(ModelUsageCall)
            .join(UsageReservation, UsageReservation.call_id == ModelUsageCall.id)
            .join(UsageBudgetBucket, UsageBudgetBucket.id == UsageReservation.bucket_id)
            .filter(
                UsageBudgetBucket.policy_id == row.id,
                UsageBudgetBucket.period_start == start,
                UsageReservation.released.is_(False),
            )
            .all()
        )
        if any(
            (max_tokens is not None and c.total_tokens is None and c.reserved_tokens is None)
            or (amounts and c.amount is None and c.reserved_amount is None)
            for c in pending
        ):
            raise UsageError("USAGE_UNRESOLVED_PRIOR_USAGE", 409)
    now = _now()
    if row is None:
        row = UsageBudgetPolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            scope_key=key,
            system_id=system_id,
            revision=0,
            history=[],
        )
        db.add(row)
    row.revision += 1
    row.enabled, row.timezone, row.max_tokens, row.currency_limits, row.updated_at = (
        enabled,
        timezone,
        max_tokens,
        amounts,
        now,
    )
    if enabled and row.activated_at is None:
        row.activated_at = now
    change = {
        "revision": row.revision,
        "at": now.isoformat() + "Z",
        "actor": user.id,
        "changes": {
            "enabled": enabled,
            "max_tokens": max_tokens,
            "currency_limits": amounts,
            "timezone": timezone,
        },
    }
    row.history = [*row.history[-19:], change]
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=workspace.id,
            actor=user.id,
            event_type="model_usage.budget_changed",
            details={"policy_id": row.id, **change},
        )
    )
    db.commit()
    return public_budget(db, row)


def public_budget(db, policy):
    start, end = period_bounds(policy)
    bucket = db.query(UsageBudgetBucket).filter_by(policy_id=policy.id, period_start=start).first()
    result = {
        "id": policy.id,
        "scope": "system" if policy.system_id else "workspace",
        "system_id": policy.system_id,
        "revision": policy.revision,
        "enabled": policy.enabled,
        "timezone": policy.timezone,
        "max_tokens": policy.max_tokens,
        "reconciliation_required": policy.reconciliation_required,
        "currency_limits": policy.currency_limits,
        "activated_at": policy.activated_at.isoformat() + "Z" if policy.activated_at else None,
        "history": policy.history,
    }
    result["current_period"] = {
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "consumed_tokens": bucket.consumed_tokens if bucket else 0,
        "reserved_tokens": bucket.reserved_tokens if bucket else 0,
        "amounts": [
            {
                "currency": currency,
                "limit": policy.currency_limits.get(currency),
                "consumed": (bucket.consumed_amounts if bucket else {}).get(currency, "0"),
                "reserved": (bucket.reserved_amounts if bucket else {}).get(currency, "0"),
            }
            for currency in sorted(
                set(policy.currency_limits)
                | set(bucket.consumed_amounts if bucket else {})
                | set(bucket.reserved_amounts if bucket else {})
            )
        ],
    }
    return result
