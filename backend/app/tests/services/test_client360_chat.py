from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

from app.models.client360 import Client360Opportunity
from app.models.workspace import Workspace
from app.services import client360_chat, client360_pdr
from app.services.actions.registry import ANDRITZ_ACTIONS


def _seed_workspace(
    db_session,
    *,
    slug: str = "andritz",
    family: str | None = "andritz",
) -> Workspace:
    settings = {"family": family} if family is not None else {}
    workspace = Workspace(id=str(uuid4()), name=slug.title(), slug=slug, settings=settings)
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _seed_opportunity(db_session, workspace: Workspace, **overrides) -> Client360Opportunity:
    payload = {
        "id": str(uuid4()),
        "workspace_id": workspace.id,
        "customer_key": "septona",
        "customer_name": "Septona",
        "site_name": "Oinofyta",
        "country": "Greece",
        "hub": "EMEA",
        "technology": "Nonwoven",
        "line_label": "Line 1",
        "machine_label": "Needlepunch",
        "part_family": "wear belts",
        "part_reference": "PDR-001",
        "installed_quantity": 10,
        "recommended_quantity": 2,
        "periodicity_weeks": 4,
        "delivery_time_weeks": 6,
        "sales_known_qty": 8,
        "sales_known_value": 1200,
        "next_due_at": datetime(2026, 8, 15, 9, 0, 0),
        "evidence_refs": [{"kind": "source", "filename": "SEPTONA - Client 360.xlsx"}],
        "source_ids": ["source-1"],
        "status": "detected",
    }
    payload.update(overrides)
    opportunity = Client360Opportunity(**payload)
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Decoupling from the general research chat
# ---------------------------------------------------------------------------
def test_not_registered_in_research_chat_actions() -> None:
    """The Client360 assistant is dedicated to the Client360 app; it must NOT be
    wired into the general Andritz research-chat action registry (otherwise the
    research chat would redirect Client360-sounding questions)."""
    manifest = next(
        (m for m in ANDRITZ_ACTIONS if m.action_id == client360_chat.CLIENT360_NL_ACTION_ID), None
    )
    assert manifest is None


def test_dedicated_surface_answers_without_trigger(db_session) -> None:
    """On the dedicated endpoint (require_trigger=False) any question is answered
    within the Client360 domain, even without a Client360 keyword."""
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query="donne-moi un aperçu", require_trigger=False
        )
    )
    assert result is not None
    assert result["action"] == "client360_nl_query"


# ---------------------------------------------------------------------------
# Workspace guard
# ---------------------------------------------------------------------------
def test_guard_blocks_non_andritz_workspace(db_session) -> None:
    workspace = _seed_workspace(db_session, slug="octocity", family="generic")
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query="montre les opportunités PDR"
        )
    )
    assert result is None


def test_guard_uses_canonical_family_not_slug(db_session) -> None:
    legacy_slug = _seed_workspace(db_session, slug="andritz", family=None)
    configured = _seed_workspace(db_session, slug="industrial-client360", family="andritz")
    _seed_opportunity(db_session, legacy_slug)
    _seed_opportunity(db_session, configured)

    blocked = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            legacy_slug,
            None,
            query="montre les opportunités PDR",
        )
    )
    allowed = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            configured,
            None,
            query="montre les opportunités PDR",
        )
    )

    assert blocked is None
    assert allowed is not None


def test_non_client360_query_returns_none(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query="Quelle est la météo à Graz aujourd'hui ?"
        )
    )
    assert result is None


# ---------------------------------------------------------------------------
# Bounded deterministic translation
# ---------------------------------------------------------------------------
def test_deterministic_translation_is_bounded(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, status="won")
    items = client360_pdr.list_opportunities(db_session, workspace, limit=500)
    filters = client360_chat._deterministic_filters(
        "montre les opportunités gagnées à haute confiance en Greece; DROP TABLE opportunities",
        client360_chat._facets(items),
    )
    assert filters == {"status": "won", "confidence": "high", "country": "Greece"}


