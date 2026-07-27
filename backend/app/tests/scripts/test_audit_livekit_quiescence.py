from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

import scripts.audit_livekit_quiescence as audit_module
from app.models.expert_capture import ExpertCaptureSession
from app.services.livekit_service import LiveKitService
from scripts.audit_livekit_quiescence import (
    LiveWriterAuditError,
    audit_livekit_quiescence,
    main,
    summarize_livekit_rooms,
)

SHA = "a" * 40
DEPLOYMENT_ID = "20260722T170000Z-aaaaaaaaaaaa"


class FakeLiveKitService:
    configured = True

    def __init__(self, payload: dict, *, participants: dict[str, dict] | None = None) -> None:
        self.payload = payload
        self.participants = participants or {}

    async def list_rooms(self) -> dict:
        return self.payload

    async def list_participants(self, *, room_name: str) -> dict:
        return self.participants.get(room_name, {})


def _capture(
    db_session,
    *,
    status: str,
    title: str,
    updated_at: datetime | None = None,
    metrics: dict | None = None,
) -> None:
    db_session.add(
        ExpertCaptureSession(
            id=str(uuid4()),
            workspace_id=str(uuid4()),
            title=title,
            objective=f"private objective for {title}",
            status=status,
            transcript=[{"text": f"private transcript for {title}"}],
            updated_at=updated_at,
            metrics=metrics or {},
        )
    )
    db_session.commit()


def test_audit_fails_on_livekit_activity_and_active_capture_without_leaking_content(
    db_session,
) -> None:
    _capture(db_session, status="active", title="Andritz private interview")
    _capture(db_session, status="paused", title="Octocity private interview")
    payload = {
        "rooms": [
            {
                "name": "tenant-private-room",
                "sid": "RM_private",
                "metadata": '{"workspace_slug":"andritz","session_id":"private"}',
                "numParticipants": "2",
                "numPublishers": 1,
            },
            {
                "name": "empty-private-room",
                "numParticipants": 0,
                "numPublishers": 0,
            },
        ]
    }

    report = asyncio.run(
        audit_livekit_quiescence(
            db_session,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            livekit_service=FakeLiveKitService(payload),
        )
    )
    serialized = json.dumps(report).lower()

    assert report["result"] == "failed"
    assert report["livekit"]["room_count"] == 2
    assert report["livekit"]["rooms_with_participants"] == 1
    assert report["livekit"]["rooms_with_publishers"] == 1
    assert report["livekit"]["participant_count"] == 2
    assert report["livekit"]["publisher_count"] == 1
    assert report["livekit"]["participant_inventory_count"] == 0
    assert report["livekit"]["publisher_inventory_count"] == 0
    assert report["expert_capture"]["active_count"] == 1
    assert report["expert_capture"]["paused_count"] == 1
    assert report["expert_capture"]["blocking_count"] == 0
    assert report["blockers"] == {
        "livekit_participant_count": 2,
        "livekit_publisher_count": 1,
        "correlated_recent_active_capture_count": 0,
    }
    for forbidden in (
        "andritz",
        "octocity",
        "private interview",
        "private objective",
        "private transcript",
        "tenant-private-room",
        "rm_private",
        "workspace_slug",
        "session_id",
    ):
        assert forbidden not in serialized


def test_historical_active_workflows_are_observed_but_do_not_block(db_session) -> None:
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    stale = now - timedelta(days=1)
    for index in range(89):
        metrics = (
            {"livekit": {"room_status": "closed", "room_name": f"private-room-{index}"}}
            if index < 34
            else {}
        )
        _capture(
            db_session,
            status="active",
            title=f"Historical private workflow {index}",
            updated_at=stale,
            metrics=metrics,
        )
    _capture(
        db_session,
        status="paused",
        title="Historical paused workflow",
        updated_at=stale,
    )

    report = asyncio.run(
        audit_livekit_quiescence(
            db_session,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            livekit_service=FakeLiveKitService({}),
            now=now,
        )
    )

    assert report["result"] == "passed"
    assert report["expert_capture"] == {
        "active_count": 89,
        "paused_count": 1,
        "recent_activity_window_seconds": 600,
        "recent_active_count": 0,
        "livekit_marked_active_count": 0,
        "recent_livekit_active_count": 0,
        "correlated_recent_active_count": 0,
        "blocking_count": 0,
    }
    assert report["policy"]["database_status_alone_blocks"] is False


