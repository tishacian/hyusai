"""Positive allowlists for execution correlation, never runtime payloads."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
TRANSITIONS = frozenset(
    {
        "node_start",
        "node_end",
        "hitl_pause",
        "hitl_resume",
        "debug_pause",
        "debug_resume",
        "subflow_wait",
        "subflow_resume",
        "node_skipped",
    }
)


def token(value):
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def label(value):
    return (
        value
        if isinstance(value, str)
        and 0 < len(value) <= 160
        and value.isprintable()
        and "<" not in value
        and ">" not in value
        else None
    )


def timestamp(value):
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        return None


def transitions(checkpoints, run_id):
    """Legacy ordinal is a persisted JSON position, never a timestamp identity.

    New producers give transitions/passages explicit identities. Historical
    records retain partial coverage; append order is not evidence of a retry.
    Duplicate delivery of an identified checkpoint does not create a new event.
    """
    seen = set()
    for index, raw in enumerate(checkpoints if isinstance(checkpoints, list) else []):
        if not isinstance(raw, dict) or raw.get("kind") not in TRANSITIONS:
            continue
        node_id = token(raw.get("node_id"))
        if not node_id:
            continue
        native_identity = token(raw.get("transition_id"))
        identity = native_identity or f"{run_id}:checkpoint:{index}"
        if identity in seen:
            continue
        seen.add(identity)
        yield {
            "id": identity,
            "node_id": node_id,
            "kind": raw["kind"],
            "passage_id": token(raw.get("passage_id")),
            "native_status": raw.get("status")
            if raw.get("status")
            in {
                "pending",
                "queued",
                "running",
                "completed",
                "failed",
                "cancelled",
                "timed_out",
                "lost",
                "skipped",
            }
            else None,
            "pause": raw.get("pause") is True,
            "skipped_reason": raw.get("skipped_reason")
            if raw.get("skipped_reason")
            in {"all_inputs_dead", "inactive_ingress", "inactive_branch"}
            else None,
            "t": timestamp(raw.get("t")),
            "coverage": "exact" if native_identity and token(raw.get("passage_id")) else "partial",
        }


def correlation(trace):
    trace = trace if isinstance(trace, dict) else {}
    index = trace.get("membrane_attempt_index")
    kind = trace.get("membrane_attempt_kind")
    return {
        "node_id": token(trace.get("node_id")),
        "passage_id": token(trace.get("passage_id")),
        "attempt_index": index
        if type(index) is int and index > 0 and kind in {"task", "retry"}
        else None,
        "iteration": index
        if type(index) is int
        and index > 0
        and kind
        in {
            "loop",
            "agent_loop",
            "agent_loop_plan",
            "agent_loop_tool",
            "agent_loop_decide",
            "agent_loop_act",
        }
        else None,
        "attempt_kind": kind
        if kind
        in {
            "task",
            "retry",
            "loop",
            "agent_loop",
            "agent_loop_plan",
            "agent_loop_tool",
            "agent_loop_decide",
            "agent_loop_act",
            "agent_decide",
            "agent_act",
        }
        else None,
    }


def invocation_cost(*, cost, provider_cost_usd, cost_measured, metrics):
    """Scalar accounting evidence shared by projections, never all metrics JSON."""
    import math

    def amount(value):
        return (
            value
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
            else None
        )

    evidence = metrics.get("cost_evidence") if isinstance(metrics, dict) else None
    state = evidence.get("state") if isinstance(evidence, dict) else None
    currency = evidence.get("currency") if isinstance(evidence, dict) else None
    known = (
        cost_measured is True
        and state in {"measured", "calculated"}
        and isinstance(currency, str)
        and len(currency) == 3
        and currency.isascii()
        and currency.isalpha()
    )
    currency = currency.upper() if known else None
    value = (
        amount(provider_cost_usd if state == "measured" and currency == "USD" else cost)
        if known
        else None
    )
    return {
        "provider_cost_usd": value if state == "measured" and currency == "USD" else None,
        "cost_amount": value,
        "currency": currency if value is not None else None,
        "cost_known": value is not None,
        "cost_basis": ("provider_measured" if state == "measured" else "catalogue_calculated")
        if value is not None
        else "unknown",
    }


def service_metadata_member(db, workspace, user):
    """Service metadata requires explicit membership, even for platform admins."""
    from app.services.governed_assets import GovernanceError
    from app.services.service_promises import require_member

    try:
        require_member(db, workspace.id, user.id)
        return True
    except GovernanceError:
        return False


def _readable_receipt_metadata(db, workspace, user, receipt_id):
    """Native recursive grants without consuming manifests or object bytes."""
    from app.models.service_contract import AssetVersion, DeliveryReceipt
    from app.services import governed_assets as assets

    if not service_metadata_member(db, workspace, user):
        return None
    receipt = db.query(DeliveryReceipt).filter_by(id=receipt_id, workspace_id=workspace.id).first()
    if receipt is None:
        return None
    asset = db.query(AssetVersion).filter_by(id=receipt.asset_id, workspace_id=workspace.id).first()
    if asset is None:
        return None
    authorize = assets.native_authorizer(db, workspace, user)
    try:
        assets.resolve_asset_ref(
            db,
            workspace.id,
            assets.asset_ref(asset),
            authorize=authorize,
            _metadata_only=True,
        )
        return receipt, asset
    except assets.GovernanceError:
        return None


def receipt_history_visible(db, workspace, user, receipt_id):
    """Keep authorized historical receipts when consumption needs requalification."""
    return _readable_receipt_metadata(db, workspace, user, receipt_id) is not None


def receipt_metadata_visible(db, workspace, user, receipt_id):
    """Flow evidence requires recursive native grants and current qualification."""
    from app.services import governed_assets as assets

    readable = _readable_receipt_metadata(db, workspace, user, receipt_id)
    if readable is None:
        return False
    receipt, asset = readable
    try:
        current = assets.validate_qualification(
            assets.current_qualification(db, workspace.id, asset.id), asset
        )
        return (
            current.id == receipt.qualification_id
            and current.digest == receipt.qualification_digest
        )
    except assets.GovernanceError:
        return False
