"""Durable, published-only operator Runner sessions.

Runner sessions deliberately reuse the canonical ``sessions`` table.  Their
typed metadata keeps them separate from Chat without introducing a second
conversation/session authority.  Every lookup repeats workspace, user and
System ownership checks so a guessed session id cannot cross any boundary.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.run import Run
from app.models.system import System
from app.models.user import Session as SessionModel
from app.services.systems import flow_ingress, flow_publication

RUNNER_SESSION_KIND = "flow_runner"
RUNNER_SESSION_SCHEMA_VERSION = 1
RUNNER_SESSION_QUERY_LIMIT = 100
RUNNER_RUN_QUERY_LIMIT = 100


@dataclass(frozen=True, slots=True)
class FlowRunnerError(ValueError):
    code: str
    message: str
    status_code: int = 409
    details: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "error": self.code.lower(),
            "code": self.code,
            "message": self.message,
            **copy.deepcopy(self.details or {}),
        }


def _translate_publication(
    exc: flow_publication.FlowPublicationError,
) -> FlowRunnerError:
    return FlowRunnerError(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=copy.deepcopy(exc.details),
    )


def _translate_ingress(exc: flow_ingress.FlowIngressError) -> FlowRunnerError:
    return FlowRunnerError(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        details=copy.deepcopy(exc.details),
    )


def _require_enabled(workspace: Any) -> None:
    try:
        flow_publication.require_flow_publication(workspace)
    except flow_publication.FlowPublicationError as exc:
        raise _translate_publication(exc) from exc


def owned_system(
    db: DBSession,
    *,
    system_id: str,
    workspace: Any,
) -> System:
    """Resolve a tenant-owned System after checking the feature boundary."""

    _require_enabled(workspace)
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .one_or_none()
    )
    if system is None:
        raise FlowRunnerError("SYSTEM_NOT_FOUND", "System not found.", 404)
    return system


def _metadata(session: SessionModel) -> Mapping[str, Any]:
    return session.meta_data if isinstance(session.meta_data, Mapping) else {}


def _is_runner_session(
    session: SessionModel,
    *,
    system_id: str,
) -> bool:
    metadata = _metadata(session)
    return bool(
        metadata.get("kind") == RUNNER_SESSION_KIND
        and metadata.get("schema_version") == RUNNER_SESSION_SCHEMA_VERSION
        and metadata.get("system_id") == system_id
    )


def list_sessions(
    db: DBSession,
    *,
    system_id: str,
    workspace_id: str,
    user_id: str,
) -> list[SessionModel]:
    """Return only the actor's live typed sessions for this exact System.

    JSON predicates vary across supported databases, so the indexed, exact
    Runner context signature narrows the bounded candidate page before typed
    metadata is verified in Python. Tenant, owner, status and deletion are
    enforced by SQL predicates before metadata is inspected.
    """

    candidates = (
        db.query(SessionModel)
        .filter(
            SessionModel.workspace_id == workspace_id,
            SessionModel.user_id == user_id,
            SessionModel.context_signature == f"flow-runner|{system_id}",
            SessionModel.status != "deleted",
            SessionModel.deleted_at.is_(None),
        )
        .order_by(SessionModel.last_activity.desc(), SessionModel.created_at.desc())
        .limit(RUNNER_SESSION_QUERY_LIMIT)
        .all()
    )
    return [
        session
        for session in candidates
        if _is_runner_session(session, system_id=system_id)
    ]


def create_session(
    db: DBSession,
    *,
    system: System,
    workspace_id: str,
    user_id: str,
    title: str | None,
) -> SessionModel:
    now = datetime.utcnow()
    resolved_title = (title or f"{system.name} · Runner").strip()[:500]
    session = SessionModel(
        id=str(uuid4()),
        user_id=user_id,
        workspace_id=workspace_id,
        title=resolved_title or f"{system.name} · Runner",
        status="active",
        context_signature=f"flow-runner|{system.id}",
        created_at=now,
        last_activity=now,
        meta_data={
            "kind": RUNNER_SESSION_KIND,
            "schema_version": RUNNER_SESSION_SCHEMA_VERSION,
            "system_id": system.id,
        },
    )
    db.add(session)
    db.flush()
    return session


def owned_session(
    db: DBSession,
    *,
    session_id: str,
    system_id: str,
    workspace_id: str,
    user_id: str,
) -> SessionModel:
    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.id == session_id,
            SessionModel.workspace_id == workspace_id,
            SessionModel.user_id == user_id,
            SessionModel.context_signature == f"flow-runner|{system_id}",
            SessionModel.status != "deleted",
            SessionModel.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if session is None or not _is_runner_session(session, system_id=system_id):
        raise FlowRunnerError("RUNNER_SESSION_NOT_FOUND", "Runner session not found.", 404)
    return session


def session_runs(
    db: DBSession,
    *,
    session: SessionModel,
    system_id: str,
    workspace_id: str,
    user_id: str,
) -> list[Run]:
    """List session Runs through every durable ownership edge."""

    return (
        db.query(Run)
        .filter(
            Run.runner_session_id == session.id,
            Run.system_id == system_id,
            Run.workspace_id == workspace_id,
            Run.initiated_by_user_id == user_id,
        )
        .order_by(Run.started_at.desc())
        .limit(RUNNER_RUN_QUERY_LIMIT)
        .all()
    )


def published_summary(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
) -> dict[str, Any]:
    """Expose published execution evidence without leaking the mutable draft."""

    try:
        summary = flow_ingress.list_published_ingresses(
            db,
            system_id=system.id,
            workspace=workspace,
        )
    except flow_ingress.FlowIngressError as exc:
        raise _translate_ingress(exc) from exc
    return {
        "system_id": system.id,
        "system_name": system.name,
        "system_status": summary["system_status"],
        "published_flow_version_id": summary["published_flow_version_id"],
        "flow_sha256": summary["flow_sha256"],
        "runtime_mode": summary["runtime_mode"],
        "validation_mode": summary["validation_mode"],
        "ingresses": summary["ingresses"],
    }


def create_run(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
    user_id: str,
    session: SessionModel,
    ingress_id: str,
    payload: Mapping[str, Any],
    expected_published_version_id: str,
    expected_flow_sha256: str,
) -> Run:
    """Create one manual published-ingress Run after all validation passes."""

    if session.status != "active":
        raise FlowRunnerError(
            "RUNNER_SESSION_INACTIVE",
            "Only an active Runner session can accept a new Run.",
            409,
            {"session_id": session.id, "status": session.status},
        )
    try:
        run = flow_ingress.create_published_ingress_run(
            db,
            system_id=system.id,
            workspace=workspace,
            ingress_id=ingress_id,
            kind="manual",
            payload=payload,
            initiated_by_user_id=user_id,
            runner_session_id=session.id,
            expected_published_version_id=expected_published_version_id,
            expected_flow_sha256=expected_flow_sha256,
            adapter_evidence={"surface": "operator_runner"},
            trigger="manual",
        )
    except flow_ingress.FlowIngressError as exc:
        raise _translate_ingress(exc) from exc
    session.last_activity = datetime.utcnow()
    db.flush()
    return run
