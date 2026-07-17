"""Ensure the Andritz Client360 installed-base knowledge collection exists.

Usage:
    cd backend
    python -m scripts.setup_andritz_client360_collection --workspace andritz

Idempotent. Does not promote deposit files or run the SPL adapter.
"""

from __future__ import annotations

import argparse
import json

from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.services.client360_contract import (
    CLIENT360_INSTALLED_BASE_COLLECTION_NAME,
    CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
)
from app.services.knowledge_collections import create_or_get_collection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz", help="Workspace slug")
    parser.add_argument(
        "--collection",
        default=CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
        help="Collection slug",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        collection = create_or_get_collection(
            db,
            workspace=workspace,
            name=CLIENT360_INSTALLED_BASE_COLLECTION_NAME,
            description=(
                "Unified Client360 vault: Installed_base_SPL (Machine/SPC/Family/"
                "Sales/Materials) + pilot Septona/Turquie spreadsheets. "
                "Structured engine input is Client360DataSource via the SPL adapter."
            ),
            slug=args.collection,
        )
        db.commit()
        print(
            json.dumps(
                {
                    "ok": True,
                    "workspace": workspace.slug,
                    "collection_id": collection.id,
                    "collection_slug": collection.slug,
                    "status": collection.status,
                    "document_count": collection.document_count,
                },
                ensure_ascii=False,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
