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
    _summary,
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


def test_the_s3_source_a_version_carries_is_one_stock_mlflow_can_fetch(registry):
    """A portability claim that only holds on a local object store is not one.

    Versions published from a MinIO deployment carry an ``s3://`` source, and
    mlflow reaches those through its S3 artifact repository, which imports
    ``boto3`` by name. botocore — which ``s3fs`` already brings for our own
    reads — does not satisfy that import, so the demo VM raised
    ``ModuleNotFoundError`` on the one step meant to prove a stranger's client
    can load our models, while the same code passed on a laptop writing to a
    directory. This asserts the repository resolves and gets its client class,
    without reaching the network.
    """

    from mlflow.store.artifact.artifact_repository_registry import (
        get_artifact_repository,
    )

    published = ml_registry.publish(
        model_name="ws.churn-radar",
        source_uri="s3://agentium-artifacts/workspaces/w/ml/models/m/model",
    )
    assert published is not None
    version = ml_registry._client().get_model_version("ws.churn-radar", "1")

    repository = get_artifact_repository(version.source)
    assert repository._get_s3_client() is not None


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


def test_the_run_points_at_the_evaluation_and_not_only_at_the_pipeline(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """skore's report state is an artifact too, and the run has to name it.

    Otherwise it is a file in a bucket that only our own database knows about —
    which is the lock-in this plane exists to avoid. With the tag, a reader who
    has the registry and nothing else can fetch the rows the published metrics
    were measured on.
    """

    from app.services.tabular_ml import report_state_key, submit_training
    from app.services.object_store import get_object_store

    _stub_harness(monkeypatch, report_state=b"skore-state-bytes")
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

    key = report_state_key(row.workspace_id, row.id)
    stored = row.metrics_json["report"]
    assert stored["key"] == key
    assert stored["bytes"] == len(b"skore-state-bytes")
    assert stored["skore"] == "0.25.0"
    # Beside the model, not inside it: serving pulls the model directory on every
    # cold load and has no use for the training split.
    store = get_object_store()
    assert store.read_bytes(key) == b"skore-state-bytes"
    assert key not in store.list_keys(row.model_uri)

    run = ml_registry._client().get_run(row.mlflow_run_id)
    assert run.data.tags["agentium.skore_report_state"] == store.uri(key)


def test_a_fit_whose_evaluation_was_too_large_to_keep_still_lands(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """The state is optional by construction, so its absence is not a gap in the row."""

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
    assert "report" not in (row.metrics_json or {})
    run = ml_registry._client().get_run(row.mlflow_run_id)
    assert run.data.tags["agentium.skore_report_state"] == ""


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


# ---------------------------------------------------------------------------
# The other half of the story: challenger
# ---------------------------------------------------------------------------


def _train(db_session, workspace, dataset, monkeypatch, *, roc_auc):
    """One version whose card scores exactly ``roc_auc``."""

    from app.services.tabular_ml import submit_training

    _stub_harness(
        monkeypatch,
        summary=_summary(
            metrics={
                "task": "classification",
                "primary": {"key": "roc_auc", "value": roc_auc},
                "scores": [{"key": "roc_auc", "value": roc_auc}],
                "rows": {"total": 60, "train": 45, "test": 15},
                "target": {"name": "churn", "classes": ["0", "1"], "positive": "1"},
            }
        ),
    )
    return submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
        algo="gradient_boosting",
    )


def test_the_runner_up_is_the_best_loser_and_not_merely_the_newest(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """``@challenger`` has to name the version with a case, not the latest fit.

    Version order was the tempting rule and it is the wrong one: a retrain is
    frequently worse, which is exactly why promotion is a human decision. Here v2
    beats v3, so v2 is the contender even though v3 came last.
    """

    from app.models.tabular import MLModel

    first = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.88)
    _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.85)
    db_session.expire_all()

    name = db_session.query(MLModel).filter_by(id=first.id).one().mlflow_model_name
    # v1 promoted itself because nothing served the lineage; it stays champion.
    assert ml_registry.alias_version(model_name=name) == "1"
    assert ml_registry.alias_version(model_name=name, alias="challenger") == "2"


def test_promotion_moves_both_aliases_so_the_demoted_version_is_still_named(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """After a promotion the pair has to describe the new arrangement, not half of it."""

    from app.models.tabular import MLModel
    from app.services.tabular_ml import set_champion

    first = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    second = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.88)
    db_session.expire_all()
    name = db_session.query(MLModel).filter_by(id=first.id).one().mlflow_model_name
    assert ml_registry.alias_version(model_name=name, alias="challenger") == "2"

    set_champion(db_session, db_session.query(MLModel).filter_by(id=second.id).one())

    assert ml_registry.alias_version(model_name=name) == "2"
    # The version just displaced is the obvious contender, so the aliases swap
    # rather than both pointing at the winner.
    assert ml_registry.alias_version(model_name=name, alias="challenger") == "1"


