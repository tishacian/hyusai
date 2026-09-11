from __future__ import annotations

from app.agents.procurement_agent import (
    _AndritzContactBoilerplateStreamFilter,
    SYSTEM_PROMPT,
    _assemble_context_and_sources,
    _build_rag_user_prompt,
    _grounding_policy_from_request,
    _strip_andritz_contact_boilerplate,
    _system_prompt_with_grounding,
)


def test_balanced_grounding_prompt_allows_foundational_fallback_without_citations():
    policy = _grounding_policy_from_request(
        {
            "grounding_policy": {
                "mode": "balanced",
                "allow_foundational_fallback": True,
                "fallback_disclaimer": "Je n'ai pas de source workspace sur ce point ; analyse generale a valider :",
            }
        }
    )

    system_prompt = _system_prompt_with_grounding(SYSTEM_PROMPT, policy)
    user_prompt = _build_rag_user_prompt(
        query="Explique la méthode pour structurer un brief cabinet.",
        context_text="No SENTINEL-CI workspace source was retrieved for this turn.",
        keyword_hint="",
        grounding_policy=policy,
        has_retrieved_context=False,
    )

    assert "answer from general knowledge" in system_prompt
    assert "Je n'ai pas de source workspace" in user_prompt
    assert "Do not include citation markers like [1]" in user_prompt


def test_strict_grounding_prompt_preserves_source_required_behavior():
    policy = _grounding_policy_from_request({"grounding_mode": "strict"})

    system_prompt = _system_prompt_with_grounding(SYSTEM_PROMPT, policy)
    user_prompt = _build_rag_user_prompt(
        query="Combien de documents sont indexés ?",
        context_text="No documents found in the knowledge base.",
        keyword_hint="",
        grounding_policy=policy,
        has_retrieved_context=False,
    )

    assert "answer from general knowledge" not in system_prompt
    assert "say so clearly rather than guessing" in user_prompt
    assert "authoritative over conversation history" in user_prompt
    assert "ignore the stale answer completely" in user_prompt


def test_context_assembly_keeps_extra_context_but_caps_displayed_sources():
    chunks = [f"Important passage {index}" for index in range(4)]
    metas = [
        {"document_filename": f"doc-{index}.pdf", "page": index}
        for index in range(4)
    ]

    context_text, sources, has_context = _assemble_context_and_sources(
        chunks,
        [0.9, 0.8, 0.7, 0.6],
        metas,
        source_display_k=2,
    )

    assert has_context is True
    assert len(sources) == 2
    assert "[1] doc-0.pdf" in context_text
    assert "[2] doc-1.pdf" in context_text
    assert "Additional retrieved context" in context_text
    assert "Important passage 3" in context_text


def test_rag_prompt_requests_synthesis_before_source_locators():
    policy = _grounding_policy_from_request({"grounding_mode": "strict"})
    prompt = _build_rag_user_prompt(
        query="Que disent les documents sur la ligne BBA120 ?",
        context_text="[1] Manual\nLa ligne BBA120 utilise un hydroentanglement.",
        keyword_hint="",
        grounding_policy=policy,
        has_retrieved_context=True,
        retrieval_summary="Coverage: 1 retrieved chunk.\nRepresentative content:\n- Manual: BBA120...",
    )

    assert "Retrieved content synthesis brief" in prompt
    assert "Start with the direct factual answer or synthesis" in prompt
    assert "synthesize by theme instead of listing every retrieved excerpt" in prompt


def test_rag_prompt_forbids_generic_andritz_contact_footer():
    policy = _grounding_policy_from_request({"grounding_mode": "strict"})
    prompt = _build_rag_user_prompt(
        query="Que disent les documents sur la ligne BBA120 ?",
        context_text="[1] Manual\nPour plus d'informations, contactez Andritz.",
        keyword_hint="",
        grounding_policy=policy,
        has_retrieved_context=True,
    )

    assert "contact Andritz" in SYSTEM_PROMPT
    assert "Do not end with generic document boilerplate" in prompt


def test_strip_andritz_contact_boilerplate_from_answer_tail():
    answer = (
        "La ligne BBA120 combine hydroentanglement et contrôle de cadence.\n\n"
        "Pour plus d'informations, contactez Andritz."
    )

    cleaned = _strip_andritz_contact_boilerplate(answer)

    assert cleaned == "La ligne BBA120 combine hydroentanglement et contrôle de cadence."


