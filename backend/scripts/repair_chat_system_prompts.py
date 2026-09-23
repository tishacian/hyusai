"""Replace the pre-generalisation system prompt stored in workspace chat Systems.

Examples::

    python -m scripts.repair_chat_system_prompts
    python -m scripts.repair_chat_system_prompts --workspace-id <uuid>
    python -m scripts.repair_chat_system_prompts --apply \
        --actor operator@example.net --report chat-prompts.json

Until lot 1b (docs/adr/0003-generalisation-frontieres.md) the chat System
bootstrap stored one system prompt for every workspace, and it named a
customer: "Agentium users in the Andritz workspace are already Andritz
experts". A stored prompt wins over the family default, because /chat reads the
published mirror of the chat System, so every workspace still sends it.

The prompt sits at three places of the chat Flow: ``prompt_contract.base_system_prompt``,
the ``runtime.prompt_assembly`` node and the ``skill.fast_answer`` node, the one
/chat reads. Each place whose value is exactly the legacy text is replaced by
``default_system_prompt(family)``; any other value is somebody's customisation
and is left alone. For the family whose wording the legacy text was, the
replacement is the same text, so nothing is published.

The change goes through the publication service, never around it: one draft
revision and one Publish, which appends a SystemVersion. Earlier versions, run
snapshots and frozen execution contracts keep the bytes they recorded. A
System is skipped, never published, when:

- its workspace has no stamped family: the generic default could strip wording
  a family owns;
- its draft has moved ahead of its published version: promoting unreviewed
  editor work is what draft/publish separation exists to prevent.

Workspaces with Flow publication switched off get the historical direct mirror
update, as the bootstrap's own reconciler does for them.

The dry run is the default. Each System is applied in its own transaction, so
one refusal is reported and the others still proceed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.procurement_agent import default_system_prompt  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.system_flow_draft import SystemFlowDraft  # noqa: E402
from app.models.system_version import SystemVersion  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.run_engine.execution_contract import canonical_flow_sha256  # noqa: E402
from app.services.systems import flow_publication  # noqa: E402
from app.services.systems.bootstrap import _find_workspace_chat_system  # noqa: E402
from app.services.workspace_features import KNOWN_FAMILIES  # noqa: E402

#: The one text the bootstrap stored before lot 1b, byte for byte.
LEGACY_SYSTEM_PROMPT = (
    "You are an intelligent assistant with access to a curated knowledge base.\n\n"
    "Answer questions accurately and concisely using the retrieved context.\n"
    "When the context contains relevant information, cite it specifically.\n"
    "If no relevant context is available, say so clearly rather than guessing.\n"
    'Do not reproduce generic supplier-document footers such as "contact Andritz for more '
    'information" as advice in the chat; Agentium users in the Andritz workspace are already '
    "Andritz experts.\n\n"
    "Be professional, precise, and helpful."
)

MESSAGE = "Replace the pre-generalisation chat system prompt (ADR 0003)"
ACTOR = "system:chat-prompt-repair"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="Publish the repaired Flows")
    parser.add_argument("--actor", default=ACTOR)
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    return parser.parse_args(argv)


def _prompt_slots(flow: dict[str, Any]) -> list[tuple[str, dict[str, Any], str]]:
    """(label, container, key) for each place a chat Flow stores its prompt."""

    slots: list[tuple[str, dict[str, Any], str]] = []
    contract = flow.get("prompt_contract")
    if isinstance(contract, dict):
        slots.append(("prompt_contract.base_system_prompt", contract, "base_system_prompt"))
    for node in flow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        node_contract = data.get("prompt_contract") if isinstance(data, dict) else None
        if not isinstance(node_contract, dict):
            continue
        if node.get("id") == "runtime.prompt_assembly":
            slots.append(("runtime.prompt_assembly.base_system_prompt", node_contract, "base_system_prompt"))
        elif node.get("id") == "skill.fast_answer":
            slots.append(("skill.fast_answer.system_prompt", node_contract, "system_prompt"))
    return slots


def repaired_flow(flow: Any, family: str) -> tuple[dict[str, Any], list[str]]:
    """The Flow with every legacy prompt replaced, and the places that changed."""

    repaired = copy.deepcopy(flow) if isinstance(flow, dict) else {}
    replacement = default_system_prompt(family)
    changed: list[str] = []
    for label, container, key in _prompt_slots(repaired):
        if container.get(key) == LEGACY_SYSTEM_PROMPT and replacement != LEGACY_SYSTEM_PROMPT:
            container[key] = replacement
            changed.append(label)
    return repaired, changed


def _stamped_family(workspace: Workspace) -> str | None:
    settings = workspace.settings if isinstance(workspace.settings, dict) else {}
    family = str(settings.get("family") or "").strip().lower()
    return family if family in KNOWN_FAMILIES else None


def plan_system(db: Any, workspace: Workspace, system: System) -> dict[str, Any]:
    """Classify one chat System without writing anything."""

    entry: dict[str, Any] = {
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "system_id": system.id,
        "family": _stamped_family(workspace),
        "changed_slots": [],
    }
    if entry["family"] is None:
        entry["status"] = "skipped_family_unstamped"
        return entry
    publication = flow_publication.flow_publication_enabled(workspace)
    entry["publication"] = publication
    if publication:
        version = (
            db.query(SystemVersion).filter(SystemVersion.id == system.published_flow_version_id).first()
            if system.published_flow_version_id
            else None
        )
        if version is None:
            entry["status"] = "skipped_no_published_version"
            return entry
        current = version.flow_definition
        draft = db.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == system.id).first()
        if draft is not None and draft.flow_sha256 != canonical_flow_sha256(current):
            entry["status"] = "skipped_draft_ahead_of_published"
            return entry
    else:
        current = system.flow_definition
    repaired, changed = repaired_flow(current, entry["family"])
    entry["changed_slots"] = changed
    if not changed:
        entry["status"] = "nothing_to_replace"
    elif canonical_flow_sha256(repaired) == canonical_flow_sha256(current):
        entry["status"] = "no_op"
    else:
        entry["status"] = "publish" if publication else "legacy_mirror_update"
    entry["_repaired"] = repaired
    return entry


def apply_entry(db: Any, workspace: Workspace, system: System, entry: dict[str, Any], *, actor: str) -> None:
    repaired = entry.pop("_repaired", None)
    if entry["status"] == "legacy_mirror_update":
        system.flow_definition = repaired
        db.add(system)
        return
    if entry["status"] != "publish":
        return
    draft = db.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == system.id).one()
    draft, _unchanged = flow_publication.save_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        flow_definition=repaired,
        expected_revision=draft.revision,
        actor=actor,
    )
    version, _draft, _no_op = flow_publication.publish_draft(
        db,
        system_id=system.id,
        workspace=workspace,
        expected_draft_revision=draft.revision,
        expected_published_version_id=system.published_flow_version_id,
        message=MESSAGE,
        breaking_change_intent="acknowledged",
        actor=actor,
    )
    entry["published_version_id"] = version.id


def run(db: Any, *, workspace_ids: list[str], apply: bool, actor: str) -> dict[str, Any]:
    query = db.query(Workspace)
    if workspace_ids:
        query = query.filter(Workspace.id.in_(workspace_ids))
    entries: list[dict[str, Any]] = []
    for workspace in query.order_by(Workspace.slug.asc()).all():
        system = _find_workspace_chat_system(db, workspace.id)
        if system is None:
            continue
        entry = plan_system(db, workspace, system)
        if apply and entry["status"] in {"publish", "legacy_mirror_update"}:
            try:
                apply_entry(db, workspace, system, entry, actor=actor)
                db.commit()
                entry["applied"] = True
            except Exception as exc:  # noqa: BLE001 - one refusal must not stop the estate
                db.rollback()
                entry["applied"] = False
                entry["error"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None), "message": str(exc)}
        entry.pop("_repaired", None)
        entries.append(entry)
    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    return {"apply": apply, "summary": summary, "systems": entries}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db = SessionLocal()
    try:
        report = run(db, workspace_ids=args.workspace_id, apply=args.apply, actor=args.actor)
    finally:
        db.close()
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    failed = [entry for entry in report["systems"] if entry.get("applied") is False]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
