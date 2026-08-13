from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

from app.models.client360 import Client360DataSource, Client360Opportunity
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


def _spc_record(**overrides) -> dict:
    record = {
        "customer_name": "Karafiber Tekstil Sanayi Ve Ticaret",
        "customer_key": "karafiber tekstil",
        "country": "TR",
        "part_reference": "208125957",
        "part_description": "SLEEVE MPC100 EQUIPED LM3750 LG4040 D516 | L 4040 D 520 MM |",
        "installed_quantity": 3.0,
        "machine_label": "400443417",
        "technology": None,
        "role": "spc",
    }
    record.update(overrides)
    return record


def _seed_spc_source(
    db_session,
    workspace: Workspace,
    records: list[dict],
    *,
    filename: str = "Installed base - SPC.xlsx",
) -> Client360DataSource:
    source = Client360DataSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        source_type="installed_base",
        label=filename,
        filename=filename,
        status="ready",
        row_count=float(len(records)),
        meta_data={"role": "spc", "records": records},
        evidence_refs=[{"kind": "client360_spl_adapter", "origin_file": filename}],
    )
    db_session.add(source)
    db_session.flush()
    return source


_DEMO_PARK_RECORDS = [
    _spc_record(),  # Karafiber · TR · MPC100 · qty 3
    _spc_record(
        customer_name="Eruslu Nonwoven",
        customer_key="eruslu nonwoven",
        installed_quantity=2.0,
    ),  # same MPC reference at a second Turkish customer
    _spc_record(
        customer_name="Eruslu Nonwoven",
        customer_key="eruslu nonwoven",
        part_reference="208180630",
        part_description="SLEEVE MPC50 JETLACE ESSENTIEL",
        installed_quantity=4.0,
    ),
    _spc_record(
        part_reference="100004511",
        part_description="PLAIN WASHER ISO7089 | - 10 - 200HV |",
        installed_quantity=4816.0,
    ),  # most installed overall but not MPC
    _spc_record(
        customer_name="Septona S.A.",
        customer_key="septona",
        country="GR",
        installed_quantity=50.0,
    ),  # MPC but wrong country: must stay out of the Turkey aggregate
]


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


# ---------------------------------------------------------------------------
# Phase 3 — extended dedicated intents
# ---------------------------------------------------------------------------
def test_detect_intent_phase3_vocabulary() -> None:
    assert client360_chat._detect_intent("audite Eruslu") == "customer_audit"
    assert client360_chat._detect_intent("quelles pièces à prévoir chez Mogul ?") == "forecast"
    assert client360_chat._detect_intent("ouvre l'onglet client Septona") == "navigation"
    assert (
        client360_chat._detect_intent("pourquoi cette opportunité wear belts ?")
        == "opportunity_detail"
    )


def test_detect_intent_greeting_and_help() -> None:
    assert client360_chat._detect_intent("hello") == "help"
    assert client360_chat._detect_intent("Bonjour !") == "help"
    assert client360_chat._detect_intent("que peux-tu faire ?") == "help"
    # Help keywords stay subordinate to domain intents.
    assert client360_chat._detect_intent("aide-moi à auditer Septona") == "customer_audit"
    assert client360_chat._detect_intent("montre les opportunités Turquie") == "opportunities"


def test_handler_greeting_returns_help_without_sources(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query="hello", require_trigger=False
        )
    )
    assert result is not None
    assert result["intent"] == "help"
    assert result["sources"] == []
    assert result["evidence_refs"] == []
    assert "Assistant Client360" in result["content"]


def test_content_is_plain_text_and_sources_deduped(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    # Same customer/family/reference labels -> would previously emit twin sources.
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query="montre les opportunités PDR"
        )
    )
    assert result is not None
    assert "**" not in result["content"]
    titles = [src["title"] for src in result["sources"]]
    assert titles and len(titles) == len(set(titles))


