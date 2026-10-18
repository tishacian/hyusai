"""Differential PostgreSQL tests: fast aggregates must equal native authorization."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.config import settings
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
from app.services.activity_observability.queries import VisibilityReadContext, list_activities
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
        {"kind": "run", "status": "pending,running,waiting"},
        {"status": "pending,running,waiting"},
        {"status": "succeeded,failed", "time_basis": "finished"},
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


@pytest.mark.parametrize("identity,expected_count", [("member", 3), ("owner", 6), ("platform", 6)])
def test_active_union_sql_matches_list_and_native_with_private_runs(pg, monkeypatch, identity, expected_count):
    seed(pg)
    with Session(pg) as db:
        db.add(System(id="active-system", workspace_id="pg-activity-ws", name="Active"))
        db.flush()
        for owner in ("member", "other"):
            for state in ("pending", "running", "waiting_subflows", "completed", "failed"):
                db.add(Run(
                    id=f"active-{owner}-{state}", workspace_id="pg-activity-ws",
                    system_id="active-system", initiated_by_user_id=owner,
                    trigger="chat_agentic", status=state, started_at=START,
                ))
        db.commit()
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
        Session(connection) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, identity)
        filters = dict(kind="run", system_id="active-system", status="pending,running,waiting")
        original = series_sql.aggregate_compat
        taken = []

        def accelerated(*args, **options):
            result = original(*args, **options)
            taken.append(result is not None)
            return result

        monkeypatch.setattr(series_sql, "aggregate_compat", accelerated)
        fast = activity_series(db, ws, user, start=START, until=UNTIL, **filters)
        assert taken == [True]
        listed = list_activities(db, ws, user, since=START, until=UNTIL, limit=1, **filters)
        assert listed["total"] == fast["totals"]["total"] == expected_count
        assert len(listed["items"]) == 1
        assert listed["has_more"]
        assert listed["aggregates"]["by_status"] == fast["totals"]["by_status"] == {
            state: expected_count // 3 for state in ("pending", "running", "waiting")
        }
        monkeypatch.setattr(series_sql, "aggregate_compat", lambda *args, **kwargs: None)
        native = activity_series(db, ws, user, start=START, until=UNTIL, **filters)
        equal(fast, native)


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


def _member(db):
    ws = db.get(Workspace, "pg-activity-ws")
    user = User(id="member", username="member", role="user", is_active=True)
    db.add(user)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="member"))
    db.flush()
    return ws, user


def test_finished_window_uses_utc_offsets_and_counts_missing_only_when_created_in_window(
    pg, monkeypatch
):
    with Session(pg) as db:
        ws, user = _member(db)
        historical = START - timedelta(days=2)
        finishes = [
            "2025-12-31T23:30:00-01:00",  # First UTC day despite previous local day.
            "2026-01-02T00:30:00+01:00",  # Last UTC day despite next local day.
            "2026-W01-4T12:00:00Z",  # Historical ISO week syntax accepted by Python.
            "2026-01-01T00:30:00+01:00",  # Before the window in UTC.
            "2026-01-02T00:00:00Z",  # Exclusive upper bound.
            "invalid-old",  # Missing date outside the coverage population.
            "invalid-current",
        ]
        for index, finish in enumerate(finishes):
            db.add(
                Run(
                    id=f"offset-{index}",
                    workspace_id=ws.id,
                    initiated_by_user_id=user.id,
                    status="completed",
                    started_at=START if index == 6 else historical,
                    completed_at=START,
                )
            )
        db.commit()
        for index, finish in enumerate(finishes):
            row = db.query(Activity).filter_by(kind="run", native_id=f"offset-{index}").one()
            row.snapshot = {**row.snapshot, "finished_at": finish}
        db.commit()
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        Session(conn) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "member")
        fast = activity_series(db, ws, user, start=START, until=UNTIL, time_basis="finished")
        assert fast["totals"]["total"] == 3
        assert fast["coverage"]["missing_finished_at"] == 1
        monkeypatch.setattr(series_sql, "aggregate_compat", lambda *args, **kwargs: None)
        equal(fast, activity_series(db, ws, user, start=START, until=UNTIL, time_basis="finished"))


@pytest.mark.parametrize("population", ["parsed_offsets", "unparsed_dates", "brd_jobs"])
def test_exception_bound_falls_back_for_whole_population(pg, monkeypatch, population):
    count = 257 if population == "brd_jobs" else 129
    dated = population in {"parsed_offsets", "unparsed_dates"}
    with Session(pg) as db:
        ws, user = _member(db)
        if dated:
            db.add_all(
                [
                    Run(
                        id=f"bound-{i}",
                        workspace_id=ws.id,
                        initiated_by_user_id=user.id,
                        status="completed",
                        started_at=START,
                        completed_at=START + timedelta(hours=1),
                    )
                    for i in range(count)
                ]
            )
        else:
            membership = (
                db.query(WorkspaceMember).filter_by(workspace_id=ws.id, user_id=user.id).one()
            )
            membership.role, membership.role_template = "admin", "workspace_admin"
            db.add(
                BrdDocument(
                    id="bound-document",
                    workspace_id=ws.id,
                    created_by_user_id=user.id,
                    sha256="b" * 64,
                    size_bytes=1,
                    filename="bound",
                    storage_key="bound",
                    extraction={},
                )
            )
            db.flush()
            db.add_all(
                [
                    WorkspaceJob(
                        id=f"bound-{i}",
                        workspace_id=ws.id,
                        created_by_user_id=user.id,
                        input_ref={"document_id": "bound-document"},
                        kind="brd_generation",
                        status="completed",
                        created_at=START,
                        completed_at=START + timedelta(hours=1),
                    )
                    for i in range(count)
                ]
            )
        db.commit()
        if dated:
            # Offsets parse natively into the typed finish (fast path); text the
            # native parser rejects stays unparsed and keeps the bounded check.
            suffix = "+00:00" if population == "parsed_offsets" else "bad"
            for i in range(count):
                row = db.query(Activity).filter_by(kind="run", native_id=f"bound-{i}").one()
                row.snapshot = {
                    **row.snapshot,
                    "finished_at": f"2026-01-01T01:00:00.{i:06d}{suffix}",
                }
            db.commit()
    original, taken = series_sql.aggregate_compat, []

    def accelerated(*args, **kwargs):
        result = original(*args, **kwargs)
        taken.append(result is not None)
        return result

    monkeypatch.setattr(series_sql, "aggregate_compat", accelerated)
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        Session(conn) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "member")
        result = activity_series(db, ws, user, start=START, until=UNTIL, time_basis="finished")
        assert taken == [population == "parsed_offsets"]
        # No exceptional population is silently clipped at the fast-path safety
        # bound; BRD authorization still reads the native document.
        if population == "unparsed_dates":
            assert result["totals"]["total"] == 0
            assert result["coverage"]["missing_finished_at"] == count
        else:
            assert result["totals"]["total"] == count
        monkeypatch.setattr(series_sql, "aggregate_compat", lambda *args, **kwargs: None)
        equal(
            result, activity_series(db, ws, user, start=START, until=UNTIL, time_basis="finished")
        )


@pytest.mark.parametrize("protected_kind", ["service_window", "delivery_receipt"])
def test_sensitive_kinds_use_native_reader_without_disabling_unrelated_population(
    pg, monkeypatch, protected_kind
):
    with Session(pg) as db:
        ws, user = _member(db)
        db.add(
            Run(
                id="ordinary-run",
                workspace_id=ws.id,
                initiated_by_user_id=user.id,
                status="completed",
                started_at=START,
                completed_at=START,
            )
        )
        db.add(
            Activity(
                id="protected",
                workspace_id=ws.id,
                kind=protected_kind,
                native_id="native-no-longer-present",
                owner_id=user.id,
                status="succeeded",
                native_status="completed",
                version=1,
                snapshot={"finished_at": "2026-01-01T01:00:00Z"},
                snapshot_digest="a" * 64,
                created_at=START,
                updated_at=START,
            )
        )
        db.commit()
    original, taken = series_sql.aggregate_compat, []

    def accelerated(*args, **kwargs):
        result = original(*args, **kwargs)
        taken.append(result is not None)
        return result

    monkeypatch.setattr(series_sql, "aggregate_compat", accelerated)
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        Session(conn) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "member")
        for time_basis in ("created", "finished"):
            result = activity_series(db, ws, user, start=START, until=UNTIL, time_basis=time_basis)
            assert taken[-1] is False
            # Native rows/grants, not owner_id on the projection, authorize a read.
            assert result["totals"]["total"] == 1
            result = activity_series(
                db, ws, user, start=START, until=UNTIL, time_basis=time_basis, kind="run"
            )
            assert taken[-1] is True
            assert result["totals"]["total"] == 1


def _track(monkeypatch, original=None):
    original, taken = original or series_sql.aggregate_compat, []

    def accelerated(*args, **kwargs):
        result = original(*args, **kwargs)
        taken.append(result is not None)
        return result

    monkeypatch.setattr(series_sql, "aggregate_compat", accelerated)
    return taken


@pytest.mark.parametrize("inside", [True, False])
def test_invocation_guard_only_considers_the_selected_population(pg, monkeypatch, inside):
    """A malformed invocation projection forces the native reader only when the
    request can select it; rows outside the window reach neither reader."""
    created = START + timedelta(hours=1) if inside else START - timedelta(days=3)
    with Session(pg) as db:
        ws, user = _member(db)
        for identifier in ("guard-run", "guard-other"):
            db.add(
                Run(
                    id=identifier,
                    workspace_id=ws.id,
                    initiated_by_user_id=user.id,
                    status="completed",
                    started_at=created,
                    completed_at=created + timedelta(minutes=5),
                )
            )
        db.flush()
        db.add(
            SkillInvocation(
                id="guard-invocation",
                run_id="guard-run",
                status="completed",
                started_at=created,
                completed_at=created + timedelta(minutes=1),
            )
        )
        db.commit()
        row = (
            db.query(Activity)
            .filter_by(kind="skill_invocation", native_id="guard-invocation")
            .one()
        )
        row.run_id = "guard-other"  # Legacy projection that disagrees with its native Run.
        db.commit()
    original = series_sql.aggregate_compat
    taken = _track(monkeypatch, original)
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        Session(conn) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "member")
        for time_basis in ("created", "finished"):
            fast = activity_series(db, ws, user, start=START, until=UNTIL, time_basis=time_basis)
            assert taken[-1] is (not inside)
            only_runs = activity_series(
                db, ws, user, start=START, until=UNTIL, time_basis=time_basis, kind="run"
            )
            assert taken[-1] is True  # No invocation can enter a Run-only population.
            monkeypatch.setattr(series_sql, "aggregate_compat", lambda *args, **kwargs: None)
            equal(
                fast, activity_series(db, ws, user, start=START, until=UNTIL, time_basis=time_basis)
            )
            equal(
                only_runs,
                activity_series(
                    db, ws, user, start=START, until=UNTIL, time_basis=time_basis, kind="run"
                ),
            )
            taken = _track(monkeypatch, original)


def test_overflowing_finish_keeps_native_error_semantics(pg, monkeypatch):
    """The typed finish stores NULL for a date Python cannot normalize; the fast
    path then yields to the native reader, which keeps raising as before."""
    with Session(pg) as db:
        ws, user = _member(db)
        db.add(
            Run(
                id="overflow-run",
                workspace_id=ws.id,
                initiated_by_user_id=user.id,
                status="completed",
                started_at=START + timedelta(hours=1),
                completed_at=START + timedelta(hours=2),
            )
        )
        db.commit()
        row = db.query(Activity).filter_by(kind="run", native_id="overflow-run").one()
        row.snapshot = {**row.snapshot, "finished_at": "0001-01-01T00:00:00+01:00"}
        db.commit()
        assert row.finished_at is None
    taken = _track(monkeypatch)
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        Session(conn) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "member")
        with pytest.raises(OverflowError):
            activity_series(db, ws, user, start=START, until=UNTIL, time_basis="finished")
        assert taken == [False]
        created = activity_series(db, ws, user, start=START, until=UNTIL)
        assert taken[-1] is True and created["totals"]["total"] == 1


def test_orphaned_invocation_keeps_the_invocation_predicate(pg, monkeypatch):
    """Counts skip the invocation join only when every selectable invocation has
    its native row; a projection left behind by an out-of-band purge keeps it."""
    with Session(pg) as db:
        ws, user = _member(db)
        db.add(
            Run(
                id="orphan-run",
                workspace_id=ws.id,
                initiated_by_user_id=user.id,
                status="completed",
                started_at=START + timedelta(hours=1),
                completed_at=START + timedelta(hours=2),
            )
        )
        db.flush()
        for identifier in ("orphan-kept", "orphan-purged"):
            db.add(
                SkillInvocation(
                    id=identifier,
                    run_id="orphan-run",
                    status="completed",
                    started_at=START + timedelta(hours=1),
                    completed_at=START + timedelta(hours=1, minutes=1),
                )
            )
        db.commit()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def read():
        statements.clear()
        with (
            pg.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
            Session(conn) as db,
        ):
            ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "member")
            fast = activity_series(db, ws, user, start=START, until=UNTIL)
            aggregate = next(sql for sql in statements if "WITH authorized" in sql)
            monkeypatch.setattr(series_sql, "aggregate_compat", lambda *args, **kwargs: None)
            equal(fast, activity_series(db, ws, user, start=START, until=UNTIL))
            monkeypatch.setattr(series_sql, "aggregate_compat", original)
            return fast, "JOIN skill_invocations i" in aggregate

    original = series_sql.aggregate_compat
    event.listen(pg, "before_cursor_execute", record)
    try:
        fast, joined = read()
        assert not joined  # Every invocation has its native row: no join.
        assert fast["totals"]["by_kind"] == {"run": 1, "skill_invocation": 2}
        monkeypatch.setattr(settings, "activity_observability_enabled", False)
        with pg.begin() as connection:  # Out-of-band purge, as raw maintenance would.
            connection.execute(text("DELETE FROM skill_invocations WHERE id = 'orphan-purged'"))
        monkeypatch.setattr(settings, "activity_observability_enabled", True)
        fast, joined = read()
        assert joined
        assert fast["totals"]["by_kind"] == {"run": 1, "skill_invocation": 1}
    finally:
        event.remove(pg, "before_cursor_execute", record)
