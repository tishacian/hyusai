"""MLflow tracking and Model Registry, on the Postgres instance already running.

Why a registry when ``ml_models`` is already a table
----------------------------------------------------
The ``ml_models`` row stays the operational record: it is what the API lists,
what the UI paginates, what carries our status machine and our API keys. This
module adds the thing a private table cannot give — a registry a *stranger* can
read. A stock MLflow client, pointed at the same backend store, resolves the
model version, reads its ``source`` off MinIO and loads the pipeline, knowing
nothing about Agentium. That is the difference between "we store models" and "we
do not lock your models in", and for a technical audience it is checkable in one
command rather than asserted on a slide::

    mlflow server --backend-store-uri postgresql://…/mlflow   # the registry, read-only

There is no MLflow **server** in the deployment. The client writes straight to a
SQL backend store, which is also the only store that supports a registry at all:
a bare ``mlruns/`` file store raises on ``create_registered_model``, which is the
documented trap this module exists to avoid falling into.

Why the artifacts are not logged through MLflow
-----------------------------------------------
The bytes are already on MinIO, written by the ``ObjectStore`` facade that every
other artifact in this codebase goes through — one storage contract, one backup
routine, one append-only policy. So a version is created with an explicit
``source`` pointing at that location instead of re-uploading the same directory
through MLflow's own S3 client. The registry row ends up holding
``s3://agentium-artifacts/workspaces/…/model``, which is what a foreign client
needs, and the bytes exist exactly once.

Failure posture
---------------
Registration is provenance, not the product. A fit that trained, scored and
uploaded has succeeded; if the registry is unreachable the run must still land.
Every entry point here therefore reports failure by returning ``None`` and
logging, never by raising into the training path.
"""
from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import settings

logger = logging.getLogger(__name__)

_ALIAS_CHAMPION = "champion"
_ALIAS_CHALLENGER = "challenger"
_EXPERIMENT = "agentium"

# MLflow's stores are synchronous SQLAlchemy. An async driver in DATABASE_URL is
# for the app, not for this client.
_SYNC_DRIVERS = {
    "postgresql+asyncpg": "postgresql",
    "postgresql+psycopg": "postgresql",
    "postgres": "postgresql",
}


def registry_uri() -> str:
    """The backend store URI: the explicit setting, or ``mlflow`` beside the app.

    Deriving it rather than requiring a second secret is deliberate: the registry
    is meant to live in the same instance, be dumped by the same routine and be
    reachable with the same credentials as everything else. Naming it separately
    would invite the two to drift.
    """

    if settings.ml_registry_uri:
        return settings.ml_registry_uri
    url = make_url(settings.database_url)
    driver = _SYNC_DRIVERS.get(url.drivername, url.drivername)
    if driver.startswith("sqlite"):
        # A sibling file, not a bare name: ``set(database="mlflow")`` on sqlite
        # means a *relative* path, so it would land wherever the process
        # happened to be started from — a stray file in a repo checkout, and a
        # different registry per working directory.
        return f"sqlite:///{_sqlite_sibling(url.database)}"
    # ``str(url)`` masks the password. MLflow needs to connect with it.
    return url.set(drivername=driver, database="mlflow").render_as_string(
        hide_password=False
    )


def _sqlite_sibling(database: str | None) -> Path:
    """Where a sqlite registry lives: beside the app's own database file."""

    if not database or database == ":memory:":
        # An in-memory app database has no directory to sit beside, and MLflow
        # cannot share the connection anyway.
        return Path(tempfile.gettempdir()) / "agentium-mlflow-registry.db"
    return Path(database).expanduser().resolve().with_name("mlflow-registry.db")


def ensure_database(uri: str | None = None) -> bool:
    """Create the registry database if it is missing. True when it is usable.

    MLflow migrates its own schema on first connection, so this only has to
    answer the one question MLflow cannot: whether the database exists at all.
    ``CREATE DATABASE`` cannot run inside a transaction, hence the autocommit.
    """

    target = uri or registry_uri()
    url = make_url(target)
    if not url.drivername.startswith("postgresql"):
        # sqlite and friends materialize on connect; nothing to provision.
        return True
    try:
        from sqlalchemy import create_engine, text

        maintenance = create_engine(
            url.set(database="postgres").render_as_string(hide_password=False),
            isolation_level="AUTOCOMMIT",
        )
        with maintenance.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                # The name is ours (a literal or DATABASE_URL's database), never
                # user input, but quote it anyway so a hyphen cannot end the
                # statement early.
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
                logger.info("ml_registry: created database %s", url.database)
        maintenance.dispose()
        return True
    except Exception:  # noqa: BLE001 - provisioning is best effort by contract
        logger.warning("ml_registry: database unavailable at %s", url.render_as_string(hide_password=True), exc_info=True)
        return False


def _client():
    """An MLflow client bound to our store, with no global state touched.

    ``mlflow.set_tracking_uri`` is process-global and this runs inside a worker
    that also serves predictions; a client instance keeps the blast radius to
    this call.
    """

    from mlflow.tracking import MlflowClient

    uri = registry_uri()
    return MlflowClient(tracking_uri=uri, registry_uri=uri)


