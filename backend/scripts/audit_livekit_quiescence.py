#!/usr/bin/env python3
"""Fail-closed, content-free audit of realtime writers before VM quiescence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.db.base import SessionLocal
from app.models.expert_capture import ExpertCaptureSession
from app.services.livekit_service import (
    LiveKitNotConfiguredError,
    LiveKitService,
    LiveKitServiceError,
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
_CAPTURE_STATUSES = ("active", "paused")
_RECENT_ACTIVITY_SECONDS = 600


class LiveWriterAuditError(RuntimeError):
    """An input or upstream response cannot safely establish quiescence."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _reject_unhandled_pagination(payload: Mapping[str, Any]) -> None:
    # Current LiveKit ListRooms/ListParticipants contracts are unpaginated.  If
    # a future server adds a continuation marker, silently auditing only the
    # first page would create a dangerous false proof of quiescence.
    for key in ("nextPageToken", "next_page_token", "nextToken", "next_token"):
        if payload.get(key) not in (None, ""):
            raise LiveWriterAuditError("livekit_pagination_unsupported")


def _counter(room: Mapping[str, Any], camel: str, snake: str) -> int:
    values = [room[key] for key in (camel, snake) if key in room]
    if not values:
        # Protobuf JSON is allowed to omit scalar fields whose value is zero.
        return 0
    if len(values) == 2 and values[0] != values[1]:
        raise LiveWriterAuditError("livekit_room_counter_ambiguous")
    value = values[0]
    if isinstance(value, bool):
        raise LiveWriterAuditError("livekit_room_counter_invalid")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        parsed = int(value)
    else:
        raise LiveWriterAuditError("livekit_room_counter_invalid")
    if parsed < 0:
        raise LiveWriterAuditError("livekit_room_counter_invalid")
    return parsed


def _livekit_inventory(payload: Mapping[str, Any]) -> tuple[dict[str, int], frozenset[str]]:
    if not isinstance(payload, Mapping):
        raise LiveWriterAuditError("livekit_response_invalid")
    _reject_unhandled_pagination(payload)
    rooms = payload.get("rooms", [])
    if not isinstance(rooms, list):
        raise LiveWriterAuditError("livekit_response_invalid")

    participants = 0
    publishers = 0
    rooms_with_participants = 0
    rooms_with_publishers = 0
    room_names: set[str] = set()
    for room in rooms:
        if not isinstance(room, Mapping):
            raise LiveWriterAuditError("livekit_response_invalid")
        room_name = room.get("name")
        if not isinstance(room_name, str) or not room_name:
            raise LiveWriterAuditError("livekit_room_name_invalid")
        if room_name in room_names:
            raise LiveWriterAuditError("livekit_room_name_duplicate")
        room_names.add(room_name)
        participant_count = _counter(room, "numParticipants", "num_participants")
        publisher_count = _counter(room, "numPublishers", "num_publishers")
        if publisher_count > participant_count:
            raise LiveWriterAuditError("livekit_room_counter_inconsistent")
        participants += participant_count
        publishers += publisher_count
        rooms_with_participants += int(participant_count > 0)
        rooms_with_publishers += int(publisher_count > 0)

    return (
        {
            "room_count": len(rooms),
            "rooms_with_participants": rooms_with_participants,
            "rooms_with_publishers": rooms_with_publishers,
            "participant_count": participants,
            "publisher_count": publishers,
        },
        frozenset(room_names),
    )


def summarize_livekit_rooms(payload: Mapping[str, Any]) -> dict[str, int]:
    """Reduce a raw ListRooms response to counters, never identities or metadata."""

    summary, _room_names = _livekit_inventory(payload)
    return summary


def _optional_boolean(value: Mapping[str, Any], camel: str, snake: str) -> bool:
    candidates = [value[key] for key in (camel, snake) if key in value]
    if not candidates:
        return False
    if len(candidates) == 2 and candidates[0] != candidates[1]:
        raise LiveWriterAuditError("livekit_participant_flag_ambiguous")
    if not isinstance(candidates[0], bool):
        raise LiveWriterAuditError("livekit_participant_flag_invalid")
    return candidates[0]


