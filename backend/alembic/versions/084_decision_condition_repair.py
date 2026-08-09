"""Rewrite the prose left in Decision branch conditions by the pre-aab6b5a6 seeds.

Revision ID: 084_decision_condition_repair
Revises: 083_workspace_skill_executor

Two seeded templates — ``Agentium Workspace Chat`` and ``Expert Knowledge
Capture`` — shipped Decision branches whose ``condition`` held English prose
describing the intended routing instead of an expression the predicate grammar
can parse. ``validate_condition`` rejects all of them, so ``validate_flow``
emits ``decision_condition_invalid`` and Publish refuses the graph with
``FLOW_PUBLISH_VALIDATION_FAILED``. These Systems have never been publishable,
under any image: the damage predates ``flow_publication_v1`` and is not a
regression from it.

Commit ``aab6b5a6`` repaired the seed templates, so every workspace created
since is clean. It could not repair the rows already written, which is what
this migration does. The replacement text is taken verbatim from those repaired
seeds rather than invented here — the mapping below is the template author's own
answer, applied to the stored copies so the estate converges on one template
shape instead of two.

Only an exact, whole-string match on a Decision branch ``condition`` is
rewritten. No prose is parsed, no expression is inferred, and a condition the
grammar already accepts is never touched. A graph that happens to hold one of
these strings anywhere other than ``config.branches[].condition`` is left alone.

The same graph is stored in three places that the publication gate requires to
agree: ``systems.flow_definition`` (the mirror), ``system_flow_drafts``
(the authority Publish validates) and ``system_versions`` (immutable history).
Repairing one without the others would move these Systems from "fails
validation" to "skipped: draft differs from the published version", which is
worse. All three are rewritten together and their digests recomputed, because
``backfill_flow_publication_contracts`` classifies a version whose stored
digest contradicts its own payload as unrepairable.

Every prior value is copied into ``flow_decision_condition_repairs`` before the
row is touched, so ``downgrade`` restores the exact bytes that were there and
this migration is genuinely reversible rather than reversible in principle.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "084_decision_condition_repair"
down_revision = "083_workspace_skill_executor"
branch_labels = None
depends_on = None

LEDGER = "flow_decision_condition_repairs"

# Verbatim from the repaired seed templates in commit aab6b5a6:
# ``app/services/systems/bootstrap.py``, nodes ``router.fast_exit``,
# ``runtime.deep_router`` and ``decision.answer_route``.
CONDITION_REPAIRS: dict[str, str] = {
    # Agentium Workspace Chat — router.fast_exit
    "maybe_trivial_bypass(query) && no pending action": "route == 'trivial_bypass'",
    "no context_id and no knowledge_scope and canonical answer match": (
        "route == 'canonical_answer'"
    ),
    "registry/calendar/action-plan/visual/map/vigie handler matches": (
        "route == 'workspace_action'"
    ),
    # The fallback branch. The grammar spells "always true" as the literal
    # ``True``; the node already names this branch as its ``default_branch``.
    "default route": "True",
    # Agentium Workspace Chat — runtime.deep_router
    "no deep recommendation or direct answer sufficient": "deep_search_requested != True",
    "retrieval degraded or Deep Search requested": "deep_search_requested == True",
    # Expert Knowledge Capture — decision.answer_route. The grammar allows a
    # dotted path only for ``ctx.<key>`` and the reserved pool namespaces, and
    # has no form at all for a nested field, so ``evaluation.verdict`` is
    # unreachable. The predicate reads the flat Decision ctx by bare name.
    "evaluation.verdict != 'sufficient'": "verdict != 'sufficient'",
}


def _sha256(flow: Any) -> str:
    """Reproduce ``execution_contract.canonical_flow_sha256`` without importing it.

    Alembic must not depend on application services, and the publication gate
    compares against exactly this encoding.
    """
    encoded = json.dumps(flow, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def repair_flow(flow: Any) -> tuple[Any, int]:
    """Return ``(repaired_copy, rewritten_count)``, leaving ``flow`` untouched.

    Exposed for the tests, which drive it over fixtures captured from the
    estate rather than restating the graphs by hand.
    """
    if not isinstance(flow, dict):
        return flow, 0
    nodes = flow.get("nodes")
    if not isinstance(nodes, list):
        return flow, 0

    repaired = deepcopy(flow)
    rewritten = 0
    for node in repaired.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if (node.get("kind") or node.get("type")) != "decision":
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        branches = config.get("branches")
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            condition = branch.get("condition")
            replacement = CONDITION_REPAIRS.get(condition) if isinstance(condition, str) else None
            if replacement is None:
                continue
            branch["condition"] = replacement
            rewritten += 1
    if not rewritten:
        return flow, 0
    return repaired, rewritten


def _ledger_table() -> Any:
    return sa.table(
        LEDGER,
        sa.column("id", sa.String()),
        sa.column("source_table", sa.String()),
        sa.column("row_key", sa.String()),
        sa.column("prior_flow_definition", sa.JSON()),
        sa.column("prior_flow_sha256", sa.String()),
        sa.column("new_flow_sha256", sa.String()),
        sa.column("conditions_rewritten", sa.Integer()),
        sa.column("repaired_at", sa.DateTime()),
    )


def _target(name: str, key: str, *, has_sha: bool) -> Any:
    columns = [
        sa.column(key, sa.String()),
        sa.column("flow_definition", sa.JSON()),
    ]
    if has_sha:
        columns.append(sa.column("flow_sha256", sa.String()))
    return sa.table(name, *columns)


# ``system_flow_drafts`` is keyed by ``system_id``; the other two by ``id``.
TARGETS: tuple[tuple[str, str, bool], ...] = (
    ("systems", "id", False),
    ("system_flow_drafts", "system_id", True),
    ("system_versions", "id", True),
)


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.utcnow()

    op.create_table(
        LEDGER,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_table", sa.String(length=64), nullable=False),
        sa.Column("row_key", sa.String(length=36), nullable=False),
        sa.Column("prior_flow_definition", sa.JSON(), nullable=False),
        sa.Column("prior_flow_sha256", sa.String(length=64), nullable=True),
        sa.Column("new_flow_sha256", sa.String(length=64), nullable=False),
        sa.Column("conditions_rewritten", sa.Integer(), nullable=False),
        sa.Column("repaired_at", sa.DateTime(), nullable=False),
    )
    ledger = _ledger_table()

    for name, key, has_sha in TARGETS:
        table = _target(name, key, has_sha=has_sha)
        # Materialized: the loop updates the table it reads from.
        rows = list(bind.execute(sa.select(table)).mappings().all())
        for row in rows:
            prior = row["flow_definition"]
            repaired, rewritten = repair_flow(prior)
            if not rewritten:
                continue

            values: dict[str, Any] = {"flow_definition": repaired}
            new_digest = _sha256(repaired)
            if has_sha:
                # A stored digest that no longer matches its own payload is
                # read as drift and makes the row unrepairable by Publish, so
                # it is recomputed here rather than left behind.
                values["flow_sha256"] = new_digest

            bind.execute(
                ledger.insert().values(
                    id=str(uuid4()),
                    source_table=name,
                    row_key=str(row[key]),
                    prior_flow_definition=prior,
                    prior_flow_sha256=row["flow_sha256"] if has_sha else None,
                    new_flow_sha256=new_digest,
                    conditions_rewritten=rewritten,
                    repaired_at=now,
                )
            )
            bind.execute(
                table.update().where(getattr(table.c, key) == row[key]).values(**values)
            )


def downgrade() -> None:
    """Put the recorded bytes back, then drop the record."""
    bind = op.get_bind()
    ledger = _ledger_table()

    for name, key, has_sha in TARGETS:
        table = _target(name, key, has_sha=has_sha)
        entries = list(
            bind.execute(
                sa.select(ledger).where(ledger.c.source_table == name)
            ).mappings().all()
        )
        for entry in entries:
            values: dict[str, Any] = {"flow_definition": entry["prior_flow_definition"]}
            if has_sha:
                values["flow_sha256"] = entry["prior_flow_sha256"]
            bind.execute(
                table.update()
                .where(getattr(table.c, key) == entry["row_key"])
                .values(**values)
            )

    op.drop_table(LEDGER)
