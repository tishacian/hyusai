"""Unit tests for the provider-neutral chat-agentic skills.

Covers the three skills that back the ``andritz_chat_agentic_v3`` DAG:
``chat_agentic_plan_v1``, ``chat_self_correct_v1`` and ``response_eval_v1``.
The LLM skills are exercised with a fake ``ModelRouter`` (never a real
provider client) and ``response_eval_v1`` with a fake ``ResponseEvaluator``
so the tests assert the FROZEN output shapes (docs/chat-agentic-thinking-spec
§7) plus the planner's JSON-parse fallback — without any network/model call.
"""
from __future__ import annotations

import pytest

from app.services.skills_registry import wrappers
from app.services.skills_registry.seed import SEED_SKILLS


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _FakeClient:
    def __init__(self, completion: str):
        self._completion = completion

    async def generate(self, model: str, prompt: str):
        _FakeClient.last_model = model
        _FakeClient.last_prompt = prompt
        return {"content": self._completion}


def _install_fake_router(monkeypatch, completion: str) -> dict:
    """Patch ModelRouter so the skill resolves a fake client (provider-neutral).

    Returns a dict that records the resolved ``preferences`` so a test can
    assert the model/provider routing without a real provider.
    """
    recorded: dict = {}

    class _FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        async def get_client(self, preferences):
            recorded["preferences"] = preferences
            return _FakeClient(completion)

    monkeypatch.setattr("app.services.model_router.ModelRouter", _FakeRouter)
    return recorded


class _FakeEvaluator:
    def __init__(self, metrics: dict):
        self._metrics = metrics

    async def evaluate(self, query: str, response: str, source_chunks):
        _FakeEvaluator.last = {"query": query, "response": response, "source_chunks": source_chunks}
        return self._metrics


# ---------------------------------------------------------------------------
# Pure helper: provider-neutral model resolution
# ---------------------------------------------------------------------------
def test_resolve_model_preferences_is_provider_neutral():
    assert wrappers._resolve_model_preferences("gpt-4o-mini") == {"provider": "openai", "model": "gpt-4o-mini"}
    assert wrappers._resolve_model_preferences("ollama:deepseek-r1:14b") == {
        "provider": "ollama",
        "model": "deepseek-r1:14b",
    }
    assert wrappers._resolve_model_preferences("openai/gpt-4o") == {"provider": "openai", "model": "gpt-4o"}
    # Azure is OpenAI-compatible -> collapses to the openai client.
    assert wrappers._resolve_model_preferences("azure:gpt-4o-mini")["provider"] == "openai"


def test_lenient_json_tolerates_fences_and_prose():
    parsed = wrappers._loads_lenient_json('Voici le plan:\n```json\n{"action": "answer",}\n```\nmerci')
    assert parsed == {"action": "answer"}
    assert wrappers._loads_lenient_json("pas de json ici") is None


# ---------------------------------------------------------------------------
# chat_agentic_plan_v1
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_plan_emits_frozen_contract(monkeypatch):
    completion = (
        '```json\n{"action":"answer","mode":"deep","answer_profile":"technical",'
        '"scope_hint":"ACJ100","clarifying_question":"","oos_reason":"","lang_target":"fr",'
        '"confidence":0.82,"retrieval":{"latency_profile":"deep","retrieval_profile":"deep_async",'
        '"top_k":12,"rag_pipeline_mode":"chah","deep_retrieval":true}}\n```'
    )
    recorded = _install_fake_router(monkeypatch, completion)

    out = await wrappers._chat_agentic_plan_v1(
        {"query": "Compare les notices ACJ100 et ACJ200", "model": "gpt-4o-mini"},
        {"workspace_id": "ws-1"},
    )

    # Provider-neutral resolution actually happened through ModelRouter.
    assert recorded["preferences"] == {"provider": "openai", "model": "gpt-4o-mini"}

    assert set(out) == {
        "action", "mode", "answer_profile", "scope_hint", "clarifying_question",
        "oos_reason", "lang_target", "confidence", "retrieval", "sub_queries",
    }
    # sub_queries port is always present (Phase 4 multi-hop); a list, empty
    # unless the profile is comparison/multi_hop/transversal.
    assert isinstance(out["sub_queries"], list)
    assert out["action"] == "answer"
    assert out["mode"] == "deep"
    assert out["scope_hint"] == "ACJ100"
    assert out["confidence"] == 0.82
    assert set(out["retrieval"]) == {
        "latency_profile", "retrieval_profile", "top_k", "synthesis_k",
        "candidate_pool_k", "rag_pipeline_mode", "deep_retrieval",
    }
    assert out["retrieval"]["deep_retrieval"] is True
    assert out["retrieval"]["top_k"] == 12
    # Recall-parity: the plan exposes the full deep budget triple (8/24/80).
    assert out["retrieval"]["synthesis_k"] == 24
    assert out["retrieval"]["candidate_pool_k"] == 80


@pytest.mark.asyncio
async def test_plan_json_parse_fallback_to_safe_defaults(monkeypatch):
    # Model returns garbage / refuses JSON -> safe defaults, never crashes.
    _install_fake_router(monkeypatch, "Je ne peux pas repondre en JSON, desole.")

    out = await wrappers._chat_agentic_plan_v1({"query": "bonjour"}, {})

    assert out["action"] == "answer"
    assert out["mode"] == "balanced"
    # The retrieval object is always present and coherent with the mode.
    assert out["retrieval"]["latency_profile"] == "balanced"
    assert out["retrieval"]["deep_retrieval"] is False
    assert isinstance(out["retrieval"]["top_k"], int)


