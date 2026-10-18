"""Transactional ML alert inbox and leased, at-least-once channel delivery.

Only references to workspace secrets are stored. Delivery IDs are stable so
receivers can deduplicate after an ambiguous SMTP/HTTP acknowledgement.
"""

import hashlib
import hmac
import html
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.ml_operations import (
    MLAlert,
    MLAlertChannel,
    MLAlertDelivery,
    MLAlertSource,
    MLAlertState,
)
from app.models.tabular import MLModel, MLModelApiKey
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ml_operations import digest

EVENT_TYPES = frozenset(
    {"monitor_transition", "monitor_failed", "key_expiring", "quota_reached", "fairness_gap"}
)


def enabled():
    return bool(getattr(settings, "ml_alerts_enabled", False))


def audit(db, workspace_id, event, details, *, actor="system"):
    # Join the source transaction: an alert without its audit is never committed.
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=workspace_id,
            event_type=event,
            actor=actor,
            details=details,
        )
    )


def emit_alert(db, *, model, event_type, state, source_id, now=None):
    if not enabled():
        return None
    if event_type not in EVENT_TYPES or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", state):
        raise ValueError("ML_ALERT_EVENT_INVALID")
    now = now or datetime.utcnow()
    db.query(MLModel).filter_by(
        id=model.id, workspace_id=model.workspace_id
    ).with_for_update().one()
    source_key = digest(model.id, event_type, source_id, state)
    source = db.get(MLAlertSource, source_key)
    if source:
        return db.get(MLAlert, source.alert_id)
    window = int(now.replace(tzinfo=UTC).timestamp()) // max(
        1, int(getattr(settings, "ml_alert_throttle_seconds", 3600))
    )
    identity = digest(model.id, event_type, state, window)
    existing = db.get(MLAlert, identity)
    if existing:
        db.add(
            MLAlertSource(
                id=source_key,
                alert_id=existing.id,
                source_id=str(source_id)[:64],
                event_type=event_type,
            )
        )
        db.flush()
        return existing
    row = MLAlert(
        id=identity,
        workspace_id=model.workspace_id,
        model_id=model.id,
        event_type=event_type,
        state=state,
        source_id=str(source_id)[:64],
        created_at=now,
    )
    db.add(row)
    db.flush()
    db.add(
        MLAlertSource(
            id=source_key, alert_id=row.id, source_id=str(source_id)[:64], event_type=event_type
        )
    )
    for channel in (
        db.query(MLAlertChannel).filter_by(workspace_id=model.workspace_id, enabled=True).all()
    ):
        db.add(
            MLAlertDelivery(
                id=digest(row.id, channel.id),
                alert_id=row.id,
                channel_id=channel.id,
                status="pending",
                attempts=0,
                available_at=now,
            )
        )
    audit(
        db,
        model.workspace_id,
        "ml.alert.created",
        {"model_id": model.id, "alert_id": row.id, "event": event_type, "state": state},
    )
    db.flush()
    return row


def monitor_transition(db, *, model, badge, source_id, now=None):
    if not enabled() or badge not in {"ok", "watch", "alert"}:
        return None
    db.query(MLModel).filter_by(id=model.id).with_for_update().one()
    previous = db.get(MLAlertState, model.id)
    if previous and previous.source_id == source_id:
        return None
    changed = (previous.badge != badge) if previous else badge != "ok"
    if previous is None:
        previous = MLAlertState(model_id=model.id)
        db.add(previous)
    previous.badge, previous.source_id, previous.updated_at = (
        badge,
        source_id,
        now or datetime.utcnow(),
    )
    db.flush()
    return (
        emit_alert(
            db,
            model=model,
            event_type="monitor_transition",
            state=badge,
            source_id=source_id,
            now=now,
        )
        if changed
        else None
    )