def test_registry_customer_names_enrich_facets(db_session, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    monkeypatch.setattr(
        client360_chat,
        "_registry_customer_names",
        lambda db, ws: ["Eruslu", "Mogul"],
    )
    items = client360_pdr.list_opportunities(db_session, workspace, limit=500)
    facets = client360_chat._build_facets(db_session, workspace, items)
    assert facets["customer"][client360_chat._norm("Eruslu")] == "Eruslu"
    assert facets["customer"][client360_chat._norm("Mogul")] == "Mogul"
    filters = client360_chat._deterministic_filters("audite Eruslu", facets)
    assert filters.get("customer") == "Eruslu"


def test_handler_customer_audit_intent(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(
        db_session,
        workspace,
        data_gaps=["sap_sales_history_missing"],
        next_due_at=datetime(2026, 9, 1, 9, 0, 0),
    )
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="audite Septona",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "customer_audit"
    assert result["filters"].get("customer") == "Septona"
    assert "sap_sales_history_missing" in (result["result"].get("data_gaps") or [])
    assert result["result"].get("next_due")
    assert result["cta"]["route"] == client360_chat.CLIENT360_CTA_ROUTE
    assert result["cta"]["query_params"].get("customer") == "Septona"
    assert result["sources"]
    assert result["evidence_refs"]


def test_handler_forecast_stub_when_module_missing(db_session, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, next_due_at=datetime(2026, 8, 15, 9, 0, 0))
    monkeypatch.setattr(client360_chat, "_call_forecast_helper", lambda *a, **k: None)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="quelles pièces à prévoir chez Septona ?",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "forecast"
    assert result["result"].get("stub") is True
    assert "data gaps" in result["result"].get("message", "").lower() or result["result"].get(
        "data_gaps"
    ) is not None
    assert result["cta"]["query_params"].get("customer") == "Septona"
    assert result["sources"]


def test_handler_forecast_uses_helper_when_available(db_session, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    monkeypatch.setattr(
        client360_chat,
        "_call_forecast_helper",
        lambda *a, **k: {
            "items": [
                {
                    "customer_name": "Septona",
                    "part_family": "wear belts",
                    "part_reference": "PDR-001",
                    "next_due_at": "2026-10-01T00:00:00",
                    "evidence_refs": [{"kind": "forecast", "filename": "sales_orders.xlsx"}],
                }
            ]
        },
    )
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="forecast Septona wear belts",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "forecast"
    assert result["result"].get("stub") is not True
    assert result["result"]["items"][0]["next_due_at"].startswith("2026-10-01")
    assert result["evidence_refs"]


def test_handler_forecast_uses_real_forecast_module(db_session) -> None:
    """No monkeypatch: the chat bridge must reach client360_forecast.customer_next_due."""
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace, next_due_at=datetime(2026, 8, 15, 9, 0, 0))
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="quelles pièces à prévoir chez Septona ?",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "forecast"
    assert result["result"].get("stub") is not True
    items = result["result"]["items"]
    assert items and str(items[0]["next_due_at"]).startswith("2026-08-15")
    assert "indisponible" not in result["content"]


def test_translation_merges_deterministic_when_llm_omits_customer(db_session, monkeypatch) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)

    async def llm_returns_empty(db, ws, query, facets):
        return {}

    monkeypatch.setattr(client360_chat, "_llm_filters", llm_returns_empty)
    items = client360_pdr.list_opportunities(db_session, workspace, limit=10)
    filters, method = _run(
        client360_chat.translate_query_to_filters(db_session, workspace, "audite Septona", items)
    )
    assert method == "llm"
    assert filters.get("customer") == "Septona"


def test_handler_navigation_intent_attaches_cta(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="ouvre l'onglet fiche client Septona",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "navigation"
    assert result["cta"]["route"] == client360_chat.CLIENT360_CTA_ROUTE
    assert result["cta"]["query_params"].get("view") == "customer"
    assert result["cta"]["query_params"].get("customer") == "Septona"


def test_handler_opportunity_detail_explains_formula(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(
        db_session,
        workspace,
        installed_quantity=10,
        recommended_quantity=2,
        periodicity_weeks=4,
        sales_known_qty=8,
        annual_theoretical_qty=260.0,
        potential_gap_qty=252.0,
        potential_gap_value=37800.0,
        evidence_refs=[
            {"kind": "source", "filename": "SEPTONA - Client 360.xlsx", "row": 12}
        ],
    )
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="pourquoi cette opportunité wear belts Septona ?",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "opportunity_detail"
    formula = result["result"]["formula"]
    assert "installed_quantity" in formula["annual_theoretical_qty"]
    assert "sales_known_qty" in formula["potential_gap_qty"]
    assert formula["plan_shorthand"] == "installed × recommended × 52/periodicity − sales"
    assert "besoin_annuel" in result["content"]
    assert "SEPTONA - Client 360.xlsx" in result["content"]
    assert result["evidence_refs"]
    assert result["cta"]["query_params"].get("customer") == "Septona"


def test_phase3_intents_remain_filter_bounded(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_opportunity(db_session, workspace)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="audite Septona; DROP TABLE opportunities; evil=1",
            require_trigger=False,
        )
    )
    assert result is not None
    assert set(result["filters"].keys()) <= set(client360_chat._ALLOWED_FILTER_KEYS)
    assert "evil" not in result["filters"]


# ---------------------------------------------------------------------------
# Installed base (SPC park) intent
# ---------------------------------------------------------------------------
_DEMO_QUESTION = "quelle est la référence MPC la plus installée chez nos clients en turquie ?"


def test_detect_intent_installed_base() -> None:
    assert client360_chat._detect_intent(_DEMO_QUESTION) == "installed_base"
    assert client360_chat._detect_intent("top références du parc installé") == "installed_base"
    assert (
        client360_chat._detect_intent("most installed MPC reference for Turkish customers")
        == "installed_base"
    )
    # The park intent also passes the research-chat trigger guard.
    assert client360_chat.is_client360_query(_DEMO_QUESTION)
    # Neighbouring intents keep their routing.
    assert client360_chat._detect_intent("montre la fiche client de Septona") == "customer"
    assert client360_chat._detect_intent("ouvre l'onglet parc installé") == "navigation"
    assert client360_chat._detect_intent("montre les opportunités Turquie") == "opportunities"


def test_installed_base_part_filter_extraction() -> None:
    records = [
        {"customer_name": "Karafiber Tekstil Sanayi Ve Ticaret", "country": "TR", "technology": "Spunlace"}
    ]
    assert client360_chat._installed_base_part_filter(_DEMO_QUESTION, records) == "MPC"
    assert (
        client360_chat._installed_base_part_filter("référence 208180630 la plus installée", records)
        == "208180630"
    )
    # Facet values (country, customer, technology) and question words never
    # become free-text part filters.
    assert client360_chat._installed_base_part_filter("parc installé EN TURQUIE", records) is None
    assert (
        client360_chat._installed_base_part_filter("top références les plus installées", records)
        is None
    )
    assert (
        client360_chat._installed_base_part_filter("parc installé de KARAFIBER TEKSTIL", records)
        is None
    )


def test_build_facets_extra_values_and_country_aliases(db_session) -> None:
    workspace = _seed_workspace(db_session)
    facets = client360_chat._build_facets(
        db_session,
        workspace,
        [],
        extra_facet_values={"country": ["TR"], "customer": ["Karafiber Tekstil"]},
    )
    assert facets["country"]["tr"] == "TR"
    assert facets["country"]["turquie"] == "TR"
    assert facets["customer"][client360_chat._norm("Karafiber Tekstil")] == "Karafiber Tekstil"
    filters = client360_chat._deterministic_filters("parc installé en turquie", facets)
    assert filters["country"] == "TR"
    # Short country codes only match as whole words ("montre" must not yield TR).
    assert "country" not in client360_chat._deterministic_filters("montre le parc installé", facets)


def test_handler_installed_base_aggregates_turkey_park(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_spc_source(db_session, workspace, _DEMO_PARK_RECORDS)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session, workspace, None, query=_DEMO_QUESTION, require_trigger=False
        )
    )
    assert result is not None
    assert result["intent"] == "installed_base"
    # « en turquie » resolved against the park countries (code "TR").
    assert result["filters"].get("country") == "TR"

    content = result["content"]
    assert "**" not in content  # plain text contract
    assert "parc installé" in content
    assert "pays=TR" in content and "filtre=MPC" in content
    assert "2 référence(s)" in content
    assert "9 unité(s)" in content
    assert "2 client(s)" in content
    # Top reference first: MPC100 (3+2 units across two Turkish customers).
    assert content.index("208125957") < content.index("208180630")

    rows = result["result"]["installed_base"]
    assert rows[0]["part_reference"] == "208125957"
    assert rows[0]["installed_quantity"] == 5.0
    assert rows[0]["customer_count"] == 2
    assert result["result"]["count"] == 2
    assert result["result"]["total_installed_quantity"] == 9.0
    assert result["result"]["customer_count"] == 2
    assert result["result"]["filters"] == {"country": "TR", "part_filter": "MPC"}

    assert [src["title"] for src in result["sources"]] == ["Installed base - SPC.xlsx"]
    assert result["sources"][0]["kind"] == "client360_data_source"
    assert result["evidence_refs"] == [
        {"kind": "client360_spl_adapter", "origin_file": "Installed base - SPC.xlsx"}
    ]
    assert result["cta"]["route"] == client360_chat.CLIENT360_CTA_ROUTE
    assert result["cta"]["query_params"] == {"view": "customer", "country": "TR"}


def test_handler_installed_base_dedupes_duplicate_sources(db_session) -> None:
    """The same SPC file registered twice (with/without folder prefix) must not
    double the installed quantities."""
    workspace = _seed_workspace(db_session)
    _seed_spc_source(db_session, workspace, _DEMO_PARK_RECORDS)
    _seed_spc_source(
        db_session,
        workspace,
        _DEMO_PARK_RECORDS,
        filename="Installed_base_SPL__Installed base - SPC.xlsx",
    )
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="top références du parc installé en turquie",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "installed_base"
    assert result["result"]["count"] == 3
    assert result["result"]["total_installed_quantity"] == 4825.0
    rows = result["result"]["installed_base"]
    assert rows[0]["part_reference"] == "100004511"
    assert rows[0]["installed_quantity"] == 4816.0  # not 9632
    assert len(result["sources"]) == 1  # only the contributing file is cited


def test_handler_installed_base_empty_filter_is_honest(db_session) -> None:
    workspace = _seed_workspace(db_session)
    _seed_spc_source(db_session, workspace, _DEMO_PARK_RECORDS)
    result = _run(
        client360_chat.handle_client360_chat_query(
            db_session,
            workspace,
            None,
            query="quelle est la référence XQZ9 la plus installée chez nos clients en turquie ?",
            require_trigger=False,
        )
    )
    assert result is not None
    assert result["intent"] == "installed_base"
    assert "aucune référence trouvée pour ce filtre" in result["content"]
    assert "Filtres compris" in result["content"]
    assert "filtre=XQZ9" in result["content"]
    assert result["sources"] == []
    assert result["evidence_refs"] == []
    assert result["result"]["installed_base"] == []


def test_help_mentions_installed_base_example() -> None:
    content = client360_chat._help_response()["content"]
    assert "la plus installée" in content
