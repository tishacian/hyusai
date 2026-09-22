import pytest

from app.services.industrial_answer_profile import (
    DEFAULT_INDUSTRIAL_ANSWER_PROFILES,
    answer_policy_prompt,
    apply_answer_policy_to_text,
    industrial_answer_policy,
    resolve_answer_profile,
)
from app.services.rag.corpus_planner import classify_intent
from app.services.rag.project_references import ANDRITZ_PROJECT_SCHEME, bind_project_reference_scheme


@pytest.fixture(autouse=True)
def andritz_project_scheme():
    with bind_project_reference_scheme(ANDRITZ_PROJECT_SCHEME):
        yield


def test_resolve_transversal_inventory_requires_exhaustive_retrieval():
    decision = resolve_answer_profile("Quels projets utilisent une pompe Uraca ?", industrial_answer_policy())

    assert decision.profile == "transversal_inventory"
    assert decision.requires_exhaustive_retrieval is True


def test_resolve_project_summary_profile():
    for query in (
        "Résume le projet AKK200",
        "resume BAO100",
        "Résume-moi BCX200",
        "summarize ACJ100",
        "résume 61038",
        "résumé 61038",
        "résume le projet 61038",
    ):
        decision = resolve_answer_profile(query, industrial_answer_policy())
        assert decision.profile == "project_summary", query
        assert decision.requires_exhaustive_retrieval is False, query


def test_resolve_french_numeric_project_comparisons():
    policy = industrial_answer_policy()
    for query in (
        "comparaison entre 61038 et 61001",
        "différences entre le projet 61038 et le projet 61001",
    ):
        assert resolve_answer_profile(query, policy).profile == "comparison", query


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


def test_resolve_imperative_project_inventory_as_transversal_inventory():
    # Reverse-lookup phrased as an imperative without a leading
    # "quels/liste/tous/which" still asks for the set of projects equipped with
    # a piece of equipment. It must route to the exhaustive cross-project
    # inventory path, not the shallow precise_fact one (which previously made the
    # assistant claim it could not list the projects).
    policy = industrial_answer_policy()
    for query in (
        "donne moi les projets avec une pompe uraca",
        "projets avec une pompe uraca",
        "donne-moi les projets équipés d'une pompe Uraca",
        "les projets qui ont une pompe Uraca",
        "list the projects with a Uraca pump",
    ):
        decision = resolve_answer_profile(query, policy)
        assert decision.profile == "transversal_inventory", query
        assert decision.requires_exhaustive_retrieval is True, query

    # A single-project factual question must NOT be promoted to the inventory
    # path by the new imperative pattern.
    assert (
        resolve_answer_profile("quelle pompe est utilisée dans ce projet ?", policy).profile
        == "precise_fact"
    )


def test_resolve_part_reference_question_as_equipment_detail():
    # "quelle est la référence de la toile du convoyeur J1" used to be claimed by
    # _PRECISE_FACT_RE (leading "quelle"), which kept part-identity questions out
    # of the equipment niche. They must resolve before the precise_fact branch.
    policy = industrial_answer_policy()
    for query in (
        "quelle est la réference de la toile du convoyeur j1",
        "quelle est la référence de la toile du convoyeur J1 ?",
        "référence du palier du J2S ?",
        "code pièce de la toile",
        "part number of the conveyor belt",
        "quelle est la reference de la courroie ?",
    ):
        decision = resolve_answer_profile(query, policy)
        assert decision.profile == "equipment_detail", query
        assert decision.reason == "part_reference_query", query
        assert decision.requires_exhaustive_retrieval is False, query


def test_part_reference_detection_does_not_claim_adjectival_reference_wording():
    # French "X de référence" is an adjectival qualifier, not a part number
    # request, so the asked fact must stay on precise_fact.
    policy = industrial_answer_policy()
    for query in (
        "quelle est la pression de référence de la pompe ?",
        "quel est le débit de référence du convoyeur ?",
    ):
        assert resolve_answer_profile(query, policy).profile == "precise_fact", query


def test_equipment_detail_covers_conveyor_and_belt_vocabulary():
    policy = industrial_answer_policy()
    for query in (
        "donne-moi la fiche de la toile du convoyeur",
        "caractéristiques du palier du J2S",
        "spécifications du strip de l'injecteur",
    ):
        decision = resolve_answer_profile(query, policy)
        assert decision.profile == "equipment_detail", query
        assert decision.reason == "equipment_detail_query", query


