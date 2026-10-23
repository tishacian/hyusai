from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import runs
from app.core.config import settings
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace


def _client(db_session, workspace: Workspace) -> TestClient:
    user = User(id="runs-summary-admin", username="runs-summary-admin", role="admin")
    app = FastAPI()
    app.include_router(runs.router, prefix="/runs")
    app.dependency_overrides[runs.get_current_workspace] = lambda: workspace
    app.dependency_overrides[runs.get_current_user] = lambda: user
    app.dependency_overrides[runs.get_db] = lambda: db_session
    return TestClient(app)


def test_runs_summary_groups_visible_runs_by_system(db_session):
    workspace = Workspace(id="ws-run-summary", slug="run-summary", name="Run summary")
    system_a = System(id="system-a", workspace_id=workspace.id, name="System A")
    system_b = System(id="system-b", workspace_id=workspace.id, name="System B")
    started = datetime(2026, 10, 1, 12, 0, 0)
    db_session.add_all(
        [
            workspace,
            system_a,
            system_b,
            Run(
                id="run-a-old",
                workspace_id=workspace.id,
                system_id=system_a.id,
                status="completed",
                started_at=started,
                duration_ms=1_000,
                provider_cost_usd=0.1,
            ),
            Run(
                id="run-a-new",
                workspace_id=workspace.id,
                system_id=system_a.id,
                status="failed",
                started_at=started + timedelta(minutes=1),
                duration_ms=2_000,
                provider_cost_usd=0.2,
            ),
            Run(
                id="run-b",
                workspace_id=workspace.id,
                system_id=system_b.id,
                status="running",
                started_at=started + timedelta(minutes=2),
                duration_ms=None,
                provider_cost_usd=None,
            ),
        ]
    )
    db_session.commit()

    response = _client(db_session, workspace).get("/runs/summary", params={"group_by": "system"})

    assert response.status_code == 200
    summaries = response.json()["summaries"]
    assert summaries == [
        {
            "system_id": system_b.id,
            "system_name": "System B",
            "last_run_id": "run-b",
            "last_status": "running",
            "last_duration_ms": None,
            "last_provider_cost_usd": None,
            "total_provider_cost_usd": None,
            "run_count": 1,
        },
        {
            "system_id": system_a.id,
            "system_name": "System A",
            "last_run_id": "run-a-new",
            "last_status": "failed",
            "last_duration_ms": 2_000,
            "last_provider_cost_usd": 0.2,
            "total_provider_cost_usd": 0.30000000000000004,
            "run_count": 2,
        },
    ]


def test_run_files_lists_only_current_run_prefix(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    workspace = Workspace(id="ws-run-files", slug="run-files", name="Run files")
    run = Run(id="run-files", workspace_id=workspace.id, status="completed")
    other = Run(id="run-other", workspace_id=workspace.id, status="completed")
    db_session.add_all([workspace, run, other])
    db_session.commit()
    from app.services.object_store import get_object_store

    store = get_object_store()
    store.write_bytes(f"membrane/{workspace.id}/{run.id}/report.txt", b"report")
    store.write_bytes(f"membrane/{workspace.id}/{other.id}/secret.txt", b"secret")

    response = _client(db_session, workspace).get(f"/runs/{run.id}/files")

    assert response.status_code == 200
    assert response.json() == {
        "files": [
            {
                "key": f"membrane/{workspace.id}/{run.id}/report.txt",
                "name": "report.txt",
                "size_bytes": 6,
                "uri": f"object://membrane/{workspace.id}/{run.id}/report.txt",
            }
        ]
    }


def test_run_projections_carry_the_follow_up_state(db_session):
    workspace = Workspace(id="ws-run-follow-up", slug="run-follow-up", name="Run follow-up")
    system = System(id="system-follow-up", workspace_id=workspace.id, name="System")
    boundary = Run(
        id="run-at-boundary",
        workspace_id=workspace.id,
        system_id=system.id,
        status="cancelled",
        error="EVALUATION_STOPPED_AT_HUMAN_GATE",
        started_at=datetime(2026, 10, 22, 13, 24, 58),
        checkpoints=[
            {
                "kind": "evaluation_boundary",
                "boundary": "human_gate",
                "node_id": "review",
                "decision_id": "dec-1",
            }
        ],
    )
    cancelled = Run(
        id="run-cancelled",
        workspace_id=workspace.id,
        system_id=system.id,
        status="cancelled",
        started_at=datetime(2026, 10, 22, 13, 20, 0),
    )
    db_session.add_all([workspace, system, boundary, cancelled])
    db_session.commit()
    client = _client(db_session, workspace)

    detail = client.get(f"/runs/{boundary.id}")
    listing = client.get("/runs", params={"system_id": system.id})

    assert detail.status_code == 200
    assert detail.json()["status"] == "cancelled"
    assert detail.json()["follow_up"] == {
        "native_status": "cancelled",
        "business_state": "stopped_at_review_boundary",
        "cause": {
            "code": "evaluation_stopped_at_review_boundary",
            "boundary": "human_gate",
            "node_id": "review",
            "decision_id": "dec-1",
        },
        "attempt": None,
    }
    assert listing.status_code == 200
    rows = listing.json()
    rows = rows.get("runs", rows) if isinstance(rows, dict) else rows
    states = {row["id"]: row["follow_up"]["business_state"] for row in rows}
    assert states == {
        "run-at-boundary": "stopped_at_review_boundary",
        "run-cancelled": "cancelled",
    }


def test_follow_up_endpoint_reads_one_visible_run(db_session):
    workspace = Workspace(id="ws-follow-up-api", slug="follow-up-api", name="Follow-up API")
    run = Run(
        id="run-follow-up-api",
        workspace_id=workspace.id,
        status="hitl_pending",
        input_ref={"claim_id": "RC-9"},
        checkpoints=[{"kind": "hitl_pause", "node_id": "review", "prompt": "Refund 49.90 EUR"}],
    )
    db_session.add_all([workspace, run])
    db_session.commit()
    client = _client(db_session, workspace)

    response = client.get(f"/runs/{run.id}/follow-up")
    missing = client.get("/runs/unknown-run/follow-up")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run.id
    assert body["business_state"] == "awaiting_human_decision"
    assert body["subject"] == {"field": "claim_id", "value": "RC-9"}
    assert body["proposal"] == "Refund 49.90 EUR"
    assert body["decision"]["state"] == "awaiting"
    assert missing.status_code == 404