def _experiment_id(client) -> str:
    existing = client.get_experiment_by_name(_EXPERIMENT)
    if existing is not None:
        return existing.experiment_id
    return client.create_experiment(_EXPERIMENT)


def _metric_pairs(metrics: dict | None) -> list[tuple[str, float]]:
    """The scalar scores worth tracking, flattened out of the card's read model."""

    pairs: list[tuple[str, float]] = []
    for score in (metrics or {}).get("scores") or []:
        key, value = score.get("key"), score.get("value")
        if isinstance(key, str) and isinstance(value, (int, float)):
            pairs.append((key, float(value)))
    folded = (metrics or {}).get("cv") or {}
    for row in folded.get("metrics") or []:
        key, value = row.get("key"), row.get("mean")
        if isinstance(key, str) and isinstance(value, (int, float)):
            pairs.append((f"cv_{key}", float(value)))
    tuning = (metrics or {}).get("tuning") or {}
    for group in ("start", "best"):
        value = (tuning.get(group) or {}).get("score")
        if isinstance(value, (int, float)):
            pairs.append((f"tuning.{group}.score", float(value)))
    return pairs


def publish(
    *,
    model_name: str,
    source_uri: str,
    metrics: dict | None = None,
    params: dict | None = None,
    tags: dict | None = None,
) -> dict[str, Any] | None:
    """Record a run and register a version of it. ``None`` when unavailable.

    The run is what makes the metrics comparable in a tool nobody here wrote;
    the version is what makes the artifact addressable as ``models:/name/n``.
    """

    if not settings.ml_registry_enabled:
        return None
    if not ensure_database():
        return None
    try:
        from mlflow.entities import RunStatus

        client = _client()
        run = client.create_run(
            experiment_id=_experiment_id(client),
            tags={str(key): str(value) for key, value in (tags or {}).items()},
            run_name=model_name,
        )
        run_id = run.info.run_id
        for key, value in (params or {}).items():
            client.log_param(run_id, str(key), str(value))
        for key, value in _metric_pairs(metrics):
            client.log_metric(run_id, key, value)
        # Client API equivalent of nested=True: keep the explicit tracking URI
        # rather than changing MLflow's process-global fluent state in a worker.
        for trial in ((metrics or {}).get("tuning") or {}).get("trials", [])[:100]:
            child = client.create_run(
                experiment_id=run.info.experiment_id,
                tags={"mlflow.parentRunId": run_id, "agentium.tuning.state": trial["state"]},
                run_name=f"trial-{trial['n']}",
            )
            child_id = child.info.run_id
            client.log_param(child_id, "trial", trial["n"])
            for key in ("score", "duration_ms"):
                value = trial.get(key)
                if isinstance(value, (int, float)):
                    client.log_metric(child_id, key, value)
            state = RunStatus.FAILED if trial["state"] == "failed" else RunStatus.FINISHED
            client.set_terminated(child_id, status=RunStatus.to_string(state))
        client.set_terminated(run_id, status=RunStatus.to_string(RunStatus.FINISHED))

        try:
            client.create_registered_model(model_name)
        except Exception:  # noqa: BLE001 - already registered is the common case
            pass
        version = client.create_model_version(
            name=model_name, source=source_uri, run_id=run_id
        )
        return {
            "run_id": run_id,
            "model_name": model_name,
            "version": str(version.version),
        }
    except Exception:  # noqa: BLE001 - provenance never fails a fit
        logger.warning("ml_registry: publish failed for %s", model_name, exc_info=True)
        return None


def set_alias(
    *, model_name: str, version: str | None, alias: str = _ALIAS_CHAMPION
) -> bool:
    """Point ``champion`` (or ``challenger``) at a version. False when unavailable.

    An alias rather than a copy: the same bytes answer under a stable name, so
    ``models:/ws.churn-radar@champion`` keeps resolving across promotions — which
    is the whole reason a caller would prefer the registry to a version number.
    """

    if not settings.ml_registry_enabled or not version:
        return False
    try:
        _client().set_registered_model_alias(model_name, alias, version)
        return True
    except Exception:  # noqa: BLE001
        logger.warning(
            "ml_registry: alias %s -> %s v%s failed", alias, model_name, version,
            exc_info=True,
        )
        return False


def clear_alias(*, model_name: str, alias: str = _ALIAS_CHALLENGER) -> bool:
    """Remove an alias. False when unavailable — including "it was never set".

    Needed because an alias that is merely *stale* is worse than one that is
    absent: ``models:/name@challenger`` resolving to a version whose row was
    deleted hands a caller bytes nobody can audit any more, and it does so
    silently, which is the one failure mode a registry is supposed to prevent.
    """

    if not settings.ml_registry_enabled:
        return False
    try:
        _client().delete_registered_model_alias(model_name, alias)
        return True
    except Exception:  # noqa: BLE001 - nothing to clear is the common case
        return False