def test_part_reference_profile_does_not_cannibalise_neighbouring_profiles():
    # The three other Pascal queries must keep the profile they already had:
    # the scope/anchor fixes own them, not the answer profile.
    policy = industrial_answer_policy()
    expected = {
        "quel strip mettre dans l'injecteur de prémouillage": "precise_fact",
        "quelle est la distance entre le j1 et le c1 en mode isojet": "precise_fact",
        "quelle toile sur le convoyeur JP": "precise_fact",
        "Compare les consignes J2S avec et sans Scorpio": "comparison",
        "Donne-moi la nomenclature des pièces du sécheur": "table_extract",
        "Quelle est la pression nominale de la pompe URACA ?": "precise_fact",
        "Donne-moi la fiche technique de la pompe URACA": "equipment_detail",
        "Quels projets utilisent une pompe Uraca ?": "transversal_inventory",
    }
    for query, profile in expected.items():
        decision = resolve_answer_profile(query, policy, include_agentic_profiles=True)
        assert decision.profile == profile, query


def test_compare_intent_always_resolves_to_the_comparison_profile():
    # The planner's compare grammar must stay a subset of the profile's, so a
    # compare turn can never reach hybrid routing on a non-niche profile. This
    # replaces a runtime "intent=compare -> agentic" net with a contract the
    # two regexes have to keep.
    policy = industrial_answer_policy()
    for query in (
        "Compare les consignes J2S avec et sans Scorpio",
        "compare AKK200 et ACJ100",
        "comparer les consignes J2S",
        "différence entre le J1 et le C1",
        "différences entre AKK200 et ACJ100",
        "J2S versus Scorpio",
        "J2S vs Scorpio",
    ):
        assert classify_intent(query) == "compare", query
        assert resolve_answer_profile(query, policy).profile == "comparison", query


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


def test_answer_policy_prompt_transversal_inventory_uses_consolidated_list():
    # The transversal_inventory profile must instruct the model to present the
    # full project list from the consolidated facet aggregation (when provided)
    # and never claim the information is unavailable / partial.
    prompt = answer_policy_prompt(
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "transversal_inventory"},
        language="fr",
    )

    assert "Inventaire projets consolidé" in prompt
    assert "couverture exhaustive" in prompt
    assert "full deduplicated set of projects" in prompt
    # A non-inventory profile must NOT carry the consolidated-list instruction.
    precise = answer_policy_prompt(
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "precise_fact"},
        language="fr",
    )
    assert "Inventaire projets consolidé" not in precise


def test_answer_policy_prompt_contains_source_conflict_instruction():
    # Case 1: documents disagree on the asked fact. The policy prompt must tell
    # the model to answer AND flag the disagreement, naming both values+sources,
    # instead of silently picking one or listing them flatly.
    prompt = answer_policy_prompt(
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "precise_fact"},
        language="fr",
    )

    assert "conflicting values for the same" in prompt
    assert "name each conflicting value with its source" in prompt
    assert "do not silently pick one" in prompt
    assert "à vérifier" in prompt


def test_conflict_and_expert_answers_survive_post_filter():
    # The new answer shapes must not trip the existing guards (absence-then-answer,
    # documentalist preamble, internal jargon), otherwise the post-filter would
    # strip the very wording we are asking the model to produce.
    policy = industrial_answer_policy()

    conflict_answer = (
        "≈ 5 500 daN selon [1], mais [2] indique ≈ 5 750 daN pour la même "
        "configuration (arasement 3750) — à vérifier."
    )
    cleaned_conflict, violations_conflict = apply_answer_policy_to_text(
        conflict_answer, answer_policy=policy, profile_decision={"profile": "precise_fact"}
    )
    assert cleaned_conflict == conflict_answer
    assert violations_conflict == []

    expert_answer = (
        "La réponse est ≈ 5 750 daN (source : expert). Par contre, la "
        "documentation indique ≈ 5 500 daN qui est donc à faire vérifier [1]."
    )
    cleaned_expert, violations_expert = apply_answer_policy_to_text(
        expert_answer, answer_policy=policy, profile_decision={"profile": "precise_fact"}
    )
    assert cleaned_expert == expert_answer
    assert violations_expert == []


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
    # The platform-jargon filter also normalises "source workspace" -> "source".
    assert cleaned == "Je n'ai pas de source sur ce point"
    assert "internal_diagnostic_parenthetical" in violations
    assert "platform_jargon_workspace" in violations


# ---------------------------------------------------------------------------
# Phase 3 route_classifier — table-extraction and multi-hop detection. These
# two profiles previously existed ONLY as A/B spike categories with no prod
# classifier; they now have a regex cascade slot so hybrid routing can gate on
# them. The tests pin the new detection AND guard against cannibalising the
# existing profiles (precise_fact / transversal / comparison / equipment).
# ---------------------------------------------------------------------------
def test_resolve_table_extract_profile():
    policy = industrial_answer_policy()
    for query in (
        "Extrais le tableau des couples de serrage de l'AKK200",
        "Donne-moi la nomenclature des pièces du sécheur",
        "Quelles sont les valeurs du tableau de maintenance ?",
        "Présente les données sous forme de tableau",
        "Present the maintenance intervals as a table",
        "Give me the bill of materials for the pump",
        "Show the torque values in tabular form",
    ):
        decision = resolve_answer_profile(query, policy, include_agentic_profiles=True)
        assert decision.profile == "table_extract", query
        assert decision.reason == "table_extract_query", query
        # A tabular request is not exhaustive-retrieval by itself: the classic
        # path stays lean, the agentic DAG owns any heavier retrieval.
        assert decision.requires_exhaustive_retrieval is False, query