def test_deterministic_translation_parses_top_n(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    items = client360_pdr.list_opportunities(db_session, workspace, limit=500)
    filters = client360_chat._deterministic_filters(
        "top 3 opportunités", client360_chat._facets(items)
    )
    assert filters["limit"] == 3


def test_sanitize_drops_unknown_keys_and_out_of_vocab_values(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    facets = client360_chat._facets(
        client360_pdr.list_opportunities(db_session, workspace, limit=500)
    )
    sanitized = client360_chat._sanitize_filters(
        {
            "status": "won'; DROP TABLE opportunities;--",
            "country": "Atlantis",
            "confidence": "super",
            "evil_key": "value",
            "limit": 9999,
            "customer": "  Septona  ",
        },
        facets,
    )
    # Only allow-listed, vocab-valid entries survive; limit is clamped.
    assert set(sanitized.keys()) <= set(client360_chat._ALLOWED_FILTER_KEYS)
    assert "evil_key" not in sanitized
    assert "status" not in sanitized  # bogus status dropped
    assert "country" not in sanitized  # unknown country dropped
    assert "confidence" not in sanitized  # invalid confidence dropped
    assert sanitized["limit"] == client360_chat._MAX_LIMIT
    assert sanitized["customer"] == "Septona"


def test_sanitize_remaps_country_to_canonical(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, country="Greece")
    facets = client360_chat._facets(
        client360_pdr.list_opportunities(db_session, workspace, limit=500)
    )
    sanitized = client360_chat._sanitize_filters({"country": "greece"}, facets)
    assert sanitized["country"] == "Greece"


# ---------------------------------------------------------------------------
# Bounded LLM translation
# ---------------------------------------------------------------------------
def test_llm_translation_is_bounded(db_session, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, status="won")

    monkeypatch.setattr(client360_chat, "_mail_ai_configured", lambda cfg: (True, None))
    monkeypatch.setattr(
        client360_chat,
        "_client360_mail_ai_config",
        lambda db, ws: {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 5.0},
    )

    class _FakeLLM:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def complete(self, **kwargs) -> str:
            # Out-of-vocab country, injected extra key + free-text SQL, valid
            # status/confidence. Only the valid, allow-listed pair may survive.
            return (
                '{"country": "Atlantis", "status": "won", "confidence": "high", '
                '"evil": "1", "note": "DROP TABLE opportunities"}'
            )

    monkeypatch.setattr("app.llm.llm.LLM", _FakeLLM)

    items = client360_pdr.list_opportunities(db_session, workspace, limit=500)
    filters, method = _run(
        client360_chat.translate_query_to_filters(
            db_session, workspace, "opportunités gagnées", items
        )
    )
    assert method == "llm"
    assert filters == {"status": "won", "confidence": "high"}


# ---------------------------------------------------------------------------
# End-to-end handler: evidence_refs preserved + CTA
# ---------------------------------------------------------------------------
def test_handler_preserves_evidence_refs_and_attaches_cta(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, confidence_label="high", confidence_score=0.9)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query="montre les opportunités PDR haute confiance"
        )
    )
    assert result is not None
    assert result["action"] == "client360_nl_query"
    assert result["intent"] == "opportunities"
    assert result["action_manifest_id"] == client360_chat.CLIENT360_NL_ACTION_ID
    # evidence_refs preserved at the top level and on each source.
    assert {"kind": "source", "filename": "SEPTONA - Client 360.xlsx"} in result["evidence_refs"]
    assert result["sources"]
    assert result["sources"][0]["evidence_refs"] == [
        {"kind": "source", "filename": "SEPTONA - Client 360.xlsx"}
    ]
    # CTA routes to Client360, no auto-navigate effect.
    assert result["cta"]["route"] == client360_chat.CLIENT360_CTA_ROUTE
    assert result["action_effects"] == []
    # Confidence filter was translated and applied.
    assert result["filters"].get("confidence") == "high"


def test_handler_customer_intent_uses_customer_payload(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query="montre la fiche client de Septona"
        )
    )
    assert result is not None
    assert result["intent"] == "customer"
    assert result["filters"].get("customer") == "Septona"
    assert result["cta"]["query_params"].get("customer") == "Septona"
