"""Durable, idempotent control requests routed to native authorities.

An applied command means the native cooperative cancellation was recorded;
only a subsequent native terminal status means the computation has stopped.
"""

import logging
import time
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.activity import Activity, ActivityCommand
from app.models.user import User
from app.models.workspace import Workspace

from .queries import authorized_activity, can_cancel, require_membership

logger = logging.getLogger(__name__)


def _outer_transaction(db):
    # Python sqlite legacy transaction mode does not BEGIN for SELECT. Without
    # this, releasing our first SAVEPOINT would commit outside Session.rollback.
    connection = db.connection()
    if (
        connection.dialect.name == "sqlite"
        and not connection.connection.driver_connection.in_transaction
    ):
        connection.exec_driver_sql("BEGIN")


def enqueue(db, *, row, workspace, user, action, expected_version, idempotency_key):
    existing = (
        db.query(ActivityCommand)
        .filter_by(workspace_id=workspace.id, actor_id=user.id, idempotency_key=idempotency_key)
        .first()
    )
    if existing:
        if (existing.activity_id, existing.action, existing.expected_version) != (
            row.id,
            action,
            expected_version,
        ):
            raise HTTPException(409, detail="ACTIVITY_IDEMPOTENCY_CONFLICT")
        return existing
    if action != "cancel" or not can_cancel(db, row, workspace, user):
        raise HTTPException(409, detail="ACTIVITY_COMMAND_UNSUPPORTED")
    current = (
        db.query(Activity)
        .filter_by(id=row.id, workspace_id=workspace.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if current.version != expected_version:
        raise HTTPException(409, detail="ACTIVITY_VERSION_CONFLICT")
    command = ActivityCommand(
        workspace_id=workspace.id,
        activity_id=row.id,
        actor_id=user.id,
        action=action,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        status="requested",
    )
    try:
        _outer_transaction(db)
        with db.begin_nested():
            db.add(command)
            db.flush()
    except IntegrityError:
        existing = (
            db.query(ActivityCommand)
            .filter_by(workspace_id=workspace.id, actor_id=user.id, idempotency_key=idempotency_key)
            .first()
        )
        if existing and (existing.activity_id, existing.action, existing.expected_version) == (
            row.id,
            action,
            expected_version,
        ):
            return existing
        raise HTTPException(409, detail="ACTIVITY_IDEMPOTENCY_CONFLICT") from None
    return command


def apply_native_cancel(db, row, *, expected_version, workspace, user):
    if row.kind == "recipe_execution":
        from app.models.recipe import RecipeExecution as Model
        from app.services.recipe_executions import request_cancel
    elif row.kind == "compute_run":
        from app.models.compute_run import ComputeRun as Model
        from app.services.compute_runs import request_cancel
    elif row.kind == "ml_training":
        from app.models.tabular import MLModel as Model
        from app.services.tabular_ml import request_cancel
    elif row.kind == "run":
        from app.models.run import Run as Model
        from app.services.execution.control import request_run_cancel as request_cancel
    else:
        raise HTTPException(409, detail="ACTIVITY_COMMAND_UNSUPPORTED")
    native = (
        db.query(Model)
        .filter_by(id=row.native_id, workspace_id=row.workspace_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if native is None:
        raise HTTPException(404, detail="ACTIVITY_NATIVE_NOT_FOUND")
    # The source lock waits for any in-flight native mutation and its observer
    # commit. Recheck after that lock, not against the earlier UI projection.
    current = db.query(Activity).filter_by(id=row.id).populate_existing().one()
    if current.version != expected_version:
        raise HTTPException(409, detail="ACTIVITY_VERSION_CONFLICT")
    # Waiting for a native row lock can outlive a permission change. Reapply the
    # complete native operator boundary immediately before the source mutation.
    require_membership(
        db,
        db.get(Workspace, workspace.id, populate_existing=True),
        db.get(User, user.id, populate_existing=True),
    )
    current = authorized_activity(db, current.id, workspace, user)
    if not can_cancel(db, current, workspace, user, new_admission=False):
        raise HTTPException(409, detail="ACTIVITY_COMMAND_NO_LONGER_ALLOWED")
    request_cancel(db, native, commit=False)


def process_commands(db, *, limit=100):
    """Called by the independent control worker; caller owns the outer commit.

    SKIP LOCKED + native row locks serialize competing consumers. A worker
    crash rolls back both native mutation and command acknowledgement; replay
    reapplies the same cooperative request, never launches another execution.
    """
    _outer_transaction(db)
    postgres = db.get_bind().dialect.name == "postgresql"
    previous_timeouts = (
        db.execute(
            text("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
        ).one()
        if postgres
        else None
    )
    rows = (
        db.query(ActivityCommand)
        .filter_by(status="requested")
        .order_by(ActivityCommand.created_at, ActivityCommand.id)
        .with_for_update(skip_locked=True)
        .limit(min(max(limit, 1), 500))
        .all()
    )
    began, processed = time.monotonic(), 0
    for command in rows:
        if time.monotonic() - began >= 1:
            break  # Leave time for the same worker's reapers and outbox.
        try:
            with db.begin_nested():
                if postgres:
                    db.execute(
                        text(
                            "SELECT set_config('lock_timeout', '250ms', true), set_config('statement_timeout', '1s', true)"
                        )
                    )
                user = db.get(User, command.actor_id, populate_existing=True)
                workspace = db.get(Workspace, command.workspace_id, populate_existing=True)
                require_membership(db, workspace, user)
                row = authorized_activity(db, command.activity_id, workspace, user)
                if not can_cancel(db, row, workspace, user, new_admission=False):
                    raise HTTPException(409, detail="ACTIVITY_COMMAND_NO_LONGER_ALLOWED")
                if row.version != command.expected_version:
                    raise HTTPException(409, detail="ACTIVITY_VERSION_CONFLICT")
                apply_native_cancel(
                    db,
                    row,
                    expected_version=command.expected_version,
                    workspace=workspace,
                    user=user,
                )
                command.status = "applied"
                command.completed_at = datetime.utcnow()
                db.flush()
                if postgres:
                    db.execute(
                        text(
                            "SELECT set_config('lock_timeout', :lock_timeout, true), set_config('statement_timeout', :statement_timeout, true)"
                        ),
                        {
                            "lock_timeout": previous_timeouts[0],
                            "statement_timeout": previous_timeouts[1],
                        },
                    )
            processed += 1
        except HTTPException as exc:
            command.status = "rejected"
            command.error_code = (
                exc.detail
                if isinstance(exc.detail, str)
                and exc.detail
                in {
                    "ACTIVITY_COMMAND_UNSUPPORTED",
                    "ACTIVITY_COMMAND_NO_LONGER_ALLOWED",
                    "ACTIVITY_VERSION_CONFLICT",
                    "ACTIVITY_NATIVE_NOT_FOUND",
                    "ACTIVITY_NOT_FOUND",
                }
                else "ACTIVITY_ACCESS_DENIED"
            )
            command.completed_at = datetime.utcnow()
            processed += 1
        except DBAPIError as exc:
            code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
            if not postgres or code not in {"55P03", "57014"}:
                raise
            # The nested rollback restores both partial native mutations and
            # local timeout settings. No acknowledgement: retry next tick.
            logger.info("ACTIVITY_COMMAND_DEFERRED_CONTENTION")
        # Unexpected DB/runtime failures abort the batch. They are never
        # acknowledged as success and remain pending after transaction rollback.
    db.flush()
    return processed
