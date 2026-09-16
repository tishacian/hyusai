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
