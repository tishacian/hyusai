"""Reading a Business Requirements document into draft material.

The parser is pinned to the template's *headers*, not to table positions: a
section inserted upstream must not silently shift what "requirements" means.
And a document it cannot make sense of has to degrade into an empty answer
with a sentence, because the wizard opens either way.
"""
from __future__ import annotations

import io
import hashlib
import zipfile

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


def test_import_identifies_exact_document_and_reports_ambiguous_references():
    data = _document(requirements=[["FR-1", "First", "M", ""], ["FR-1", "Second", "M", ""]])
    parsed = parse_business_requirements(data)
    assert parsed["document"] == {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    assert len(parsed["requirements"]) == 2
    assert any("Duplicate reference FR-1" in p for p in parsed["problems"])


def test_missing_descriptions_and_truncation_are_not_silently_complete():
    data = _document(requirements=[["FR-1", "", "M", ""], ["FR-2", "x" * 2001, "M", ""]])
    parsed = parse_business_requirements(data)
    assert any("has no description" in p for p in parsed["problems"])
    assert any("truncated" in p for p in parsed["problems"])
    assert len(parsed["requirements"][1]["requirement"]) == 2000


def test_expanded_archive_is_bounded_before_word_parsing(monkeypatch):
    from app.services.skills_registry import brd_import
    monkeypatch.setattr(brd_import, "_MAX_EXPANDED_BYTES", 1024)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "x" * 2048)
    with pytest.raises(BrdUnreadableError, match="expanded document"):
        parse_business_requirements(archive.getvalue())


def test_provenance_distinguishes_duplicate_ids_and_keeps_word_row_positions():
    data = _document(requirements=[
        ["FR-1", "First", "M", ""],
        ["FR-2", "", "", ""],
        ["FR-1", "Second", "M", ""],
        ["", "Third", "M", ""],
    ])
    parsed = parse_business_requirements(data)
    sources = [p for p in parsed["provenance"] if p["section"] == "functional requirements"]
    assert [(p["reference"], p["table"], p["row"], p["reference_generated"]) for p in sources] == [
        ("FR-1", 2, 2, False), ("FR-1", 2, 4, False), ("FR-4", 2, 5, True),
    ]


def test_second_requirements_table_is_reported_instead_of_silently_discarded():
    document = docx.Document(io.BytesIO(_document()))
    _table(document, ["ID", "Requirement", "Priority", "Capability"], [["FR-9", "Critical prohibition", "M", ""]])
    buffer = io.BytesIO()
    document.save(buffer)
    parsed = parse_business_requirements(buffer.getvalue())
    assert any("Multiple functional requirements tables" in p for p in parsed["problems"])
    assert len(parsed["requirements"]) == 1
    assert all(p["table"] != 7 for p in parsed["provenance"])


def test_northforge_acceptance_cases_are_retained_with_source_positions():
    from pathlib import Path
    from app.services.skills_registry.brd_import import parse_business_requirements
    data = (Path(__file__).parents[1] / "fixtures/brd/northforge-intervention.docx").read_bytes()
    parsed = parse_business_requirements(data)
    cases = parsed["acceptance_cases"]
    assert len(cases) == 5
    assert "700 bar" in cases[0]["text"]
    assert "30 and 55 minutes" in cases[1]["text"]
    assert "Refuse mutations" in cases[3]["text"]
    assert all(case["paragraph"] > 0 for case in cases)
