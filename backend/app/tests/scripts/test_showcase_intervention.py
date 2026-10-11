"""The second R1 resource must not invent another NorthForge dataset."""
from scripts.showcase_intervention import history_document, REFERENCE_CASES
from scripts.showcase_operational_analysis import ROWS


def test_history_uses_the_existing_orders_and_keeps_unknowns_explicit():
    text = history_document()
    assert text.count("## NF-") == len(ROWS)
    for row in ROWS:
        section = text.split(f"## {row['order']}\n", 1)[1].split("## ", 1)[0]
        assert f"Planned duration: {row['planned_minutes']} minutes." in section
        assert f"Actual duration: {row['actual_minutes']} minutes." in section
        assert "Cause: not supplied. Equipment: not supplied." in section
    assert REFERENCE_CASES[0]["resource"] != REFERENCE_CASES[1]["resource"]


def test_tools_use_distinct_frozen_native_retrieval_resources():
    from scripts.showcase_intervention import retrieval_tool_specs
    from app.services.skills_registry.executors import validate_executor_binding
    specs = retrieval_tool_specs('notices', 'history')
    assert [spec['executor']['params']['frozen_input']['context_collection'] for spec in specs] == ['notices', 'history']
    for spec in specs:
        validate_executor_binding(spec['executor'])
        assert spec['input_schema']['additionalProperties'] is False
