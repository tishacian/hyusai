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
    def_strip_chunk = next(chunk for chunk in parsed.chunks if chunk["sheet_name"] == "Def strips")
    assert "B2=85" in def_strip_chunk["content"]
    assert "B = 85" in def_strip_chunk["content"]
    assert def_strip_chunk["row_start"] == 1
    assert def_strip_chunk["row_end"] == 4
    assert def_strip_chunk["cell_range"] == "A1:B4"
    assert def_strip_chunk["source_path"] == str(workbook_path)


@pytest.mark.asyncio
async def test_spreadsheet_parser_rejects_legacy_xls_without_text_fallback(tmp_path):
    workbook_path = tmp_path / "legacy.xls"
    workbook_path.write_bytes(b"not parsed as text")

    parser = DocumentParserFactory.get_parser(str(workbook_path))

    with pytest.raises(ValueError, match="Legacy .xls spreadsheets are not supported"):
        await parser.parse(str(workbook_path))
