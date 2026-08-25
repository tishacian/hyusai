"""API surface for /datasets."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import datasets as datasets_api
from app.core.config import settings
from app.models.tabular import TabularDataset
from app.models.user import User
from app.models.workspace import Workspace

pl = pytest.importorskip("polars")

CSV = (
    "customer_id,tenure_months,monthly_charges,contract,churn\n"
    "C1,12,45.5,monthly,true\n"
    "C2,36,80.25,yearly,false\n"
)


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Datasets API",
        slug=f"datasets-api-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def user(db_session) -> User:
    token = uuid4().hex[:8]
    row = User(
        id=str(uuid4()),
        username=f"datasets-{token}",
        email=f"datasets-{token}@example.invalid",
        role="user",
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def client(db_session, workspace, user, tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    # Eager mode keeps the ingest inline so the API test observes the settled row.
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    app = FastAPI()
    app.include_router(datasets_api.router, prefix="/datasets")
    app.dependency_overrides[datasets_api.get_current_workspace] = lambda: workspace
    app.dependency_overrides[datasets_api.get_current_user] = lambda: user
    app.dependency_overrides[datasets_api.get_db] = lambda: db_session
    return TestClient(app)


def _upload(client, *, name="Churn export", filename="churn.csv", payload=None):
    return client.post(
        "/datasets/upload",
        files={
            "file": (filename, io.BytesIO(payload or CSV.encode()), "text/csv"),
        },
        data={"name": name},
    )


def test_upload_ingests_and_exposes_the_settled_dataset(client):
    response = _upload(client)

    assert response.status_code == 200
    body = response.json()
    assert body["queued"] is False  # eager mode ran it inline
    dataset = body["dataset"]
    assert dataset["status"] == "ready"
    assert dataset["row_count"] == 2 and dataset["column_count"] == 5
    assert dataset["source"] == "upload"
    assert {col["name"] for col in dataset["schema"]} == {
        "customer_id",
        "tenure_months",
        "monthly_charges",
        "contract",
        "churn",
    }
    # List payloads stay light: no preview rows, no per-column profile.
    assert "preview" not in dataset


def test_detail_returns_preview_stats_versions_and_lineage(client, db_session, workspace):
    first = _upload(client).json()["dataset"]
    second = _upload(client).json()["dataset"]

    response = client.get(f"/datasets/{second['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["dataset"]["preview"]
    assert body["dataset"]["stats"]["contract"]["top_values"]
    # Same name uploaded twice ⇒ two versions of one logical table.
    assert [row["version"] for row in body["versions"]] == [2, 1]
    assert body["lineage"] == {"parents": [], "children": []}
    assert first["slug"] == second["slug"]


def test_detail_walks_the_lineage_both_ways(client, db_session, workspace):
    from app.services.tabular_datasets import register_frame

    parent = _upload(client).json()["dataset"]
    child = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Churn features",
        frame=pl.DataFrame({"customer_id": ["C1"], "risk": [0.8]}),
        produced_by="sql_transform_v1",
        parent_ids=[parent["id"]],
    )
    db_session.commit()

    upstream = client.get(f"/datasets/{child.id}").json()
    downstream = client.get(f"/datasets/{parent['id']}").json()

    assert [row["id"] for row in upstream["lineage"]["parents"]] == [parent["id"]]
    assert [row["id"] for row in downstream["lineage"]["children"]] == [child.id]


def test_list_is_workspace_scoped_and_hides_retired_rows(
    client, db_session, workspace
):
    mine = _upload(client).json()["dataset"]
    other_ws = Workspace(
        id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={}
    )
    db_session.add(other_ws)
    db_session.commit()
    db_session.add(
        TabularDataset(
            id=str(uuid4()),
            workspace_id=other_ws.id,
            name="Foreign",
            slug="foreign",
            version=1,
            source="upload",
            status="ready",
        )
    )
    db_session.commit()

    listed = client.get("/datasets").json()
    assert [row["id"] for row in listed["datasets"]] == [mine["id"]]
    assert listed["feature"]["enabled"] is True

    assert client.delete(f"/datasets/{mine['id']}").json()["dataset"]["status"] == (
        "deleted"
    )
    assert client.get("/datasets").json()["datasets"] == []
    # A retired dataset is gone from reads too, not just from the list.
    assert client.get(f"/datasets/{mine['id']}").status_code == 404


def test_unknown_and_cross_workspace_reads_are_404_with_a_code(client, db_session):
    response = client.get(f"/datasets/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATASET_NOT_FOUND"


def test_upload_rejects_unsupported_formats_with_a_readable_code(client):
    response = client.post(
        "/datasets/upload",
        files={"file": ("holiday.png", io.BytesIO(b"\x89PNG"), "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DATASET_FORMAT_UNSUPPORTED"


def test_reingest_retries_a_failed_parse_without_a_new_upload(client, db_session):
    broken = _upload(client, filename="broken.csv", payload=b"a,b\n1,2\n3,4,5\n")
    dataset_id = broken.json()["dataset"]["id"]
    assert broken.json()["dataset"]["status"] == "failed"

    response = client.post(f"/datasets/{dataset_id}/reingest")

    assert response.status_code == 200
    # Still broken (same bytes), but the retry path works and reports a reason.
    assert response.json()["dataset"]["status"] == "failed"
    assert response.json()["dataset"]["error"]


def test_sql_preview_returns_rows_stats_and_the_editor_source_catalog(client):
    dataset = _upload(client).json()["dataset"]

    response = client.post(
        "/datasets/sql-preview",
        json={
            "sql": "SELECT contract, count(*) AS n FROM input GROUP BY 1 ORDER BY 1",
            "sources": [{"view": "input", "dataset_id": dataset["id"]}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview"]["row_count"] == 2
    assert [col["name"] for col in body["preview"]["schema"]] == ["contract", "n"]
    assert body["preview"]["duration_ms"] >= 0
    # The catalog is what the editor autocompletes from.
    assert body["sources"][0]["view"] == "input"
    assert {col["name"] for col in body["sources"][0]["columns"]} >= {"contract"}


def test_sql_preview_answers_with_the_catalog_before_a_statement_is_written(client):
    """An empty editor still needs to know what it can autocomplete."""

    dataset = _upload(client).json()["dataset"]

    response = client.post(
        "/datasets/sql-preview",
        json={"sql": "", "sources": [{"dataset_id": dataset["id"]}]},
    )

    assert response.status_code == 200
    assert response.json()["preview"] is None
    assert response.json()["sources"][0]["rows"] == 2


def test_sql_preview_surfaces_a_refusal_as_a_coded_error(client):
    dataset = _upload(client).json()["dataset"]

    response = client.post(
        "/datasets/sql-preview",
        json={
            "sql": "DROP TABLE input",
            "sources": [{"dataset_id": dataset["id"]}],
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "SQL_FORBIDDEN_KEYWORD"
    assert "DROP" in detail["message"]


def test_sql_preview_without_a_source_says_what_to_do(client):
    response = client.post("/datasets/sql-preview", json={"sql": "SELECT 1"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TRANSFORM_NO_INPUT"


def test_queued_ingest_dispatches_to_the_worker_plane(
    client, db_session, monkeypatch
):
    """Non-eager deployments must hand the parse to Celery, not block the API."""

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    from app.workers.celery_app import celery_app

    sent: list[tuple[str, tuple]] = []
    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda name, **kwargs: sent.append((name, kwargs.get("args"))),
    )

    body = _upload(client).json()

    assert body["queued"] is True
    assert body["dataset"]["status"] == "pending"
    # The author sees a step, never a mute spinner.
    assert body["dataset"]["status_detail"]
    assert sent and sent[0][0] == "agentium.dataset_ingest"
    assert sent[0][1] == (body["dataset"]["id"],)