def _participant_inventory(payload: Mapping[str, Any]) -> tuple[int, int]:
    if not isinstance(payload, Mapping):
        raise LiveWriterAuditError("livekit_participant_response_invalid")
    _reject_unhandled_pagination(payload)
    participants = payload.get("participants", [])
    if not isinstance(participants, list):
        raise LiveWriterAuditError("livekit_participant_response_invalid")
    publishers = 0
    identities: set[str] = set()
    for participant in participants:
        if not isinstance(participant, Mapping):
            raise LiveWriterAuditError("livekit_participant_response_invalid")
        identity = participant.get("identity")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise LiveWriterAuditError("livekit_participant_identity_invalid")
        identities.add(identity)
        publishers += int(_optional_boolean(participant, "isPublisher", "is_publisher"))
    return len(participants), publishers


async def _summarize_participants(
    service: LiveKitService,
    room_names: frozenset[str],
) -> dict[str, int]:
    participants = 0
    publishers = 0
    rooms_with_participants = 0
    rooms_with_publishers = 0
    for room_name in sorted(room_names):
        room_participants, room_publishers = _participant_inventory(
            await service.list_participants(room_name=room_name)
        )
        participants += room_participants
        publishers += room_publishers
        rooms_with_participants += int(room_participants > 0)
        rooms_with_publishers += int(room_publishers > 0)
    return {
        "participant_inventory_count": participants,
        "publisher_inventory_count": publishers,
        "rooms_with_inventory_participants": rooms_with_participants,
        "rooms_with_inventory_publishers": rooms_with_publishers,
    }


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def summarize_capture_sessions(
    db: Any,
    *,
    livekit_room_names: frozenset[str],
    now: datetime,
    recent_activity_seconds: int = _RECENT_ACTIVITY_SECONDS,
) -> dict[str, int]:
    """Correlate durable session state in memory and return content-free counts.

    An ``active`` database status alone is not a live-writer signal: sessions are
    durable workflows and old deployments contain intentionally resumable rows.
    Only a recent row with an explicit active LiveKit status whose private room
    name is present in the authoritative ListRooms response is blocking.
    """

    if isinstance(recent_activity_seconds, bool) or not isinstance(recent_activity_seconds, int):
        raise LiveWriterAuditError("recent_activity_window_invalid")
    if recent_activity_seconds < 1 or recent_activity_seconds > 86_400:
        raise LiveWriterAuditError("recent_activity_window_invalid")
    now_utc = _naive_utc(now)
    recent_cutoff = now_utc - timedelta(seconds=recent_activity_seconds)
    rows = (
        db.query(
            ExpertCaptureSession.status,
            ExpertCaptureSession.updated_at,
            ExpertCaptureSession.metrics,
        )
        .filter(ExpertCaptureSession.status.in_(_CAPTURE_STATUSES))
        .all()
    )
    counts = {status: 0 for status in _CAPTURE_STATUSES}
    recent_active_count = 0
    livekit_marked_active_count = 0
    recent_livekit_active_count = 0
    correlated_recent_active_count = 0
    for status, updated_at, metrics in rows:
        if status not in counts:
            raise LiveWriterAuditError("capture_session_status_invalid")
        counts[status] += 1
        if status != "active":
            continue
        is_recent = isinstance(updated_at, datetime) and _naive_utc(updated_at) >= recent_cutoff
        recent_active_count += int(is_recent)
        livekit = metrics.get("livekit") if isinstance(metrics, Mapping) else None
        room_status_active = (
            isinstance(livekit, Mapping)
            and str(livekit.get("room_status") or "").strip().lower() == "active"
        )
        livekit_marked_active_count += int(room_status_active)
        if not (is_recent and room_status_active):
            continue
        recent_livekit_active_count += 1
        room_name = livekit.get("room_name")
        if isinstance(room_name, str) and room_name in livekit_room_names:
            correlated_recent_active_count += 1
    return {
        "active_count": counts["active"],
        "paused_count": counts["paused"],
        "recent_activity_window_seconds": recent_activity_seconds,
        "recent_active_count": recent_active_count,
        "livekit_marked_active_count": livekit_marked_active_count,
        "recent_livekit_active_count": recent_livekit_active_count,
        "correlated_recent_active_count": correlated_recent_active_count,
        "blocking_count": correlated_recent_active_count,
    }


