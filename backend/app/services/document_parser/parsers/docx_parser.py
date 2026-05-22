"""DOCX parser for Agentium document intelligence.

The parser intentionally uses the DOCX XML package directly instead of making
python-docx mandatory in every runtime. It extracts paragraphs, style hints and
tables into the canonical ParsedDocument shape; higher-level fact extraction is
handled by document_intelligence.py.
"""
from __future__ import annotations

import asyncio
import os
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from app.services.document_parser.base import BaseDocumentParser, DocumentType, ParsedDocument
from app.services.document_parser.chunker import ChunkingMethod, DocumentChunker
from app.services.document_parser.text_processor import TextProcessor


_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


class DocxParser(BaseDocumentParser):
    """Parser for Microsoft Word `.docx` files."""

    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        chunk_size = kwargs.get("chunk_size", 1000)
        chunk_overlap = kwargs.get("chunk_overlap", 200)
        chunking_method = kwargs.get("chunking_method", ChunkingMethod.RECURSIVE_CHARACTER)
        metadata = await self.extract_metadata(file_path)
        loop = asyncio.get_event_loop()
        extracted = await loop.run_in_executor(None, self._extract_docx, file_path)

        paragraphs: list[dict[str, Any]] = extracted["paragraphs"]
        tables: list[dict[str, Any]] = extracted["tables"]
        raw_content = "\n".join(p["text"] for p in paragraphs if p.get("text"))
        if tables:
            table_text = []
            for table in tables:
                table_text.append(f"Table {table['table_index']}")
                for row in table.get("rows", []):
                    table_text.append(" | ".join(str(cell) for cell in row))
            raw_content = "\n\n".join(part for part in [raw_content, "\n".join(table_text)] if part)

        cleaned_content = TextProcessor.clean_text(raw_content) or raw_content
        chunker = DocumentChunker(default_chunk_size=chunk_size, default_overlap=chunk_overlap)
        chunk_texts = chunker.chunk(
            cleaned_content,
            method=chunking_method,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
        )

        chunks: list[dict[str, Any]] = []
        current_pos = 0
        for index, chunk_text in enumerate(chunk_texts):
            start = cleaned_content.find(chunk_text, current_pos)
            if start == -1:
                start = current_pos
            end = start + len(chunk_text)
            current_pos = end
            chunks.append(
                {
                    "content": chunk_text,
                    "start_char": start,
                    "end_char": end,
                    "chunk_index": index,
                }
            )

        headings = [
            {
                "level": p.get("heading_level") or 1,
                "text": p.get("text"),
                "paragraph_index": p.get("paragraph_index"),
            }
            for p in paragraphs
            if p.get("is_heading") and p.get("text")
        ]
        structured_content = {
            "paragraphs": paragraphs,
            "headings": headings,
            "heading_count": len(headings),
            "tables": tables,
            "table_count": len(tables),
            "chunks_count": len(chunks),
            "total_chars": len(cleaned_content),
        }

        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=os.path.basename(file_path),
            file_path=file_path,
            document_type=DocumentType.DOCX,
            raw_content=cleaned_content,
            structured_content=structured_content,
            metadata=metadata,
            chunks=chunks,
            images=[],
            tables=tables,
            code_blocks=[],
            entities=[],
            relationships=[],
            language=self._detect_language(cleaned_content),
            encoding="utf-8",
            file_size=metadata["file_size"],
            created_at=metadata["created_at"],
            modified_at=metadata["modified_at"],
        )

    def _extract_docx(self, file_path: str) -> dict[str, Any]:
        with zipfile.ZipFile(file_path) as archive:
            document_xml = archive.read("word/document.xml")
        root = ET.fromstring(document_xml)
        body = root.find("w:body", _NS)
        if body is None:
            return {"paragraphs": [], "tables": []}

        paragraphs: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        paragraph_index = 0
        table_index = 0
        for child in list(body):
            if child.tag == _tag("p"):
                text = _text_from_element(child)
                if not text.strip():
                    continue
                style = _paragraph_style(child)
                paragraph_index += 1
                heading_level = _heading_level(style)
                paragraphs.append(
                    {
                        "paragraph_index": paragraph_index,
                        "text": text.strip(),
                        "style": style,
                        "is_heading": heading_level is not None,
                        "heading_level": heading_level,
                    }
                )
            elif child.tag == _tag("tbl"):
                table_index += 1
                rows = _table_rows(child)
                tables.append(
                    {
                        "table_index": table_index,
                        "rows": rows,
                        "row_count": len(rows),
                        "col_count": max((len(row) for row in rows), default=0),
                    }
                )
        return {"paragraphs": paragraphs, "tables": tables}

    def _detect_language(self, text: str) -> str:
        lower = text.lower()
        if sum(1 for word in ("the", "and", "of", "to") if word in lower) > 2:
            return "en"
        if sum(1 for word in ("le", "la", "les", "et", "des") if word in lower) > 2:
            return "fr"
        return "unknown"

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith(".docx")


def _tag(name: str) -> str:
    if ":" in name:
        prefix, local = name.split(":", 1)
    else:
        prefix, local = "w", name
    return f"{{{_NS[prefix]}}}{local}"


def _text_from_element(element: ET.Element) -> str:
    parts: list[str] = []
    for text_node in element.findall(".//w:t", _NS):
        if text_node.text:
            parts.append(text_node.text)
    return "".join(parts)


def _paragraph_style(paragraph: ET.Element) -> str | None:
    style = paragraph.find("w:pPr/w:pStyle", _NS)
    if style is None:
        return None
    return style.attrib.get(_tag("w:val"))


def _heading_level(style: str | None) -> int | None:
    if not style:
        return None
    lowered = style.lower()
    if "heading" in lowered or "titre" in lowered:
        digits = "".join(ch for ch in style if ch.isdigit())
        if digits:
            try:
                return max(1, min(6, int(digits)))
            except ValueError:
                return 1
        return 1
    return None


def _table_rows(table: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.findall("w:tr", _NS):
        cells: list[str] = []
        for cell in row.findall("w:tc", _NS):
            cell_texts = [_text_from_element(paragraph).strip() for paragraph in cell.findall("w:p", _NS)]
            cells.append(" ".join(text for text in cell_texts if text))
        if any(cells):
            rows.append(cells)
    return rows