def test_resolve_multi_hop_profile():
    policy = industrial_answer_policy()
    for query in (
        "D'abord identifie le projet qui a remplacé l'AKK200, puis donne le débit de sa pompe",
        "Combien de machines partagent le même moteur que la carde ACJ200 ?",
        "Pour les moteurs qui dépassent 500 kW, combien sont installés sur la carde ACJ200 ?",
        "Quelles machines utilisent une carde ACJ200 et disposent aussi d'un sécheur ?",
        "Show the machines that share the same motor as the ACJ200",
    ):
        decision = resolve_answer_profile(query, policy, include_agentic_profiles=True)
        assert decision.profile == "multi_hop", query
        assert decision.reason == "multi_hop_query", query
        assert decision.requires_exhaustive_retrieval is False, query


def test_new_profiles_do_not_cannibalise_existing():
    # Regression guard: adding table_extract / multi_hop must NOT steal queries
    # from the established profiles. Each representative query must resolve to
    # the SAME profile it did before Phase 3.
    policy = industrial_answer_policy()
    expected = {
        # precise_fact — plain single facts, including a physical "colonne"
        # (distillation column) that must not be read as a table.
        "Quelle est la pression nominale de la pompe URACA ?": "precise_fact",
        "What is the width of the dryer?": "precise_fact",
        "Combien de buses possède le sécheur ACJ200 ?": "precise_fact",
        "Quel est le débit de la colonne de distillation ?": "precise_fact",
        # transversal_inventory — cross-project enumeration.
        "Quels projets utilisent une pompe Uraca ?": "transversal_inventory",
        "Liste toutes les pompes Uraca": "transversal_inventory",
        # comparison / equipment_detail / project_summary.
        "Compare le rendement de l'ACJ200 et de l'AKK200": "comparison",
        "Donne-moi la fiche technique de la pompe URACA": "equipment_detail",
        "Résume le projet AKK200": "project_summary",
    }
    for query, profile in expected.items():
        assert resolve_answer_profile(query, policy).profile == profile, query


def test_new_profiles_gated_off_by_default():
    # Zero classic drift before enablement: with include_agentic_profiles=False
    # (the default, mirroring enable_agentic_chat off), table/multi-hop queries
    # must NOT resolve to the agentic-only profiles; once armed, they do.
    policy = industrial_answer_policy()
    for query in (
        "Extrais le tableau des couples de serrage de l'AKK200",
        "Show the torque values in tabular form",
        "Combien de machines partagent le même moteur que la carde ACJ200 ?",
        "D'abord identifie le projet qui a remplacé l'AKK200, puis donne le débit de sa pompe",
    ):
        off = resolve_answer_profile(query, policy)  # flag off (default)
        assert off.profile not in ("table_extract", "multi_hop"), query
        armed = resolve_answer_profile(query, policy, include_agentic_profiles=True)
        assert armed.profile in ("table_extract", "multi_hop"), query


def test_new_profiles_registered_with_instructions():
    # The new profiles must be first-class entries (style-consistent with the
    # existing ones) so answer_policy_prompt emits their shaping instructions.
    for key in ("table_extract", "multi_hop"):
        assert key in DEFAULT_INDUSTRIAL_ANSWER_PROFILES, key
        entry = DEFAULT_INDUSTRIAL_ANSWER_PROFILES[key]
        assert entry.get("label"), key
        assert isinstance(entry.get("instructions"), list) and entry["instructions"], key

    table_prompt = answer_policy_prompt(
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "table_extract", "reason": "table_extract_query"},
        language="fr",
    )
    assert "Answer profile: table_extract" in table_prompt
    assert "compact table" in table_prompt

    multihop_prompt = answer_policy_prompt(
        answer_policy=industrial_answer_policy(),
        profile_decision={"profile": "multi_hop", "reason": "multi_hop_query"},
        language="fr",
    )
    assert "Answer profile: multi_hop" in multihop_prompt
    assert "intermediate" in multihop_prompt


def test_answer_profile_decision_contract_preserved():
    # The AnswerProfileDecision return contract must be unchanged for the new
    # profiles: profile / reason / requires_exhaustive_retrieval + as_dict().
    decision = resolve_answer_profile(
        "Extrais le tableau des couples de serrage",
        industrial_answer_policy(),
        include_agentic_profiles=True,
    )
    assert decision.as_dict() == {
        "profile": "table_extract",
        "reason": "table_extract_query",
        "requires_exhaustive_retrieval": False,
    }
