"""R4 cursor/native checkpoint atomicity on an isolated PostgreSQL schema."""

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.activity_observability import queries
from app.services.activity_observability.projection import activity_id
from app.services.execution_view import execution_view
from app.tests.services.test_activity_observability_postgres import pg as pg


@pytest.mark.parametrize("commit", [True, False])
def test_native_checkpoint_transaction_and_children_after_snapshot(pg, monkeypatch, commit):
    monkeypatch.setattr(settings, "execution_view_enabled", True)
    with Session(pg) as db:
        db.add(User(id="view-admin", username="view-admin", role="admin", is_active=True))
        db.add(
            Run(
                id="root",
                workspace_id="pg-activity-ws",
                status="running",
                flow_snapshot={"nodes": [{"id": "gate", "kind": "hitl"}]},
            )
        )
        db.commit()
        workspace, user = db.get(Workspace, "pg-activity-ws"), db.get(User, "view-admin")
        initial = execution_view(db, workspace, user, "root")
        writer = Session(pg)
        try:
            writer.execute(
                update(Run)
                .where(Run.id == "root")
                .values(
                    checkpoints=[
                        {
                            "kind": "hitl_pause",
                            "node_id": "gate",
                            "transition_id": "transition-one",
                            "passage_id": "passage-one",
                            "t": "2026-10-16T10:00:00",
                            "state": {"secret": "hidden"},
                        }
                    ]
                )
            )
            assert (
                queries.event_page(
                    db, workspace, user, cursor=initial["snapshot_cursor"], run_id="root"
                )["items"]
                == []
            )
            writer.commit() if commit else writer.rollback()
        finally:
            writer.close()
        db.expire_all()
        page = queries.event_page(
            db, workspace, user, cursor=initial["snapshot_cursor"], run_id="root"
        )
        assert len(page["items"]) == int(commit)
        assert execution_view(db, workspace, user, "root")["nodes"][0]["status"] == (
            "waiting" if commit else "not_started"
        )
        db.add(
            Run(
                id="child-after-snapshot",
                workspace_id=workspace.id,
                parent_run_id="root",
                status="running",
            )
        )
        db.commit()
        descendants = queries.event_page(
            db, workspace, user, cursor=page["next_cursor"], run_id="root", subtree=True
        )
        assert [item["activity_id"] for item in descendants["items"]] == [
            activity_id("run", "child-after-snapshot")
        ]
