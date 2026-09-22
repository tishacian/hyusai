from app.services.systems.preparation_diagnostic import preparation_diagnostic


def _flow(*nodes):
    return {"nodes": list(nodes)}


def _skill(slug: str):
    return {"id": slug, "kind": "task", "config": {"skill_slug": slug}}


def test_six_checks_are_named_and_an_unperformed_check_is_not_ready():
    report = preparation_diagnostic(None)
    assert [item["name"] for item in report["checks"]] == [
        "model",
        "provider",
        "source",
        "indexing",
        "rights",
        "worker",
    ]
    assert report["ready"] is False
    assert {item["status"] for item in report["checks"]} <= {"not_checked", "not_applicable"}


def test_workspace_model_with_a_trigger_is_ready_only_for_the_checks_performed():
    report = preparation_diagnostic(
        _flow(
            {"id": "trigger", "kind": "source"},
            _skill("workspace_llm_v1"),
            {"id": "output", "kind": "sink"},
        ),
        provider="openai",
        caller_can_run=True,
    )
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["model"] == {"name": "model", "status": "ready", "detail": "workspace_llm_v1"}
    assert by_name["provider"]["status"] == "ready"
    assert by_name["source"]["status"] == "ready"
    assert by_name["indexing"]["status"] == "not_applicable"
    assert by_name["rights"]["status"] == "ready"
    assert by_name["worker"]["status"] == "not_checked"
    assert report["ready"] is False


def test_a_retrieval_skill_blocks_the_model_and_leaves_indexing_unchecked():
    report = preparation_diagnostic(_flow(_skill("llm_rag_answer_v1")))
    by_name = {item["name"]: item for item in report["checks"]}
    assert by_name["model"]["status"] == "blocked"
    assert by_name["model"]["detail"] == "llm_rag_answer_v1"
    assert by_name["indexing"]["status"] == "not_checked"
    assert report["ready"] is False


def test_a_caller_who_cannot_run_is_a_blocked_rights_check():
    report = preparation_diagnostic(_flow({"id": "trigger", "kind": "source"}), caller_can_run=False)
    rights = next(item for item in report["checks"] if item["name"] == "rights")
    assert rights["status"] == "blocked"
