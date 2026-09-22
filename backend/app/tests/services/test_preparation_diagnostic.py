from app.services.systems.preparation_diagnostic import (
    caller_run_right,
    preparation_diagnostic,
    provider_name,
)


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


def test_a_reachable_runner_makes_the_performed_checks_ready():
    report = preparation_diagnostic(
        _flow(
            {"id": "trigger", "kind": "source"},
            _skill("workspace_llm_v1"),
            {"id": "output", "kind": "sink"},
        ),
        provider="openai",
        caller_can_run=True,
        worker_reachable=True,
    )
    worker = next(item for item in report["checks"] if item["name"] == "worker")
    assert worker["status"] == "ready"
    assert report["ready"] is True


def test_a_silent_runner_is_blocked_and_an_unknown_runner_stays_unchecked():
    blocked = preparation_diagnostic(None, worker_reachable=False)
    unknown = preparation_diagnostic(None, worker_reachable=None)
    assert next(item for item in blocked["checks"] if item["name"] == "worker")["status"] == "blocked"
    assert next(item for item in unknown["checks"] if item["name"] == "worker")["status"] == "not_checked"
    assert blocked["ready"] is False
    assert unknown["ready"] is False


def test_a_caller_who_cannot_run_is_a_blocked_rights_check():
    report = preparation_diagnostic(_flow({"id": "trigger", "kind": "source"}), caller_can_run=False)
    rights = next(item for item in report["checks"] if item["name"] == "rights")
    assert rights["status"] == "blocked"


def test_a_named_provider_is_ready_even_when_routing_is_global():
    assert provider_name({"default_provider": "openai", "source": "global"}) == "openai"
    assert provider_name({"default_provider": "  "}) is None
    assert provider_name(None) is None
    report = preparation_diagnostic(None, provider=provider_name({"default_provider": "openai", "source": "global"}))
    provider = next(item for item in report["checks"] if item["name"] == "provider")
    assert provider["status"] == "ready"
    assert provider["detail"] == "openai"
    worker = next(item for item in report["checks"] if item["name"] == "worker")
    assert worker["status"] == "not_checked"
    assert report["ready"] is False


def test_run_authority_403_blocks_rights_and_other_errors_stay_unchecked():
    assert caller_run_right(None) is True
    assert caller_run_right(403) is False
    assert caller_run_right(400) is None
    allowed = preparation_diagnostic(None, caller_can_run=caller_run_right(None))
    refused = preparation_diagnostic(None, caller_can_run=caller_run_right(403))
    unanswered = preparation_diagnostic(None, caller_can_run=caller_run_right(400))
    assert next(item for item in allowed["checks"] if item["name"] == "rights")["status"] == "ready"
    assert next(item for item in refused["checks"] if item["name"] == "rights")["status"] == "blocked"
    assert next(item for item in unanswered["checks"] if item["name"] == "rights")["status"] == "not_checked"
