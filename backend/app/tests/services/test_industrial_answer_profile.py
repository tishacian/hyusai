from app.services.industrial_answer_profile import (
    answer_policy_prompt,
    apply_answer_policy_to_text,
    industrial_answer_policy,
    resolve_answer_profile,
)


def test_resolve_transversal_inventory_requires_exhaustive_retrieval():
    decision = resolve_answer_profile("Quels projets utilisent une pompe Uraca ?", industrial_answer_policy())

    assert decision.profile == "transversal_inventory"
    assert decision.requires_exhaustive_retrieval is True


def test_resolve_project_summary_profile():
    decision = resolve_answer_profile("Résume le projet AKK200", industrial_answer_policy())

    assert decision.profile == "project_summary"
    assert decision.requires_exhaustive_retrieval is False


def test_resolve_broad_knowledge_request_as_project_summary():
    # "Tell me everything about project X" wants a structured synthesis, not the
    # terse precise_fact one-liner.
    policy = industrial_answer_policy()
    for query in (
        "donne moi tout ce que tu sais sur le projet AKK200",
        "parle-moi du projet AKK200",
        "tout sur le projet AKK200",
    ):
        assert resolve_answer_profile(query, policy).profile == "project_summary", query
    # A single factual question on the same project stays precise_fact.
    assert resolve_answer_profile("quelle pompe est utilisée dans ce projet ?", policy).profile == "precise_fact"


def test_resolve_equipment_list_as_transversal_inventory():
    decision = resolve_answer_profile("Liste toutes les pompes Uraca", industrial_answer_policy())

    assert decision.profile == "transversal_inventory"
    assert decision.requires_exhaustive_retrieval is True


def test_answer_policy_removes_internal_mechanics_terms():
    cleaned, violations = apply_answer_policy_to_text(
        "J'ai trouvé cette information dans 17 chunks avec un score vectoriel élevé. "
        "La largeur est de 3 600 mm.",
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "precise_fact"},
    )

    assert "chunks" not in cleaned.lower()
    assert "score vectoriel" not in cleaned.lower()
    assert "j'ai trouvé" not in cleaned.lower()
    assert "La largeur est de 3 600 mm." in cleaned
    assert any(item.startswith("internal_term:") for item in violations)
    assert "documentalist_preamble" in violations


def test_answer_policy_strips_documentalist_preamble():
    cleaned, violations = apply_answer_policy_to_text(
        "Les sources indiquent que la pompe utilisée est une Uraca KD724 [1].",
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "precise_fact"},
    )

    assert cleaned == "La pompe utilisée est une Uraca KD724 [1]."
    assert "documentalist_preamble" in violations


def test_answer_policy_keeps_fact_when_stripping_found_preamble():
    cleaned, violations = apply_answer_policy_to_text(
        "J'ai trouvé la pompe utilisée : Uraca KD724 [1].",
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "precise_fact"},
    )

    assert cleaned == "La pompe utilisée : Uraca KD724 [1]."
    assert "documentalist_preamble" in violations


def test_answer_policy_prompt_prefers_direct_factual_answers():
    prompt = answer_policy_prompt(
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "precise_fact"},
        language="fr",
    )

    assert "Start with the answer itself" in prompt
    assert "I found" in prompt
    assert "source-by-source lists" in prompt


def test_answer_policy_removes_absence_then_answer_preamble():
    cleaned, violations = apply_answer_policy_to_text(
        "Je n'ai aucune information exploitable sur ce projet. Le projet AKK200 utilise une pompe Uraca KD724.",
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "precise_fact"},
    )

    assert "aucune information" not in cleaned.lower()
    assert "Uraca KD724" in cleaned
    assert "absence_then_answer" in violations


def test_answer_policy_removes_internal_diagnostic_parenthetical():
    cleaned, violations = apply_answer_policy_to_text(
        "Je n'ai pas de source workspace sur ce point (retrieval: retrieval_deadline_exceeded)",
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "insufficient_context"},
    )

    assert "retrieval" not in cleaned.lower()
    assert cleaned == "Je n'ai pas de source workspace sur ce point"
    assert "internal_diagnostic_parenthetical" in violations