def retire_version(*, model_name: str, run_id: str) -> bool:
    """Remove the version a run produced. False when there was nothing to remove.

    Clearing the aliases that named it is not enough. An alias is a *name* for a
    version; the version is the row that carries the ``source``, so a stranger
    who lists ``models:/name`` after we deleted our row still sees it, still
    resolves it by number, and still pulls bytes out of a bucket that keeps them
    — a version we would be unable to say anything about. The registry is here
    to be more trustworthy than a private table, not to be a longer-lived one.
    """

    if not settings.ml_registry_enabled:
        return False
    version = version_of_run(model_name=model_name, run_id=run_id)
    if not version:
        return False
    try:
        _client().delete_model_version(model_name, version)
        return True
    except Exception:  # noqa: BLE001 - already gone is not a failure
        logger.warning(
            "ml_registry: retiring %s v%s failed", model_name, version, exc_info=True
        )
        return False


def forget_model(*, model_name: str) -> bool:
    """Drop a registered model with its versions and aliases. False if unavailable.

    For the last version of a lineage. Retiring that version alone would leave a
    named container behind whose ``champion`` still resolves — to a version that
    no longer exists on either side — and the demo host proved it: four
    registered models survived the runs that made them, each still answering
    ``@champion``.
    """

    if not settings.ml_registry_enabled:
        return False
    try:
        _client().delete_registered_model(model_name)
        return True
    except Exception:  # noqa: BLE001 - never registered is the common case
        return False


def version_of_run(*, model_name: str, run_id: str) -> str | None:
    """The registered version a run produced, looked up rather than stored.

    The alternative was a ``mlflow_version`` column on ``ml_models``, i.e. a
    second copy of a number the registry already owns and could renumber. The
    run id we do store is the stable join key, so the version is derived from it
    on the rare path that needs it — promotion.
    """

    if not settings.ml_registry_enabled:
        return None
    try:
        found = _client().search_model_versions(f"run_id='{run_id}'")
        for version in found:
            if version.name == model_name:
                return str(version.version)
        return None
    except Exception:  # noqa: BLE001
        logger.warning(
            "ml_registry: version lookup failed for run %s", run_id, exc_info=True
        )
        return None


def artifact_s3_environment() -> dict[str, str]:
    """The environment a *foreign* MLflow client needs to read our artifacts.

    A registered version's ``source`` is an ``s3://`` URI. MLflow resolves those
    with boto3, and boto3 takes its endpoint and credentials from the process
    environment and nowhere else — so a stranger handed only the registry URI
    gets ``NoCredentialsError``, which reads like the artifacts are unreachable
    when they are merely unaddressed.

    Nothing in Agentium's own paths needs this: the serving loader pulls the
    directory through the ``ObjectStore`` facade and hands ``load_model`` a local
    path. Publishing these three names is therefore not a hole in the no-lock-in
    claim, it *is* the claim — the S3 configuration any MLflow speaks to any
    object store with, and no Agentium code. Local postures hand back ``file://``
    sources and this correctly returns nothing.
    """

    if str(settings.object_store_backend or "").lower() != "s3":
        return {}
    named = (
        ("AWS_ACCESS_KEY_ID", settings.object_store_s3_access_key),
        ("AWS_SECRET_ACCESS_KEY", settings.object_store_s3_secret_key),
        ("MLFLOW_S3_ENDPOINT_URL", settings.object_store_s3_endpoint_url),
    )
    return {name: str(value) for name, value in named if value}


@contextmanager
def artifact_s3_credentials() -> Iterator[dict[str, str]]:
    """Apply ``artifact_s3_environment`` for the duration of a block.

    Scoped rather than exported at boot because ``AWS_ACCESS_KEY_ID`` is not
    ours alone: the Bedrock provider reads the same name when it was given no
    explicit key, and a process-wide export would quietly point it at MinIO.
    A variable already set by the deployment is left exactly as it was.
    """

    applied = artifact_s3_environment()
    previous = {name: os.environ.get(name) for name in applied}
    for name, value in applied.items():
        os.environ.setdefault(name, value)
    try:
        yield applied
    finally:
        for name, was in previous.items():
            if was is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = was


def alias_version(*, model_name: str, alias: str = _ALIAS_CHAMPION) -> str | None:
    """The version an alias resolves to, or ``None``. Used by tests and support."""

    if not settings.ml_registry_enabled:
        return None
    try:
        return str(
            _client().get_model_version_by_alias(model_name, alias).version
        )
    except Exception:  # noqa: BLE001 - no alias yet is not an error
        return None


__all__ = [
    "alias_version",
    "artifact_s3_credentials",
    "artifact_s3_environment",
    "clear_alias",
    "ensure_database",
    "forget_model",
    "publish",
    "registry_uri",
    "retire_version",
    "set_alias",
    "version_of_run",
    "_ALIAS_CHAMPION",
    "_ALIAS_CHALLENGER",
]
