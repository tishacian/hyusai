"""L33 — Work home receipts are measured on the Run or left unknown."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.experience.work_receipt import agent_work_ms, run_receipt, steps_done


def _run(**fields):
    base = {"checkpoints": [], "duration_ms": None, "output_ref": {}}
    base.update(fields)
    return SimpleNamespace(**base)


def _call(slug: str, output: dict):
    return SimpleNamespace(skill_slug=slug, output_ref=output)


def test_unknown_fields_stay_unknown() -> None:
    assert run_receipt(_run()) == {
        "steps": None,
        "agent_ms": None,
        "write": None,
        "passages_read": None,
        "passages_cited": None,
    }


def test_steps_fall_back_to_recorded_calls_only() -> None:
    assert steps_done(_run(), [_call("a", {}), _call("b", {})]) == 2
    closed = _run(checkpoints=[{"kind": "node_end", "node_id": "x"}, {"kind": "node_end", "node_id": "x"}])
    assert steps_done(closed, [_call("a", {})]) == 1


def test_duration_without_stamps_is_used_only_without_a_human_wait() -> None:
    assert agent_work_ms(_run(duration_ms=1800)) == 1800
    assert agent_work_ms(_run(duration_ms=1800, checkpoints=[{"kind": "hitl_pause"}])) is None


def test_write_outcome_and_passages() -> None:
    receipt = run_receipt(
        _run(output_ref={"citations": [1]}),
        [_call("sap_create_po_v1", {"called": True}), _call("semantic_search_v1", {"results": [1, 2]})],
    )
    assert receipt["write"] == "done"
    assert receipt["passages_read"] == 2
    assert receipt["passages_cited"] == 1