def scan_key_expiry(db, *, now=None, limit=100):
    if not enabled() or not hasattr(MLModelApiKey, "expires_at"):
        return 0
    now = now or datetime.utcnow()
    days = int(getattr(settings, "ml_alert_key_expiry_days", 7))
    active_rotation = (
        or_(MLModelApiKey.revoke_after.is_(None), MLModelApiKey.revoke_after > now)
        if hasattr(MLModelApiKey, "revoke_after") else True
    )
    keys = (
        db.query(MLModelApiKey)
        .filter(
            MLModelApiKey.revoked_at.is_(None),
            active_rotation,
            ~db.query(MLAlertSource.id)
            .filter(
                MLAlertSource.source_id == MLModelApiKey.id,
                MLAlertSource.event_type == "key_expiring",
            )
            .exists(),
            MLModelApiKey.expires_at > now,
            MLModelApiKey.expires_at <= now + timedelta(days=days),
        )
        .order_by(MLModelApiKey.expires_at)
        .limit(limit)
        .all()
    )
    for key in keys:
        model = db.get(MLModel, key.model_id)
        if model:
            emit_alert(
                db,
                model=model,
                event_type="key_expiring",
                state="expiring",
                source_id=key.id,
                now=now,
            )
    return len(keys)


def claim_delivery(db, *, now=None):
    now = now or datetime.utcnow()
    max_attempts = int(getattr(settings, "ml_alert_max_attempts", 5))
    row = (
        db.query(MLAlertDelivery)
        .filter(
            or_(
                and_(
                    MLAlertDelivery.status.in_(["pending", "retry"]),
                    MLAlertDelivery.available_at <= now,
                ),
                and_(MLAlertDelivery.status == "sending", MLAlertDelivery.lease_expires_at <= now),
            ),
        )
        .order_by(MLAlertDelivery.available_at, MLAlertDelivery.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if row is None:
        return None
    if row.attempts >= max_attempts:
        row.status, row.error_code = "failed", "ML_ALERT_ATTEMPTS_EXHAUSTED"
        return {"exhausted": True}
    row.status, row.attempts = "sending", row.attempts + 1
    row.lease_token, row.lease_expires_at = str(uuid4()), now + timedelta(seconds=90)
    db.flush()
    return {"id": row.id, "token": row.lease_token}


def _secret(db, channel, ref):
    from app.services.secrets import registry

    parsed = registry.parse_ref(ref)
    if parsed.scope != "workspace":
        raise ValueError("ML_ALERT_SECRET_SCOPE_INVALID")
    return registry.resolve(
        db,
        ref,
        consumer=registry.SecretConsumer(
            "ml_alert", channel.id, workspace_id=channel.workspace_id, user_id=channel.created_by
        ),
    ).reveal()


def _payload(alert, delivery_id):
    return json.dumps(
        {
            "id": delivery_id,
            "alert_id": alert.id,
            "workspace_id": alert.workspace_id,
            "model_id": alert.model_id,
            "event": alert.event_type,
            "state": alert.state,
            "occurred_at": alert.created_at.isoformat() + "Z",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def send_delivery(db, row, *, smtp_sender=None, http_request=None):
    channel, alert = db.get(MLAlertChannel, row.channel_id), db.get(MLAlert, row.alert_id)
    from app.services.huggingface.access import is_workspace_admin

    if (
        not channel
        or not channel.enabled
        or not alert
        or channel.workspace_id != alert.workspace_id
    ):
        return "ML_ALERT_CHANNEL_DISABLED"
    if not is_workspace_admin(
        db, db.get(User, channel.created_by), db.get(Workspace, channel.workspace_id)
    ):
        return "ML_ALERT_OWNER_REVOKED"
    body = _payload(alert, row.id)
    if channel.kind == "email":
        from app.services.email import _default_delivery_config, send_email_with_config

        config = _default_delivery_config()
        if not (config.host and config.username and config.password):
            return "ML_ALERT_SMTP_UNCONFIGURED"
        sender = smtp_sender or send_email_with_config
        ok = sender(
            config=config,
            to=channel.destination_email,
            subject=f"[Agentium ML] {alert.event_type}: {alert.state}",
            html="<pre>" + html.escape(body.decode()) + "</pre>",
            text=body.decode(),
        )
        return None if ok else "ML_ALERT_EMAIL_FAILED"
    if channel.kind == "webhook":
        destination, key = (
            _secret(db, channel, channel.webhook_url_ref),
            _secret(db, channel, channel.signing_key_ref),
        )
        if len(key.encode()) < 32:
            return "ML_ALERT_SIGNING_KEY_INVALID"
        timestamp = str(int(datetime.now(UTC).timestamp()))
        signature = hmac.new(
            key.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        sender = http_request or _send_webhook
        sender(
            "POST",
            destination,
            deadline_at=(datetime.utcnow() + timedelta(seconds=5)).isoformat(),
            headers={
                "Content-Type": "application/json",
                "X-Agentium-Delivery": row.id,
                "X-Agentium-Timestamp": timestamp,
                "X-Agentium-Signature": "sha256=" + signature,
            },
            content=body,
            max_bytes=4096,
        )
        return None
    return "ML_ALERT_CHANNEL_INVALID"


def deliver_pending(session_factory, *, limit=None, sender=send_delivery, now=None):
    if not enabled():
        return 0
    limit = limit or int(getattr(settings, "ml_alert_batch_size", 10))
    delivered = 0
    for _ in range(limit):
        with session_factory() as db:
            claimed = claim_delivery(db, now=now)
            db.commit()
        if claimed is None:
            break
        if claimed.get("exhausted"):
            continue
        with session_factory() as db:
            row = db.get(MLAlertDelivery, claimed["id"])
            try:
                error = sender(db, row)
            except Exception:
                # Exception text can contain a signed URL or driver credentials.
                error = "ML_ALERT_DELIVERY_FAILED"
            stamp = now or datetime.utcnow()
            values = {
                "status": "delivered" if error is None else "retry",
                "error_code": error,
                "delivered_at": stamp if error is None else None,
                "lease_token": None,
                "lease_expires_at": None,
                "available_at": stamp
                + timedelta(seconds=min(3600, 30 * 2 ** min(row.attempts, 7))),
            }
            if error and row.attempts >= int(getattr(settings, "ml_alert_max_attempts", 5)):
                values["status"] = "failed"
            changed = (
                db.query(MLAlertDelivery)
                .filter_by(id=row.id, status="sending", lease_token=claimed["token"])
                .update(values, synchronize_session=False)
            )
            if changed:
                alert = db.get(MLAlert, row.alert_id)
                audit(
                    db,
                    alert.workspace_id,
                    "ml.alert.delivery",
                    {
                        "alert_id": alert.id,
                        "delivery_id": row.id,
                        "status": values["status"],
                        "error_code": error,
                    },
                )
                delivered += int(error is None)
            db.commit()
    return delivered


def scan_monitor_failures(db, *, limit=100):
    if not enabled():
        return 0
    from app.models.run import Run
    from app.models.system import System

    # Monitoring systems already carry the canonical model binding. Iterate
    # oldest first; durable source IDs avoid re-alerting a failed run forever.
    query = (
        db.query(Run, System)
        .join(System, Run.system_id == System.id)
        .filter(
            Run.status == "failed",
            ~db.query(MLAlertSource.id)
            .filter(MLAlertSource.source_id == Run.id, MLAlertSource.event_type == "monitor_failed")
            .exists(),
            System.settings["ml_monitoring_model_id"].as_string().isnot(None),
        )
    )
    count = 0
    for run, system in query.order_by(Run.started_at, Run.id).limit(limit).all():
        model_id = (system.settings or {}).get("ml_monitoring_model_id")
        source_key = digest(model_id, "monitor_failed", run.id, "failed")
        if db.get(MLAlertSource, source_key):
            continue
        model = db.get(MLModel, model_id)
        if model and model.workspace_id == run.workspace_id:
            emit_alert(
                db, model=model, event_type="monitor_failed", state="failed", source_id=run.id
            )
            count += 1
        if count >= limit:
            break
    return count


def _send_webhook(method, destination, *, deadline_at, headers, content, max_bytes):
    import logging
    import time

    import httpx

    from app.services.connectors.http_transport import origin, pinned_client
    from app.services.connectors.network_policy import resolve_destination

    # The legacy connector observation window must never authorize a new alert
    # credential surface. Resolve once in enforce mode, then retain TLS SNI.
    url = httpx.URL(destination)
    scheme, host, port = origin(url)
    if scheme != "https":
        raise ValueError("ML_ALERT_TLS_REQUIRED")
    checked = resolve_destination(host, port, mode="enforce")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    expires = time.monotonic() + 5
    with pinned_client(url, checked, timeout=5) as client:
        with client.stream(method, url, headers=headers, content=content) as response:
            if not 200 <= response.status_code < 300:
                raise ValueError("ML_ALERT_HTTP_FAILED")
            size = 0
            for chunk in response.iter_raw():
                size += len(chunk)
                if size > max_bytes or time.monotonic() > expires:
                    raise ValueError("ML_ALERT_RESPONSE_LIMIT")
