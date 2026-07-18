from __future__ import annotations

import pytest

from app.services.document_parser.base import DocumentType
from app.services.document_parser.factory import DocumentParserFactory


@pytest.mark.asyncio
async def test_spreadsheet_parser_extracts_def_strip_label_values(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook_path = tmp_path / "GEOTEX-SPL-Y25.05.22-PIL.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Def strips"
    sheet.append(["A", 80])
    sheet.append(["B", 85])
    sheet.append(["C", 90])
    sheet.append(["D", 95])
    protocol = workbook.create_sheet("Protocole essais")
    protocol.append(["Customer", "GEOTEX"])
    protocol.append(["trials N°", "A1", "A2", "3B"])
    workbook.save(workbook_path)

    parser = DocumentParserFactory.get_parser(str(workbook_path))
    parsed = await parser.parse(str(workbook_path), spreadsheet_rows_per_chunk=20)

    assert parsed.document_type == DocumentType.SPREADSHEET
    assert parsed.structured_content["sheet_count"] == 2
    assert any(chunk["sheet_name"] == "Def strips" for chunk in parsed.chunks)
    def_strip_chunk = next(
        chunk
        for chunk in parsed.chunks
        if chunk["sheet_name"] == "Def strips" and chunk.get("semantic_type") == "spreadsheet_row"
    )
    assert "B2=85" in def_strip_chunk["content"]
    assert "B = 85" in def_strip_chunk["content"]
    assert def_strip_chunk["row_start"] == 1
    assert def_strip_chunk["row_end"] == 4
    assert def_strip_chunk["cell_range"] == "A1:B4"
    assert def_strip_chunk["source_path"] == str(workbook_path)

    fact_chunk = next(
        chunk
        for chunk in parsed.chunks
        if chunk["sheet_name"] == "Def strips"
        and chunk.get("semantic_type") == "spreadsheet_cell_fact"
        and chunk.get("row_label") == "B"
    )
    assert 'Spreadsheet cell fact: sheet="Def strips" row=2 label="B" value="85"' in fact_chunk[
        "content"
    ]
    assert "B = 85" in fact_chunk["content"]
    assert fact_chunk["cell_ref"] == "B2"
    assert parsed.structured_content["table_artifacts"]["cell_facts"]


@pytest.mark.asyncio
async def test_spreadsheet_parser_extracts_interpreted_cell_facts(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook_path = tmp_path / "non-wovens.xlsx"
    workbook = openpyxl.Workbook()

    protocol = workbook.active
    protocol.title = "Protocole essais"
    protocol.append(["Customer", "GEOTEX"])
    protocol.append(["DATE", "2025-05-21"])
    protocol.append(["trials N°", "1", "2A", "3"])
    protocol.append(["Length (mm)", 10, "non roui", 30])

    test_sheet = workbook.create_sheet("test 2")
    test_sheet.append(["Sample", "1", "2", "Avg"])
    test_sheet.append(["Weight (g/m²)", 122, 124, 123])

    workbook.save(workbook_path)

    parser = DocumentParserFactory.get_parser(str(workbook_path))
    parsed = await parser.parse(str(workbook_path), spreadsheet_rows_per_chunk=20)

    protocol_facts = "\n".join(
        chunk["content"]
        for chunk in parsed.chunks
        if chunk["sheet_name"] == "Protocole essais"
        and chunk.get("semantic_type") in {"spreadsheet_schema", "spreadsheet_table_fact"}
    )
    assert 'Spreadsheet schema: sheet="Protocole essais" header_row=3' in protocol_facts
    assert 'cell=C4 value="non roui" row_label="Length (mm)"' in protocol_facts
    assert 'column_header="2A"' in protocol_facts

    test_facts = "\n".join(
        chunk["content"]
        for chunk in parsed.chunks
        if chunk["sheet_name"] == "test 2"
        and chunk.get("semantic_type") == "spreadsheet_table_fact"
    )
    assert 'cell=D2 value="123" row_label="Weight (g/m²)"' in test_facts
    assert 'column_header="Avg"' in test_facts
    assert 'metric="Weight (g/m²)"' in test_facts
    assert any(
        fact.get("cell_ref") == "D2" and fact.get("unit") == "g/m²"
        for fact in parsed.structured_content["table_artifacts"]["table_facts"]
    )


@pytest.mark.asyncio
async def test_spreadsheet_parser_extracts_csv_table_artifacts(tmp_path):
    csv_path = tmp_path / "measurements.csv"
    csv_path.write_text("Sample,Weight (g/m²),Strip\n2A,123,J7\n", encoding="utf-8")

    parser = DocumentParserFactory.get_parser(str(csv_path))
    parsed = await parser.parse(str(csv_path), spreadsheet_rows_per_chunk=20)

    assert parsed.document_type == DocumentType.CSV
    assert parsed.structured_content["table_artifacts"]["workbook_schema"]["sheet_count"] == 1
    facts = "\n".join(
        chunk["content"]
        for chunk in parsed.chunks
        if chunk.get("semantic_type") == "spreadsheet_table_fact"
    )
    assert 'cell=B2 value="123"' in facts
    assert 'row_label="2A"' in facts
    assert 'column_header="Weight (g/m²)"' in facts


@pytest.mark.asyncio
async def test_spreadsheet_parser_converts_legacy_xls_without_text_fallback(
    tmp_path, monkeypatch
):
    openpyxl = pytest.importorskip("openpyxl")
    workbook_path = tmp_path / "legacy.xls"
    workbook_path.write_bytes(b"legacy-binary-container")

    def fake_run(command, **_kwargs):
        output_dir = command[command.index("--outdir") + 1]
        converted = openpyxl.Workbook()
        converted.active.append(["Project", "61038"])
        converted.save(f"{output_dir}/legacy.xlsx")
        return type("Completed", (), {"returncode": 0, "stderr": b"", "stdout": b""})()

    monkeypatch.setattr(
        "app.services.document_parser.parsers.spreadsheet_parser.subprocess.run",
        fake_run,
    )

    parser = DocumentParserFactory.get_parser(str(workbook_path))
    parsed = await parser.parse(str(workbook_path))

    assert parsed.document_type == DocumentType.SPREADSHEET
    assert parsed.metadata["conversion"] == "libreoffice_xlsx"
    assert any("61038" in chunk["content"] for chunk in parsed.chunks)
