"""PPTX parser with slide-level chunks for capture document references."""
from __future__ import annotations

import asyncio
import os
import re
import zipfile
from xml.etree import ElementTree
from typing import Any

from app.services.document_parser.base import BaseDocumentParser, DocumentType, ParsedDocument
from app.services.document_parser.text_processor import TextProcessor


class PptxParser(BaseDocumentParser):
    """Parser for Microsoft PowerPoint `.pptx` files.

    Capture users refer to "this slide" while speaking, so chunks are deliberately
    slide-scoped rather than re-chunked by character windows.
    """

    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        metadata = await self.extract_metadata(file_path)
        loop = asyncio.get_event_loop()
        slides = await loop.run_in_executor(None, self._extract_pptx, file_path)

        raw_parts: list[str] = []
        chunks: list[dict[str, Any]] = []
        cursor = 0
        for slide in slides:
            text = TextProcessor.clean_text(slide.get("text") or "") or str(slide.get("text") or "").strip()
            if not text:
                continue
            header = f"Slide {slide['slide']}"
            content = f"{header}\n{text}"
            if raw_parts:
                cursor += 2
            start = cursor
            end = start + len(content)
            raw_parts.append(content)
            cursor = end
            chunks.append(
                {
                    "content": content,
                    "start_char": start,
                    "end_char": end,
                    "chunk_index": len(chunks),
                    "page": slide["slide"],
                    "page_number": slide["slide"],
                    "slide": slide["slide"],
                    "slide_title": slide.get("title"),
                }
            )

        raw_content = "\n\n".join(raw_parts)
        structured_content = {
            "slides": slides,
            "slide_count": len(slides),
            "chunks_count": len(chunks),
            "total_chars": len(raw_content),
        }
        metadata.update({"pages": len(slides), "slides": len(slides), "num_slides": len(slides)})
        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=os.path.basename(file_path),
            file_path=file_path,
            document_type=DocumentType.PPTX,
            raw_content=raw_content,
            structured_content=structured_content,
            metadata=metadata,
            chunks=chunks,
            images=[],
            tables=[],
            code_blocks=[],
            entities=[],
            relationships=[],
            language=self._detect_language(raw_content),
            encoding="utf-8",
            file_size=metadata["file_size"],
            created_at=metadata["created_at"],
            modified_at=metadata["modified_at"],
        )

    def _extract_pptx(self, file_path: str) -> list[dict[str, Any]]:
        slides: list[dict[str, Any]] = []
        with zipfile.ZipFile(file_path) as archive:
            def slide_index(name: str) -> int:
                match = re.search(r"slide(\d+)\.xml$", name)
                return int(match.group(1)) if match else 0

            slide_names = sorted(
                (name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)),
                key=slide_index,
            )
            for name in slide_names:
                match = re.search(r"slide(\d+)\.xml$", name)
                slide_no = int(match.group(1)) if match else len(slides) + 1
                xml_bytes = archive.read(name)
                root = ElementTree.fromstring(xml_bytes)
                texts = [
                    str(node.text or "").strip()
                    for node in root.iter()
                    if node.tag.endswith("}t") and str(node.text or "").strip()
                ]
                normalized = "\n".join(texts)
                title = texts[0][:180] if texts else None
                slides.append({"slide": slide_no, "title": title, "text": normalized})
        return slides

    def _detect_language(self, text: str) -> str:
        lower = text.lower()
        if sum(1 for word in ("the", "and", "of", "to") if word in lower) > 2:
            return "en"
        if sum(1 for word in ("le", "la", "les", "et", "des") if word in lower) > 2:
            return "fr"
        return "unknown"

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pptx")
