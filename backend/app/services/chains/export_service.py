"""Custom-chain export / import — Vague E / E3.4.

A System can be shared across workspaces / environments without leaking
DB-scoped identifiers. The export envelope preserves everything the
editor needs to rehydrate the graph, with one stability invariant:
**skills are referenced by ``slug``**, never by their DB ``id``.

On import the receiver tries to rebind every ``skill_slug`` found on
task nodes (and on the system-level ``skill_ids`` list) against its own
skill catalog. Unresolved slugs are surfaced in the response so the UI
can warn but the import never fails for that reason — users can bind
the remaining skills manually afterwards.

Envelope shape (``schema_version = 1``):

```json
{
  "kind": "agentium.system.export",
  "schema_version": 1,
  "exported_at": "2026-04-24T22:00:00Z",
  "exported_by": "demo-user",
  "source": {"workspace_id": "...", "system_id": "..."},
  "system": {
    "name": "...",
    "objective": "...",
    "flow_definition": {...},        # ``skill_id`` stripped on task nodes
    "skill_slugs": ["llm_rag_answer", "guardrail_pii"],
    "execution_mode": "real_time_decision",
    "execution_profile": {...},
    "default_prompt_type": null,
    "default_model": null,
    "retrieval_mode_default": null
  }
}
```

Anything else (``capability_id``, ``context_id``, policies, audit
metadata) is intentionally omitted — those are workspace-scoped pieces
that don't round-trip cleanly; the user re-associates them inside the
target workspace after import.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy.orm import Session as DBSession

from app.models.skill import Skill
from app.models.system import System

SCHEMA_VERSION = 1
ENVELOPE_KIND = "agentium.system.export"


class ChainExportError(ValueError):
    """Raised on malformed import payloads (bad envelope / bad flow)."""


def serialize_for_export(
    *,
    db: DBSession,
    system: System,
    exported_by: str,
) -> dict[str, Any]:
    """Build a portable JSON envelope for ``system``.

    - Pulls the slugs for every ``skill_id`` on the system so the
      receiver can rebind them even if the internal IDs differ.
    - Strips per-node ``skill_id`` from ``flow_definition`` to avoid
      cross-workspace ID contamination; ``skill_slug`` is preserved.
    """
    raw_flow = system.flow_definition or {}
    flow = _strip_flow_for_export(raw_flow)

    skill_ids = list(system.skill_ids or [])
    skill_slugs = _resolve_slugs_from_ids(db, skill_ids)

    return {
        "kind": ENVELOPE_KIND,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "exported_by": exported_by,
        "source": {
            "workspace_id": system.workspace_id,
            "system_id": system.id,
        },
        "system": {
            "name": system.name,
            "objective": system.objective or "",
            "flow_definition": flow,
            "skill_slugs": skill_slugs,
            "execution_mode": system.execution_mode,
            "execution_profile": system.execution_profile or {},
            "coordination_pattern": system.coordination_pattern,
            "default_prompt_type": getattr(system, "default_prompt_type", None),
            "default_model": getattr(system, "default_model", None),
            "retrieval_mode_default": getattr(system, "retrieval_mode_default", None),
        },
    }


def prepare_import(
    *,
    db: DBSession,
    envelope: Mapping[str, Any],
    workspace_id: str,
    target_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate ``envelope`` and rehydrate it against the target workspace.

    Returns a ``(system_create_kwargs, rebind_report)`` tuple where
    ``rebind_report`` carries::

        {
            "resolved_skills": [{"slug": ..., "skill_id": ...}, ...],
            "unresolved_skills": ["slug1", "slug2"],
            "task_node_rebinds": [{"node_id": ..., "slug": ..., "skill_id": ...|None}]
        }

    Caller creates the System + seeds v1; this function is kept pure so
    it can be unit-tested and reused by a future dry-run endpoint.
    """
    _validate_envelope(envelope)

    sys_payload = envelope.get("system") or {}
    raw_flow = sys_payload.get("flow_definition") or {}
    if not isinstance(raw_flow, Mapping):
        raise ChainExportError("``system.flow_definition`` must be an object.")

    # Rebind skill slugs on task nodes.
    flow, task_rebinds, unresolved_from_nodes = _rebind_task_skills(
        db=db,
        flow=dict(raw_flow),
        workspace_id=workspace_id,
    )

    # Rebind system-level skill_ids from ``skill_slugs``.
    slugs = list(sys_payload.get("skill_slugs") or [])
    resolved: list[dict[str, str]] = []
    unresolved: list[str] = []
    skill_ids: list[str] = []
    for slug in slugs:
        skill_id = _lookup_skill_id(db, slug=slug, workspace_id=workspace_id)
        if skill_id:
            resolved.append({"slug": slug, "skill_id": skill_id})
            skill_ids.append(skill_id)
        else:
            unresolved.append(slug)

    for slug in unresolved_from_nodes:
        if slug not in unresolved and slug not in slugs:
            unresolved.append(slug)

    kwargs: dict[str, Any] = {
        "name": target_name or sys_payload.get("name") or "Imported chain",
        "objective": sys_payload.get("objective") or "",
        "flow_definition": flow,
        "skill_ids": skill_ids,
        "execution_mode": sys_payload.get("execution_mode") or "real_time_decision",
        "execution_profile": sys_payload.get("execution_profile") or {},
        "coordination_pattern": sys_payload.get("coordination_pattern") or "single_agent",
        "default_prompt_type": sys_payload.get("default_prompt_type"),
        "default_model": sys_payload.get("default_model"),
        "retrieval_mode_default": sys_payload.get("retrieval_mode_default"),
    }
    report = {
        "resolved_skills": resolved,
        "unresolved_skills": unresolved,
        "task_node_rebinds": task_rebinds,
        "source": envelope.get("source") or {},
    }
    return kwargs, report


