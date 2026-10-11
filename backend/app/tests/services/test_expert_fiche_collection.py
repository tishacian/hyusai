from __future__ import annotations

from types import SimpleNamespace

from app.services.rag.knowledge_scopes import (
    EXPERT_FICHE_COLLECTION_FALLBACK,
    resolve_expert_fiche_collection,
)


def _workspace(slug):
    return SimpleNamespace(slug=slug)


def test_configured_slug_takes_precedence():
    workspace = _workspace("andritz")
    result = resolve_expert_fiche_collection(
        workspace, {"expert_fiche_collection": "andritz-validated-fiches"}
    )
    assert result == "andritz-validated-fiches"


def test_configured_slug_is_stripped_before_validation():
    workspace = _workspace("andritz")
    result = resolve_expert_fiche_collection(
        workspace, {"expert_fiche_collection": "  shared-capture-pub  "}
    )
    assert result == "shared-capture-pub"


def test_default_derived_from_workspace_slug():
    workspace = _workspace("andritz")
    result = resolve_expert_fiche_collection(workspace, {})
    assert result == "andritz-expert-fiche"


def test_invalid_configured_slug_falls_back_to_default():
    workspace = _workspace("andritz")
    result = resolve_expert_fiche_collection(
        workspace, {"expert_fiche_collection": "Invalid Slug!"}
    )
    assert result == "andritz-expert-fiche"


def test_empty_configured_slug_falls_back_to_default():
    workspace = _workspace("andritz")
    result = resolve_expert_fiche_collection(
        workspace, {"expert_fiche_collection": ""}
    )
    assert result == "andritz-expert-fiche"


def test_workspace_slug_is_sanitized():
    workspace = _workspace("Acme Corp!")
    result = resolve_expert_fiche_collection(workspace, None)
    assert result == "Acme-Corp--expert-fiche"


def test_mapping_workspace_is_supported():
    result = resolve_expert_fiche_collection({"slug": "andritz"}, None)
    assert result == "andritz-expert-fiche"


def test_missing_workspace_returns_constant_fallback():
    assert resolve_expert_fiche_collection(None, None) == EXPERT_FICHE_COLLECTION_FALLBACK
    assert resolve_expert_fiche_collection(None, None) == "expert-fiche"


def test_blank_workspace_slug_returns_constant_fallback():
    workspace = _workspace("")
    assert (
        resolve_expert_fiche_collection(workspace, {})
        == EXPERT_FICHE_COLLECTION_FALLBACK
    )


def test_garbage_workspace_slug_recovers_to_constant():
    workspace = _workspace("!!!")
    assert resolve_expert_fiche_collection(workspace, {}) == "expert-fiche"
