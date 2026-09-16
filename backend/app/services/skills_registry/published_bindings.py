"""What a published Flow froze of an authored Skill, and whether it still matches.

A workspace Skill is catalog data and may be edited; a published Flow is an
account of what was accepted and must not change because the catalog did. The
two are reconciled by publication freezing the Skill's contract and runtime into
``SystemVersion.execution_contract``, so an edit is admitted without reaching
production. What is missing without this module is the other half: an author who
edits a Skill has no way to learn that some published Flow is now behind, which
would make the freeze indistinguishable from the edit having taken effect.

Only the version each System currently points at is examined. Earlier versions
are history and nothing dispatches them, so reporting them as affected would
name work no republish can resolve.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.services.flow_contracts import (
    FlowContractError,
    skill_definition_sha256,
    validate_schema_definition,
)


@dataclass(frozen=True, slots=True)
class PublishedSkillBinding:
    """One published version that dispatches a Skill, and its freshness."""

    system_id: str
    system_name: str
    version_id: str
    version_number: int
    node_ids: tuple[str, ...]
    stale: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "system_name": self.system_name,
            "version_id": self.version_id,
            "version_number": self.version_number,
            "node_ids": list(self.node_ids),
            "stale": self.stale,
        }


def live_skill_definition_sha256(skill: Skill) -> str | None:
    """Digest the current row the way publication would freeze it.

    ``None`` when the row is not authored, or when its schemas would no longer
    compile: neither can be compared against a frozen digest, and reporting
    "unchanged" for a row that cannot be published is the failure mode 522632e0
    was written to remove.
    """

    if not isinstance(skill.executor, Mapping):
        return None
    try:
        return skill_definition_sha256(
            input_schema=validate_schema_definition(
                skill.input_schema or {}, field="input_schema"
            ),
            output_schema=validate_schema_definition(
                skill.output_schema or {}, field="output_schema"
            ),
            executor=dict(skill.executor),
        )
    except FlowContractError:
        return None


def published_skill_bindings(
    db: DBSession,
    *,
    workspace_id: str,
    skill: Skill,
) -> list[PublishedSkillBinding]:
    """Published versions dispatching ``skill``, newest System name first.

    The contract nodes are scanned in Python rather than queried as JSON: the
    set is one row per published System in a workspace, and a portable filter
    across SQLite and Postgres JSON columns costs more than it saves.
    """

    rows = (
        db.query(System, SystemVersion)
        .join(SystemVersion, SystemVersion.id == System.published_flow_version_id)
        .filter(System.workspace_id == workspace_id)
        .all()
    )
    live_digest = live_skill_definition_sha256(skill)
    bindings: list[PublishedSkillBinding] = []
    for system, version in rows:
        contract = version.execution_contract
        nodes = contract.get("nodes") if isinstance(contract, Mapping) else None
        if not isinstance(nodes, Mapping):
            continue
        frozen_digests: dict[str, Any] = {}
        for node_id, node in nodes.items():
            if not isinstance(node, Mapping):
                continue
            if node.get("skill_slug") == skill.slug:
                frozen_digests[str(node_id)] = node.get("skill_definition_sha256")
            tools = node.get("tool_contract")
            tool_nodes = tools.get("nodes", {}) if isinstance(tools, Mapping) else {}
            tool = tool_nodes.get(skill.slug)
            if isinstance(tool, Mapping):
                frozen_digests[str(node_id)] = tool.get("skill_definition_sha256")
        if not frozen_digests:
            continue
        # A node frozen before authored runtimes were captured carries no digest
        # and resolves its executor live, so it is behind by construction.
        stale = live_digest is None or any(
            digest != live_digest for digest in frozen_digests.values()
        )
        bindings.append(
            PublishedSkillBinding(
                system_id=system.id,
                system_name=system.name,
                version_id=version.id,
                version_number=version.version_number,
                node_ids=tuple(sorted(frozen_digests)),
                stale=stale,
            )
        )
    return sorted(bindings, key=lambda item: (item.system_name, item.system_id))


__all__ = [
    "PublishedSkillBinding",
    "live_skill_definition_sha256",
    "published_skill_bindings",
]
