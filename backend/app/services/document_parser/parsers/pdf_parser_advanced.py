"""Advanced PDF parser based on streaming-decision-process"""
import asyncio
import os
import tempfile
from typing import List, Dict
from app.services.document_parser.base import BaseDocumentParser, ParsedDocument, DocumentType
from app.services.document_parser.text_processor import TextProcessor
from app.services.document_parser.chunker import DocumentChunker, ChunkingMethod
from app.core.logging import get_logger

logger = get_logger(__name__)


class AdvancedPDFParser(BaseDocumentParser):
    """Advanced PDF parser using markdown converter or OCR from streaming-decision-process"""
    
    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        """Parse PDF document using advanced extraction methods"""
        chunk_size = kwargs.get('chunk_size', 1000)
        chunk_overlap = kwargs.get('chunk_overlap', 200)
        chunking_method = kwargs.get('chunking_method', ChunkingMethod.RECURSIVE_CHARACTER)
        use_ocr = kwargs.get('use_ocr', False)
        use_markdown_converter = kwargs.get('use_markdown_converter', True)
        
        metadata = await self.extract_metadata(file_path)
        
        # Try markdown converter first (better quality), fallback to OCR
        try:
            if use_markdown_converter:
                content = await self._extract_with_markdown_converter(file_path)
            else:
                content = await self._extract_with_ocr(file_path)
        except Exception as e:
            logger.warning(f"Primary extraction method failed: {e}, trying fallback")
            # Fallback to OCR if markdown converter fails
            if use_markdown_converter:
                try:
                    content = await self._extract_with_ocr(file_path)
                except Exception as fallback_error:
                    logger.error(f"Both extraction methods failed: {fallback_error}")
                    # Final fallback to basic PDF extraction
                    content = await self._extract_basic(file_path)
            else:
                content = await self._extract_basic(file_path)
        
        # Clean and process text (preserves paragraph breaks)
        cleaned_content = TextProcessor.clean_text(content)
        if not cleaned_content:
            logger.warning(f"No content extracted from {file_path} after cleaning")
            cleaned_content = "No content could be extracted from this document."
        
        # Create chunks using the chunker service
        chunker = DocumentChunker(default_chunk_size=chunk_size, default_overlap=chunk_overlap)
        chunk_texts = chunker.chunk(
            cleaned_content,
            method=chunking_method,
            chunk_size=chunk_size,
            overlap=chunk_overlap
        )
        
        # Convert to chunk dict format
        chunks = []
        current_pos = 0
        for i, chunk_text in enumerate(chunk_texts):
            chunk_start = cleaned_content.find(chunk_text, current_pos)
            if chunk_start == -1:
                chunk_start = current_pos
            chunk_end = chunk_start + len(chunk_text)
            current_pos = chunk_end
            
            chunks.append({
                "content": chunk_text,
                "start_char": chunk_start,
                "end_char": chunk_end,
                "chunk_index": i,
                "page": 1,  # Will be updated if page info is available
            })
        
        # Process chunks to remove low-quality content
        processed_chunks = TextProcessor.process_chunks(chunks)
        
        if not processed_chunks:
            logger.warning(f"No valid chunks after processing for {file_path}")
            processed_chunks = [{
                "content": cleaned_content[:chunk_size],
                "start_char": 0,
                "end_char": len(cleaned_content),
                "chunk_index": 0,
                "page": 1,
            }]
        
        language = self._detect_language(cleaned_content)
        
        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=os.path.basename(file_path),
            file_path=file_path,
            document_type=DocumentType.PDF,
            raw_content=cleaned_content,
            structured_content={
                "pages": metadata.get("pages", 1),
                "chunks_count": len(processed_chunks),
                "total_chars": len(cleaned_content),
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
    
    async def _extract_with_markdown_converter(self, file_path: str) -> str:
        """Extract text using markdown converter (best quality)"""
        try:
            # Try to use markdown converter if available
            # This is a simplified version - full implementation would use the markdown_converter module
            import pdfplumber
            
            loop = asyncio.get_event_loop()
            
            def _extract():
                text_parts = []
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                return "\n\n".join(text_parts)
            
            return await loop.run_in_executor(None, _extract)
        except ImportError:
            logger.warning("pdfplumber not available, falling back to basic extraction")
            return await self._extract_basic(file_path)
        except Exception as e:
            logger.error(f"Markdown converter extraction failed: {e}")
            raise
    
    async def _extract_with_ocr(self, file_path: str) -> str:
        """Extract text using OCR (for scanned PDFs)"""
        try:
            # Try to use OCR if available
            import pytesseract
            import pymupdf
            from PIL import Image
            
            loop = asyncio.get_event_loop()
            
            def _extract():
                text_parts = []
                doc = pymupdf.open(file_path)
                try:
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        # Try text extraction first
                        text = page.get_text("text")
                        if text.strip():
                            text_parts.append(text)
                        else:
                            # Use OCR for pages without text
                            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            ocr_text = pytesseract.image_to_string(img)
                            if ocr_text.strip():
                                text_parts.append(ocr_text)
                finally:
                    doc.close()
                return "\n\n".join(text_parts)
            
            return await loop.run_in_executor(None, _extract)
        except ImportError:
            logger.warning("OCR dependencies not available, falling back to basic extraction")
            return await self._extract_basic(file_path)
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            raise
    
    async def _extract_basic(self, file_path: str) -> str:
        """Basic PDF extraction fallback"""
        loop = asyncio.get_event_loop()
        
        def _extract():
            text_parts = []
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
            except ImportError:
                try:
                    import PyPDF2
                    with open(file_path, 'rb') as file:
                        pdf_reader = PyPDF2.PdfReader(file)
                        for page in pdf_reader.pages:
                            text = page.extract_text()
                            if text:
                                text_parts.append(text)
                except ImportError:
                    raise ImportError("Neither pdfplumber nor PyPDF2 is installed")
            return "\n\n".join(text_parts)
        
        return await loop.run_in_executor(None, _extract)
    
    
    def _detect_language(self, text: str) -> str:
        """Detect language"""
        return "en"  # Default
    
    def supports(self, file_path: str) -> bool:
        """Check if file is a PDF"""
        return file_path.lower().endswith('.pdf')

