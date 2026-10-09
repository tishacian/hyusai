"""Tabular data plane — datasets produced by uploads, transforms and scoring.

A ``TabularDataset`` is metadata only: the bytes live in the ObjectStore as a
single Parquet file (MinIO in production, a local directory in dev), and the row
carries everything a surface needs to render without ever touching them —
``schema_json`` (columns and types), ``preview_json`` (first rows) and
``stats_json`` (per-column profile: nulls, distincts, ranges, histogram bins,
top values). That profile is computed once at write time by the ingesting
worker, which is what lets the dataset detail page and every workshop preview
show column histograms for free.

``status_detail`` carries the human-readable step of an in-flight ingest
("Parsing CSV — 8 412 rows") so the UI shows progress instead of a mute
spinner.

Deletes are soft: the production MinIO policy is append-only by design, so
dropping a dataset retires the row and leaves byte reclamation to the storage
lifecycle.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base

DATASET_STATUSES = ("pending", "ingesting", "ready", "failed", "deleted")
DATASET_TERMINAL_STATUSES = frozenset({"ready", "failed", "deleted"})
# How the bytes came to exist. Drives the icon and the lineage wording.
DATASET_SOURCES = ("upload", "transform", "score", "generated", "postgresql", "huggingface")

MODEL_TASKS = ("classification", "regression", "forecasting", "clustering")
# Which declaration in app.services.ml.families trains and serves the row.
MODEL_FAMILIES = ("tabular", "forecasting", "forecasting_deep", "tabular_deep", "clustering")
MODEL_STATUSES = ("pending", "training", "ready", "failed", "cancelled")
MODEL_TERMINAL_STATUSES = frozenset({"ready", "failed", "cancelled"})


class TabularDataset(Base):
    __tablename__ = "tabular_datasets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    # Stable within a workspace across versions: ``slug`` names the logical
    # table, ``version`` counts its materializations.
    slug = Column(String(200), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    description = Column(Text, nullable=True)

    # upload | transform | score | generated | postgresql
    source = Column(String(16), default="upload", nullable=False, index=True)
    # pending | ingesting | ready | failed | deleted
    status = Column(String(16), default="pending", nullable=False, index=True)
    status_detail = Column(String(300), nullable=True)
    error = Column(Text, nullable=True)

    # ObjectStore keys, never absolute paths: the backend and the workers reach
    # the same bytes through different backends (local dir vs MinIO).
    storage_key = Column(String(500), nullable=True)
    upload_key = Column(String(500), nullable=True)
    original_filename = Column(String(400), nullable=True)
    content_type = Column(String(200), nullable=True)

    row_count = Column(BigInteger, nullable=True)
    column_count = Column(Integer, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    schema_json = Column(JSON, default=list)
    preview_json = Column(JSON, default=list)
    stats_json = Column(JSON, default=dict)

    # Provenance rendered as the lineage chip chain. No FKs on run/node: run
    # purges and workspace teardown must stay cheap (same posture as Run).
    run_id = Column(String(36), nullable=True, index=True)
    node_id = Column(String(160), nullable=True)
    # The System whose run produced the row — the one fact that places a
    # dataset in the mental model (System → Flow → Run → what it produced).
    # Resolved from the run at write time; NULL for a hand upload. A deleted
    # System leaves its datasets: the bytes and the lineage still stand.
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parent_ids = Column(JSON, default=list)
    produced_by = Column(String(120), nullable=True)
    lineage_json = Column(JSON, default=dict)

    celery_task_id = Column(String(255), nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    ingested_at = Column(DateTime, nullable=True)
    ingest_duration_ms = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "slug",
            "version",
            name="uq_tabular_datasets_workspace_slug_version",
        ),
    )


class MLModel(Base):
    """One trained sklearn pipeline, saved in the MLflow model format.

    The row is the read model every surface renders: metrics and curves live in
    ``metrics_json`` (computed at train time), the input contract in
    ``signature_json`` (derived from the MLflow signature, which also types the
    published skill and the prediction playground form). The artifact itself is
    an MLflow model directory in the ObjectStore, addressed by ``model_uri``.

    The row is ALSO the registry: ``slug``/``version`` name the lineage of
    retrains and ``is_champion`` names the one that serves. That is deliberate —
    a tracking server would be a second database to operate for facts this table
    already holds, while the on-disk format stays MLflow's so the artifact is
    loadable by anything that speaks ``mlflow.pyfunc``.

    ``status_detail`` carries the human-readable step of an in-flight training
    run ("Fitting HistGradientBoostingClassifier") for the same reason the
    dataset row does: a run that takes a minute should say what it is doing.
    """

    __tablename__ = "ml_models"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    slug = Column(String(200), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    description = Column(Text, nullable=True)

    # classification | regression | forecasting | clustering
    task = Column(String(20), nullable=False)
    # The family whose harness trained the row and whose runtime serves it.
    family = Column(
        String(24), default="tabular", server_default="tabular", nullable=False, index=True
    )
    algo = Column(String(80), nullable=False)
    target = Column(String(200), nullable=False)
    features = Column(JSON, default=list)
    # How the estimator is built (knobs → class and constructor params), which
    # the harness reads; the problem definition is spec_json.
    params_json = Column(JSON, default=dict)
    # The family's problem definition beyond target and features — a time
    # column, a horizon, series columns — as validated at submit time.
    spec_json = Column(JSON, default=dict)
    # The interpreter that fitted the row: runtime name, image revision,
    # installed-package fingerprint and the versions a load depends on.
    runtime_json = Column(JSON, default=dict)

    # pending | training | ready | failed | cancelled
    status = Column(String(16), default="pending", nullable=False, index=True)
    status_detail = Column(String(300), nullable=True)
    error = Column(Text, nullable=True)
    # Cooperative stop, read by the supervisor between polls — same posture as
    # RecipeExecution.cancel_requested: a fit cannot be interrupted from inside.
    cancel_requested = Column(Boolean, default=False, nullable=False)
    # Champion alias mirrors the MLflow registry alias so the UI can badge the
    # serving version without a registry round-trip.
    is_champion = Column(Boolean, default=False, nullable=False)

    dataset_id = Column(
        String(36),
        ForeignKey("tabular_datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dataset_slug = Column(String(200), nullable=True)
    row_count = Column(BigInteger, nullable=True)
    test_size = Column(Float, nullable=True)
    cross_validation = Column(Integer, nullable=True)

    metrics_json = Column(JSON, default=dict)
    signature_json = Column(JSON, default=dict)
    input_example_json = Column(JSON, default=dict)
    # Classification only: the labels, in the order predict_proba returns them,
    # so a probability vector can be named without loading the pipeline.
    classes_json = Column(JSON, default=list)
    model_uri = Column(String(500), nullable=True)
    artifact_bytes = Column(BigInteger, nullable=True)
    mlflow_run_id = Column(String(64), nullable=True)
    mlflow_model_name = Column(String(300), nullable=True)

    # Serving counters: what makes a published model visibly in use.
    predict_count = Column(BigInteger, default=0, nullable=False)
    last_predict_at = Column(DateTime, nullable=True)

    run_id = Column(String(36), nullable=True, index=True)
    node_id = Column(String(160), nullable=True)
    # Same posture as the dataset: the System whose run trained the row.
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    celery_task_id = Column(String(255), nullable=True)
    # Publication makes the lineage a Skill. The id is the link the registry
    # joins on and the fact "this lineage is published": a Skill deleted from
    # the registry nulls it, so the card stops claiming a Skill that is gone.
    # The slug is the name the card shows. Both are written together.
    published_skill_id = Column(
        String(36),
        ForeignKey("skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_skill_slug = Column(String(200), nullable=True)

    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    trained_at = Column(DateTime, nullable=True)
    train_duration_ms = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "slug",
            "version",
            name="uq_ml_models_workspace_slug_version",
        ),
    )


class MLRuntimeHeartbeat(Base):
    """A worker image announcing it consumes an ML family's queues.

    A family trained outside the general worker is only offered while an image
    that can train it is listening. Celery's own presence channel is off
    (workers run without gossip or mingle), and asking the broker per request
    costs a broadcast round-trip, so each such worker upserts one row on a
    timer and the catalog reads how fresh it is.
    """

    __tablename__ = "ml_runtime_heartbeats"

    runtime = Column(String(40), primary_key=True)
    hostname = Column(String(200), primary_key=True)
    queues = Column(JSON, default=list)
    image_revision = Column(String(80), nullable=True)
    fingerprint = Column(String(64), nullable=True)
    packages_json = Column(JSON, default=dict)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    seen_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class MLModelApiKey(Base):
    """Scoped credential for the machine-facing predict endpoint.

    Only the sha256 of the secret is stored; the plaintext is shown once at
    mint time. Scoping is per model, so revoking a demo key cannot affect
    anything else.
    """

    __tablename__ = "ml_model_api_keys"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id = Column(
        String(36),
        ForeignKey("ml_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    key_prefix = Column(String(16), nullable=False, index=True)
    key_sha256 = Column(String(64), nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, default=0, nullable=False)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MLPrediction(Base):
    """One serving call — the unit monitoring and feedback attach to.

    A playground click, an API key request and a batch score are the same
    fact: a version answered, on a payload, at a time. Drift is measured
    from this table; ground truth is written back onto the same row. Without
    it a model card can show a fit and not whether the fit still holds.
    """

    __tablename__ = "ml_predictions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The card that was addressed. May differ from ``served_id`` when the
    # lineage's champion answers an unpinned call.
    model_id = Column(
        String(36),
        ForeignKey("ml_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    served_id = Column(
        String(36),
        ForeignKey("ml_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    served_version = Column(Integer, nullable=False)
    slug = Column(String(200), nullable=False, index=True)
    # session | api_key | score
    caller = Column(String(32), nullable=False)
    row_count = Column(Integer, nullable=False)
    payload_json = Column(JSON, default=list)
    output_json = Column(JSON, default=list)
    # Score histogram / mean even when the payload was capped or a batch.
    scores_json = Column(JSON, default=dict)
    duration_ms = Column(Float, nullable=True)
    dataset_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Ground truth, written later by POST .../feedback.
    label = Column(String(200), nullable=True)
    labeled_at = Column(DateTime, nullable=True)
    labeled_by = Column(String(36), nullable=True)
