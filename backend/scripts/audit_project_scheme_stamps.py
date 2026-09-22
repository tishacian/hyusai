"""Find workspaces whose data carries project codes their tenant can no longer parse.

Since ADR 0002 the Andritz identifier grammar runs only where
``workspaces.settings["family"]`` is stamped ``andritz``. The stamp is the only
switch, and losing it is silent: no filter, no project inventory, no
comparative decomposition, no error anywhere. A database restored from a dump
older than migration 058, or a workspace recreated by hand, is exactly how that
happens.

This audit is data-driven rather than name-driven, which is the point. It does
not guess from a slug -- the doctrine forbids inferring a specialization from a
mutable name. It compares two facts that must agree:

* the knowledge ledger already holds ``project_code`` values for the workspace;
* the workspace resolves to a scheme able to produce such values.

A workspace holding project codes while resolving to an empty scheme is the
inconsistency worth a human. The reverse, a stamped workspace with no codes
yet, is normal for a fresh tenant and is reported as information only.

Read-only. Run it after a restore, and after any release that touches
workspace settings.

    python -m scripts.audit_project_scheme_stamps
    python -m scripts.audit_project_scheme_stamps --json
"""

from __future__ import annotations

import argparse
import json
import sys

import sqlalchemy as sa

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.rag.project_references import project_reference_scheme
from app.services.workspace_features import workspace_family

LEDGER_PROJECT_CODES = sa.text(
    """
    SELECT COUNT(*)
    FROM knowledge_collection_sources s
    JOIN knowledge_collections c ON c.id = s.collection_id
    WHERE c.workspace_id = :workspace_id
      AND COALESCE(s.source_metadata->>'project_code', '') <> ''
    """
)


def audit(db) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for workspace in db.query(Workspace).order_by(Workspace.slug).all():
        try:
            coded = int(db.execute(LEDGER_PROJECT_CODES, {"workspace_id": workspace.id}).scalar() or 0)
        except Exception as exc:  # noqa: BLE001 - a missing ledger is not this audit's business
            print(f"! ledger unreadable for {workspace.slug}: {exc}", file=sys.stderr)
            coded = 0
        scheme = project_reference_scheme(workspace)
        rows.append(
            {
                "slug": workspace.slug,
                "family": workspace_family(workspace),
                "scheme": scheme or "(none)",
                "ledger_project_codes": coded,
                "verdict": "ORPHANED" if coded and not scheme else "ok",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = audit(db)
    finally:
        db.close()

    orphaned = [row for row in rows if row["verdict"] == "ORPHANED"]

    if args.json:
        print(json.dumps({"workspaces": rows, "orphaned": len(orphaned)}, indent=2))
    else:
        print(f"{'slug':<28} {'family':<14} {'scheme':<10} {'codes':>7}  verdict")
        for row in rows:
            print(
                f"{str(row['slug']):<28} {str(row['family']):<14} "
                f"{str(row['scheme']):<10} {row['ledger_project_codes']:>7}  {row['verdict']}"
            )
        print()
        if orphaned:
            print(
                f"{len(orphaned)} workspace(s) hold project codes that their tenant can no "
                "longer parse. Check whether the family stamp was lost."
            )
        else:
            print("Every workspace holding project codes resolves to a scheme that produces them.")

    sys.exit(1 if orphaned else 0)


if __name__ == "__main__":
    main()
