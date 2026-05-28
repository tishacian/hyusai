"""Seed the Andritz SPL notices pilot collection, scope and guide.

Usage:
    cd backend
    python -m scripts.setup_andritz_notices_spl --workspace andritz

The script is intentionally idempotent. It creates collection metadata and the
Knowledge Scope/Guide wiring, but it does not promote SFTP files by itself.
Promotion stays an explicit operator action from the Secure Deposit queue.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_guide import KnowledgeGuide
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_or_get_collection
from app.services.knowledge_guides import create_guide, update_guide
from app.services.rag.knowledge_scopes import normalize_knowledge_scopes


DEFAULT_COLLECTION = "andritz-notices-techniques-spl-pilot"
DEFAULT_SCOPE = "andritz-spl-knowledge-experiment"
GUIDE_TITLE = "ANDRITZ Notices Techniques SPL - Knowledge Guide"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _guide_markdown() -> str:
    return (_repo_root() / "docs" / "andritz-notices-techniques-spl-knowledge-guide.md").read_text(encoding="utf-8")


def _collection_exists(db, workspace: Workspace, slug: str) -> bool:
    return bool(
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug)
        .first()
    )


def _upsert_scope(db, workspace: Workspace, *, scope_key: str, collection_slug: str) -> None:
    settings = dict(workspace.settings or {})
    scopes = normalize_knowledge_scopes(settings.get("knowledge_scopes"))
    candidate_slugs = [
        "andritz-manuals-bba120-pilot",
        collection_slug,
        "andritz-non-wovens-france-excel-pilot",
    ]
    collection_slugs = [slug for slug in candidate_slugs if _collection_exists(db, workspace, slug)]
    if collection_slug not in collection_slugs:
        collection_slugs.append(collection_slug)

    next_scope = {
        "key": scope_key,
        "label": "Andritz SPL knowledge experiment",
        "description": "Combines BBA120 project notices, SPL technical notices and optional SPL Excel trials.",
        "collection_slugs": collection_slugs,
        "default_mode": "chah",
        "top_k": 6,
        "is_default": False,
    }
    scopes = [scope for scope in scopes if scope["key"] != scope_key]
    scopes.append(next_scope)
    settings["knowledge_scopes"] = scopes
    workspace.settings = settings
    db.add(workspace)


def _publish_guide(db, workspace: Workspace, *, collection_slug: str, actor: str | None) -> str:
    markdown = _guide_markdown()
    user = SimpleNamespace(id=None, email=actor, username=actor)
    existing = (
        db.query(KnowledgeGuide)
        .filter(
            KnowledgeGuide.workspace_id == workspace.id,
            KnowledgeGuide.target_type == "collection",
            KnowledgeGuide.target_ref == collection_slug,
            KnowledgeGuide.title == GUIDE_TITLE,
            KnowledgeGuide.is_current.is_(True),
        )
        .first()
    )
    if existing:
        guide = update_guide(
            db,
            workspace,
            existing.guide_key,
            patch={"markdown": markdown, "status": "published"},
            user=user,
        )
        return guide.guide_key
    guide = create_guide(
        db,
        workspace,
        target_type="collection",
        target_ref=collection_slug,
        title=GUIDE_TITLE,
        markdown=markdown,
        status="published",
        user=user,
    )
    return guide.guide_key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz", help="Workspace slug")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Pilot collection slug")
    parser.add_argument("--scope", default=DEFAULT_SCOPE, help="Knowledge Scope key")
    parser.add_argument("--actor", default="system:andritz-spl-setup", help="Audit actor label")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if not workspace:
            raise SystemExit(f"Workspace not found: {args.workspace}")

        collection = create_or_get_collection(
            db,
            workspace=workspace,
            name="Andritz Notices Techniques SPL Pilot",
            description="Pilot collection for SPL technical notices from Secure Deposit SFTP.",
            slug=args.collection,
        )
        _upsert_scope(db, workspace, scope_key=args.scope, collection_slug=collection.slug)
        db.commit()
        guide_key = _publish_guide(db, workspace, collection_slug=collection.slug, actor=args.actor)
        print(
            "andritz_spl_setup ok "
            f"workspace={workspace.slug} collection={collection.slug} scope={args.scope} guide={guide_key}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
