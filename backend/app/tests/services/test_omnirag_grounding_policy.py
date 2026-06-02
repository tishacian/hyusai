from __future__ import annotations

from app.agents.procurement_agent import (
    SYSTEM_PROMPT,
    _assemble_context_and_sources,
    _build_rag_user_prompt,
    _grounding_policy_from_request,
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
    assert "Start with a concise synthesis" in prompt
    assert "not only with source locators" in prompt