def test_strip_andritz_contact_boilerplate_preserves_explicit_contact_answers():
    answer = "Le document indique de contacter le représentant Andritz pour plus d'informations."

    assert _strip_andritz_contact_boilerplate(answer, allow_contact_answer=True) == answer


def test_stream_filter_removes_chunked_andritz_contact_footer():
    stream_filter = _AndritzContactBoilerplateStreamFilter(enabled=True, tail_chars=80)
    emitted = ""

    emitted += stream_filter.feed("La ligne BBA120 combine hydroentanglement et contrôle de cadence. ")
    emitted += stream_filter.feed("Pour plus d'informations, ")
    emitted += stream_filter.feed("contactez Andritz.")
    emitted += stream_filter.flush()

    assert "contactez Andritz" not in emitted
    assert emitted == "La ligne BBA120 combine hydroentanglement et contrôle de cadence."


# --- Expert-fiche answer posture (expert first, doc flagged outdated) --------


def test_rag_prompt_expert_fiche_leads_with_expert_and_flags_doc_outdated():
    # Case 2: a validated expert fiche is present. The answer must lead with the
    # expert reply, say it comes from an expert, and flag any differing document
    # as outdated / to verify (the opposite of the old "no contradiction" posture).
    policy = _grounding_policy_from_request({"grounding_mode": "strict"})
    prompt = _build_rag_user_prompt(
        query="Quelle est la pression nominale de la pompe KD724 ?",
        context_text="[1] Fiche\nLa pression nominale est 7 bar.",
        keyword_hint="",
        grounding_policy=policy,
        has_retrieved_context=True,
        has_expert_fiche=True,
    )

    # Expert-priority instruction present: expert answer first + doc flagged stale.
    assert "donne d'abord cette réponse" in prompt
    assert "provient d'un expert" in prompt
    assert "obsolète / à faire vérifier" in prompt
    # Case 3: conflicting expert fiches carry equal weight -> ambiguity handling.
    assert "plusieurs fiches expertes se contredisent" in prompt
    assert "le même poids" in prompt
    # The old "treat as reference truth, do not narrate the contradiction" posture
    # is gone, and the contradiction-handling invitation is kept for every turn.
    assert "vérité de référence" not in prompt
    assert "ne mentionne pas qu'elle contredit ou remplace" not in prompt
    assert "too thin or contradictory" in prompt


def test_rag_prompt_without_expert_fiche_is_unchanged():
    policy = _grounding_policy_from_request({"grounding_mode": "strict"})
    base_kwargs = dict(
        query="Quelle est la pression nominale de la pompe KD724 ?",
        context_text="[1] Manual\nLa pression nominale est 5 bar.",
        keyword_hint="",
        grounding_policy=policy,
        has_retrieved_context=True,
    )
    prompt_default = _build_rag_user_prompt(**base_kwargs)
    prompt_no_fiche = _build_rag_user_prompt(**base_kwargs, has_expert_fiche=False)

    # has_expert_fiche defaults to False; no expert-priority text leaks in, and the
    # generic contradiction-handling line stays in place.
    assert prompt_default == prompt_no_fiche
    assert "donne d'abord cette réponse" not in prompt_no_fiche
    assert "plusieurs fiches expertes" not in prompt_no_fiche
    assert "too thin or contradictory" in prompt_no_fiche


def test_context_assembly_labels_expert_fiche_when_pin_enabled(monkeypatch):
    from app.core.config import settings as app_config

    monkeypatch.setattr(app_config, "rag_expert_fiche_pin_enabled", True)
    chunks = ["Plain doc passage.", "Expert correction passage."]
    metas = [
        {"document_filename": "manual.pdf"},
        {"document_filename": "fiche.md", "source_type": "expert_fiche"},
    ]

    context_text, _sources, _has = _assemble_context_and_sources(
        chunks, [0.9, 0.8], metas
    )

    assert "(Fiche experte — validée)" in context_text


def test_context_assembly_does_not_label_when_pin_disabled(monkeypatch):
    from app.core.config import settings as app_config

    monkeypatch.setattr(app_config, "rag_expert_fiche_pin_enabled", False)
    chunks = ["Plain doc passage.", "Expert correction passage."]
    metas = [
        {"document_filename": "manual.pdf"},
        {"document_filename": "fiche.md", "source_type": "expert_fiche"},
    ]

    context_text, _sources, _has = _assemble_context_and_sources(
        chunks, [0.9, 0.8], metas
    )

    assert "(Fiche experte — validée)" not in context_text
