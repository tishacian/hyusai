#!/usr/bin/env python3
"""Backfill retrieval_decision_trace from existing retrieval telemetry.

Default mode is dry-run. Use ``--apply`` to mutate JSON payloads. The script
never re-runs retrieval; it only summarizes telemetry already stored on runs,
messages and skill invocations.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.base import SessionLocal  # noqa: E402
from app.models.run import Run, SkillInvocation  # noqa: E402
from app.models.user import Message, Session as ChatSession  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.rag.decision_trace import build_retrieval_decision_trace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill retrieval decision traces from stored metrics.")
    parser.add_argument("--workspace-slug", default=None, help="Optional workspace slug to target.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum runs/messages to inspect per table.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Omit for dry-run.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        workspace = None
        if args.workspace_slug:
            workspace = db.query(Workspace).filter(Workspace.slug == args.workspace_slug).first()
            if not workspace:
                print(json.dumps({"status": "workspace_not_found", "workspace_slug": args.workspace_slug}, indent=2))
                return 2

        run_rows = _run_query(db, workspace_id=workspace.id if workspace else None, limit=args.limit)
        message_rows = _message_query(db, workspace_id=workspace.id if workspace else None, limit=args.limit)

        stats: dict[str, Any] = {
            "status": "applied" if args.apply else "dry_run",
            "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name} if workspace else None,
            "runs_scanned": len(run_rows),
            "runs_updated": 0,
            "messages_scanned": len(message_rows),
            "messages_updated": 0,
            "invocations_updated": 0,
            "skipped_no_metrics": 0,
            "skipped_existing_trace": 0,
            "items": [],
        }

        for run in run_rows:
            changed = False
            output = dict(run.output_ref or {})
            if _has_trace(output):
                stats["skipped_existing_trace"] += 1
            elif _has_retrieval_metrics(output):
                trace = _build_trace(output, request=run.input_ref or {})
                if trace:
                    changed = True
                    output["retrieval_decision_trace"] = trace
                    metrics = output.get("retrieval_metrics")
                    if isinstance(metrics, dict):
                        metrics["retrieval_decision_trace"] = trace
                    if args.apply:
                        run.output_ref = output
                        flag_modified(run, "output_ref")
            else:
                stats["skipped_no_metrics"] += 1

            for invocation in run.invocations or []:
                if _backfill_invocation(invocation, request=run.input_ref or {}, apply=args.apply):
                    changed = True
                    stats["invocations_updated"] += 1

            if changed:
                stats["runs_updated"] += 1
                stats["items"].append({"kind": "run", "id": run.id, "started_at": str(run.started_at)})

        for message in message_rows:
            meta = dict(message.meta_data or {})
            if _has_trace(meta):
                stats["skipped_existing_trace"] += 1
                continue
            if not _has_retrieval_metrics(meta):
                stats["skipped_no_metrics"] += 1
                continue
            trace = _build_trace(meta, request={})
            if not trace:
                stats["skipped_no_metrics"] += 1
                continue
            meta["retrieval_decision_trace"] = trace
            metrics = meta.get("retrieval_metrics")
            if isinstance(metrics, dict):
                metrics["retrieval_decision_trace"] = trace
            if args.apply:
                message.meta_data = meta
                flag_modified(message, "meta_data")
            stats["messages_updated"] += 1
            stats["items"].append({"kind": "message", "id": message.id, "timestamp": str(message.timestamp)})

        if args.apply:
            db.commit()
        else:
            db.rollback()

        stats["items"] = stats["items"][:100]
        print(json.dumps(stats, indent=2, default=str))
        return 0
    finally:
        db.close()


def _run_query(db: Any, *, workspace_id: str | None, limit: int) -> list[Run]:
    query = db.query(Run)
    if workspace_id:
        query = query.filter(Run.workspace_id == workspace_id)
    return query.order_by(Run.started_at.desc()).limit(max(1, limit)).all()


def _message_query(db: Any, *, workspace_id: str | None, limit: int) -> list[Message]:
    query = db.query(Message)
    if workspace_id:
        query = query.join(ChatSession, ChatSession.id == Message.session_id).filter(ChatSession.workspace_id == workspace_id)
    return query.order_by(Message.timestamp.desc()).limit(max(1, limit)).all()


def _backfill_invocation(invocation: SkillInvocation, *, request: Mapping[str, Any], apply: bool) -> bool:
    changed = False
    for attr in ("metrics", "output_ref", "trace"):
        payload = dict(getattr(invocation, attr) or {})
        if _has_trace(payload) or not _has_retrieval_metrics(payload):
            continue
        trace = _build_trace(payload, request=request)
        if not trace:
            continue
        payload["retrieval_decision_trace"] = trace
        metrics = payload.get("retrieval_metrics")
        if isinstance(metrics, dict):
            metrics["retrieval_decision_trace"] = trace
        if apply:
            setattr(invocation, attr, payload)
            flag_modified(invocation, attr)
        changed = True
    return changed


def _has_trace(payload: Mapping[str, Any]) -> bool:
    if isinstance(payload.get("retrieval_decision_trace"), Mapping):
        return True
    metrics = payload.get("retrieval_metrics")
    return isinstance(metrics, Mapping) and isinstance(metrics.get("retrieval_decision_trace"), Mapping)


def _has_retrieval_metrics(payload: Mapping[str, Any]) -> bool:
    if isinstance(payload.get("retrieval_metrics"), Mapping):
        return True
    return any(
        key in payload
        for key in (
            "retrieval_scope",
            "retrieval_plan",
            "dense_policy",
            "sparse_status",
            "cross_encoder_status",
            "pipeline",
            "mode_label",
            "selected_sources",
        )
    )


def _build_trace(payload: Mapping[str, Any], *, request: Mapping[str, Any]) -> dict[str, Any] | None:
    metrics = payload.get("retrieval_metrics") if isinstance(payload.get("retrieval_metrics"), Mapping) else payload
    try:
        return build_retrieval_decision_trace(
            request=request,
            context=payload,
            metrics=metrics,
            trace_source="backfilled_partial",
        )
    except Exception:  # noqa: BLE001 - one bad legacy row must not stop the audit
        return None


if __name__ == "__main__":
    raise SystemExit(main())
