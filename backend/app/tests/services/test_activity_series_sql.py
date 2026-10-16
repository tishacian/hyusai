"""Differential PostgreSQL tests: fast aggregates must equal native authorization."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.brd_document import BrdDocument
from app.models.compute_run import ComputeRun
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import Session as ChatSession
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIAMConfig, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.activity_observability import series_sql
from app.services.activity_observability.queries import VisibilityReadContext
from app.services.activity_observability.series import activity_series
from app.tests.services import test_activity_observability_postgres as pg_fixtures

pg = pg_fixtures.pg
START, UNTIL = datetime(2026, 1, 1), datetime(2026, 1, 2)


def seed(engine):
    with Session(engine) as db:
        ws = db.get(Workspace, "pg-activity-ws")
        users = [
            User(
                id=name,
                username=name,
                role="admin" if name == "platform" else "user",
                is_active=True,
            )
            for name in ("member", "other", "reviewer", "owner", "platform")
        ]
        db.add_all(users)
        db.flush()
        db.add_all(
            [
                WorkspaceMember(
                    workspace_id=ws.id,
                    user_id=user.id,
                    role="member",
                    role_template={
                        "reviewer": "workspace_reviewer",
                        "owner": "workspace_admin",
                    }.get(user.id, "workspace_contributor"),
                )
                for user in users
            ]
        )
        db.add(WorkspaceIAMConfig(workspace_id=ws.id, role_flags={}, capability_overrides={}))
        db.add(System(id="series-system", workspace_id=ws.id, name="Series"))
        db.add_all(
            [
                ChatSession(id="session-own", workspace_id=ws.id, user_id="member"),
                ChatSession(
                    id="session-deleted", workspace_id=ws.id, user_id="member", status="deleted"
                ),
            ]
        )
        db.add(
            BrdDocument(
                id="series-brd",
                workspace_id=ws.id,
                created_by_user_id="owner",
                sha256="1" * 64,
                size_bytes=1,
                filename="series",
                storage_key="series",
                extraction={},
            )
        )
        db.flush()
        for i in range(48):
            started = START + timedelta(minutes=i * 29)
            if i < 4:
                started -= timedelta(days=2)
            finished = START + timedelta(minutes=i * 29 + 10)
            run = Run(
                id=f"r{i}",
                workspace_id=ws.id,
                system_id="series-system" if i % 2 else None,
                initiated_by_user_id="member" if i % 3 == 0 else "other",
                trigger="chat_agentic" if i % 4 == 0 else "manual",
                execution_surface="\tBuIlDeR_PrEvIeW\u00a0" if i % 7 == 0 else None,
                status="running" if i % 5 == 0 else "failed" if i % 3 == 0 else "completed",
                started_at=started,
                completed_at=finished if i % 5 else None,
                duration_ms=None if i % 4 else i,
            )
            db.add(run)
            db.flush()
            for j in range(3):
                currency = ("USD", "EUR", "éUR")[j]
                db.add(
                    SkillInvocation(
                        id=f"i{i}-{j}",
                        run_id=run.id,
                        status="completed",
                        started_at=started,
                        completed_at=finished,
                        cost_measured=i % 5 != 0,
                        cost=0 if i % 7 == 0 else 0.1,
                        provider_cost_usd=None if i % 6 == 0 else 0.2,
                        metrics={
                            "cost_evidence": {
                                "state": "measured" if j == 0 else "calculated",
                                "currency": currency,
                            }
                        },
                    )
                )
            db.add(
                ComputeRun(
                    id=f"c{i}",
                    workspace_id=ws.id,
                    run_id=run.id,
                    user_id="member" if i % 2 else "other",
                    kind="dataops",
                    operation="prepare",
                    status="succeeded",
                    deadline_at=UNTIL,
                    created_at=started,
                    started_at=started,
                    finished_at=finished,
                    cost_usd=None if i % 5 else 0.3,
                )
            )
            db.add(
                WorkspaceJob(
                    id=f"j{i}",
                    workspace_id=ws.id,
                    run_id=run.id,
                    created_by_user_id="member" if i % 2 else "other",
                    session_id="session-own"
                    if i % 3 == 0
                    else "session-deleted"
                    if i % 4 == 0
                    else None,
                    kind="qualification",
                    status="completed",
                    created_at=started,
                    started_at=started,
                    completed_at=finished,
                )
            )
        for owner in ("owner", "other"):
            db.add(
                WorkspaceJob(
                    id=f"brd-{owner}",
                    workspace_id=ws.id,
                    system_id="series-system",
                    created_by_user_id=owner,
                    kind="brd_generation",
                    status="completed",
                    created_at=START,
                    completed_at=START + timedelta(hours=1),
                    input_ref={"document_id": "series-brd"},
                )
            )
        db.commit()
        # Historical measurement shapes: corruption cannot fabricate a number or
        # make the SQL cast fail across all other authorized records.
        for identifier, finish, duration in (
            ("r1", "2026-01-01T12:00:bad", "12"),
            ("r2", None, True),
            ("r3", "2026-01-01T12:00:00+01:00", -3),
            ("r4", "2026-01-01T00:00:00.000001Z", 1),
            ("r5", "2026-01-02T00:00:00Z", 10000),
            ("r6", "2026-01-01T24:00:00Z", 1),
            ("r7", "2026-01-01T23:59:60Z", 1),
            ("r8", "2026-01-01T23:59:59.9999999Z", 1),
        ):
            row = db.query(Activity).filter_by(native_id=identifier, kind="run").one()
            row.snapshot = {
                **row.snapshot,
                "finished_at": finish,
                "measurements": {"duration_ms": duration},
            }
            row.origin = "snapshot_only"
        db.commit()


def equal(actual, expected):
    if isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            if key != "as_of":
                equal(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected, strict=True):
            equal(left, right)
    else:
        assert actual == expected


def test_fast_aggregate_matches_native_for_mixed_rights_measurements_and_windows(pg, monkeypatch):
    seed(pg)
    original = series_sql.aggregate_compat
    cases = [
        {},
        {"system_id": ""},
        {"time_basis": "finished"},
        {"bucket": "day"},
        {"kind": "run", "status": "succeeded", "system_id": "series-system"},
        {"metric": "cost", "kind": "skill_invocation", "time_basis": "finished"},
        {"metric": "cost", "kind": "compute_run", "time_basis": "finished", "bucket": "day"},
    ]
    for identity in ("member", "reviewer", "owner", "platform"):
        with (
            pg.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
            Session(connection) as db,
        ):
            ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, identity)
            for kwargs in cases:
                taken = []

                def accelerated(*args, **options):
                    result = original(*args, **options)
                    taken.append(result is not None)
                    return result

                monkeypatch.setattr(series_sql, "aggregate_compat", accelerated)
                fast = activity_series(db, ws, user, start=START, until=UNTIL, **kwargs)
                assert taken == [True]
                monkeypatch.setattr(series_sql, "aggregate_compat", lambda *args, **kwargs: None)
                native = activity_series(db, ws, user, start=START, until=UNTIL, **kwargs)
                equal(fast, native)
            monkeypatch.setattr(series_sql, "aggregate_compat", original)


def test_unsupported_iam_and_migration_marker_use_native_path(pg):
    seed(pg)
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
        Session(connection) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "member")
        config = db.get(WorkspaceIAMConfig, ws.id)
        for mode in ("shadow", "enforce"):
            config.capability_overrides = {
                "authorization_v2": {"policy_version": 2, "modes": {"skill_invocation.read": mode}}
            }
            db.flush()
            context = VisibilityReadContext(db, ws, user)
            assert (
                series_sql.aggregate_compat(
                    db,
                    ws,
                    user,
                    read_context=context,
                    start=START,
                    until=UNTIL,
                    metric="activity",
                    kind=None,
                    status=None,
                    system_id=None,
                    bucket="hour",
                    time_basis="created",
                )
                is None
            )
        config.capability_overrides = {}
        ws.settings = {
            "_migration_059_andritz_agentic_default_state": {
                "revision": "059_andritz_agentic_default",
                "schema": 1,
                "system_id": "series-system",
            }
        }
        db.flush()
        context = VisibilityReadContext(db, ws, user)
        assert (
            series_sql.aggregate_compat(
                db,
                ws,
                user,
                read_context=context,
                start=START,
                until=UNTIL,
                metric="activity",
                kind=None,
                status=None,
                system_id=None,
                bucket="hour",
                time_basis="created",
            )
            is None
        )
