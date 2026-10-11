"""Image parser backed by the provider-neutral OCR layer."""
from __future__ import annotations

import os
from pathlib import Path

from app.services.document_parser.base import BaseDocumentParser, DocumentType, ParsedDocument
from app.services.ocr import extract_ocr_for_image


class ImageParser(BaseDocumentParser):
    """Parse image files by extracting OCR text and visual evidence blocks."""

    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        metadata = await self.extract_metadata(file_path)
        ocr_artifact = extract_ocr_for_image(
            file_path,
            config=kwargs.get("ocr_config"),
        )
        text = str(ocr_artifact.get("text") or "").strip()
        if not text:
            text = "No OCR text could be extracted from this image."
        chunks = [
            {
                "content": text,
                "start_char": 0,
                "end_char": len(text),
                "chunk_index": 0,
                "page": 1,
                "semantic_type": "document_ocr_text",
                "ocr_provider": ocr_artifact.get("provider"),
                "ocr_confidence": _average_confidence(ocr_artifact.get("blocks") or []),
            }
        ]
        structured_content = {
            "schema_version": "image_document_v1",
            "ocr_artifacts": [ocr_artifact],
            "ocr_block_count": len(ocr_artifact.get("blocks") or []),
            "total_chars": len(text),
        }
        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=os.path.basename(file_path),
            file_path=file_path,
            document_type=DocumentType.IMAGE,
            raw_content=text,
            structured_content=structured_content,
            metadata=metadata,
            chunks=chunks,
            images=[{"path": file_path, "ocr_artifact": ocr_artifact}],
            tables=[],
            code_blocks=[],
            entities=[],
            relationships=[],
            language="unknown",
            encoding="binary",
            file_size=metadata.get("file_size", 0),
            created_at=metadata.get("created_at"),
            modified_at=metadata.get("modified_at"),
        )

    def supports(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _average_confidence(blocks: list[dict]) -> float | None:
    values = [float(block["confidence"]) for block in blocks if isinstance(block.get("confidence"), (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 4)
