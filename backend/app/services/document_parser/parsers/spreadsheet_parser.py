"""Spreadsheet parser for Excel workbooks."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.services.document_parser.base import BaseDocumentParser, DocumentType, ParsedDocument


_SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
_MAX_ROWS_PER_CHUNK = 80
_MAX_SHEET_ROWS = 5_000
_MAX_SHEET_COLS = 80


class SpreadsheetParser(BaseDocumentParser):
    """Parse Excel workbooks into RAG-friendly row/table chunks."""

    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        path = Path(file_path)
        if path.suffix.lower() == ".xls":
            raise ValueError("Legacy .xls spreadsheets are not supported for Knowledge ingestion yet")
        if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported spreadsheet extension: {path.suffix}")

        metadata = await self.extract_metadata(file_path)
        rows_per_chunk = _safe_positive_int(kwargs.get("spreadsheet_rows_per_chunk"), _MAX_ROWS_PER_CHUNK)
        max_sheet_rows = _safe_positive_int(kwargs.get("spreadsheet_max_rows"), _MAX_SHEET_ROWS)
        max_sheet_cols = _safe_positive_int(kwargs.get("spreadsheet_max_cols"), _MAX_SHEET_COLS)

        loop = asyncio.get_event_loop()
        parsed = await loop.run_in_executor(
            None,
            lambda: self._parse_workbook(
                path,
                rows_per_chunk=rows_per_chunk,
                max_sheet_rows=max_sheet_rows,
                max_sheet_cols=max_sheet_cols,
            ),
        )

        metadata.update(
            {
                "source_path": file_path,
                "sheet_count": len(parsed["sheets"]),
                "spreadsheet_truncated": parsed["truncated"],
            }
        )
        raw_content = "\n\n".join(chunk["content"] for chunk in parsed["chunks"])

        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=path.name,
            file_path=file_path,
            document_type=DocumentType.SPREADSHEET,
            raw_content=raw_content,
            structured_content={
                "sheet_count": len(parsed["sheets"]),
                "sheets": parsed["sheets"],
                "chunks_count": len(parsed["chunks"]),
                "truncated": parsed["truncated"],
            },
            metadata=metadata,
            chunks=parsed["chunks"],
            images=[],
            tables=parsed["tables"],
            code_blocks=[],
            entities=[],
            relationships=[],
            language="unknown",
            encoding="binary",
            file_size=metadata["file_size"],
            created_at=metadata["created_at"],
            modified_at=metadata["modified_at"],
        )

    def supports(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in _SUPPORTED_EXTENSIONS

    def _parse_workbook(
        self,
        path: Path,
        *,
        rows_per_chunk: int,
        max_sheet_rows: int,
        max_sheet_cols: int,
    ) -> dict[str, Any]:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError("Excel parsing requires openpyxl to ingest modern spreadsheet files") from exc

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            chunks: list[dict[str, Any]] = []
            sheets: list[dict[str, Any]] = []
            tables: list[dict[str, Any]] = []
            current_pos = 0
            truncated = False

            for worksheet in workbook.worksheets:
                rows = self._extract_rows(
                    worksheet,
                    max_sheet_rows=max_sheet_rows,
                    max_sheet_cols=max_sheet_cols,
                )
                truncated = truncated or bool(rows["truncated"])
                sheets.append(
                    {
                        "name": worksheet.title,
                        "rows": len(rows["rows"]),
                        "max_row": worksheet.max_row,
                        "max_column": worksheet.max_column,
                        "truncated": rows["truncated"],
                    }
                )
                if rows["rows"]:
                    tables.append(
                        {
                            "sheet_name": worksheet.title,
                            "rows": rows["rows"][:50],
                            "truncated": rows["truncated"] or len(rows["rows"]) > 50,
                        }
                    )

                for batch in _batched(rows["rows"], rows_per_chunk):
                    content = self._render_chunk(worksheet.title, batch)
                    row_start = batch[0]["row_index"]
                    row_end = batch[-1]["row_index"]
                    cell_range = f"A{row_start}:{_column_letter(rows['max_col'])}{row_end}"
                    start_char = current_pos
                    end_char = start_char + len(content)
                    chunks.append(
                        {
                            "content": content,
                            "start_char": start_char,
                            "end_char": end_char,
                            "chunk_index": len(chunks),
                            "sheet_name": worksheet.title,
                            "row_start": row_start,
                            "row_end": row_end,
                            "cell_range": cell_range,
                            "source_path": str(path),
                        }
                    )
                    current_pos = end_char + 2

            return {"chunks": chunks, "sheets": sheets, "tables": tables, "truncated": truncated}
        finally:
            workbook.close()

    def _extract_rows(self, worksheet: Any, *, max_sheet_rows: int, max_sheet_cols: int) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        max_col_seen = 1
        truncated = False
        for row_index, row in enumerate(
            worksheet.iter_rows(max_row=max_sheet_rows + 1, max_col=max_sheet_cols, values_only=True),
            start=1,
        ):
            if row_index > max_sheet_rows:
                truncated = True
                break
            cells = []
            for col_index, value in enumerate(row, start=1):
                clean = _format_cell(value)
                if clean == "":
                    continue
                max_col_seen = max(max_col_seen, col_index)
                cells.append(
                    {
                        "column_index": col_index,
                        "column": _column_letter(col_index),
                        "value": clean,
                    }
                )
            if cells:
                rows.append({"row_index": row_index, "cells": cells})
        if worksheet.max_column and worksheet.max_column > max_sheet_cols:
            truncated = True
        return {"rows": rows, "max_col": max_col_seen, "truncated": truncated}

    def _render_chunk(self, sheet_name: str, rows: list[dict[str, Any]]) -> str:
        lines = [f"Spreadsheet sheet: {sheet_name}"]
        for row in rows:
            cells = row["cells"]
            rendered_cells = [f"{cell['column']}{row['row_index']}={cell['value']}" for cell in cells]
            line = f"Row {row['row_index']}: " + " | ".join(rendered_cells)
            if len(cells) >= 2:
                label = cells[0]["value"]
                value = cells[1]["value"]
                if label:
                    line += f" | {label} = {value}"
            lines.append(line)
        return "\n".join(lines)


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\n", " ").strip()


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _batched(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters or "A"
