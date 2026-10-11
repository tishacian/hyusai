"""Pin an execution contract on every published Flow that lacks one.

Examples::

    python -m scripts.backfill_flow_publication_contracts
    python -m scripts.backfill_flow_publication_contracts --workspace-id <uuid>
    python -m scripts.backfill_flow_publication_contracts --apply \
        --actor operator@example.net --report contracts.json

Migrations 077 and 081 give every System a published pointer, but they leave
``execution_contract`` NULL: a contract is compiled from workspace Skills, which
Alembic must not reach. A published version without one is valid history and
hydrates fine, yet refuses to run with ``PUBLISHED_EXECUTION_CONTRACT_MISSING``.
The remedy the service already implements is one explicit Publish, which appends
a version carrying the frozen contract even when the graph bytes are unchanged.
This script performs that Publish for the whole estate.

Run it after ``081_flow_publication_baseline`` and before traffic resumes.
A System whose draft has moved ahead of its published version is skipped, never
published: promoting unreviewed editor work is exactly the destructive behaviour
draft/publish separation exists to prevent.

That skip is decided against the digest recomputed from the published version's
own immutable JSON, never against ``SystemVersion.flow_sha256``. The stored
column is nullable and migration 077 left it NULL on every historical snapshot
it reused as a published pointer. Comparing a draft digest to NULL reads as
"different", which classified the exact Systems this script exists to repair as
edited-by-hand and skipped them. A missing digest means the published identity
is unknown, not that the draft moved: the payload is the authority, and it is
always hashable.

For the same reason a populated ``execution_contract`` is not evidence that the
contract is usable. A structurally valid contract compiled by an older compiler
can name no ingress at all, and freezing means no later compiler fix reaches it;
the System keeps refusing every dispatch adapter until a new version is
published. So the contract, like the digest, is classified by recomputing it:
the published payload is recompiled with today's compiler and the resulting
``contract_sha256`` compared to the frozen one. This is the same test
``publish_draft`` already applies to decide whether a Publish is a no-op, which
is what makes the pass idempotent — a second consecutive run recompiles to the
same digest and publishes nothing.

Re-publishing a stale contract is reported apart from giving an unpublished
version its first one (``publication_kind``, and the two summary counters that
partition ``publish``): an operator must be able to see that this run touches
rows an earlier run left alone.

The dry run is a plan, not a guarantee. It compiles contracts but never calls
``publish_draft``, so ``report["limits"]`` states what it could not check and
``apply_risk`` names the apply-time refusals it can already see.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.system_flow_draft import SystemFlowDraft  # noqa: E402
from app.models.system_version import SystemVersion  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import flow_contracts  # noqa: E402
from app.services.run_engine.execution_contract import canonical_flow_sha256  # noqa: E402
from app.services.systems import flow_publication  # noqa: E402

MESSAGE = "Pin execution contract for the migration publication baseline"

DRY_RUN_LIMITS = (
    "A `publish` action is a plan: the dry run never calls publish_draft.",
    "The contract is compiled here only to classify staleness. publish_draft "
    "validates the draft graph first, so a blocking DAG diagnostic (an invalid "
    "Decision condition, an unwired branch) still refuses a System this plan "
    "shows as publishable.",
    "A System whose contract cannot be recompiled carries `contract_freshness` "
    "= unverified: its frozen contract may already be stale and this run will "
    "not repair it.",
    "The plan reflects the rows read at this instant. A draft saved between this "
    "report and --apply moves that System to skipped or failed.",
    "`apply_risk` names the apply-time refusals this plan can see structurally. "
    "Its absence is not proof that --apply will succeed.",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", action="append", default=[])
    parser.add_argument("--system-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="Persist the publications")
    parser.add_argument("--actor", default="system:flow-contract-backfill")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    return parser.parse_args()


def _recompiled_contract_sha256(
    db: Any,
    *,
    system: System,
    version: SystemVersion,
    workspace: Any,
) -> tuple[str | None, dict[str, str] | None]:
    """The contract digest today's compiler produces for the published payload.

    ``publish_draft`` compiles the very same payload and appends a version
    unless the digest it obtains equals the frozen one, so recompiling here
    predicts that decision exactly instead of guessing at it.
    """

    try:
        contract = flow_publication.compile_execution_contract(
            db,
            version.flow_definition,
            workspace,
            system=system,
        )
    except flow_publication.FlowPublicationError as exc:
        return None, {"code": exc.code, "message": exc.message}
    digest = contract.get("contract_sha256")
    return (digest if isinstance(digest, str) else None), None


def _publication_defects(
    version: SystemVersion,
    *,
    published_digest: str,
    recompiled_contract_sha256: str | None = None,
) -> list[str]:
    """What stops this version from serving a Run the estate would recognise.

    The two conditions ``published_run_evidence`` enforces — a structurally
    valid frozen contract and a stored digest equal to the payload it names —
    plus the one it cannot see: a contract that is valid but no longer what the
    current compiler produces. A vacuous contract satisfies both runtime gates
    and still refuses every dispatch adapter, so presence is not health here
    any more than a populated ``flow_sha256`` column was.
    """

    defects: list[str] = []
    contract: dict[str, Any] | None = None
    try:
        contract = flow_contracts.validate_execution_contract(version.execution_contract)
    except flow_contracts.FlowContractError:
        defects.append("execution_contract_missing")
    if version.flow_sha256 != published_digest:
        defects.append("flow_sha256_drift" if version.flow_sha256 else "flow_sha256_missing")
    if (
        contract is not None
        and recompiled_contract_sha256 is not None
        and contract.get("contract_sha256") != recompiled_contract_sha256
    ):
        defects.append("execution_contract_stale")
    return defects


def _apply_risk(
    defects: list[str],
    *,
    mirror_digest: str,
    published_digest: str,
    compile_error: dict[str, str] | None,
) -> dict[str, str] | None:
    """Apply-time refusals already visible before publish_draft is called."""

    if mirror_digest != published_digest:
        return {
            "code": "PUBLISHED_FLOW_MIRROR_DRIFT",
            "message": (
                "systems.flow_definition no longer mirrors the published version, so "
                "publish_draft will refuse this System; publishing the migration draft "
                "would discard that legacy edit."
            ),
        }
    if compile_error is not None:
        return {
            "code": compile_error["code"],
            "message": (
                "the execution contract does not compile from the published payload, "
                f"so publish_draft will refuse this System: {compile_error['message']}"
            ),
        }
    if defects == ["flow_sha256_missing"]:
        return {
            "code": "PUBLISHED_FLOW_VERSION_HASH_MISSING",
            "message": (
                "the published contract is already valid and still current, so Publish "
                "returns a no-op and the absent digest survives."
            ),
        }
    return None


def _plan(db: Any, system: System, workspace: Any) -> dict[str, Any]:
    """Classify a System without mutating it. ``action`` drives the apply pass."""

    item: dict[str, Any] = {"system_id": system.id, "status": system.status}
    if not system.published_flow_version_id:
        item["action"] = "skipped"
        item["reason"] = "no published pointer; run migration 081 first"
        return item

    version = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == system.published_flow_version_id,
            SystemVersion.system_id == system.id,
        )
        .one_or_none()
    )
    if version is None:
        item["action"] = "skipped"
        item["reason"] = "published pointer does not reference an owned immutable version"
        return item

    try:
        # The immutable payload is the authority for published identity; the
        # nullable column is only a cache of it.
        published_digest = canonical_flow_sha256(version.flow_definition)
        mirror_digest = canonical_flow_sha256(system.flow_definition)
    except ValueError:
        item["action"] = "skipped"
        item["reason"] = "flow_definition is not a JSON object; qualify this System by hand"
        return item

    recompiled_sha256, compile_error = _recompiled_contract_sha256(
        db,
        system=system,
        version=version,
        workspace=workspace,
    )
    defects = _publication_defects(
        version,
        published_digest=published_digest,
        recompiled_contract_sha256=recompiled_sha256,
    )
    if not defects:
        item["action"] = "already_pinned"
        if compile_error is not None:
            # Staleness could not be tested, so "nothing to do" is a reading of
            # the rows rather than a verified fact.
            item["contract_freshness"] = "unverified"
            item["recompile_error"] = compile_error
        return item
    item["defects"] = defects
    if "flow_sha256_drift" in defects:
        item["action"] = "skipped"
        item["reason"] = (
            "the published digest contradicts its own immutable payload; publish_draft "
            "refuses this version, so no Publish can repair it"
        )
        return item

    draft = (
        db.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == system.id).one_or_none()
    )
    if draft is None:
        item["action"] = "skipped"
        item["reason"] = "no server draft; run migration 081 first"
        return item
    if draft.flow_sha256 != published_digest:
        item["action"] = "skipped"
        item["reason"] = "draft differs from the published version; publish it by hand"
        item["draft_revision"] = draft.revision
        return item

    item["action"] = "publish"
    # `republication` means the pointer already carries a valid frozen contract
    # and this run appends another one anyway. An operator must see that apart
    # from a first publication: it is the bucket an earlier run of this script
    # reported as already_pinned and left alone.
    item["publication_kind"] = (
        "initial" if "execution_contract_missing" in defects else "republication"
    )
    item["draft_revision"] = draft.revision
    item["published_flow_version_id"] = system.published_flow_version_id
    item["expected_contract_sha256"] = recompiled_sha256
    risk = _apply_risk(
        defects,
        mirror_digest=mirror_digest,
        published_digest=published_digest,
        compile_error=compile_error,
    )
    if risk is not None:
        item["apply_risk"] = risk
    return item


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    report: dict[str, Any] = {
        "schema_version": 2,
        "mode": "apply" if args.apply else "dry_run",
        "workspaces": [],
        "summary": {
            "systems": 0,
            "already_pinned": 0,
            "publish": 0,
            "published": 0,
            "skipped": 0,
            "failed": 0,
            # Annotations over the `publish` bucket, not buckets of their own.
            # `publish_initial` and `publish_republication` partition it: the
            # second names Systems an earlier run reported as already_pinned.
            "at_risk": 0,
            "publish_initial": 0,
            "publish_republication": 0,
        },
    }
    if not args.apply:
        report["limits"] = list(DRY_RUN_LIMITS)
    summary = report["summary"]
    try:
        workspace_query = db.query(Workspace).filter(Workspace.deleted_at.is_(None))
        if args.workspace_id:
            workspace_query = workspace_query.filter(
                Workspace.id.in_(sorted(set(args.workspace_id)))
            )
        for workspace in workspace_query.order_by(Workspace.id.asc()).all():
            workspace_report: dict[str, Any] = {
                "workspace_id": workspace.id,
                "publication_enabled": flow_publication.flow_publication_enabled(workspace),
                "systems": [],
            }
            report["workspaces"].append(workspace_report)
            if not workspace_report["publication_enabled"]:
                workspace_report["skipped"] = "flow_publication_v1 is off for this workspace"
                continue

            systems_query = db.query(System).filter(System.workspace_id == workspace.id)
            if args.system_id:
                systems_query = systems_query.filter(System.id.in_(sorted(set(args.system_id))))
            for system in systems_query.order_by(System.id.asc()).all():
                item = _plan(db, system, workspace)
                summary["systems"] += 1
                if item["action"] != "publish":
                    summary["already_pinned" if item["action"] == "already_pinned" else "skipped"] += 1
                    workspace_report["systems"].append(item)
                    continue

                summary["publish"] += 1
                summary[f"publish_{item['publication_kind']}"] += 1
                if "apply_risk" in item:
                    summary["at_risk"] += 1
                if args.apply:
                    try:
                        version, _draft, no_op = flow_publication.publish_draft(
                            db,
                            system_id=system.id,
                            workspace=workspace,
                            expected_draft_revision=int(item["draft_revision"]),
                            expected_published_version_id=item["published_flow_version_id"],
                            message=MESSAGE,
                            # The graph is unchanged, so any breaking finding
                            # comes from materializing the absent contract.
                            breaking_change_intent="acknowledged",
                            actor=args.actor,
                        )
                    except flow_publication.FlowPublicationError as exc:
                        db.rollback()
                        item["action"] = "failed"
                        item["error"] = {"code": exc.code, "message": exc.message}
                        summary["failed"] += 1
                        workspace_report["systems"].append(item)
                        continue
                    db.commit()
                    item["new_published_version_id"] = version.id
                    item["no_op"] = no_op
                    # Assert the post-condition the window needs rather than
                    # inferring it: publish_draft can legitimately return a
                    # no-op that leaves the version unexecutable. Carrying the
                    # planned contract digest in makes the same check prove
                    # idempotency — a version still classified stale here is one
                    # the next run would publish all over again.
                    remaining = _publication_defects(
                        version,
                        published_digest=canonical_flow_sha256(version.flow_definition),
                        recompiled_contract_sha256=item["expected_contract_sha256"],
                    )
                    if remaining:
                        item["action"] = "not_repaired"
                        item["remaining_defects"] = remaining
                        summary["failed"] += 1
                    else:
                        item["action"] = "published"
                        summary["published"] += 1
                workspace_report["systems"].append(item)
    finally:
        db.rollback()
        db.close()

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    # A dry run that can already name an apply-time refusal must not read as
    # green; the apply pass is judged on what actually happened instead.
    return 1 if summary["failed"] or (not args.apply and summary["at_risk"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
