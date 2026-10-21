"""Service promises outlive Runs: immutable terms, fenced attempts, receipts.

No helper schedules a Celery job or sends an external notification. The existing
tick calls ``tick``/``watchdog`` in its transaction; execution claims a window.
"""

from __future__ import annotations

import math
import secrets
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.core.iam.roles import is_admin_template
from app.models.decision import Decision
from app.models.service_contract import (
    AssetVersion,
    DeliveryReceipt,
    ServiceAttempt,
    ServiceContract,
    ServiceIncident,
    ServiceWindow,
)
from app.models.system import System
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.schemas.service_contract import ServiceDefinition
from app.services.governed_assets import (
    GovernanceError,
    _workspace,
    asset_ref,
    content_digest,
    current_qualification,
    record_qualification,
    resolve_asset_ref,
    validate_qualification,
)


def utc(value=None):
    value = value or datetime.now(UTC)
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def require_member(db, workspace_id, user_id, *, admin=False):
    from app.models.workspace import Workspace

    if db.query(Workspace.id).filter_by(id=workspace_id, is_active=True).first() is None:
        raise GovernanceError("SERVICE_PERMISSION_DENIED", 403)
    user = db.query(User).filter_by(id=user_id, is_active=True).first()
    member = db.query(WorkspaceMember).filter_by(workspace_id=workspace_id, user_id=user_id).first()
    if (
        user is None
        or member is None
        or (admin and not is_admin_template(member.role_template, member.role))
    ):
        raise GovernanceError("SERVICE_PERMISSION_DENIED", 403)
    return user


def contract_public(row):
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "system_id": row.system_id,
        "logical_key": row.logical_key,
        "version": row.version,
        "owner_user_id": row.owner_user_id,
        "definition": row.definition_json,
        "digest": row.digest,
        "published_at": row.published_at,
        "created_at": row.created_at,
    }


def window_public(row, db=None):
    fields = (
        "id",
        "workspace_id",
        "contract_id",
        "system_id",
        "logical_key",
        "period_start",
        "period_end",
        "deadline_at",
        "status",
        "fence",
        "attempts",
        "cost_used",
        "tokens_used",
        "seconds_used",
        "candidate_ref",
        "created_at",
        "updated_at",
    )
    result = {key: getattr(row, key) for key in fields}
    session = db or object_session(row)
    attempts = (
        session.query(ServiceAttempt)
        .filter_by(workspace_id=row.workspace_id, window_id=row.id)
        .all()
        if session is not None
        else []
    )
    for unit in ("cost", "tokens", "seconds"):
        measured = [getattr(attempt, f"actual_{unit}") for attempt in attempts]
        known = [value for value in measured if value is not None]
        result[f"{unit}_coverage"] = (
            "unavailable" if not known else "measured" if len(known) == len(measured) else "partial"
        )
        result[f"measured_{unit}"] = sum(known) if known else None
        result[f"reserved_{unit}"] = (
            sum(getattr(attempt, f"reserved_{unit}") for attempt in attempts)
            if session is not None
            else None
        )
    if session is not None:
        from app.services.window_budget import summary as budget_summary

        ledger = budget_summary(session, row.workspace_id, row.id)
        if ledger:
            result["budget_ledger"] = ledger
            for unit in ("cost", "tokens", "seconds"):
                result[f"measured_{unit}"] = ledger[f"measured_{unit}"]
                result[f"reserved_{unit}"] = ledger[f"reserved_{unit}"]
                result[f"{unit}_coverage"] = ledger[f"{unit}_coverage"]
    return result


def receipt_public(row):
    fields = (
        "id",
        "workspace_id",
        "window_id",
        "asset_id",
        "asset_digest",
        "qualification_id",
        "qualification_digest",
        "destination",
        "decision_id",
        "binding_digest",
        "published_at",
    )
    result = {key: getattr(row, key) for key in fields}
    from sqlalchemy.orm import object_session

    session = object_session(row)
    if session is not None:
        window = (
            session.query(ServiceWindow)
            .filter_by(id=row.window_id, workspace_id=row.workspace_id)
            .first()
        )
        asset = (
            session.query(AssetVersion)
            .filter_by(id=row.asset_id, workspace_id=row.workspace_id)
            .first()
        )
        decision = (
            session.query(Decision)
            .filter_by(id=row.decision_id, workspace_id=row.workspace_id)
            .first()
        )
        result.update(
            period_start=window.period_start if window else None,
            period_end=window.period_end if window else None,
            asset_version=asset.version if asset else None,
            published_by=(decision.approved_by or decision.human_confirmed_by)
            if decision
            else None,
        )
    return result


