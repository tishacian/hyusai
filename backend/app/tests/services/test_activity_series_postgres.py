"""PostgreSQL snapshot/permission qualification; generated private schema only."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.activity_observability.queries import VisibilityReadContext, filter_visible
from app.services.activity_observability.series import activity_series
from app.tests.services import test_activity_observability_postgres as pg_fixtures

pg = pg_fixtures.pg


def seed(engine):
    start, until = datetime(2026, 1, 1), datetime(2026, 1, 2)
    with Session(engine) as db:
        user = User(id="series-pg-reader", username="series-pg-reader", role="user", is_active=True)
        db.add(user)
        db.flush()
        db.add(WorkspaceMember(workspace_id="pg-activity-ws", user_id=user.id, role="admin"))
        db.add(
            Run(
                id="series-pg-run",
                workspace_id="pg-activity-ws",
                status="completed",
                trigger="chat_agentic",
                started_at=start,
                completed_at=until - timedelta(hours=1),
            )
        )
        db.flush()
        db.add(
            SkillInvocation(
                id="series-pg-inv",
                run_id="series-pg-run",
                status="completed",
                started_at=start,
                completed_at=until - timedelta(hours=1),
                cost_measured=True,
                cost=0.1,
                provider_cost_usd=0.1,
                metrics={"cost_evidence": {"state": "measured", "currency": "USD"}},
            )
        )
        db.commit()
    return start, until


def test_cost_and_authorization_are_one_repeatable_read_snapshot(pg):
    start, until = seed(pg)
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
        Session(connection) as reader,
    ):
        workspace = reader.get(Workspace, "pg-activity-ws")
        user = reader.get(User, "series-pg-reader")
        before = activity_series(
            reader,
            workspace,
            user,
            start=start,
            until=until,
            metric="cost",
            kind="skill_invocation",
            time_basis="finished",
        )
        with Session(pg) as writer:
            # The writer commits while the reader keeps its transaction open.
            invocation = writer.get(SkillInvocation, "series-pg-inv")
            invocation.cost = invocation.provider_cost_usd = 0.4
            member = writer.query(WorkspaceMember).filter_by(user_id=user.id).one()
            member.role = "member"
            writer.commit()
        after = activity_series(
            reader,
            workspace,
            user,
            start=start,
            until=until,
            metric="cost",
            kind="skill_invocation",
            time_basis="finished",
        )
        assert (
            before["totals"]["costs"]
            == after["totals"]["costs"]
            == [
                {
                    "basis": "provider_measured",
                    "currency": "USD",
                    "known_amount": 0.1,
                    "known_count": 1,
                },
            ]
        )
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
        Session(connection) as reader,
    ):
        workspace = reader.get(Workspace, "pg-activity-ws")
        user = reader.get(User, "series-pg-reader")
        # Fresh snapshots see the revocation; a cached parent cannot survive it.
        result = activity_series(
            reader,
            workspace,
            user,
            start=start,
            until=until,
            metric="cost",
            kind="skill_invocation",
            time_basis="finished",
        )
        assert result["totals"]["total"] == 0
        assert result["totals"]["costs"] == []


def test_context_rejects_read_committed_and_cannot_survive_commit(pg):
    seed(pg)
    with Session(pg) as db:
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "series-pg-reader")
        with pytest.raises(ValueError, match="REPEATABLE READ"):
            VisibilityReadContext(db, ws, user)
    with (
        pg.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
        Session(connection) as db,
    ):
        ws, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "series-pg-reader")
        context = VisibilityReadContext(db, ws, user)
        rows = db.query(Activity).all()
        assert len(filter_visible(db, rows, ws, user, read_context=context)) == 2
        db.commit()
        with pytest.raises(ValueError, match="expired"):
            filter_visible(db, rows, ws, user, read_context=context)
