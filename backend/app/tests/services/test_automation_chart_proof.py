from app.services.automation_chart import AutomationChartRefusal, freeze_chart, open_point
from app.services.automation_dossiers import dossier_rows
from app.services.automation_proof import proof_identity, same_proof


def _rows():
    datasets = [
        {"name": "Omar", "slug": "laptop", "version": 1, "system_id": "sys", "run_id": "run-1", "status": "ready"},
        {"name": "Maya", "slug": "desk", "version": 1, "system_id": "sys", "run_id": None, "status": "ready"},
    ]
    runs = {"run-1": {"system_id": "sys", "status": "completed"}}
    return dossier_rows(datasets, runs)


def test_the_chart_is_frozen_and_a_point_without_proof_has_no_run():
    rows = _rows()
    first = freeze_chart(rows)
    second = freeze_chart(rows)
    assert first["hash"] == second["hash"]
    assert len(first["points"]) == 2
    opened = open_point(first, "laptop:1")
    assert opened["dossier"]["name"] == "Omar"
    assert opened["run"] == {"id": "run-1", "status": "completed"}
    missing = open_point(first, "desk:1")
    assert missing["dossier"]["proof"] == "absent"
    assert missing["run"] is None


def test_an_unknown_point_is_refused():
    chart = freeze_chart(_rows())
    try:
        open_point(chart, "missing:1")
    except AutomationChartRefusal as refusal:
        assert refusal.code == "point_unknown"
    else:
        raise AssertionError("expected point_unknown")


def test_work_conversation_and_api_share_one_proof():
    card = {
        "convention": {"status": "absent"},
        "gap": {"status": "absent"},
        "proof": {
            "run_id": "run-1",
            "status": "completed",
            "sap": {"sealed": True, "called": False},
            "citations": [{"source": "src-1", "passage": "secret text"}],
        },
    }
    assert same_proof(card, card, card)
    identity = proof_identity(card)
    assert identity["sources"] == ["src-1"]
    assert "secret text" not in str(identity)
    assert identity["sealed"] is True
    assert identity["called"] is False
    assert proof_identity(None)["status"] == "absent"
    assert proof_identity(None)["run_id"] is None