@pytest.mark.asyncio
async def test_plan_coerces_invalid_enums(monkeypatch):
    _install_fake_router(monkeypatch, '{"action":"explode","mode":"turbo","confidence":"high"}')

    out = await wrappers._chat_agentic_plan_v1({"query": "x"}, {})

    assert out["action"] == "answer"  # invalid -> default
    assert out["mode"] == "balanced"  # invalid -> default
    assert out["confidence"] == 0.6  # unparseable -> default


@pytest.mark.asyncio
async def test_plan_survives_model_exception(monkeypatch):
    class _BoomRouter:
        def __init__(self, *a, **k):
            pass

        async def get_client(self, preferences):
            raise RuntimeError("no provider available")

    monkeypatch.setattr("app.services.model_router.ModelRouter", _BoomRouter)

    out = await wrappers._chat_agentic_plan_v1({"query": "x"}, {})
    assert out["action"] == "answer"
    assert out["mode"] == "balanced"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_profile", "expected_scope", "expected_mode"),
    [
        ("quelles sont les pompes du projet BCX200", "equipment_detail", "BCX200", "balanced"),
        ("liste toutes les pompes du projet BCX200", "equipment_detail", "BCX200", "balanced"),
        ("résume BAO100", "project_summary", "BAO100", "balanced"),
        ("quelle est la pression du projet BCX200 ?", "precise_fact", "BCX200", "balanced"),
    ],
)
async def test_plan_shortcuts_simple_single_project_lookup_without_llm(
    monkeypatch, query, expected_profile, expected_scope, expected_mode
):
    """A simple mono-project chat turn is routed without the planner LLM.

    This is an end-to-end latency guard: the old planner spent six seconds
    before routing the BCX200 inventory and exhausted the 40 s interactive
    budget. The deterministic route uses the bounded mono-project evidence
    floor with 18 synthesis slots; summaries use the standard balanced lane.
    """

    async def _unexpected_model_call(*args, **kwargs):
        raise AssertionError(
            "the deterministic single-project lane must not call the planner LLM"
        )

    monkeypatch.setattr(wrappers, "_route_llm_complete", _unexpected_model_call)

    out = await wrappers._chat_agentic_plan_v1(
        {"query": query, "model": "gpt-4o-mini"},
        {"input": {"response_language": "fr"}},
    )

    assert out["action"] == "answer"
    assert out["mode"] == expected_mode
    assert out["answer_profile"] == expected_profile
    assert out["scope_hint"] == expected_scope
    assert out["lang_target"] == "fr"
    assert out["confidence"] == 1.0
    assert out["sub_queries"] == []
    expected_retrieval = (
        wrappers._SINGLE_PROJECT_INVENTORY_RETRIEVAL
        if expected_profile == "equipment_detail"
        else wrappers._RETRIEVAL_BY_MODE[expected_mode]
    )
    assert out["retrieval"] == expected_retrieval


@pytest.mark.asyncio
async def test_plan_shortcut_uses_server_run_language_not_payload_override(monkeypatch):
    async def _unexpected_model_call(*args, **kwargs):
        raise AssertionError("simple project summaries must not call the planner LLM")

    monkeypatch.setattr(wrappers, "_route_llm_complete", _unexpected_model_call)

    out = await wrappers._chat_agentic_plan_v1(
        {"query": "résume BAO100", "response_language": "en"},
        {"input": {"response_language": "fr"}},
    )

    assert out["lang_target"] == "fr"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Analyse en profondeur BCX200",
        "Welche Pumpen hat Projekt BCX200?",
        "Compare les pompes BCX200 avec les pompes KSB",
        "donne les précautions de maintenance des pompes BCX200",
    ],
)
async def test_plan_keeps_complex_or_german_single_project_queries_on_llm(monkeypatch, query):
    recorded = _install_fake_router(
        monkeypatch,
        '{"action":"answer","mode":"deep","answer_profile":"technical","lang_target":"fr"}',
    )

    out = await wrappers._chat_agentic_plan_v1(
        {"query": query, "model": "gpt-4o-mini"},
        {"input": {"response_language": "fr"}},
    )

    assert recorded["preferences"] == {"provider": "openai", "model": "gpt-4o-mini"}
    assert out["mode"] == "deep"


@pytest.mark.asyncio
async def test_plan_keeps_followup_with_history_on_llm(monkeypatch):
    recorded = _install_fake_router(
        monkeypatch,
        '{"action":"answer","mode":"balanced","answer_profile":"procedure","lang_target":"fr"}',
    )

    out = await wrappers._chat_agentic_plan_v1(
        {
            "query": "quelles sont les pompes du projet BCX200",
            "conversation_history": [{"role": "user", "content": "résume BCX200"}],
            "model": "gpt-4o-mini",
        },
        {"input": {"response_language": "fr"}},
    )

    assert recorded["preferences"] == {"provider": "openai", "model": "gpt-4o-mini"}
    assert out["answer_profile"] == "procedure"