async def audit_livekit_quiescence(
    db: Any,
    *,
    candidate_sha: str,
    deployment_id: str,
    livekit_service: LiveKitService | None = None,
    now: datetime | None = None,
    recent_activity_seconds: int = _RECENT_ACTIVITY_SECONDS,
) -> dict[str, Any]:
    """Audit LiveKit and persisted capture writers using only aggregate evidence.

    Durable database statuses are observed but do not block by themselves.
    ``paused`` sessions are non-blocking because they have no live writer and
    their resumable state is already persisted in PostgreSQL.
    """

    service = livekit_service or LiveKitService()
    if not service.configured:
        raise LiveKitNotConfiguredError("LiveKit control plane is not configured")

    livekit, livekit_room_names = _livekit_inventory(await service.list_rooms())
    participants = await _summarize_participants(service, livekit_room_names)
    room_reported_participants = livekit["participant_count"]
    room_reported_publishers = livekit["publisher_count"]
    livekit.update(participants)
    livekit["room_reported_participant_count"] = room_reported_participants
    livekit["room_reported_publisher_count"] = room_reported_publishers
    # Room.num_participants excludes hidden participants.  The candidate voice
    # sidecar is intentionally hidden, so ListParticipants is authoritative when
    # it observes a larger count; the room counters remain an independent floor.
    livekit["participant_count"] = max(
        room_reported_participants,
        participants["participant_inventory_count"],
    )
    livekit["publisher_count"] = max(
        room_reported_publishers,
        participants["publisher_inventory_count"],
    )
    capture = summarize_capture_sessions(
        db,
        livekit_room_names=livekit_room_names,
        now=now or datetime.now(UTC),
        recent_activity_seconds=recent_activity_seconds,
    )
    blockers = {
        "livekit_participant_count": livekit["participant_count"],
        "livekit_publisher_count": livekit["publisher_count"],
        "correlated_recent_active_capture_count": capture["blocking_count"],
    }
    passed = all(value == 0 for value in blockers.values())
    return {
        "schema_version": 1,
        "kind": "live_writer_quiescence_audit",
        "result": "passed" if passed else "failed",
        "candidate_sha": candidate_sha,
        "deployment_id": deployment_id,
        "policy": {
            "livekit_control_required": True,
            "participant_inventory_required": True,
            "observed_capture_statuses": list(_CAPTURE_STATUSES),
            "database_status_alone_blocks": False,
            "recent_activity_requires_livekit_room_correlation": True,
            "paused_capture_sessions_block": False,
        },
        "livekit": livekit,
        "expert_capture": capture,
        "blockers": blockers,
    }


def _failure_report(*, candidate_sha: str, deployment_id: str, code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "live_writer_quiescence_audit",
        "result": "failed",
        "candidate_sha": candidate_sha,
        "deployment_id": deployment_id,
        "failure_code": code,
    }


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _emit(payload: Mapping[str, Any], output: Path | None) -> None:
    if output is not None:
        _write_atomic(output, payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    candidate_sha = str(args.expected_sha).lower()
    deployment_id = str(args.deployment_id)
    if not _SHA_RE.fullmatch(candidate_sha):
        _emit(
            _failure_report(candidate_sha="invalid", deployment_id=deployment_id, code="expected_sha_invalid"),
            args.output,
        )
        return 1
    if not _DEPLOYMENT_ID_RE.fullmatch(deployment_id):
        _emit(
            _failure_report(candidate_sha=candidate_sha, deployment_id="invalid", code="deployment_id_invalid"),
            args.output,
        )
        return 1
    if os.environ.get("AGENTIUM_IMAGE_REVISION", "").lower() != candidate_sha:
        _emit(
            _failure_report(
                candidate_sha=candidate_sha,
                deployment_id=deployment_id,
                code="candidate_revision_mismatch",
            ),
            args.output,
        )
        return 1

    try:
        with SessionLocal() as db:
            report = asyncio.run(
                audit_livekit_quiescence(
                    db,
                    candidate_sha=candidate_sha,
                    deployment_id=deployment_id,
                )
            )
            db.rollback()
    except LiveKitNotConfiguredError:
        report = _failure_report(
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
            code="livekit_not_configured",
        )
    except LiveKitServiceError:
        report = _failure_report(
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
            code="livekit_control_unavailable",
        )
    except SQLAlchemyError:
        report = _failure_report(
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
            code="database_unavailable",
        )
    except LiveWriterAuditError as exc:
        report = _failure_report(
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
            code=exc.code,
        )
    except Exception:
        # Never serialize exception text: upstream responses may contain room or
        # tenant metadata and database errors may contain business values.
        report = _failure_report(
            candidate_sha=candidate_sha,
            deployment_id=deployment_id,
            code="audit_internal_error",
        )

    _emit(report, args.output)
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
