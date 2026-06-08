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
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.orm.attributes import flag_modified

from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_guide import KnowledgeGuide
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_or_get_collection
from app.services.knowledge_guides import create_guide, update_guide
from app.services.rag.knowledge_scopes import normalize_knowledge_scopes
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.systems.bootstrap import ensure_workspace_chat_system_default


DEFAULT_COLLECTION = "andritz-notices-techniques-spl-pilot"
DEFAULT_SCOPE = "andritz-spl-knowledge-experiment"
GUIDE_TITLE = "ANDRITZ Notices Techniques SPL - Knowledge Guide"
ANDRITZ_SPL_ADVISOR_PROFILE = "andritz_spl_advisor"
ANDRITZ_BALANCED_GROUNDING = {
    "default_mode": "balanced",
    "allowed_modes": ["strict", "balanced"],
    "fallback_disclaimer": (
        "Interprétation métier à valider : les sources Andritz restent prioritaires "
        "et toute valeur documentaire doit être vérifiée dans les notices."
    ),
    "strict_guard": "business_interpretation",
}
ANDRITZ_WORKSPACE_GROUNDING = {
    "default_mode": "strict",
    "allowed_modes": ["strict", "balanced"],
    "fallback_disclaimer": ANDRITZ_BALANCED_GROUNDING["fallback_disclaimer"],
    "strict_guard": "business_interpretation",
}
# Andritz runs voice in Conversation mode by default: a continuous streaming
# loop with the tandem oracle following the speech live, auto-submitting the
# final transcript, and re-arming the microphone after each answer.
ANDRITZ_VOICE_LOOP = {
    "default_mode": "session_loop",
    "enabled_default": True,
    "auto_endpoint": True,
    "auto_send_final_transcript": True,
    "auto_rearm_after_tts": True,
    "barge_in": True,
    "commands_enabled": True,
}


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


def _as_dict(value) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _profile_defaults(scope_key: str) -> dict:
    return {
        "key": ANDRITZ_SPL_ADVISOR_PROFILE,
        "label": "Andritz SPL Advisor",
        "subtitle": "Notices SPL + essais non-wovens · sources préférées",
        "default_knowledge_scope": scope_key,
        "executive_mode": False,
        "tone": "technical_advisor",
        "prompt_pack": [
            "andritz_project_reference_grammar",
            "andritz_spl_notices",
            "andritz_non_wovens_excel",
        ],
        "grounding": dict(ANDRITZ_BALANCED_GROUNDING),
    }


def _merge_profile(existing: dict, defaults: dict) -> dict:
    merged = {**defaults, **existing}
    merged["grounding"] = {**dict(ANDRITZ_BALANCED_GROUNDING), **_as_dict(existing.get("grounding"))}
    if defaults["key"] == ANDRITZ_SPL_ADVISOR_PROFILE:
        merged["default_knowledge_scope"] = defaults["default_knowledge_scope"]
    return merged


def _upsert_chat_profiles(workspace: Workspace, *, scope_key: str, make_default: bool) -> None:
    settings = dict(workspace.settings or {})
    chat = _as_dict(settings.get("chat"))
    chat["grounding"] = {**ANDRITZ_WORKSPACE_GROUNDING, **_as_dict(chat.get("grounding"))}
    settings["chat"] = chat

    # Default the workspace voice surface to Conversation while preserving any
    # operator-tuned thresholds (silence_ms, rms_threshold, ...) already set.
    voice_loop = {**ANDRITZ_VOICE_LOOP, **_as_dict(settings.get("voice_loop"))}
    voice_loop["default_mode"] = "session_loop"
    voice_loop["enabled_default"] = True
    settings["voice_loop"] = voice_loop

    raw_profiles = settings.get("assistant_profiles")
    profiles = [dict(profile) for profile in raw_profiles if isinstance(profile, Mapping)] if isinstance(raw_profiles, list) else []
    next_profiles: list[dict] = []
    seen_spl_profile = False

    for profile in profiles:
        key = str(profile.get("key") or "")
        if key == ANDRITZ_SPL_ADVISOR_PROFILE:
            next_profiles.append(_merge_profile(profile, _profile_defaults(scope_key)))
            seen_spl_profile = True
            continue
        if key == "andritz_non_wovens_excel":
            profile = dict(profile)
            profile["grounding"] = {**dict(ANDRITZ_BALANCED_GROUNDING), **_as_dict(profile.get("grounding"))}
        next_profiles.append(profile)

    if not seen_spl_profile:
        next_profiles.append(_profile_defaults(scope_key))

    settings["assistant_profiles"] = next_profiles
    if make_default:
        settings["assistant_profile_default"] = ANDRITZ_SPL_ADVISOR_PROFILE

    workspace.settings = settings
    flag_modified(workspace, "settings")


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
        "label": "Contexte Andritz SPL",
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
    parser.add_argument(
        "--keep-default-profile",
        action="store_true",
        help="Upsert the SPL advisor profile without making it the workspace default.",
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
            name="Andritz Notices Techniques SPL Pilot",
            description="Pilot collection for SPL technical notices from Secure Deposit SFTP.",
            slug=args.collection,
        )
        _upsert_scope(db, workspace, scope_key=args.scope, collection_slug=collection.slug)
        _upsert_chat_profiles(workspace, scope_key=args.scope, make_default=not args.keep_default_profile)
        db.commit()
        seed_skills_and_capabilities(db)
        workspace_chat = ensure_workspace_chat_system_default(db, workspace.id)
        guide_key = _publish_guide(db, workspace, collection_slug=collection.slug, actor=args.actor)
        print(
            "andritz_spl_setup ok "
            f"workspace={workspace.slug} collection={collection.slug} scope={args.scope} "
            f"profile={ANDRITZ_SPL_ADVISOR_PROFILE} "
            f"workspace_chat_system={workspace_chat.id if workspace_chat else 'skipped'} "
            f"guide={guide_key}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