@pytest.mark.asyncio
async def test_plan_keeps_cross_project_inventory_on_llm(monkeypatch):
    recorded = _install_fake_router(
        monkeypatch,
        '{"action":"answer","mode":"deep","answer_profile":"transversal_inventory",'
        '"lang_target":"fr"}',
    )

    out = await wrappers._chat_agentic_plan_v1(
        {"query": "quels projets utilisent la pompe AKK200 ?", "model": "gpt-4o-mini"},
        {"input": {"response_language": "fr"}},
    )

    assert recorded["preferences"] == {"provider": "openai", "model": "gpt-4o-mini"}
    assert out["answer_profile"] == "transversal_inventory"
    assert out["mode"] == "deep"


# ---------------------------------------------------------------------------
# chat_self_correct_v1 — C2: escalate_deep is re-retrieve-or-abstain
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_self_correct_escalate_deep_re_retrieves_and_grounds(monkeypatch):
    """High hallucination -> escalate_deep must RE-RETRIEVE (deep lane) and
    re-ground the answer on the NEW context, never free-generate."""
    recorded: dict = {}

    async def fake_search(payload, ctx=None):
        recorded["search"] = payload
        recorded["search_ctx"] = ctx
        return {
            "results": [
                {
                    "content": "Working width 0.3 m, line speed 10 to 20 m/min.",
                    "metadata": {"chunk_id": "50a149bf-chunk_0", "document_filename": "AKK200.pdf"},
                    "score": 0.91,
                }
            ]
        }

    monkeypatch.setattr(wrappers, "_semantic_search_v1", fake_search)
    # The grounded synthesis call returns plain prose (not JSON).
    _install_fake_router(monkeypatch, "La largeur de travail est de 0.3 m [1].")

    out = await wrappers._chat_self_correct_v1(
        {
            "draft_answer": "(brouillon non source)",
            "query": "Quelle est la largeur de travail de l'AKK200 ?",
            "scope_hint": "AKK200",
            "lang_target": "fr",
            "answer_profile": "technical",
            "citations": [{"source_id": "stale"}],
            "composite": 40.0,
            "hallucination_rate": 0.3,
            "mode": "balanced",
            "model": "gpt-4o-mini",
        },
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )

    assert set(out) == {"answer", "citations", "action_taken"}
    assert out["action_taken"] == "escalate_deep"
    assert "0.3 m" in out["answer"]
    # Citations now come from the RE-RETRIEVED passages, not the stale draft.
    assert out["citations"][0]["source_id"] == "50a149bf-chunk_0"
    # Re-retrieval used the deep lane + original query (no narrowing).
    assert recorded["search"]["latency_profile"] == "deep"
    assert recorded["search"]["query"] == "Quelle est la largeur de travail de l'AKK200 ?"


@pytest.mark.asyncio
async def test_self_correct_escalate_deep_abstains_when_retrieval_empty(monkeypatch):
    """If the deep re-retrieval still finds nothing, abstain honestly — never
    fabricate (this is the regression the audit C2 flagged)."""
    async def fake_search_empty(payload, ctx=None):
        return {"results": []}

    monkeypatch.setattr(wrappers, "_semantic_search_v1", fake_search_empty)
    # Router would only be reached on a (forbidden) free generation.
    _install_fake_router(monkeypatch, "TEXTE LIBRE INTERDIT")

    out = await wrappers._chat_self_correct_v1(
        {
            "draft_answer": "(brouillon non source)",
            "query": "Spec introuvable ?",
            "lang_target": "fr",
            "composite": 30.0,
            "hallucination_rate": 0.4,
            "mode": "balanced",
        },
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )
    assert out["action_taken"] == "declare_partial"
    assert out["citations"] == []
    assert "TEXTE LIBRE INTERDIT" not in out["answer"]
    assert "Aucune source" in out["answer"]


@pytest.mark.asyncio
async def test_self_correct_declare_partial_transforms_draft(monkeypatch):
    """Mid-quality verdict -> declare_partial: a bounded transform of the
    EXISTING draft (frozen shape, citations carried over)."""
    _install_fake_router(monkeypatch, '{"answer":"Reponse partielle, limites declarees.","action_taken":"declare_partial"}')

    citations = [{"source_id": "src-1"}]
    out = await wrappers._chat_self_correct_v1(
        {
            "draft_answer": "brouillon ok",
            "query": "Q",
            "citations": citations,
            "composite": 65.0,
            "hallucination_rate": 0.05,
            "mode": "balanced",
            "model": "gpt-4o-mini",
        },
        {},
    )
    assert set(out) == {"answer", "citations", "action_taken"}
    assert out["answer"] == "Reponse partielle, limites declarees."
    assert out["action_taken"] == "declare_partial"
    assert out["citations"] == citations


# --- A/B parity (2026-06-26): self_correct must not fire on the embedding
#     hallucination proxy, must MERGE original context, and never downgrade. ----
def test_pick_self_correct_action_ignores_embedding_halluc():
    """The verdict's hallucination_rate is 1 - embedding factuality (~0.45 even
    for clean answers). A grounded draft with a healthy composite must NOT
    escalate just because that proxy is high — that fired escalate_deep on every
    run (latency aborts + lossy deep swaps)."""
    assert wrappers._pick_self_correct_action("balanced", 82.0, 0.45) == "declare_partial"
    # A genuinely low composite still escalates (real quality floor breach).
    assert wrappers._pick_self_correct_action("balanced", 40.0, 0.0) == "escalate_deep"
    # An abstaining draft escalates regardless of composite (try deeper recall).
    assert (
        wrappers._pick_self_correct_action(
            "balanced", 90.0, 0.0, draft_is_abstention=True
        )
        == "escalate_deep"
    )


