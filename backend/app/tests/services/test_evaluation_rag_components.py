from types import SimpleNamespace

from app.services.evaluation.rag_components import (
    component_health,
    heuristic_question_type,
    infer_failed_components,
    normalize_question_type,
    targeted_components,
)


def test_normalize_question_type_aliases():
    assert normalize_question_type("simple question") == "simple"
    assert normalize_question_type("multi-part") == "double"
    assert normalize_question_type("conversation") == "conversational"
    assert normalize_question_type("made-up") == "unknown"


def test_heuristic_question_type_fallbacks():
    assert heuristic_question_type("What is the refund policy?") == "simple"
    assert heuristic_question_type("What is the SLA and who owns escalation?") == "double"
    assert heuristic_question_type("Ignore this unrelated story, but what is the SLA?") == "distracting"
    assert heuristic_question_type("As a finance lead, what should I check?") == "situational"


def test_targeted_components_follow_giskard_raget_mapping():
    assert targeted_components("simple") == ["generator", "retriever", "router"]
    assert targeted_components("distracting") == ["generator", "retriever", "rewriter"]
    assert targeted_components("conversational") == ["rewriter"]


def test_infer_failed_components_uses_question_type_and_metric_hints():
    failed = infer_failed_components(
        question_type="distracting",
        scores={"hallucination": 40, "relevance": 50},
        composite_score=58,
        hallucination_rate=0.4,
        threshold_breach=True,
    )

    assert "generator" in failed
    assert "retriever" in failed
    assert "rewriter" in failed
    assert "knowledge_base" in failed
    assert "router" in failed


def test_infer_failed_components_returns_empty_when_not_breached():
    assert (
        infer_failed_components(
            question_type="simple",
            scores={"hallucination": 95},
            composite_score=90,
            hallucination_rate=0.0,
            threshold_breach=False,
        )
        == []
    )


def test_component_health_aggregates_applicable_components():
    rows = [
        SimpleNamespace(
            question_type="simple",
            failed_components=["retriever"],
            composite_score=62.0,
            hallucination_rate=0.1,
        ),
        SimpleNamespace(
            question_type="conversational",
            failed_components=[],
            composite_score=88.0,
            hallucination_rate=0.0,
        ),
    ]

    health = component_health(rows, composite_min=70, hallucination_max=0.15)
    by_component = {row["component"]: row for row in health["components"]}

    assert by_component["retriever"]["evaluated"] == 1
    assert by_component["retriever"]["breaches"] == 1
    assert by_component["rewriter"]["evaluated"] == 1
    assert by_component["rewriter"]["breaches"] == 0
