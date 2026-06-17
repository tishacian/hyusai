from app.services.industrial_answer_profile import (
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
    assert "La largeur est de 3 600 mm." in cleaned
    assert any(item.startswith("internal_term:") for item in violations)


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