def test_hidden_livekit_participant_is_found_by_participant_inventory(db_session) -> None:
    payload = {
        "rooms": [
            {
                "name": "private-hidden-room",
                # LiveKit Room.num_participants excludes hidden participants.
                "numParticipants": 0,
                "numPublishers": 0,
            }
        ]
    }
    participants = {
        "private-hidden-room": {
            "participants": [
                {
                    "identity": "private-hidden-agent",
                    "hidden": True,
                    "isPublisher": True,
                    "metadata": "private-sidecar-metadata",
                }
            ]
        }
    }

    report = asyncio.run(
        audit_livekit_quiescence(
            db_session,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            livekit_service=FakeLiveKitService(payload, participants=participants),
        )
    )
    serialized = json.dumps(report).lower()

    assert report["result"] == "failed"
    assert report["livekit"]["room_reported_participant_count"] == 0
    assert report["livekit"]["participant_inventory_count"] == 1
    assert report["blockers"]["livekit_participant_count"] == 1
    assert report["blockers"]["livekit_publisher_count"] == 1
    for forbidden in ("private-hidden-room", "private-hidden-agent", "private-sidecar-metadata"):
        assert forbidden not in serialized


def test_recent_explicit_livekit_session_only_blocks_when_room_is_correlated(
    db_session,
) -> None:
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    _capture(
        db_session,
        status="active",
        title="Current private workflow",
        updated_at=now - timedelta(seconds=30),
        metrics={"livekit": {"room_status": "active", "room_name": "private-current-room"}},
    )

    uncorrelated = asyncio.run(
        audit_livekit_quiescence(
            db_session,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            livekit_service=FakeLiveKitService({}),
            now=now,
        )
    )
    correlated = asyncio.run(
        audit_livekit_quiescence(
            db_session,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            livekit_service=FakeLiveKitService(
                {
                    "rooms": [
                        {
                            "name": "private-current-room",
                            "numParticipants": 0,
                            "numPublishers": 0,
                        }
                    ]
                }
            ),
            now=now,
        )
    )

    assert uncorrelated["result"] == "passed"
    assert uncorrelated["expert_capture"]["recent_livekit_active_count"] == 1
    assert uncorrelated["expert_capture"]["correlated_recent_active_count"] == 0
    assert correlated["result"] == "failed"
    assert correlated["blockers"]["correlated_recent_active_capture_count"] == 1
    assert "private-current-room" not in json.dumps(correlated)


def test_paused_capture_and_empty_rooms_are_non_blocking(db_session) -> None:
    _capture(db_session, status="paused", title="Persisted resumable session")

    report = asyncio.run(
        audit_livekit_quiescence(
            db_session,
            candidate_sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            livekit_service=FakeLiveKitService({}),
        )
    )

    assert report["result"] == "passed"
    assert report["livekit"]["room_count"] == 0
    assert report["expert_capture"]["paused_count"] == 1
    assert report["expert_capture"]["blocking_count"] == 0
    assert report["policy"]["paused_capture_sessions_block"] is False


