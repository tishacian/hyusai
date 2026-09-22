import pytest

from app.services.automation_portfolio import (
    AutomationPortfolioRefusal,
    job_explanation,
    run_package,
    work_job,
)


def _system(**overrides):
    body = {
        "id": "sys-1",
        "name": "Minutes",
        "status": "active",
        "objective": "Draft the meeting minutes.",
    }
    body.update(overrides)
    return body


def _job():
    return work_job(
        _system(),
        variant="automation_v1",
        published_version_id="ver-1",
        flow_sha256="a" * 64,
    )


def test_a_published_automation_is_a_work_job():
    job = _job()
    assert job["kind"] == "automation_work_job"
    assert job["objective_status"] == "stated"
    assert job["published_version_id"] == "ver-1"


def test_a_draft_automation_is_not_a_work_job():
    with pytest.raises(AutomationPortfolioRefusal) as refusal:
        work_job(
            _system(status="draft"),
            variant="automation_v1",
            published_version_id=None,
            flow_sha256=None,
        )
    assert refusal.value.code == "unpublished"


def test_another_flow_variant_is_not_an_automation_job():
    with pytest.raises(AutomationPortfolioRefusal) as refusal:
        work_job(
            _system(),
            variant="chat_agentic_thinking_v1",
            published_version_id="ver-1",
            flow_sha256="a" * 64,
        )
    assert refusal.value.code == "not_automation"


def test_a_missing_objective_stays_absent():
    job = work_job(
        _system(objective="  "),
        variant="automation_v1",
        published_version_id="ver-1",
        flow_sha256="a" * 64,
    )
    assert job["objective_status"] == "absent"
    assert job["objective"] is None


def test_package_keeps_an_absent_convention_and_drops_source_text():
    package = run_package(
        _job(),
        {
            "id": "run-1",
            "system_id": "sys-1",
            "status": "completed",
            "flow_sha256": "a" * 64,
            "execution_surface": "published_manual",
        },
        convention=None,
        proof={
            "decision_status": "proposed",
            "sap": {"sealed": True, "called": False, "reason": "unattended"},
            "citations": [{
                "source": "doc-1",
                "passage": "The laptop request is approved.",
            }],
        },
    )
    assert package["convention"] == {"status": "absent"}
    assert package["gap"] == {"status": "absent"}
    assert package["proof"]["citations"] == [{"run_id": "run-1", "source": "doc-1"}]
    assert package["proof"]["sap"] == {"sealed": True, "called": False}
    assert "passage" not in str(package)


def test_a_declared_convention_is_named_and_not_turned_into_a_saving():
    package = run_package(
        _job(),
        {
            "id": "run-1",
            "system_id": "sys-1",
            "status": "completed",
            "flow_sha256": "a" * 64,
            "execution_surface": "published_manual",
            "value_estimated": 4800,
        },
        convention={
            "status": "declared",
            "unit": "brief",
            "currency": "EUR",
            "value_per_unit": 6,
            "declared_by": "controller",
            "declared_at": "2026-08-01T00:00:00",
        },
    )
    assert package["convention"]["status"] == "declared"
    assert package["convention"]["value_per_unit"] == 6
    assert "value_estimated" not in package["proof"]
    assert 4800 not in package["convention"].values()


def test_without_a_run_the_proof_stays_absent():
    explained = job_explanation(_job(), None)
    assert explained["proof"] is None
    assert explained["convention"] == {"status": "absent"}
    assert explained["gap"] == {"status": "absent"}


def test_a_draft_test_is_not_portfolio_proof():
    with pytest.raises(AutomationPortfolioRefusal) as refusal:
        run_package(
            _job(),
            {
                "id": "run-1",
                "system_id": "sys-1",
                "status": "hitl_pending",
                "flow_sha256": "a" * 64,
                "execution_surface": "draft_test",
            },
        )
    assert refusal.value.code == "draft_not_proof"


def test_a_run_from_another_publication_is_refused():
    with pytest.raises(AutomationPortfolioRefusal) as refusal:
        run_package(
            _job(),
            {
                "id": "run-1",
                "system_id": "sys-1",
                "status": "completed",
                "flow_sha256": "b" * 64,
                "execution_surface": "published_manual",
            },
        )
    assert refusal.value.code == "stale_proof"
