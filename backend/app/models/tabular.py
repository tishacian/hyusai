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
DATASET_SOURCES = ("upload", "transform", "score", "generated")

MODEL_TASKS = ("classification", "regression")
MODEL_STATUSES = ("pending", "training", "ready", "failed")


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

    # upload | transform | score | generated
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
    parent_ids = Column(JSON, default=list)
    produced_by = Column(String(120), nullable=True)
    lineage_json = Column(JSON, default=dict)

    celery_task_id = Column(String(255), nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
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
    """One trained sklearn pipeline, logged in the MLflow format.

    The row is the read model every surface renders: metrics and curves live in
    ``metrics_json`` (computed by skore at train time), the input contract in
    ``signature_json`` (derived from the MLflow signature, which also types the
    published skill and the prediction playground form). The artifact itself is
    an MLflow model directory addressed by ``model_uri``.
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

    # classification | regression
    task = Column(String(20), nullable=False)
    algo = Column(String(80), nullable=False)
    target = Column(String(200), nullable=False)
    features = Column(JSON, default=list)
    params_json = Column(JSON, default=dict)

    # pending | training | ready | failed
    status = Column(String(16), default="pending", nullable=False, index=True)
    status_detail = Column(String(300), nullable=True)
    error = Column(Text, nullable=True)
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
    model_uri = Column(String(500), nullable=True)
    mlflow_run_id = Column(String(64), nullable=True)
    mlflow_model_name = Column(String(300), nullable=True)

    run_id = Column(String(36), nullable=True, index=True)
    node_id = Column(String(160), nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    published_skill_slug = Column(String(200), nullable=True)

    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
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
