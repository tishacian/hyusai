"""Reading a Business Requirements document into draft material.

The parser is pinned to the template's *headers*, not to table positions: a
section inserted upstream must not silently shift what "requirements" means.
And a document it cannot make sense of has to degrade into an empty answer
with a sentence, because the wizard opens either way.
"""
from __future__ import annotations

import io

import pytest

from app.services.skills_registry.brd_import import (
    BrdUnreadableError,
    parse_business_requirements,
)

docx = pytest.importorskip("docx")


def _table(document, header, rows):
    table = document.add_table(rows=1 + len(rows), cols=len(header))
    for column, text in enumerate(header):
        table.cell(0, column).text = text
    for index, row in enumerate(rows, start=1):
        for column, text in enumerate(row):
            table.cell(index, column).text = text
    return table


def _document(**overrides) -> bytes:
    document = docx.Document()
    document.add_heading("1.  Context & objective", level=1)
    document.add_paragraph("Client / entity : Estithmar, healthcare, 4000 staff")
    document.add_paragraph("Sponsor & business owner : ‹ who owns the outcome ›")
    document.add_heading("2.  Primary persona", level=1)
    document.add_paragraph("Persona & volume : ignored, this is not section 1")

    _table(
        document,
        ["ID", "Business outcome", "Why it matters", "Target signal"],
        overrides.get("outcomes", [["BO-1", "Answer tickets in an hour", "SLA", "median < 60m"]]),
    )
    _table(
        document,
        ["ID", "Requirement", "Priority (M/S/C/W)", "Maps to capability"],
        overrides.get(
            "requirements",
            [
                ["FR-1", "Draft a reply from the ticket history", "M", "Ticket triage"],
                ["FR-2", "", "", ""],
            ],
        ),
    )
    _table(
        document,
        ["Step", "Actor", "Systems", "Time", "Pain point"],
        [["Read the ticket", "Agent", "ITSM", "5m", "context switching"]],
    )
    _table(
        document,
        ["ID", "Decision", "Inputs", "Possible outcomes", "Threshold / default-if-uncertain", "Escalation"],
        overrides.get(
            "decisions",
            [["D1", "Reply or escalate", "ticket, history", "reply | escalate", "confidence < 0.7", "L2"]],
        ),
    )
    _table(
        document,
        ["ID", "Rule (IF … THEN …)", "Source / rationale"],
        [["R1", "IF the ticket mentions billing THEN route to finance", "policy"]],
    )
    _table(document, ["ID", "The agent must never…"], [["N1", "Invent a refund amount"]])
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_the_traceability_chain_is_what_the_parser_returns():
    parsed = parse_business_requirements(_document())

    assert parsed["problems"] == []
    assert parsed["outcomes"] == [
        {
            "id": "BO-1",
            "outcome": "Answer tickets in an hour",
            "why": "SLA",
            "signal": "median < 60m",
        }
    ]
    assert parsed["requirements"] == [
        {
            "id": "FR-1",
            "requirement": "Draft a reply from the ticket history",
            "priority": "M",
            "capability": "Ticket triage",
        }
    ]
    assert parsed["decisions"][0]["threshold"] == "confidence < 0.7"
    assert parsed["guardrails"] == [
        {
            "id": "R1",
            "text": "IF the ticket mentions billing THEN route to finance",
            "kind": "rule",
        },
        {"id": "N1", "text": "Invent a refund amount", "kind": "prohibition"},
    ]


def test_section_one_is_read_and_the_unfilled_placeholders_are_not():
    parsed = parse_business_requirements(_document())

    assert parsed["context"] == [
        {"label": "Client / entity", "value": "Estithmar, healthcare, 4000 staff"}
    ]


def test_the_process_and_quality_tables_are_left_alone():
    """Only the four chains a Skill can be drafted from are read; the as-is
    steps are a description of today, not a requirement."""

    parsed = parse_business_requirements(_document())

    flattened = str(parsed)
    assert "context switching" not in flattened


def test_a_blank_template_yields_no_rows_and_no_complaint():
    parsed = parse_business_requirements(
        _document(outcomes=[["BO-1", "", "", ""]], requirements=[["FR-1", "", "", ""]], decisions=[])
    )

    assert parsed["outcomes"] == []
    assert parsed["requirements"] == []
    assert parsed["problems"] == []


def test_a_missing_table_is_a_sentence_not_an_exception():
    document = docx.Document()
    document.add_paragraph("A memo that is not the template at all.")
    buffer = io.BytesIO()
    document.save(buffer)

    parsed = parse_business_requirements(buffer.getvalue())

    assert parsed["requirements"] == []
    assert any("functional requirements" in problem for problem in parsed["problems"])
    assert len(parsed["problems"]) == 5


def test_a_file_that_is_not_a_word_document_is_refused_clearly():
    with pytest.raises(BrdUnreadableError):
        parse_business_requirements(b"this is not a docx")


def test_the_shipped_template_parses_without_complaint():
    """The blank template every client receives must at least be recognised,
    or the import screen would open on a wall of missing-table warnings."""

    from pathlib import Path

    template = (
        Path(__file__).resolve().parents[4]
        / "docs/render/out/Datategy-Template-Business-Requirements.docx"
    )
    if not template.exists():  # pragma: no cover - the repo ships it
        pytest.skip("template not present in this checkout")

    parsed = parse_business_requirements(template.read_bytes())

    assert parsed["problems"] == []