def test_a_lineage_with_one_version_names_no_challenger(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """Nothing to contend with, so the alias is absent rather than self-referential."""

    from app.models.tabular import MLModel

    only = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    db_session.expire_all()
    name = db_session.query(MLModel).filter_by(id=only.id).one().mlflow_model_name

    assert ml_registry.alias_version(model_name=name) == "1"
    assert ml_registry.alias_version(model_name=name, alias="challenger") is None


def test_deleting_the_contender_takes_its_alias_with_it(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """A stale alias is worse than none: it hands out bytes nobody can audit."""

    from app.models.tabular import MLModel
    from app.services.tabular_ml import delete_model

    first = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    second = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.88)
    db_session.expire_all()
    name = db_session.query(MLModel).filter_by(id=first.id).one().mlflow_model_name
    assert ml_registry.alias_version(model_name=name, alias="challenger") == "2"

    delete_model(db_session, db_session.query(MLModel).filter_by(id=second.id).one())

    assert ml_registry.alias_version(model_name=name, alias="challenger") is None
    # The champion is untouched: only the contender left.
    assert ml_registry.alias_version(model_name=name) == "1"


def test_deleting_a_version_takes_it_out_of_the_registry_too(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """A version a stranger can still list is a version we can no longer explain."""

    from app.models.tabular import MLModel
    from app.services.tabular_ml import delete_model

    first = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    second = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.88)
    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=second.id).one()
    name, run_id = row.mlflow_model_name, row.mlflow_run_id
    assert ml_registry.version_of_run(model_name=name, run_id=run_id) == "2"

    delete_model(db_session, row)

    assert ml_registry.version_of_run(model_name=name, run_id=run_id) is None
    # The lineage still has a version, so the registered model stays.
    assert ml_registry.alias_version(model_name=name) == "1"


def test_the_last_version_takes_the_registered_model_with_it(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """Four of these outlived their runs on the demo host, each still a champion.

    The alias is the part that hurts: ``models:/ws.churn-radar@champion``
    resolving after every version was deleted hands a caller bytes that no row,
    no card and no audit trail accounts for.
    """

    from app.models.tabular import MLModel
    from app.services.tabular_ml import delete_model

    only = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=only.id).one()
    name = row.mlflow_model_name
    assert ml_registry.alias_version(model_name=name) == "1"

    delete_model(db_session, row)

    assert ml_registry.alias_version(model_name=name) is None
    client = ml_registry._client()
    assert [
        found.name
        for found in client.search_registered_models(filter_string=f"name='{name}'")
    ] == []


def test_a_registry_outage_does_not_block_a_delete(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """The row is the operational record; the mirror going quiet cannot keep it."""

    from app.models.tabular import MLModel
    from app.services.tabular_ml import delete_model

    only = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=only.id).one()
    monkeypatch.setattr(
        settings, "ml_registry_uri", "postgresql://nobody:nothing@127.0.0.1:1/absent"
    )

    assert delete_model(db_session, row) == only.id
    assert db_session.query(MLModel).filter_by(id=only.id).first() is None


def test_a_metric_whose_direction_is_unknown_is_not_ranked_on(
    db_session, workspace, dataset, enabled, registry, monkeypatch, store
):
    """``rmse`` sorted as if bigger were better would nominate the worst model.

    The harness normally leads its ordered list with a higher-is-better score,
    but it falls further down that list when one is unavailable — so an
    unrecognised key means "do not rank", never "assume up is good".
    """

    from app.models.tabular import MLModel
    from app.services.tabular_ml import sync_challenger

    first = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.83)
    second = _train(db_session, workspace, dataset, monkeypatch, roc_auc=0.88)
    db_session.expire_all()

    contender = db_session.query(MLModel).filter_by(id=second.id).one()
    contender.metrics_json = {
        **contender.metrics_json,
        "primary": {"key": "rmse", "value": 12.5},
    }
    db_session.commit()

    champion = db_session.query(MLModel).filter_by(id=first.id).one()
    assert sync_challenger(db_session, champion) is None
    assert (
        ml_registry.alias_version(
            model_name=champion.mlflow_model_name, alias="challenger"
        )
        is None
    )


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