@pytest.mark.asyncio
async def test_self_correct_escalate_deep_merges_original_context(monkeypatch):
    """escalate_deep must UNION the original (balanced) context with the deep
    re-retrieval so a deep pass that drops the carrier chunk cannot lose it."""
    seen_context: dict = {}

    async def fake_search(payload, ctx=None):
        # Deep re-retrieval returns DIFFERENT chunks (no carrier).
        return {"results": [{"content": "Generic AKK200 overview, high-speed line.", "metadata": {}}]}

    async def fake_generate(payload, ctx=None):
        seen_context["contents"] = [c.get("content") for c in payload.get("context") or []]
        return {"answer": "Largeur 0,3 m, vitesse 10-20 m/min [1].", "citations": []}

    monkeypatch.setattr(wrappers, "_semantic_search_v1", fake_search)
    monkeypatch.setattr(wrappers, "_llm_rag_answer_v1", fake_generate)

    out = await wrappers._chat_self_correct_v1(
        {
            "draft_answer": "Le contexte ne contient pas la largeur.",  # abstention -> escalate
            "query": "largeur AKK200 ?",
            "context": [
                {"content": "Arbeitsbreite 0,3 m, Produktionsgeschwindigkeit 10 bis 20 m/min.", "metadata": {}}
            ],
            "mode": "balanced",
            "composite": 80.0,
        },
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )
    # The carrier chunk from the ORIGINAL context survived the deep re-retrieval.
    assert any("0,3 m" in c for c in seen_context["contents"])
    # The deep chunk was also merged in (union, not replace).
    assert any("overview" in c for c in seen_context["contents"])
    assert out["action_taken"] == "escalate_deep"


@pytest.mark.asyncio
async def test_self_correct_never_downgrades_grounded_draft(monkeypatch):
    """If the deep re-ground abstains but we already had a substantive grounded
    draft, keep the draft (never replace an answer with an abstention)."""
    async def fake_search(payload, ctx=None):
        return {"results": [{"content": "noise", "metadata": {}}]}

    async def fake_generate_abstains(payload, ctx=None):
        return {"answer": "Le contexte ne contient pas cette information.", "citations": []}

    monkeypatch.setattr(wrappers, "_semantic_search_v1", fake_search)
    monkeypatch.setattr(wrappers, "_llm_rag_answer_v1", fake_generate_abstains)

    grounded_draft = "Largeur de travail: 0,3 m; vitesse 10-20 m/min [2]."
    out = await wrappers._chat_self_correct_v1(
        {
            "draft_answer": grounded_draft,
            "query": "largeur AKK200 ?",
            "context": [{"content": "ctx", "metadata": {}}],
            "citations": [{"source_id": "keep"}],
            "mode": "balanced",
            "composite": 40.0,  # low -> escalate path
        },
        {"workspace_id": "ws-1"},
    )
    assert out["answer"] == grounded_draft
    assert out["action_taken"] == "declare_partial"
    assert out["citations"] == [{"source_id": "keep"}]


@pytest.mark.asyncio
async def test_self_correct_falls_back_to_draft_on_failure(monkeypatch):
    class _BoomRouter:
        def __init__(self, *a, **k):
            pass

        async def get_client(self, preferences):
            raise RuntimeError("model down")

    monkeypatch.setattr("app.services.model_router.ModelRouter", _BoomRouter)

    out = await wrappers._chat_self_correct_v1(
        {"draft_answer": "le brouillon", "mode": "deep", "composite": 65.0},
        {},
    )
    assert out["answer"] == "le brouillon"
    assert out["action_taken"] == "declare_partial"
    assert out["citations"] == []


# ---------------------------------------------------------------------------
# llm_rag_answer_v1 — C1(a): consume join.retrieval context, no empty re-search
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rag_answer_consumes_join_context_without_re_retrieval(monkeypatch):
    _install_fake_router(monkeypatch, "Largeur de travail 0.3 m [1].")

    async def _boom_answer(**kwargs):
        raise AssertionError("orchestrator retrieval must NOT run when context is supplied")

    monkeypatch.setattr("app.services.rag.rag_service.answer", _boom_answer)

    out = await wrappers._llm_rag_answer_v1(
        {
            "query": "largeur AKK200 ?",
            "context": [
                {"content": "Working width 0.3 m.", "metadata": {"chunk_id": "c0", "document_filename": "AKK200.pdf"}},
            ],
            "lang_target": "fr",
        },
        {},
    )
    assert out["answer"] == "Largeur de travail 0.3 m [1]."
    assert out["meta"]["retrieval"]["source"] == "join_context"
    assert out["meta"]["retrieval"]["raw_chunks_retrieved"] == 1
    assert out["citations"][0]["source_id"] == "c0"


@pytest.mark.asyncio
async def test_rag_answer_abstains_on_empty_join_context(monkeypatch):
    out = await wrappers._llm_rag_answer_v1(
        {"query": "q", "context": [], "lang_target": "en"},
        {},
    )
    assert out["citations"] == []
    assert out["meta"]["retrieval"]["no_context"] is True
    assert "No indexed source" in out["answer"]


def test_grounded_prompt_forbids_unsupported_equipment_analogies():
    prompt = wrappers._build_grounded_answer_prompt(
        "quelles sont les pompes du projet BCX200 ?",
        [{"content": "Pompe HP PHP31", "metadata": {"document_filename": "pump.pdf"}}],
        "fr",
        "equipment_detail",
    )

    assert "aucun equipement, type, modele ou usage par analogie" in prompt
    assert "non explicitement atteste" in prompt


