"""SystemVersion — immutable history for a System's executable definition.

Before E3.1 the canonical flow editor stored chains as
``systems.flow_definition`` (JSON) mutated in place by
``PATCH /api/v1/systems/{id}``. That meant:

- No way to roll back a mistake (auto-save on the editor could erase
  a working flow in one click).
- No audit trail of *who changed the flow and when*.
- Runs executed before a save lost the DAG context they ran against
  (``Run.system_id`` only references the current state), breaking
  replayability the moment a builder tweaked the flow.

E3.1 solves the first two by keeping a rolling window of historical
snapshots in this table, and the third by snapshotting the DAG inline
on ``Run.flow_snapshot`` (see ``run.py``) at execution start so runs
stay rejouables even after their version has been purged from the
window.

**Rolling window semantics** (decision 2026-04-24):
    - At every ``PATCH /systems/{id}`` that mutates ``flow_definition``,
      a new row lands here with the next ``version_number`` for the
      system. The parent ``System.flow_definition`` stays updated in
      place so legacy readers (run engine, list endpoints) don't
      notice anything.
    - ``CUSTOM_CHAIN_VERSION_WINDOW`` (default 500) bounds the number
      of rows kept per system. Any surplus is trimmed FIFO (oldest
      ``version_number`` first). A dedicated ``chain.version.purged``
      audit event is emitted so governance stays traceable.
    - Rollback = "create a new version whose ``flow_definition``
      equals an older one". We never rewrite history — ``version_number``
      is strictly monotonic and old rows are never edited.

**Configuration evidence** (decision 2026-07-22):
    - ``configuration_snapshot`` is nullable so every historical row and every
      flow-only caller keeps its original semantics.
    - An explicit snapshot contains only allowlisted binding references and
      contract digests.  It never stores policy bodies, workspace settings,
      credentials, prompts, or other secret-bearing values.
    - A configuration-only transition appends a row even when the flow is
      unchanged.  This is evidence of the transition, not a claim that the DAG
      changed, and no historical row is rewritten to manufacture that proof.

**Cascade**: ``ondelete=CASCADE`` — if a ``System`` is deleted, its
versions go with it. The system itself already cascades its runs, and
there is no use case for retaining orphan versions of a deleted chain.

**Workspace scoping**: we denormalize ``workspace_id`` here (instead of
joining through ``systems``) so the listing endpoint
``GET /systems/{id}/versions`` can gate with a single ``WHERE
workspace_id = ?`` clause and so a cross-tenant leak through a typo
on ``system_id`` is structurally impossible.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class SystemVersion(Base):
    __tablename__ = "system_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id"),
        nullable=True,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    flow_definition = Column(JSON, nullable=False)
    # Optional, positive-allowlisted evidence for a configuration-only
    # transition. Validation lives in ``chains.version_service``; nullable is
    # intentional for backward compatibility with all pre-065 rows.
    configuration_snapshot = Column(JSON, nullable=True)
    # Publication metadata is nullable for all pre-077 immutable rows. Runtime
    # treats NULL release_kind as ``legacy_snapshot`` without rewriting them.
    flow_sha256 = Column(String(64), nullable=True, index=True)
    release_kind = Column(String(32), nullable=True)
    draft_revision = Column(Integer, nullable=True)
    execution_contract = Column(JSON, nullable=True)
    # Free-form changelog-style note ("rollback to v34", "add retry on
    # LLM node"). Optional — empty when auto-saved by the editor.
    message = Column(Text, nullable=True)
    # UUID of the version this one was rolled back from, NULL for
    # normal edits. Lets the UI render "v42 — rolled back to v17"
    # without needing to parse the message.
    rolled_back_from_id = Column(String(36), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String(255), default="demo-user", nullable=False)

    __table_args__ = (
        # Allocation is serialized by locking the parent System row.  This
        # constraint is the final invariant for imports, legacy callers, or a
        # future writer that bypasses the shared version service.
        UniqueConstraint(
            "system_id",
            "version_number",
            name="uq_system_versions_system_version_number",
        ),
        CheckConstraint(
            "release_kind IS NULL OR release_kind IN "
            "('legacy_snapshot', 'publish', 'rollback', 'migration')",
            name="ck_system_versions_release_kind",
        ),
        CheckConstraint(
            "draft_revision IS NULL OR draft_revision >= 1",
            name="ck_system_versions_draft_revision_positive",
        ),
    )
