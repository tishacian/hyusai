"""Compare the canonical Skills/Capabilities catalog with the database, or apply it.

The API seeds the catalog at boot only when ``STARTUP_RECONCILIATION=enabled``.
A transactional deployment runs with it disabled — nothing writes to the
database while it starts — so a release that adds or changes a canonical Skill
has to reconcile the catalog explicitly. On the VM, through the deploy
launcher (the one-off ``agentium-migrate`` container, the release's image):

    agentium-vm-deploy.sh catalog-check   # read-only; exit 3 when the catalog is behind
    agentium-vm-deploy.sh catalog-apply   # writes only the rows that differ

Directly:

    python -m app.cli.reconcile_catalog [--apply]

The report is JSON on stdout (missing, changed with the fields named, and
orphaned rows per kind); a one-line verdict goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys

BEHIND = 3


def _verdict(report: dict) -> str:
    skills, capabilities = report["skills"], report["capabilities"]
    counts = (
        f"{len(skills['missing'])} skill(s) missing, {len(skills['changed'])} changed; "
        f"{len(capabilities['missing'])} capability(ies) missing, {len(capabilities['changed'])} changed"
    )
    orphans = len(skills["orphaned"]) + len(capabilities["orphaned"])
    tail = f"; {orphans} seeded row(s) no longer in code (kept)" if orphans else ""
    if report["applied"]:
        return f"catalog applied: {counts}{tail}"
    if report["in_sync"]:
        return f"catalog in sync with the code{tail}"
    return f"catalog BEHIND the code: {counts}{tail} — run catalog-apply"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the rows that differ")
    args = parser.parse_args(argv)

    from app.db.base import SessionLocal
    from app.services.skills_registry import reconcile_catalog

    with SessionLocal() as db:
        report = reconcile_catalog(db, apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    print(_verdict(report), file=sys.stderr)
    return 0 if report["in_sync"] else BEHIND


if __name__ == "__main__":
    sys.exit(main())