def test_grounded_inventory_prompt_requires_complete_evidence_scan_and_scope_distinction():
    prompt = wrappers._build_grounded_answer_prompt(
        "quelles sont les pompes du projet ABC100 ?",
        [
            {
                "content": "Projet ABC100 : pompe process P-101.",
                "metadata": {
                    "document_filename": "ABC100 equipment list.pdf",
                    "project_code": "ABC100",
                    "source_family": "equipment_list",
                },
            },
            {
                "content": "Manuel fournisseur du modele GenericPump Z9.",
                "metadata": {
                    "document_filename": "GenericPump Z9 manual.pdf",
                    "inventory_evidence": True,
                    "inventory_equipment_family": "genericpump-z9",
                    "inventory_functional_category": "process-pumps",
                    "inventory_family_attested_by_spare": False,
                },
            },
            {
                "content": "Projet ABC100 : pompe haute pression HP-202.",
                "metadata": {"document_filename": "ABC100 spare parts.pdf"},
            },
        ],
        "fr",
        "equipment_detail",
    )

    assert "parcours TOUS les extraits" in prompt
    assert "project=ABC100; source_family=equipment_list" in prompt
    assert "chaque equipement, type, modele et reference" in prompt
    assert "Ne privilegie pas seulement les premiers extraits" in prompt
    assert "CONTROLE D'INVENTAIRE OBLIGATOIRE" in prompt
    assert "famille demandee (pompes)" in prompt
    assert "ses formes singulier/pluriel, ses traductions" in prompt
    assert "deux sections" in prompt
    assert "modeles seulement decrits dans une notice generique ou fournisseur" in prompt
    assert "ne prouve jamais a lui seul que le modele est installe" in prompt
    assert "CONTROLE FINAL DE COUVERTURE" in prompt
    assert "couple nom de fichier / equipment_family" in prompt
    assert "equipment_family=genericpump-z9" in prompt
    assert "functional_category=process-pumps" in prompt
    assert "family_attested_by_spare=false" in prompt
    assert "conserve le nom du constructeur avec ce modele" in prompt
    assert "ne le deduis jamais par analogie" in prompt
    assert "Termine chaque ligne factuelle par au moins un repere de source [n]" in prompt
    assert "Ne conclus jamais qu'il n'existe aucun autre item" in prompt
    assert "liste documentee dans les extraits" in prompt


def test_grounded_prompt_keeps_long_inventory_evidence_but_bounds_regular_passages():
    tail_marker = "TAIL_INVENTORY_MODEL_Z9"
    filler = "x" * 4500
    prompt = wrappers._build_grounded_answer_prompt(
        "quelles sont les pompes du projet ABC100 ?",
        [
            {
                "content": filler + tail_marker,
                "metadata": {
                    "document_filename": "ABC100 spare parts.pdf",
                    "project_code": "ABC100",
                    "source_family": "spare_parts_list",
                    "inventory_evidence": True,
                },
            },
            {
                "content": filler + "REGULAR_TAIL_MUST_BE_TRUNCATED",
                "metadata": {"document_filename": "regular.pdf"},
            },
        ],
        "fr",
        "equipment_detail",
    )

    assert tail_marker in prompt
    assert "inventory_evidence=true" in prompt
    assert "REGULAR_TAIL_MUST_BE_TRUNCATED" not in prompt


def test_grounded_non_inventory_equipment_prompt_avoids_exhaustive_scan_contract():
    prompt = wrappers._build_grounded_answer_prompt(
        "detaille les caracteristiques de la pompe du projet ABC100",
        [{"content": "Pression : 120 bar.", "metadata": {}}],
        "fr",
        "equipment_detail",
    )

    assert "parcours TOUS les extraits" not in prompt
    assert "liste documentee dans les extraits" not in prompt


def test_grounded_custom_inventory_profile_uses_inventory_contract():
    prompt = wrappers._build_grounded_answer_prompt(
        "inventaire demande",
        [{"content": "Moteur M-1.", "metadata": {}}],
        "fr",
        "equipment_inventory",
    )

    assert "parcours TOUS les extraits" in prompt


def test_inventory_synthesis_keeps_all_evidence_and_bounds_expansions():
    evidence = [
        {
            "content": f"inventory evidence {index}",
            "metadata": {"inventory_evidence": True, "document_id": f"e-{index}"},
        }
        for index in range(6)
    ]
    regular = [
        {"content": f"semantic expansion {index}", "metadata": {"document_id": f"s-{index}"}}
        for index in range(12)
    ]

    selected = wrappers._select_inventory_synthesis_passages(
        "quelles sont les pompes du projet ABC100 ?",
        "equipment_detail",
        [*evidence, *regular],
    )

    assert len(selected) == 10
    assert selected[:6] == evidence
    assert selected[6:] == regular[:4]


def test_inventory_synthesis_preserves_full_context_without_evidence_floor():
    passages = [
        {"content": f"canonical {index}", "metadata": {}}
        for index in range(14)
    ]

    assert (
        wrappers._select_inventory_synthesis_passages(
            "quelles sont les pompes du projet ABC100 ?",
            "equipment_detail",
            passages,
        )
        is passages
    )