def test_livekit_inventory_uses_the_authenticated_service_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict, str | None]] = []
    service = LiveKitService()
    monkeypatch.setattr(service, "require_configured", lambda: None)

    async def fake_twirp(method: str, body: dict, *, room_name: str | None = None) -> dict:
        calls.append((method, body, room_name))
        return {"rooms": []}

    monkeypatch.setattr(service, "_twirp", fake_twirp)

    assert asyncio.run(service.list_rooms()) == {"rooms": []}
    assert asyncio.run(service.list_participants(room_name="private-room")) == {"rooms": []}
    assert calls == [
        ("ListRooms", {}, None),
        ("ListParticipants", {"room": "private-room"}, "private-room"),
    ]


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"rooms": "not-a-list"}, "livekit_response_invalid"),
        ({"rooms": ["not-a-room"]}, "livekit_response_invalid"),
        (
            {"rooms": [], "nextPageToken": "private-continuation"},
            "livekit_pagination_unsupported",
        ),
        ({"rooms": [{"name": "room", "numParticipants": True}]}, "livekit_room_counter_invalid"),
        (
            {"rooms": [{"name": "room", "numParticipants": 1, "num_participants": 2}]},
            "livekit_room_counter_ambiguous",
        ),
        (
            {"rooms": [{"name": "room", "numParticipants": 0, "numPublishers": 1}]},
            "livekit_room_counter_inconsistent",
        ),
    ],
)
def test_livekit_payload_is_parsed_fail_closed(payload: dict, code: str) -> None:
    with pytest.raises(LiveWriterAuditError) as error:
        summarize_livekit_rooms(payload)
    assert error.value.code == code


@pytest.mark.parametrize(
    "participants,code",
    [
        ({"participants": "not-a-list"}, "livekit_participant_response_invalid"),
        (
            {"participants": [], "next_page_token": "private-continuation"},
            "livekit_pagination_unsupported",
        ),
        (
            {"participants": [{"identity": "duplicate"}, {"identity": "duplicate"}]},
            "livekit_participant_identity_invalid",
        ),
        (
            {"participants": [{"identity": "private", "isPublisher": "yes"}]},
            "livekit_participant_flag_invalid",
        ),
    ],
)
def test_participant_inventory_is_parsed_fail_closed(
    db_session,
    participants: dict,
    code: str,
) -> None:
    rooms = {
        "rooms": [
            {
                "name": "private-room",
                "numParticipants": 0,
                "numPublishers": 0,
            }
        ]
    }
    with pytest.raises(LiveWriterAuditError) as error:
        asyncio.run(
            audit_livekit_quiescence(
                db_session,
                candidate_sha=SHA,
                deployment_id=DEPLOYMENT_ID,
                livekit_service=FakeLiveKitService(
                    rooms,
                    participants={"private-room": participants},
                ),
            )
        )
    assert error.value.code == code


def test_cli_rejects_a_different_candidate_image_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENTIUM_IMAGE_REVISION", "b" * 40)

    exit_code = main(
        [
            "--expected-sha",
            SHA,
            "--deployment-id",
            DEPLOYMENT_ID,
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report == {
        "schema_version": 1,
        "kind": "live_writer_quiescence_audit",
        "result": "failed",
        "candidate_sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "failure_code": "candidate_revision_mismatch",
    }
    assert "b" * 40 not in json.dumps(report)


def test_cli_never_serializes_upstream_exception_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeSession:
        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def rollback(self) -> None:
            return None

    async def explode(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("private-room andritz secret-session-id")

    monkeypatch.setenv("AGENTIUM_IMAGE_REVISION", SHA)
    monkeypatch.setattr(audit_module, "SessionLocal", FakeSession)
    monkeypatch.setattr(audit_module, "audit_livekit_quiescence", explode)

    exit_code = main(
        [
            "--expected-sha",
            SHA,
            "--deployment-id",
            DEPLOYMENT_ID,
        ]
    )
    serialized = capsys.readouterr().out.lower()
    report = json.loads(serialized)

    assert exit_code == 1
    assert report["failure_code"] == "audit_internal_error"
    for forbidden in ("private-room", "andritz", "secret-session-id"):
        assert forbidden not in serialized