# ---------------- Internals ----------------


def _validate_envelope(envelope: Mapping[str, Any]) -> None:
    if not isinstance(envelope, Mapping):
        raise ChainExportError("Envelope must be a JSON object.")
    if envelope.get("kind") != ENVELOPE_KIND:
        raise ChainExportError(
            f"Unexpected envelope kind: {envelope.get('kind')!r} (expected {ENVELOPE_KIND!r})."
        )
    version = envelope.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ChainExportError(
            f"Unsupported schema_version: {version!r} (expected {SCHEMA_VERSION})."
        )
    if not isinstance(envelope.get("system"), Mapping):
        raise ChainExportError("Missing ``system`` section in envelope.")


def _strip_flow_for_export(flow: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep-enough copy of ``flow`` with per-node ``skill_id``
    removed. ``skill_slug`` stays so the receiver can rebind."""
    out: dict[str, Any] = {k: v for k, v in flow.items() if k != "nodes"}
    out_nodes: list[dict[str, Any]] = []
    for n in flow.get("nodes") or []:
        if not isinstance(n, Mapping):
            continue
        node = {k: v for k, v in n.items()}
        cfg = node.get("config")
        if isinstance(cfg, Mapping):
            new_cfg = {k: v for k, v in cfg.items() if k != "skill_id"}
            node["config"] = new_cfg
        out_nodes.append(node)
    out["nodes"] = out_nodes
    return out


def _rebind_task_skills(
    *,
    db: DBSession,
    flow: dict[str, Any],
    workspace_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    rebinds: list[dict[str, Any]] = []
    unresolved: list[str] = []
    nodes = flow.get("nodes") or []
    out_nodes: list[dict[str, Any]] = []
    for n in nodes:
        if not isinstance(n, Mapping):
            out_nodes.append(n)
            continue
        node = {k: v for k, v in n.items()}
        cfg = node.get("config")
        if isinstance(cfg, Mapping) and cfg.get("skill_slug"):
            slug = str(cfg.get("skill_slug"))
            skill_id = _lookup_skill_id(db, slug=slug, workspace_id=workspace_id)
            new_cfg = {k: v for k, v in cfg.items()}
            if skill_id:
                new_cfg["skill_id"] = skill_id
            else:
                # Remove any stale ``skill_id`` so nothing leaks from the
                # source workspace into the imported graph.
                new_cfg.pop("skill_id", None)
                unresolved.append(slug)
            node["config"] = new_cfg
            rebinds.append(
                {
                    "node_id": node.get("id"),
                    "slug": slug,
                    "skill_id": skill_id,
                }
            )
        out_nodes.append(node)
    flow["nodes"] = out_nodes
    return flow, rebinds, unresolved


def _lookup_skill_id(db: DBSession, *, slug: str, workspace_id: str) -> str | None:
    """Resolve a skill slug against the catalog.

    Matches either the workspace-scoped skill (``workspace_id = ws``) or
    a globally-seeded one (``workspace_id IS NULL``), preferring the
    workspace-scoped match when both exist.
    """
    skill = (
        db.query(Skill)
        .filter(Skill.slug == slug)
        .filter((Skill.workspace_id == workspace_id) | (Skill.workspace_id.is_(None)))
        .order_by(Skill.workspace_id.is_(None))  # False (ws-scoped) < True (global)
        .first()
    )
    return skill.id if skill else None


def _resolve_slugs_from_ids(db: DBSession, skill_ids: list[str]) -> list[str]:
    if not skill_ids:
        return []
    rows = db.query(Skill.id, Skill.slug).filter(Skill.id.in_(skill_ids)).all()
    by_id = {r.id: r.slug for r in rows}
    return [by_id[i] for i in skill_ids if i in by_id]