def test_inventory_synthesis_uses_query_shape_not_planner_profile():
    evidence = [
        {"content": "inventory evidence", "metadata": {"inventory_evidence": True}}
    ]
    regular = [
        {"content": f"regular {index}", "metadata": {}}
        for index in range(14)
    ]

    selected = wrappers._select_inventory_synthesis_passages(
        "quelles sont les pompes du projet ABC100 ?",
        "technical",
        [*evidence, *regular],
    )

    assert len(selected) == 10
    cross_project = [*evidence, *regular]
    assert (
        wrappers._select_inventory_synthesis_passages(
            "quels projets ABC100 et DEF200 utilisent ces pompes ?",
            "transversal_inventory",
            cross_project,
        )
        is cross_project
    )

    english_selected = wrappers._select_inventory_synthesis_passages(
        "inventory of injectors for project ABC100",
        "technical",
        [*evidence, *regular],
    )
    assert len(english_selected) == 10
    assert "CONTROLE D'INVENTAIRE OBLIGATOIRE" in wrappers._grounded_profile_contract(
        "inventory of injectors for project ABC100",
        "equipment_detail",
    )


def test_inventory_synthesis_keeps_all_protected_context_after_evidence():
    evidence = [
        {
            "content": f"inventory evidence {index}",
            "metadata": {"inventory_evidence": True},
        }
        for index in range(6)
    ]
    regular = [{"content": f"regular {index}", "metadata": {}} for index in range(8)]
    protected = [
        {
            "content": "guide",
            "metadata": {"source_type": "knowledge_guide"},
        },
        {
            "content": "summary",
            "metadata": {"semantic_type": "summary_artifact"},
        },
        {
            "content": "table",
            "metadata": {"source_type": "table_analysis"},
        },
        {
            "content": "document",
            "metadata": {"semantic_type": "document_analysis"},
        },
        {
            "content": "exact guardrail",
            "metadata": {"semantic_type": "exact_match_guardrail"},
        },
    ]

    selected = wrappers._select_inventory_synthesis_passages(
        "quelles sont les pompes du projet ABC100 ?",
        "equipment_detail",
        [*evidence, *regular, *protected],
    )

    assert selected[:6] == evidence
    assert selected[6:] == protected
    assert len(selected) == 11


