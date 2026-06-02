"""Advanced PDF parser based on streaming-decision-process"""
import asyncio
import os
import tempfile
from typing import List, Dict, Tuple, Any
from app.core.config import settings
from app.services.document_parser.base import BaseDocumentParser, ParsedDocument, DocumentType
from app.services.document_parser.text_processor import TextProcessor
from app.services.document_parser.chunker import DocumentChunker, ChunkingMethod
from app.core.logging import get_logger
from app.services.ocr import extract_ocr_for_image

logger = get_logger(__name__)


# Separator inserted between pages when joining per-page texts. Kept in sync
# with pdf_parser.py so char offsets line up with the char→page map below.
_PAGE_SEP = "\n\n"


class AdvancedPDFParser(BaseDocumentParser):
    """Advanced PDF parser using markdown converter or OCR from streaming-decision-process"""
    
    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        """Parse PDF document using advanced extraction methods"""
        chunk_size = kwargs.get('chunk_size', 1000)
        chunk_overlap = kwargs.get('chunk_overlap', 200)
        chunking_method = kwargs.get('chunking_method', ChunkingMethod.RECURSIVE_CHARACTER)
        use_ocr = kwargs.get('use_ocr', False)
        use_markdown_converter = kwargs.get('use_markdown_converter', True)
        ocr_config = kwargs.get("ocr_config") if isinstance(kwargs.get("ocr_config"), dict) else {}
        
        metadata = await self.extract_metadata(file_path)
        
        # Extractors now return a list of per-page ``(page_number, text)``
        # tuples instead of a single blob, so every chunk can be pinned to the
        # source page. This fixes the issue where all PDF chunks were being
        # indexed with ``page=1`` and shown as indistinguishable duplicates in
        # the Chat UI sources panel.
        pages_data: List[Dict] = []
        ocr_artifacts: List[Dict[str, Any]] = []
        try:
            if use_markdown_converter:
                pages_data = await self._extract_with_markdown_converter(file_path)
                if self._should_run_ocr(pages_data, use_ocr=use_ocr, ocr_config=ocr_config):
                    ocr_pages, ocr_artifacts = await self._extract_with_ocr(file_path, ocr_config)
                    if ocr_pages:
                        pages_data = ocr_pages
            else:
                pages_data, ocr_artifacts = await self._extract_with_ocr(file_path, ocr_config)
        except Exception as e:
            logger.warning(f"Primary extraction method failed: {e}, trying fallback")
            if use_markdown_converter:
                try:
                    pages_data, ocr_artifacts = await self._extract_with_ocr(file_path, ocr_config)
                except Exception as fallback_error:
                    logger.error(f"Both extraction methods failed: {fallback_error}")
                    pages_data = await self._extract_basic(file_path)
            else:
                pages_data = await self._extract_basic(file_path)

        raw_content = _PAGE_SEP.join(p.get("text", "") for p in pages_data)

        cleaned_content = TextProcessor.clean_text(raw_content)
        if not cleaned_content:
            logger.warning(f"No content extracted from {file_path} after cleaning")
            cleaned_content = "No content could be extracted from this document."
        
        chunker = DocumentChunker(default_chunk_size=chunk_size, default_overlap=chunk_overlap)
        chunk_texts = chunker.chunk(
            cleaned_content,
            method=chunking_method,
            chunk_size=chunk_size,
            overlap=chunk_overlap
        )

        chunks = self._map_chunks_to_pages(chunk_texts, pages_data, cleaned_content)

        processed_chunks = TextProcessor.process_chunks(chunks)
        
        if not processed_chunks:
            logger.warning(f"No valid chunks after processing for {file_path}")
            processed_chunks = [{
                "content": cleaned_content[:chunk_size],
                "start_char": 0,
                "end_char": len(cleaned_content),
                "chunk_index": 0,
                "page": pages_data[0].get("page_number", 1) if pages_data else 1,
            }]
        
        language = self._detect_language(cleaned_content)
        
        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=os.path.basename(file_path),
            file_path=file_path,
            document_type=DocumentType.PDF,
            raw_content=cleaned_content,
            structured_content={
                "pages": metadata.get("pages", len(pages_data) or 1),
                "chunks_count": len(processed_chunks),
                "total_chars": len(cleaned_content),
                "ocr_artifacts": ocr_artifacts,
                "ocr_block_count": sum(len(item.get("blocks") or []) for item in ocr_artifacts),
            },
            metadata=metadata,
            chunks=processed_chunks,
            images=[],
            tables=[],
            code_blocks=[],
            entities=[],
            relationships=[],
            language=language,
            encoding="utf-8",
            file_size=metadata.get("file_size", 0),
            created_at=metadata.get("created_at"),
            modified_at=metadata.get("modified_at"),
        )

    def _map_chunks_to_pages(
        self,
        chunk_texts: List[str],
        pages_data: List[Dict],
        full_text: str,
    ) -> List[Dict]:
        """Map chunk texts to pages and create chunk dictionaries.

        Mirrors ``PDFParser._map_chunks_to_pages`` so both parsers expose
        the same chunk schema. Falls back to page 1 when the char→page
        map cannot locate a chunk (e.g. heavy cleaning collapsed it).
        """
        chunks: List[Dict] = []

        char_to_page: Dict[int, int] = {}
        cursor = 0
        for page_data in pages_data:
            page_text = page_data.get("text", "") or ""
            page_num = page_data.get("page_number", 0) or 0
            for i in range(len(page_text)):
                char_to_page[cursor + i] = page_num
            cursor += len(page_text) + len(_PAGE_SEP)

        current_pos = 0
        fallback_page = pages_data[0].get("page_number", 1) if pages_data else 1
        for i, chunk_text in enumerate(chunk_texts):
            chunk_start = full_text.find(chunk_text, current_pos)
            if chunk_start == -1:
                chunk_start = current_pos
            chunk_end = chunk_start + len(chunk_text)
            current_pos = chunk_end

            page_num = char_to_page.get(chunk_start, fallback_page)

            chunks.append({
                "content": chunk_text,
                "start_char": chunk_start,
                "end_char": chunk_end,
                "chunk_index": i,
                "page": page_num,
            })

        return chunks

    async def _extract_with_markdown_converter(self, file_path: str) -> List[Dict]:
        """Extract text using markdown converter (best quality)"""
        try:
            import pdfplumber

            loop = asyncio.get_event_loop()

            def _extract() -> List[Dict]:
                pages: List[Dict] = []
                with pdfplumber.open(file_path) as pdf:
                    for page_num, page in enumerate(pdf.pages, 1):
                        text = page.extract_text()
                        if text:
                            pages.append({"page_number": page_num, "text": text})
                return pages

            return await loop.run_in_executor(None, _extract)
        except ImportError:
            logger.warning("pdfplumber not available, falling back to basic extraction")
            return await self._extract_basic(file_path)
        except Exception as e:
            logger.error(f"Markdown converter extraction failed: {e}")
            raise

    def _should_run_ocr(self, pages_data: List[Dict], *, use_ocr: bool, ocr_config: dict | None = None) -> bool:
        config = ocr_config or {}
        enabled = bool(config.get("enabled", settings.document_ocr_enabled))
        if not enabled:
            return False
        if use_ocr or bool(config.get("force_ocr", settings.document_ocr_force_ocr)):
            return True
        if not bool(config.get("scan_detection", settings.document_ocr_scan_detection)):
            return False
        total_chars = sum(len(str(page.get("text") or "").strip()) for page in pages_data)
        min_chars = int(config.get("min_text_chars_for_native_pdf", settings.document_ocr_min_text_chars_for_native_pdf) or 0)
        return total_chars < max(0, min_chars)

    async def _extract_with_ocr(self, file_path: str, ocr_config: dict | None = None) -> Tuple[List[Dict], List[Dict]]:
        """Extract text using OCR (for scanned PDFs)"""
        try:
            import pymupdf
            from PIL import Image

            loop = asyncio.get_event_loop()

            force_ocr = bool((ocr_config or {}).get("force_ocr", settings.document_ocr_force_ocr))

            def _extract() -> Tuple[List[Dict], List[Dict]]:
                pages: List[Dict] = []
                artifacts: List[Dict] = []
                doc = pymupdf.open(file_path)
                try:
                    for idx in range(len(doc)):
                        page = doc[idx]
                        page_num = idx + 1
                        text = page.get_text("text")
                        if text and text.strip() and not force_ocr:
                            pages.append({"page_number": page_num, "text": text})
                            continue
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            tmp_path = tmp.name
                        try:
                            img.save(tmp_path)
                            artifact = extract_ocr_for_image(tmp_path, config=ocr_config, page_number=page_num)
                            artifact["source_pdf"] = file_path
                            artifacts.append(artifact)
                            ocr_text = str(artifact.get("text") or "").strip()
                            if ocr_text:
                                pages.append({"page_number": page_num, "text": ocr_text, "extraction_method": "ocr"})
                        finally:
                            try:
                                os.unlink(tmp_path)
                            except OSError:
                                pass
                finally:
                    doc.close()
                return pages, artifacts

            return await loop.run_in_executor(None, _extract)
        except ImportError:
            logger.warning("OCR dependencies not available, falling back to basic extraction")
            return await self._extract_basic(file_path), []
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            raise

    async def _extract_basic(self, file_path: str) -> List[Dict]:
        """Basic PDF extraction fallback"""
        loop = asyncio.get_event_loop()

        def _extract() -> List[Dict]:
            pages: List[Dict] = []
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    for page_num, page in enumerate(pdf.pages, 1):
                        text = page.extract_text()
                        if text:
                            pages.append({"page_number": page_num, "text": text})
            except ImportError:
                try:
                    import PyPDF2
                    with open(file_path, 'rb') as file:
                        pdf_reader = PyPDF2.PdfReader(file)
                        for page_num, page in enumerate(pdf_reader.pages, 1):
                            text = page.extract_text()
                            if text:
                                pages.append({"page_number": page_num, "text": text})
                except ImportError:
                    raise ImportError("Neither pdfplumber nor PyPDF2 is installed")
            return pages

        return await loop.run_in_executor(None, _extract)
    
    
    def _detect_language(self, text: str) -> str:
        """Detect language"""
        return "en"  # Default
    
    def supports(self, file_path: str) -> bool:
        """Check if file is a PDF"""
        return file_path.lower().endswith('.pdf')
