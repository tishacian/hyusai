"""The MLflow registry mirror: where it points, what it records, when it stays out of the way.

The claim this plane makes to a technical audience is not "we save models" — a
table does that — it is *"your models are not locked in here"*. That claim is
only worth making if it is checkable, so these tests check the two halves of it:
a version created against the object store's own URI (so a foreign MLflow client
can resolve the bytes), and a ``champion`` alias that tracks the promotion an
operator performed in our UI.

The registry runs on a temporary sqlite backend store here. It is the same code
path as Postgres — MLflow's SQL store, the only kind that supports a registry at
all — with a file instead of an instance.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.tabular import MLModel
from app.services import ml_registry

# The training plane's fixtures, reused rather than re-declared: a second
# definition of "a workspace with a churn dataset" would be a second thing to
# keep true.
from app.tests.services.test_ml_training import (  # noqa: F401
    _stub_harness,
    dataset,
    enabled,
    store,
    workspace,
)

pytest.importorskip("mlflow")


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    """Point the registry at a throwaway sqlite store for the duration of a test."""

    monkeypatch.setattr(settings, "ml_registry_enabled", True)
    monkeypatch.setattr(
        settings, "ml_registry_uri", f"sqlite:///{tmp_path / 'registry.db'}"
    )
    return tmp_path / "registry.db"


# ---------------------------------------------------------------------------
# Where the registry points
# ---------------------------------------------------------------------------


def test_the_registry_lands_beside_the_application_database(monkeypatch):
    """Derived, not configured: same instance, same credentials, same dump."""

    monkeypatch.setattr(settings, "ml_registry_uri", "")
    monkeypatch.setattr(
        settings, "database_url", "postgresql://agentium:secret@db:5432/agentium"
    )

    uri = ml_registry.registry_uri()
    assert uri == "postgresql://agentium:secret@db:5432/mlflow"
    # The password has to survive: MLflow opens this connection itself, and
    # SQLAlchemy's ``str(url)`` masks it.
    assert "secret" in uri and "***" not in uri


def test_an_async_application_driver_becomes_a_synchronous_one(monkeypatch):
    """MLflow's stores are synchronous SQLAlchemy; asyncpg would raise on connect."""

    monkeypatch.setattr(settings, "ml_registry_uri", "")
    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://u:p@db:5432/agentium"
    )
    assert ml_registry.registry_uri().startswith("postgresql://")


def test_a_sqlite_deployment_gets_a_sibling_file_and_not_a_relative_name(monkeypatch):
    """A bare name would follow the working directory: a registry per shell."""

    monkeypatch.setattr(settings, "ml_registry_uri", "")
    monkeypatch.setattr(settings, "database_url", "sqlite:////srv/data/agentium.db")

    uri = ml_registry.registry_uri()
    assert uri == "sqlite:////srv/data/mlflow-registry.db"
    assert Path("/srv/data/mlflow-registry.db").is_absolute()


def test_an_explicit_setting_wins_over_the_derivation(monkeypatch):
    monkeypatch.setattr(settings, "ml_registry_uri", "postgresql://x:y@elsewhere/reg")
    monkeypatch.setattr(settings, "database_url", "postgresql://a:b@db:5432/agentium")
    assert ml_registry.registry_uri() == "postgresql://x:y@elsewhere/reg"


# ---------------------------------------------------------------------------
# What it records
# ---------------------------------------------------------------------------


def test_a_version_points_at_the_bytes_the_object_store_already_holds(registry):
    """The artifact is not uploaded twice: the version's source is our URI."""

    published = ml_registry.publish(
        model_name="ws.churn-radar",
        source_uri="s3://agentium-artifacts/workspaces/w/ml/models/m/model",
        metrics={
            "scores": [{"key": "roc_auc", "value": 0.86}],
            "cv": {"metrics": [{"key": "roc_auc", "mean": 0.84}]},
        },
        params={"algo": "gradient_boosting"},
        tags={"agentium.model_id": "m"},
    )

    assert published is not None
    assert published["version"] == "1"
    client = ml_registry._client()
    version = client.get_model_version("ws.churn-radar", "1")
    assert version.source == "s3://agentium-artifacts/workspaces/w/ml/models/m/model"
    assert version.run_id == published["run_id"]
    # The run carries the card's numbers, so a stranger's MLflow can compare
    # versions without reading our database.
    run = client.get_run(published["run_id"])
    assert run.data.metrics["roc_auc"] == pytest.approx(0.86)
    assert run.data.metrics["cv_roc_auc"] == pytest.approx(0.84)
    assert run.data.params["algo"] == "gradient_boosting"
    assert run.data.tags["agentium.model_id"] == "m"


