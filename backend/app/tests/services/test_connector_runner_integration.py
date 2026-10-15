"""Exercise the actual supervised child and publication with explicit HANA fixtures."""

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.schemas.connection import ConnectionCreate
from app.services import compute_runs
from app.services.connectors import connections
from app.services.connectors.hana.service import _demo_tables
from app.tests.services.test_connection_registry import setup as registry_setup
from app.workers.tasks_connectors import execute_run

setup = registry_setup


def test_real_child_demo_import_publishes_fenced_dataset(db_session, setup, monkeypatch, tmp_path):
    workspace, _, users, _ = setup
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "connector_scratch_dir", str(tmp_path / "scratch"))
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    connection = connections.create_connection(
        db_session,
        workspace_id=workspace.id,
        actor=users[0].id,
        data=ConnectionCreate(
            name="Explicit demo",
            profile_key="sap_hana",
            values={"host": "unused.example.test", "user": "demo", "demo_mode": True},
            secret_refs={},
        ),
    )
    db_session.commit()
    table = _demo_tables()[0]["name"]
    run = compute_runs.create_run(
        db_session,
        workspace_id=workspace.id,
        user_id=users[0].id,
        connection_id=connection.id,
        operation="import",
        parameters={"schema": "DEMO", "table": table},
    )
    db_session.commit()
    result = execute_run(run.id)
    assert result["status"] == "succeeded", result
    db_session.refresh(run)
    assert run.output_json["source"] == "demo"
    dataset = db_session.get(TabularDataset, run.output_json["dataset"]["dataset_id"])
    assert dataset.status == "ready"
    assert dataset.lineage_json["source_mode"] == "demo"
    assert dataset.lineage_json["compute_run_id"] == run.id
    assert not list((tmp_path / "scratch").iterdir())
