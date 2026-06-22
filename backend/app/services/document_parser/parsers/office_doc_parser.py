"""Legacy `.doc` parser backed by LibreOffice text conversion."""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

from app.services.document_parser.base import BaseDocumentParser, DocumentType, ParsedDocument
from app.services.document_parser.chunker import ChunkingMethod, DocumentChunker
from app.services.document_parser.text_processor import TextProcessor


class OfficeDocParser(BaseDocumentParser):
    """Parser for legacy Microsoft Word `.doc` files.

    Binary `.doc` cannot be read safely as plain text. In the backend image we
    install LibreOffice Writer and convert to a temporary text file first.
    """

    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        chunk_size = kwargs.get("chunk_size", 1000)
        chunk_overlap = kwargs.get("chunk_overlap", 200)
        chunking_method = kwargs.get("chunking_method", ChunkingMethod.RECURSIVE_CHARACTER)
        metadata = await self.extract_metadata(file_path)
        loop = asyncio.get_event_loop()
        raw_content = await loop.run_in_executor(None, self._extract_text, file_path)
        cleaned_content = TextProcessor.clean_text(raw_content) or raw_content

        chunker = DocumentChunker(default_chunk_size=chunk_size, default_overlap=chunk_overlap)
        chunk_texts = chunker.chunk(
            cleaned_content,
            method=chunking_method,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
        )
        chunks: list[dict] = []
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

        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=os.path.basename(file_path),
            file_path=file_path,
            document_type=DocumentType.DOC,
            raw_content=cleaned_content,
            structured_content={
                "chunks_count": len(chunks),
                "total_chars": len(cleaned_content),
                "conversion": "libreoffice_txt",
            },
            metadata=metadata,
            chunks=chunks,
            images=[],
            tables=[],
            code_blocks=[],
            entities=[],
            relationships=[],
            language=self._detect_language(cleaned_content),
            encoding="utf-8",
            file_size=metadata["file_size"],
            created_at=metadata["created_at"],
            modified_at=metadata["modified_at"],
        )

    def _extract_text(self, file_path: str) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            completed = subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    tmp_dir,
                    file_path,
                ],
                capture_output=True,
                timeout=45,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or b"").decode("utf-8", errors="ignore")[:300]
                raise RuntimeError(f"office_doc_text_conversion_failed:{detail}")
            candidates = list(Path(tmp_dir).glob("*.txt"))
            if not candidates:
                raise RuntimeError("office_doc_text_conversion_missing")
            data = candidates[0].read_bytes()
            for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    return data.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")

    def _detect_language(self, text: str) -> str:
        lower = text.lower()
        if sum(1 for word in ("the", "and", "of", "to") if word in lower) > 2:
            return "en"
        if sum(1 for word in ("le", "la", "les", "et", "des") if word in lower) > 2:
            return "fr"
        return "unknown"

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith(".doc")