def get_contract(db, workspace_id, contract_id):
    row = db.query(ServiceContract).filter_by(id=contract_id, workspace_id=workspace_id).first()
    if row is None:
        raise GovernanceError("SERVICE_CONTRACT_NOT_FOUND", 404)
    expected = content_digest(
        {
            "workspace_id": row.workspace_id,
            "system_id": row.system_id,
            "logical_key": row.logical_key,
            "version": row.version,
            "owner_user_id": row.owner_user_id,
            "definition": row.definition_json,
        }
    )
    if expected != row.digest:
        raise GovernanceError("SERVICE_CONTRACT_CHANGED")
    return row


def create_contract(
    db, workspace_id, system_id, owner_user_id, definition, *, created_by, logical_key="default"
):
    require_member(db, workspace_id, created_by, admin=True)
    require_member(db, workspace_id, owner_user_id)
    _workspace(db, workspace_id)
    if db.query(System.id).filter_by(id=system_id, workspace_id=workspace_id).first() is None:
        raise GovernanceError("SERVICE_SYSTEM_SCOPE_DENIED", 403)
    if not isinstance(logical_key, str) or not 1 <= len(logical_key) <= 200:
        raise GovernanceError("SERVICE_LOGICAL_KEY_INVALID", 422)
    try:
        definition = ServiceDefinition.model_validate(definition).model_dump(mode="json")
    except Exception:
        raise GovernanceError("SERVICE_DEFINITION_INVALID", 422) from None
    version = (
        db.query(func.max(ServiceContract.version))
        .filter_by(workspace_id=workspace_id, system_id=system_id, logical_key=logical_key)
        .scalar()
        or 0
    ) + 1
    body = {
        "workspace_id": workspace_id,
        "system_id": system_id,
        "logical_key": logical_key,
        "version": version,
        "owner_user_id": owner_user_id,
        "definition": definition,
    }
    row = ServiceContract(
        workspace_id=workspace_id,
        system_id=system_id,
        owner_user_id=owner_user_id,
        logical_key=logical_key,
        version=version,
        definition_json=definition,
        digest=content_digest(body),
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def publish_contract(db, workspace_id, contract_id, *, user_id, now=None):
    require_member(db, workspace_id, user_id, admin=True)
    row = get_contract(db, workspace_id, contract_id)
    require_member(db, workspace_id, row.owner_user_id)
    newer = (
        db.query(ServiceContract.id)
        .filter(
            ServiceContract.workspace_id == workspace_id,
            ServiceContract.system_id == row.system_id,
            ServiceContract.logical_key == row.logical_key,
            ServiceContract.version > row.version,
            ServiceContract.published_at.is_not(None),
        )
        .first()
    )
    if newer:
        raise GovernanceError("SERVICE_CONTRACT_SUPERSEDED")
    if row.published_at is None:
        row.published_at = utc(now)
        db.flush()
    return row


def _local_instant(day: date, clock: time, zone: ZoneInfo):
    """Earliest occurrence of an ambiguous wall time; gap shifts to next minute.

    The round trip distinguishes a nonexistent spring-forward time from a
    genuine UTC instant. Period lengths naturally become 23/25 hours.
    """
    wall = datetime.combine(day, clock)
    for minutes in range(181):
        candidate = wall + timedelta(minutes=minutes)
        instants = []
        for fold in (0, 1):
            zoned = candidate.replace(tzinfo=zone, fold=fold)
            actual = zoned.astimezone(UTC)
            if actual.astimezone(zone).replace(tzinfo=None) == candidate:
                instants.append(actual.replace(tzinfo=None))
        if instants:
            return min(instants)
    raise GovernanceError("SERVICE_CALENDAR_UNRESOLVABLE", 422)


def due_windows(db, now=None, *, workspace_id=None):
    now = utc(now)
    query = db.query(ServiceContract).filter(ServiceContract.published_at.is_not(None))
    if workspace_id:
        query = query.filter_by(workspace_id=workspace_id)
    latest = {}
    for row in query.order_by(ServiceContract.version.desc()).all():
        latest.setdefault((row.workspace_id, row.system_id, row.logical_key), row)
    for row in latest.values():
        get_contract(db, row.workspace_id, row.id)
        definition = ServiceDefinition.model_validate(row.definition_json)
        zone = ZoneInfo(definition.timezone)
        today = now.replace(tzinfo=UTC).astimezone(zone).date()
        final = min(today, definition.ends_on or today)
        day = definition.starts_on
        while day <= final:
            if day.weekday() in definition.days:
                first = day if definition.cadence == "daily" else day - timedelta(days=6)
                start = _local_instant(first, time.min, zone)
                end = _local_instant(day + timedelta(days=1), time.min, zone)
                deadline = _local_instant(day, time.fromisoformat(definition.deadline), zone)
                if start <= now:
                    yield {
                        "contract": row,
                        "period_start": start,
                        "period_end": end,
                        "deadline_at": deadline,
                    }
            day += timedelta(days=1)


def tick(db, now=None, *, workspace_id=None, limit=1000):
    """Materialize missing periods only; never submit or duplicate a Run."""
    created = []
    for spec in due_windows(db, now, workspace_id=workspace_id):
        contract = spec.pop("contract")
        query = db.query(ServiceWindow).filter_by(
            workspace_id=contract.workspace_id,
            system_id=contract.system_id,
            logical_key=contract.logical_key,
            period_start=spec["period_start"],
        )
        if query.first():
            continue
        row = ServiceWindow(
            workspace_id=contract.workspace_id,
            contract_id=contract.id,
            system_id=contract.system_id,
            logical_key=contract.logical_key,
            **spec,
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            if query.first() is None:
                raise
            continue
        created.append(row)
        if len(created) >= limit:
            break
    return created


def get_window(db, workspace_id, window_id, *, lock=False):
    query = db.query(ServiceWindow).filter_by(id=window_id, workspace_id=workspace_id)
    if lock:
        query = query.with_for_update().populate_existing()
    window = query.first()
    if window is None:
        raise GovernanceError("SERVICE_WINDOW_NOT_FOUND", 404)
    return window


def _incident(db, window, code, now):
    query = db.query(ServiceIncident).filter_by(window_id=window.id, code=code)
    existing = query.first()
    if existing:
        return existing
    contract = get_contract(db, window.workspace_id, window.contract_id)
    row = ServiceIncident(
        workspace_id=window.workspace_id,
        window_id=window.id,
        owner_user_id=contract.owner_user_id,
        code=code,
        created_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return query.one()
    return row


def _amounts(cost, tokens, seconds, *, nullable=False):
    if (not (nullable and tokens is None) and (type(tokens) is not int or tokens < 0)) or any(
        not (nullable and value is None)
        and (type(value) not in {int, float} or not math.isfinite(value) or value < 0)
        for value in (cost, seconds)
    ):
        raise GovernanceError("SERVICE_USAGE_INVALID", 422)


def claim_window(
    db,
    workspace_id,
    window_id,
    *,
    worker_id,
    lease_seconds=300,
    reserve_cost=0,
    reserve_tokens=0,
    reserve_seconds=0,
    run_id=None,
    now=None,
):
    now = utc(now)
    _amounts(reserve_cost, reserve_tokens, reserve_seconds)
    if (
        type(lease_seconds) is not int
        or not 1 <= lease_seconds <= 86400
        or not isinstance(worker_id, str)
        or not 1 <= len(worker_id) <= 160
    ):
        raise GovernanceError("SERVICE_LEASE_INVALID", 422)
    window = get_window(db, workspace_id, window_id, lock=True)
    contract = get_contract(db, workspace_id, window.contract_id)
    if window.status in {"delivered", "missed", "awaiting_review"} or now >= window.deadline_at:
        raise GovernanceError("SERVICE_WINDOW_CLOSED")
    if window.lease_expires_at and window.lease_expires_at > now and window.status == "running":
        raise GovernanceError("SERVICE_LEASE_BUSY")
    budget = contract.definition_json["budget"]
    if (
        window.attempts >= budget["max_attempts"]
        or window.cost_used + reserve_cost > budget["max_cost"]
        or window.tokens_used + reserve_tokens > budget["max_tokens"]
        or window.seconds_used + reserve_seconds > budget["max_seconds"]
    ):
        raise GovernanceError("SERVICE_BUDGET_EXHAUSTED")
    if run_id:
        from app.models.run import Run

        if (
            db.query(Run.id)
            .filter_by(id=run_id, workspace_id=workspace_id, system_id=window.system_id)
            .first()
            is None
        ):
            raise GovernanceError("SERVICE_RUN_SCOPE_DENIED", 403)
    fence = window.fence + 1
    token = secrets.token_hex(32)
    result = db.execute(
        update(ServiceWindow)
        .where(
            ServiceWindow.id == window.id,
            ServiceWindow.workspace_id == workspace_id,
            ServiceWindow.fence == window.fence,
            ServiceWindow.status == window.status,
        )
        .values(
            status="running",
            fence=fence,
            lease_token=token,
            lease_owner=worker_id,
            lease_expires_at=min(now + timedelta(seconds=lease_seconds), window.deadline_at),
            attempts=window.attempts + 1,
            cost_used=window.cost_used + reserve_cost,
            tokens_used=window.tokens_used + reserve_tokens,
            seconds_used=window.seconds_used + reserve_seconds,
            candidate_ref=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise GovernanceError("SERVICE_STALE_LEASE")
    db.query(ServiceAttempt).filter_by(window_id=window.id, status="running").update(
        {"status": "expired", "completed_at": now, "error_code": "SERVICE_LEASE_EXPIRED"},
        synchronize_session=False,
    )
    attempt = ServiceAttempt(
        workspace_id=workspace_id,
        window_id=window.id,
        run_id=run_id,
        fence=fence,
        lease_token=token,
        reserved_cost=reserve_cost,
        reserved_tokens=reserve_tokens,
        reserved_seconds=reserve_seconds,
        started_at=now,
    )
    db.add(attempt)
    db.flush()
    db.refresh(window)
    return attempt


def _lease(window, fence, token, now):
    if (
        window.fence != fence
        or not isinstance(token, str)
        or not window.lease_token
        or not secrets.compare_digest(window.lease_token, token)
        or window.lease_expires_at is None
        or window.lease_expires_at <= now
    ):
        raise GovernanceError("SERVICE_STALE_LEASE")


def renew_lease(db, workspace_id, window_id, *, fence, lease_token, lease_seconds=300, now=None):
    now = utc(now)
    window = get_window(db, workspace_id, window_id, lock=True)
    _lease(window, fence, lease_token, now)
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 86400:
        raise GovernanceError("SERVICE_LEASE_INVALID", 422)
    window.lease_expires_at = min(window.deadline_at, now + timedelta(seconds=lease_seconds))
    db.flush()
    return window


def complete_attempt(
    db,
    workspace_id,
    window_id,
    *,
    fence,
    lease_token,
    candidate_ref=None,
    error_code=None,
    cost=None,
    tokens=None,
    seconds=None,
    now=None,
):
    now = utc(now)
    _amounts(cost, tokens, seconds, nullable=True)
    window = get_window(db, workspace_id, window_id, lock=True)
    _lease(window, fence, lease_token, now)
    attempt = (
        db.query(ServiceAttempt)
        .filter_by(workspace_id=workspace_id, window_id=window.id, fence=fence)
        .one()
    )
    expected_candidate = (
        asset_ref(resolve_asset_ref(db, workspace_id, candidate_ref)) if candidate_ref else None
    )
    if attempt.completed_at:
        if window.candidate_ref != expected_candidate or (
            attempt.actual_cost,
            attempt.actual_tokens,
            attempt.actual_seconds,
            attempt.error_code,
        ) != (cost, tokens, seconds, error_code):
            raise GovernanceError("SERVICE_COMPLETION_CONFLICT")
        return window
    if window.status != "running" or bool(candidate_ref) == bool(error_code):
        raise GovernanceError("SERVICE_COMPLETION_INVALID", 422)
    if error_code is not None and (
        not isinstance(error_code, str)
        or not error_code.isupper()
        or len(error_code) > 80
        or not error_code.replace("_", "").isalnum()
    ):
        raise GovernanceError("SERVICE_ERROR_CODE_INVALID", 422)
    # Unknown measurements retain their full reservation. In particular, reserving
    # the maximum budget on a first attempt prevents an unmeasured retry from
    # silently spending the same budget a second time.
    if cost is not None:
        window.cost_used += max(0, cost - attempt.reserved_cost)
    if tokens is not None:
        window.tokens_used += max(0, tokens - attempt.reserved_tokens)
    if seconds is not None:
        window.seconds_used += max(0, seconds - attempt.reserved_seconds)
    budget = get_contract(db, workspace_id, window.contract_id).definition_json["budget"]
    over_budget = (
        window.cost_used > budget["max_cost"]
        or window.tokens_used > budget["max_tokens"]
        or window.seconds_used > budget["max_seconds"]
    )
    attempt.actual_cost, attempt.actual_tokens, attempt.actual_seconds = cost, tokens, seconds
    attempt.error_code = "SERVICE_BUDGET_EXHAUSTED" if over_budget else error_code
    attempt.status = "failed" if attempt.error_code else "completed"
    attempt.completed_at = now
    window.candidate_ref = expected_candidate if not attempt.error_code else None
    window.status = "failed" if attempt.error_code else "awaiting_review"
    # A finished Run relinquishes its short runtime lease. Review/publication
    # keeps the same fence and may occur until this window's deadline.
    window.lease_expires_at = now if attempt.error_code else window.deadline_at
    window.updated_at = now
    db.flush()
    if attempt.error_code:
        _incident(db, window, attempt.error_code, now)
    return window


def _technical_output(asset):
    """A human verdict cannot turn a failed/incomplete producer into success."""
    manifest = asset.manifest_json
    output = manifest.get("output", manifest)
    for value in (manifest, output):
        if not isinstance(value, dict):
            continue
        if "technical_status" in value and value["technical_status"] != "completed":
            raise GovernanceError("SERVICE_TECHNICAL_OUTPUT_INCOMPLETE")
        if "coverage" in value:
            coverage = value["coverage"]
            if not isinstance(coverage, dict) or any(
                type(coverage.get(key)) is not int or coverage[key] < 0
                for key in ("expected", "processed", "failed")
            ):
                raise GovernanceError("SERVICE_COVERAGE_INVALID")
            if (
                coverage["expected"] == 0
                or coverage["processed"] != coverage["expected"]
                or coverage["failed"] != 0
            ):
                raise GovernanceError("SERVICE_COVERAGE_INCOMPLETE")
    return output


def _delivery_facts(db, window):
    from app.services.service_engine import validate_frozen_inputs

    validate_frozen_inputs(db, window)
    contract = get_contract(db, window.workspace_id, window.contract_id)
    from app.services.window_budget import summary as budget_summary

    ledger = budget_summary(db, window.workspace_id, window.id)
    if ledger and (ledger["over_budget"] or ledger.get("measurement_conflict")):
        raise GovernanceError("SERVICE_BUDGET_EXCEEDED")
    if (
        contract.published_at is None
        or not window.candidate_ref
        or window.status not in {"awaiting_review", "delivered"}
    ):
        raise GovernanceError("SERVICE_DELIVERY_PREMATURE")
    asset = resolve_asset_ref(db, window.workspace_id, window.candidate_ref)
    _technical_output(asset)
    qualification = validate_qualification(
        current_qualification(db, window.workspace_id, asset.id), asset
    )
    policy = contract.definition_json["output_policy"]
    if (
        policy.get("qualification_policy_digest")
        and qualification.policy_digest != policy["qualification_policy_digest"]
    ):
        raise GovernanceError("SERVICE_QUALIFICATION_POLICY_CHANGED")
    try:
        Draft202012Validator(contract.definition_json["output_schema"]).validate(
            asset.manifest_json.get("output", asset.manifest_json)
        )
    except Exception:
        raise GovernanceError("SERVICE_OUTPUT_SCHEMA_MISMATCH") from None
    binding = content_digest(
        {
            "window_id": window.id,
            "workspace_id": window.workspace_id,
            "fence": window.fence,
            "contract_digest": contract.digest,
            "asset_digest": asset.digest,
            "qualification_id": qualification.id,
            "qualification_digest": qualification.digest,
            "destination": policy["destination"],
        }
    )
    return contract, asset, qualification, policy, binding


def review_delivery(
    db,
    workspace_id,
    window_id,
    *,
    reviewer_user_id,
    accept,
    expected_fence,
    expected_asset_digest,
    expected_qualification_digest,
    note="",
    qualify_candidate=False,
    now=None,
):
    now = utc(now)
    user = require_member(db, workspace_id, reviewer_user_id, admin=True)
    if type(accept) is not bool:
        raise GovernanceError("SERVICE_REVIEW_INVALID", 422)
    window = get_window(db, workspace_id, window_id, lock=True)
    workspace = _workspace(db, workspace_id)
    if window.status != "awaiting_review" or now >= window.deadline_at:
        raise GovernanceError("SERVICE_WINDOW_CLOSED")
    from app.services.governed_assets import native_authorizer

    asset = resolve_asset_ref(
        db, workspace_id, window.candidate_ref, authorize=native_authorizer(db, workspace, user)
    )
    previous = current_qualification(db, workspace_id, asset.id)
    if (
        window.fence != expected_fence
        or asset.digest != expected_asset_digest
        or (previous.digest if previous else None) != expected_qualification_digest
    ):
        raise GovernanceError("SERVICE_REVIEW_STALE")
    if accept:
        from app.services.service_engine import validate_frozen_inputs

        validate_frozen_inputs(db, window)
    if qualify_candidate:
        if accept is not True or not isinstance(note, str) or not note.strip():
            raise GovernanceError("SERVICE_HUMAN_QUALIFICATION_NOTE_REQUIRED", 422)
        contract = get_contract(db, workspace_id, window.contract_id)
        _technical_output(asset)
        try:
            Draft202012Validator(contract.definition_json["output_schema"]).validate(
                asset.manifest_json.get("output", asset.manifest_json)
            )
        except Exception:
            raise GovernanceError("SERVICE_OUTPUT_SCHEMA_MISMATCH") from None
        if previous and previous.status == "rejected":
            raise GovernanceError("SERVICE_REJECTED_ASSET_REQUIRES_NEW_VERSION")
        human_policy = {"authority": "human_review", "contract_digest": contract.digest}
        required_policy = contract.definition_json["output_policy"].get(
            "qualification_policy_digest"
        )
        if required_policy and required_policy != content_digest(human_policy):
            raise GovernanceError("SERVICE_QUALIFICATION_POLICY_CHANGED")
        record_qualification(
            db,
            workspace_id,
            assets_ref := asset_ref(asset),
            status="qualified",
            policy=human_policy,
            evidence={
                "reviewer_user_id": user.id,
                "window_id": window.id,
                "asset_ref": assets_ref,
                "note": note.strip(),
                "reviewed_output_sha256": content_digest(
                    asset.manifest_json.get("output", asset.manifest_json)
                ),
                "coverage_measured": "coverage" in asset.manifest_json
                or isinstance(asset.manifest_json.get("output"), dict)
                and "coverage" in asset.manifest_json["output"],
            },
        )
    if accept:
        contract, asset, qualification, policy, binding = _delivery_facts(db, window)
    else:
        # Refusal is possible for an unqualified or incomplete candidate. It
        # still binds the authorized, exact facts inspected by this reviewer.
        contract = get_contract(db, workspace_id, window.contract_id)
        qualification = previous
        policy = contract.definition_json["output_policy"]
        binding = content_digest(
            {
                "window_id": window.id,
                "workspace_id": window.workspace_id,
                "fence": window.fence,
                "contract_digest": contract.digest,
                "asset_digest": asset.digest,
                "qualification_id": qualification.id if qualification else None,
                "qualification_digest": qualification.digest if qualification else None,
                "destination": policy["destination"],
            }
        )
    decision = Decision(
        workspace_id=workspace_id,
        scope="system",
        target_id=window.system_id,
        kind="service_delivery",
        status="accepted" if accept else "rejected",
        title="Service delivery review",
        rationale={
            "binding_digest": binding,
            "window_id": window.id,
            "asset_id": asset.id,
            "qualification_id": qualification.id if qualification else None,
        },
        notes=str(note)[:2000],
        approved_by=user.id,
        approved_at=now,
        human_confirmed_by=user.id,
        human_confirmed_at=now,
        created_at=now,
    )
    db.add(decision)
    db.flush()
    if not accept:
        window.status = "failed"
        window.lease_expires_at = now
        _incident(db, window, "SERVICE_REVIEW_REJECTED", now)
    return decision


def automatic_delivery_decision(db, workspace_id, window_id, *, now=None):
    """Only an explicit numeric threshold permits non-human acceptance."""
    now = utc(now)
    window = get_window(db, workspace_id, window_id, lock=True)
    _workspace(db, workspace_id)
    if window.status != "awaiting_review" or now >= window.deadline_at:
        raise GovernanceError("SERVICE_WINDOW_CLOSED")
    contract, asset, qualification, policy, binding = _delivery_facts(db, window)
    minimum = policy.get("min_confidence")
    if (
        policy["require_human_review"]
        or minimum is None
        or qualification.confidence is None
        or qualification.confidence < minimum
    ):
        raise GovernanceError("SERVICE_HUMAN_REVIEW_REQUIRED")
    decision = Decision(
        workspace_id=workspace_id,
        scope="system",
        target_id=window.system_id,
        kind="service_delivery",
        status="accepted",
        title="Service delivery policy decision",
        rationale={
            "binding_digest": binding,
            "window_id": window.id,
            "asset_id": asset.id,
            "qualification_id": qualification.id,
        },
        approved_by="service-policy",
        approved_at=now,
        created_at=now,
    )
    db.add(decision)
    db.flush()
    return decision


def publish_delivery(db, workspace_id, window_id, *, decision_id, fence, lease_token, now=None):
    now = utc(now)
    window = get_window(db, workspace_id, window_id, lock=True)
    _workspace(db, workspace_id)
    contract, asset, qualification, policy, binding = _delivery_facts(db, window)
    query = db.query(DeliveryReceipt).filter_by(
        window_id=window.id, asset_digest=asset.digest, destination=policy["destination"]
    )
    existing = query.first()
    if existing:
        if (
            existing.binding_digest != binding
            or window.fence != fence
            or not window.lease_token
            or not secrets.compare_digest(window.lease_token, lease_token)
        ):
            raise GovernanceError("SERVICE_STALE_LEASE")
        return existing
    _lease(window, fence, lease_token, now)
    if window.status != "awaiting_review" or now >= window.deadline_at:
        raise GovernanceError("SERVICE_WINDOW_CLOSED")
    decision = (
        db.query(Decision)
        .filter_by(
            id=decision_id,
            workspace_id=workspace_id,
            target_id=window.system_id,
            kind="service_delivery",
            status="accepted",
        )
        .first()
    )
    if (
        not decision
        or (decision.rationale or {}).get("binding_digest") != binding
        or (decision.rationale or {}).get("window_id") != window.id
    ):
        raise GovernanceError("SERVICE_DECISION_REQUIRED")
    if decision.human_confirmed_by and decision.human_confirmed_at:
        require_member(db, workspace_id, decision.human_confirmed_by, admin=True)
    else:
        threshold = policy.get("min_confidence")
        if (
            policy["require_human_review"]
            or threshold is None
            or qualification.confidence is None
            or qualification.confidence < threshold
            or decision.approved_by != "service-policy"
        ):
            raise GovernanceError("SERVICE_HUMAN_REVIEW_REQUIRED")
    receipt = DeliveryReceipt(
        workspace_id=workspace_id,
        window_id=window.id,
        asset_id=asset.id,
        asset_digest=asset.digest,
        qualification_id=qualification.id,
        qualification_digest=qualification.digest,
        destination=policy["destination"],
        decision_id=decision.id,
        binding_digest=binding,
        published_at=now,
    )
    try:
        with db.begin_nested():
            db.add(receipt)
            db.flush()
            result = db.execute(
                update(ServiceWindow)
                .where(
                    ServiceWindow.id == window.id,
                    ServiceWindow.fence == fence,
                    ServiceWindow.status == "awaiting_review",
                    ServiceWindow.lease_token == lease_token,
                )
                .values(status="delivered", updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise GovernanceError("SERVICE_STALE_LEASE")
    except IntegrityError:
        existing = query.first()
        if existing is None or existing.binding_digest != binding:
            raise GovernanceError("SERVICE_DELIVERY_CONFLICT") from None
        return existing
    db.refresh(window)
    return receipt


def get_receipt(db, workspace_id, receipt_id, *, user_id, authorize_native=None):
    from app.models.workspace import Workspace
    from app.services.governed_assets import native_authorizer

    user = require_member(db, workspace_id, user_id)
    if authorize_native is None:
        authorize_native = native_authorizer(db, db.get(Workspace, workspace_id), user)
    receipt = db.query(DeliveryReceipt).filter_by(id=receipt_id, workspace_id=workspace_id).first()
    if receipt is None:
        raise GovernanceError("SERVICE_RECEIPT_NOT_FOUND", 404)
    asset = db.query(AssetVersion).filter_by(id=receipt.asset_id, workspace_id=workspace_id).one()
    # Receipts expose metadata, never ObjectStore URLs or a new dataset grant.
    # Consumers still apply their released component/native dataset guard.
    resolve_asset_ref(db, workspace_id, asset_ref(asset), authorize=authorize_native)
    current = validate_qualification(current_qualification(db, workspace_id, asset.id), asset)
    if current.id != receipt.qualification_id or current.digest != receipt.qualification_digest:
        raise GovernanceError("SERVICE_RECEIPT_REQUALIFICATION_REQUIRED")
    return receipt


def list_receipts(db, workspace_id, *, user_id, offset=0, limit=50, authorize_native=None):
    require_member(db, workspace_id, user_id)
    query = db.query(DeliveryReceipt).filter_by(workspace_id=workspace_id)
    total = query.count()
    rows = (
        query.order_by(DeliveryReceipt.published_at.desc(), DeliveryReceipt.id)
        .offset(max(0, offset))
        .limit(min(100, max(1, limit)))
        .all()
    )
    items = []
    for row in rows:
        try:
            items.append(
                receipt_public(
                    get_receipt(
                        db, workspace_id, row.id, user_id=user_id, authorize_native=authorize_native
                    )
                )
            )
        except GovernanceError as exc:
            if exc.status_code == 403:
                continue
            # Keep the historical fact visible, with consumption closed.
            item = receipt_public(row)
            item["available"] = False
            item["unavailable_code"] = exc.code
            items.append(item)
    return {"items": items, "total": total, "offset": offset, "limit": min(100, max(1, limit))}


def watchdog(db, now=None, *, workspace_id=None, limit=1000):
    now = utc(now)
    tick(db, now, workspace_id=workspace_id, limit=limit)
    query = db.query(ServiceWindow).filter(
        ServiceWindow.status.notin_(["delivered", "missed"]),
        or_(
            ServiceWindow.deadline_at <= now,
            (ServiceWindow.status == "running") & (ServiceWindow.lease_expires_at <= now),
        ),
    )
    if workspace_id:
        query = query.filter_by(workspace_id=workspace_id)
    incidents = []
    for row in query.order_by(ServiceWindow.deadline_at).limit(limit).with_for_update().all():
        if row.deadline_at <= now:
            code = (
                "SERVICE_RUN_MISSING"
                if row.attempts == 0
                else "SERVICE_REVIEW_OVERDUE"
                if row.status == "awaiting_review"
                else "SERVICE_DELIVERY_MISSED"
            )
            row.status = "missed"
        else:
            code = "SERVICE_LEASE_EXPIRED"
            row.status = "failed"
        db.query(ServiceAttempt).filter_by(window_id=row.id, status="running").update(
            {"status": "expired", "completed_at": now, "error_code": code},
            synchronize_session=False,
        )
        row.updated_at = now
        incidents.append(_incident(db, row, code, now))
    db.flush()
    return incidents