def test_the_second_version_of_a_lineage_registers_under_the_same_name(registry):
    first = ml_registry.publish(
        model_name="ws.churn-radar", source_uri="file:///tmp/one"
    )
    second = ml_registry.publish(
        model_name="ws.churn-radar", source_uri="file:///tmp/two"
    )

    assert (first or {}).get("version") == "1"
    assert (second or {}).get("version") == "2"


def test_an_alias_moves_and_keeps_resolving_to_one_version(registry):
    """``models:/name@champion`` is the point: a stable handle across promotions."""

    first = ml_registry.publish(model_name="ws.churn", source_uri="file:///tmp/one")
    second = ml_registry.publish(model_name="ws.churn", source_uri="file:///tmp/two")

    assert ml_registry.set_alias(model_name="ws.churn", version=(first or {})["version"])
    assert ml_registry.alias_version(model_name="ws.churn") == "1"

    assert ml_registry.set_alias(
        model_name="ws.churn", version=(second or {})["version"]
    )
    assert ml_registry.alias_version(model_name="ws.churn") == "2"


def test_a_run_can_be_traced_back_to_the_version_it_produced(registry):
    """Promotion needs this: the row stores a run id, the alias needs a version."""

    published = ml_registry.publish(
        model_name="ws.churn", source_uri="file:///tmp/one"
    )
    assert ml_registry.version_of_run(
        model_name="ws.churn", run_id=(published or {})["run_id"]
    ) == "1"
    assert (
        ml_registry.version_of_run(model_name="ws.churn", run_id="nope") is None
    )


def test_the_mirror_stays_out_of_the_way_when_it_is_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "ml_registry_enabled", False)
    assert ml_registry.publish(model_name="x", source_uri="file:///tmp/x") is None
    assert ml_registry.set_alias(model_name="x", version="1") is False


def test_an_unreachable_registry_reports_itself_instead_of_raising(monkeypatch):
    """A fit that trained and uploaded has succeeded; provenance is not the product."""

    monkeypatch.setattr(settings, "ml_registry_enabled", True)
    monkeypatch.setattr(
        settings, "ml_registry_uri", "postgresql://nobody:nothing@127.0.0.1:1/absent"
    )
    assert ml_registry.publish(model_name="x", source_uri="file:///tmp/x") is None
    assert ml_registry.alias_version(model_name="x") is None


# ---------------------------------------------------------------------------
# The training path
# ---------------------------------------------------------------------------


def test_a_ready_model_is_mirrored_and_the_row_keeps_the_run_id(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """The integration: training writes ``mlflow_run_id`` and the champion alias."""

    from app.services.tabular_ml import submit_training

    _stub_harness(monkeypatch)
    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
        algo="gradient_boosting",
    )

    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "ready", row.error
    assert row.mlflow_run_id, "a ready model has to be traceable in the registry"

    version = ml_registry.version_of_run(
        model_name=row.mlflow_model_name, run_id=row.mlflow_run_id
    )
    assert version == "1"
    # Nothing else served this lineage, so the row promoted itself — and the
    # alias has to say the same thing.
    assert row.is_champion is True
    assert ml_registry.alias_version(model_name=row.mlflow_model_name) == "1"

    client = ml_registry._client()
    registered = client.get_model_version(row.mlflow_model_name, version)
    # The source resolves to the bytes the object store holds, not a copy.
    assert registered.source.endswith(row.model_uri)


def test_promoting_a_version_moves_the_alias_with_the_row(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    from app.services.tabular_ml import set_champion, submit_training

    _stub_harness(monkeypatch)
    first = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
        algo="gradient_boosting",
    )
    second = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
        algo="gradient_boosting",
    )
    db_session.expire_all()

    name = db_session.query(MLModel).filter_by(id=first.id).one().mlflow_model_name
    # The first version promoted itself; a retrain must not take over.
    assert ml_registry.alias_version(model_name=name) == "1"

    set_champion(db_session, db_session.query(MLModel).filter_by(id=second.id).one())
    assert ml_registry.alias_version(model_name=name) == "2"


def test_a_registry_outage_does_not_fail_a_training_run(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    monkeypatch.setattr(settings, "ml_registry_enabled", True)
    monkeypatch.setattr(
        settings, "ml_registry_uri", "postgresql://nobody:nothing@127.0.0.1:1/absent"
    )
    from app.services.tabular_ml import submit_training

    _stub_harness(monkeypatch)
    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
        algo="gradient_boosting",
    )

    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "ready", row.error
    assert row.model_uri, "the artifact is the product, and it landed"
    assert row.mlflow_run_id is None