# ---------------------------------------------------------------------------
# semantic_search_v1 — C1(b): resolve tenant slug + balanced lane + budgets
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_semantic_search_resolves_slug_and_forwards_budgets(monkeypatch):
    captured: dict = {}

    async def _fake_retrieve(request):
        captured["request"] = request
        return {
            "chunks": ["Working width 0.3 m."],
            "scores": [0.9],
            "metadatas": [{"chunk_id": "c0"}],
            "metrics": {"raw_chunks_retrieved": 1, "document_chunks_retrieved": 1, "stage_timings": {"embedding_ms": 12}},
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", _fake_retrieve)
    monkeypatch.setattr("app.services.rag.context.apply_retrieval_profile_to_request", lambda r: r)

    out = await wrappers._semantic_search_v1(
        {
            "query": "AKK200 width",
            "latency_profile": "balanced",
            "retrieval_profile": "chat",
            "top_k": 6,
            "knowledge_scope": "AKK200",
        },
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )

    req = captured["request"]
    assert req["workspace_slug"] == "andritz"          # tenant slug wired (root cause fix)
    assert req["query"] == "AKK200 width"
    assert req["top_k"] == 6
    assert req["latency_profile"] == "balanced"
    # Recall-parity backfill: balanced lane budgets reach retrieval even when the
    # plan only pinned top_k (otherwise get_retrieval_profile collapses them).
    assert req["synthesis_k"] == 16
    assert req["candidate_pool_k"] == 40
    assert out["results"][0]["content"] == "Working width 0.3 m."
    assert out["raw_chunks_retrieved"] == 1            # observable grounding proof


@pytest.mark.asyncio
async def test_semantic_search_defaults_to_balanced_never_fast(monkeypatch):
    captured: dict = {}

    async def _fake_retrieve(request):
        captured["request"] = request
        return {"chunks": [], "scores": [], "metadatas": [], "metrics": {"raw_chunks_retrieved": 0}}

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", _fake_retrieve)
    monkeypatch.setattr("app.services.rag.context.apply_retrieval_profile_to_request", lambda r: r)

    await wrappers._semantic_search_v1(
        {"query": "x"},
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )
    # The old hardcoded "fast" is gone; absent a plan lane we default balanced.
    assert captured["request"]["latency_profile"] == "balanced"


@pytest.mark.asyncio
async def test_semantic_search_deep_lane_uses_full_deep_budget(monkeypatch):
    """A deep re-retrieve (escalate_deep / inventory) must get the FULL deep
    budget (8/24/80), never a collapsed lone-top_k pool."""
    captured: dict = {}

    async def _fake_retrieve(request):
        captured["request"] = request
        return {"chunks": [], "scores": [], "metadatas": [], "metrics": {"raw_chunks_retrieved": 0}}

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", _fake_retrieve)
    monkeypatch.setattr("app.services.rag.context.apply_retrieval_profile_to_request", lambda r: r)

    await wrappers._semantic_search_v1(
        {"query": "URACA pumps", "latency_profile": "deep", "deep_retrieval": True},
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )
    req = captured["request"]
    assert req["latency_profile"] == "deep"
    assert req["top_k"] == 8
    assert req["synthesis_k"] == 24
    assert req["candidate_pool_k"] == 80


def test_project_inventory_passage_enumerates_projects():
    passage = wrappers._project_inventory_passage(
        {
            "terms": ["uraca"],
            "total_projects": 3,
            "projects": [
                {"project_code": "BHX100", "chunk_count": 9},
                {"project_code": "AKI500", "chunk_count": 7},
                {"project_code": "PHO300", "chunk_count": 4},
            ],
        }
    )
    assert passage is not None
    assert "BHX100" in passage["content"] and "PHO300" in passage["content"]
    assert "3 projet" in passage["content"]
    assert passage["metadata"]["kind"] == "transversal_inventory"
    # No projects -> no synthetic passage.
    assert wrappers._project_inventory_passage({"projects": []}) is None
    assert wrappers._project_inventory_passage(None) is None


@pytest.mark.asyncio
async def test_semantic_search_arms_inventory_facet_for_project_question(monkeypatch):
    """A 'which projects use X' question must arm the transversal_inventory facet
    and surface the exhaustive enumeration as the TOP passage (classic parity)."""
    captured: dict = {}

    async def _fake_retrieve(request):
        captured["request"] = request
        return {
            "chunks": ["URACA KD724-G pump operating manual."],
            "scores": [0.5],
            "metadatas": [{}],
            "metrics": {"raw_chunks_retrieved": 1},
            "project_inventory": {
                "terms": ["uraca"],
                "total_projects": 2,
                "projects": [
                    {"project_code": "BHX100", "chunk_count": 9},
                    {"project_code": "AKI500", "chunk_count": 7},
                ],
            },
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", _fake_retrieve)
    monkeypatch.setattr("app.services.rag.context.apply_retrieval_profile_to_request", lambda r: r)

    out = await wrappers._semantic_search_v1(
        {"query": "Quels projets utilisent une pompe URACA ?", "latency_profile": "deep"},
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )
    assert captured["request"]["answer_profile"] == "transversal_inventory"
    # The enumeration is the #1 passage so generate lists the projects.
    assert out["results"][0]["metadata"]["kind"] == "transversal_inventory"
    assert "BHX100" in out["results"][0]["content"]
    assert out["results"][1]["content"] == "URACA KD724-G pump operating manual."


# ---------------------------------------------------------------------------
# _coerce_plan — C3: gate clarify / reject placeholder scope hints
# ---------------------------------------------------------------------------
def test_coerce_plan_demotes_clarify_when_project_code_present():
    out = wrappers._coerce_plan(
        {"action": "clarify", "scope_hint": "perimetre de recherche", "clarifying_question": "Quel projet ?"},
        "Quelle est la largeur de travail de l'AKK200 ?",
    )
    assert out["action"] == "answer"          # project code -> answerable
    assert out["scope_hint"] == ""            # schema placeholder dropped


def test_coerce_plan_demotes_clarify_on_placeholder_question():
    out = wrappers._coerce_plan(
        {"action": "clarify", "clarifying_question": "perimetre de recherche"},
        "Donne moi les informations",
    )
    assert out["action"] == "answer"          # placeholder question -> dropped -> answer


def test_coerce_plan_preserves_genuine_clarify():
    out = wrappers._coerce_plan(
        {"action": "clarify", "clarifying_question": "Quel equipement vous interesse ?"},
        "infos",                               # 1 word, no anchor -> genuinely ambiguous
    )
    assert out["action"] == "clarify"
    assert out["clarifying_question"] == "Quel equipement vous interesse ?"


# ---------------------------------------------------------------------------
# _coerce_plan — OOS gate (never reject a valid in-corpus question, incl. DE)
# ---------------------------------------------------------------------------
def test_coerce_plan_demotes_reject_oos_on_known_entity_german():
    # Valid German question about a known system (QMS-12) was wrongly reject_oos.
    out = wrappers._coerce_plan(
        {"action": "reject_oos", "oos_reason": "hors perimetre"},
        "Wozu dient das Qualiscan QMS-12 System und wie funktioniert es?",
    )
    assert out["action"] == "answer"          # known entity -> never OOS
    assert out["oos_reason"] == ""


def test_coerce_plan_demotes_reject_oos_on_project_code():
    out = wrappers._coerce_plan(
        {"action": "reject_oos"},
        "Quel est le role du module CU250S-2 ?",
    )
    assert out["action"] == "answer"


def test_coerce_plan_keeps_reject_oos_when_truly_out_of_corpus():
    # No project code / known entity -> the planner's reject_oos is honoured
    # (the deliver context_count gate is the runtime backstop, not tested here).
    out = wrappers._coerce_plan(
        {"action": "reject_oos", "oos_reason": "hors industrie Andritz"},
        "Quelle est la capitale de l'Australie ?",
    )
    assert out["action"] == "reject_oos"


# ---------------------------------------------------------------------------
# _coerce_plan — inventory/transversal routing -> deep lane + deep budget
# ---------------------------------------------------------------------------
def test_coerce_plan_routes_inventory_to_deep():
    # Planner under-routed this to balanced; the gate must force deep.
    out = wrappers._coerce_plan(
        {"action": "answer", "mode": "balanced",
         "retrieval": {"latency_profile": "balanced", "retrieval_profile": "chat",
                       "top_k": 8, "synthesis_k": 16, "candidate_pool_k": 40,
                       "rag_pipeline_mode": "chah", "deep_retrieval": False}},
        "Quels projets utilisent une pompe URACA ?",
    )
    assert out["mode"] == "deep"
    assert out["retrieval"]["latency_profile"] == "deep"
    assert out["retrieval"]["deep_retrieval"] is True
    assert out["retrieval"]["synthesis_k"] >= 24
    assert out["retrieval"]["candidate_pool_k"] >= 80


def test_coerce_plan_enforces_bounded_single_project_inventory_budget():
    out = wrappers._coerce_plan(
        {
            "action": "answer",
            "mode": "fast",
            "retrieval": {
                "latency_profile": "fast",
                "retrieval_profile": "oracle_fast",
                "top_k": 5,
                "synthesis_k": 12,
                "candidate_pool_k": 20,
                "rag_pipeline_mode": "chah",
                "deep_retrieval": False,
            },
        },
        "liste toutes les pompes du projet BCX200",
        has_history=True,
    )

    assert out["mode"] == "balanced"
    assert out["retrieval"] == wrappers._SINGLE_PROJECT_INVENTORY_RETRIEVAL


def test_coerce_plan_preserves_explicit_deep_single_project_analysis():
    out = wrappers._coerce_plan(
        {"action": "answer", "mode": "deep"},
        "analyse en profondeur la liste de toutes les pompes du projet BCX200",
    )

    assert out["mode"] == "deep"
    assert out["retrieval"]["retrieval_profile"] == "deep_async"


def test_coerce_plan_emits_balanced_budget_triple_by_default():
    out = wrappers._coerce_plan({"action": "answer", "mode": "balanced"}, "Largeur AKK200 ?")
    assert out["retrieval"]["top_k"] == 8
    assert out["retrieval"]["synthesis_k"] == 16
    assert out["retrieval"]["candidate_pool_k"] == 40


# ---------------------------------------------------------------------------
# response_eval_v1
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_response_eval_emits_frozen_contract(monkeypatch):
    metrics = {"relevance": 0.8, "factuality": 0.7, "coherence": 0.9, "hhem": 0.25, "adv_hhem": 0.12}
    monkeypatch.setattr(
        "app.services.metrics.evaluator.ResponseEvaluator",
        lambda: _FakeEvaluator(metrics),
    )

    out = await wrappers._response_eval_v1(
        {
            "answer": "une reponse",
            "query": "une question",
            "citations": [{"source_id": "s1"}],
            "context_chunks": [
                {"content": "chunk A"},
                {"text": "chunk B"},
                "chunk C",
            ],
        },
        {},
    )

    assert set(out) == {"composite", "hallucination_rate", "context_count", "hhem", "factuality", "coherence"}
    # composite = mean(relevance, factuality, coherence) * 100
    assert out["composite"] == pytest.approx((0.8 + 0.7 + 0.9) / 3 * 100, abs=0.01)
    # hallucination_rate = 1 - factuality
    assert out["hallucination_rate"] == pytest.approx(0.3, abs=0.001)
    assert out["context_count"] == 3
    assert out["factuality"] == 0.7
    assert out["coherence"] == 0.9
    assert out["hhem"] == 0.25
    # The evaluator received the flattened chunk texts.
    assert _FakeEvaluator.last["source_chunks"] == ["chunk A", "chunk B", "chunk C"]


@pytest.mark.asyncio
async def test_response_eval_empty_metrics_route_weak(monkeypatch):
    monkeypatch.setattr(
        "app.services.metrics.evaluator.ResponseEvaluator",
        lambda: _FakeEvaluator({"relevance": 0.0, "factuality": 0.0, "coherence": 0.0, "hhem": 0.0, "adv_hhem": 0.0}),
    )

    out = await wrappers._response_eval_v1({"answer": "", "query": "q", "context_chunks": []}, {})
    assert out["composite"] == 0.0
    assert out["hallucination_rate"] == 1.0
    assert out["context_count"] == 0


# ---------------------------------------------------------------------------
# Registry + seed wiring
# ---------------------------------------------------------------------------
def test_skills_are_registered_and_seeded():
    for slug in ("chat_agentic_plan_v1", "chat_self_correct_v1", "response_eval_v1"):
        assert wrappers.resolve(slug) is not wrappers._unimplemented

    by_slug = {entry["slug"]: entry for entry in SEED_SKILLS}
    plan_out = by_slug["chat_agentic_plan_v1"]["output_schema"]["properties"]
    assert {"action", "mode", "retrieval"} <= set(plan_out)
    # Recall-parity: the plan retrieval contract exposes the budget triple.
    plan_retrieval = plan_out["retrieval"]["properties"]
    assert {"top_k", "synthesis_k", "candidate_pool_k"} <= set(plan_retrieval)
    correct_out = by_slug["chat_self_correct_v1"]["output_schema"]["properties"]
    assert {"answer", "citations", "action_taken"} <= set(correct_out)
    eval_out = by_slug["response_eval_v1"]["output_schema"]["properties"]
    assert {"composite", "hallucination_rate", "context_count", "hhem", "factuality", "coherence"} == set(eval_out)

    # Grounding-fix I/O contract: generate accepts a pre-retrieved context array,
    # self_correct accepts the scope/lang/profile hints its escalate_deep needs.
    rag_in = by_slug["llm_rag_answer_v1"]["input_schema"]["properties"]
    assert {"context", "answer_profile", "lang_target"} <= set(rag_in)
    correct_in = by_slug["chat_self_correct_v1"]["input_schema"]["properties"]
    assert {"scope_hint", "lang_target", "answer_profile"} <= set(correct_in)
