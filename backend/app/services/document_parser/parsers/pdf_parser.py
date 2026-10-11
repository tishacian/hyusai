"""PDF document parser (basic fallback)"""
import asyncio
from typing import List, Dict
from app.services.document_parser.base import BaseDocumentParser, ParsedDocument, DocumentType
from app.services.document_parser.text_processor import TextProcessor
from app.services.document_parser.chunker import DocumentChunker, ChunkingMethod
from app.core.logging import get_logger

logger = get_logger(__name__)


class PDFParser(BaseDocumentParser):
    """Parser for PDF files"""
    
    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        """Parse PDF document"""
        chunk_size = kwargs.get('chunk_size', 1000)
        chunk_overlap = kwargs.get('chunk_overlap', 200)
        chunking_method = kwargs.get('chunking_method', ChunkingMethod.RECURSIVE_CHARACTER)
        use_ocr = kwargs.get('use_ocr', False)
        
        metadata = await self.extract_metadata(file_path)
        
        loop = asyncio.get_event_loop()
        
        def _parse_pdf():
            """Parse PDF using pdfplumber (preferred) or PyPDF2"""
            text_content = []
            pages_data = []
            
            # Try pdfplumber first (better text extraction)
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    for page_num, page in enumerate(pdf.pages, 1):
                        text = page.extract_text()
                        if text:
                            text_content.append(text)
                            pages_data.append({
                                "page_number": page_num,
                                "text": text,
                                "bbox": page.bbox if hasattr(page, 'bbox') else None,
                            })
                        
                        # Extract tables if any
                        tables = page.extract_tables()
                        if tables:
                            for table in tables:
                                pages_data[-1].setdefault("tables", []).append(table)
                
                full_text = "\n\n".join(text_content)
                
            except ImportError:
                # Fallback to PyPDF2
                try:
                    import PyPDF2
                    with open(file_path, 'rb') as file:
                        pdf_reader = PyPDF2.PdfReader(file)
                        for page_num, page in enumerate(pdf_reader.pages, 1):
                            text = page.extract_text()
                            if text:
                                text_content.append(text)
                                pages_data.append({
                                    "page_number": page_num,
                                    "text": text,
                                })
                        full_text = "\n\n".join(text_content)
                except ImportError:
                    raise ImportError("Neither pdfplumber nor PyPDF2 is installed. Install with: pip install pdfplumber PyPDF2")
            
            return full_text, pages_data
        
        raw_content, pages_data = await loop.run_in_executor(None, _parse_pdf)
        
        # Clean text before chunking (preserves paragraph breaks)
        cleaned_content = TextProcessor.clean_text(raw_content)
        if not cleaned_content:
            logger.warning(f"No content extracted from {file_path} after cleaning")
            cleaned_content = "No content could be extracted from this document."
        
        # Use chunker service for consistent chunking
        chunker = DocumentChunker(default_chunk_size=chunk_size, default_overlap=chunk_overlap)
        chunk_texts = chunker.chunk(
            cleaned_content,
            method=chunking_method,
            chunk_size=chunk_size,
            overlap=chunk_overlap
        )
        
        # Map chunks to pages and create chunk dicts
        chunks = self._map_chunks_to_pages(chunk_texts, pages_data, cleaned_content)
        
        # Process chunks to remove low-quality content
        chunks = TextProcessor.process_chunks(chunks)
        
        # Extract tables from pages_data
        tables = []
        for page_data in pages_data:
            if "tables" in page_data:
                for table in page_data["tables"]:
                    tables.append({
                        "page": page_data["page_number"],
                        "data": table,
                        "rows": len(table) if table else 0,
                        "cols": len(table[0]) if table and table[0] else 0,
                    })
        
        language = self._detect_language(raw_content)
        
        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=file_path.split('/')[-1],
            file_path=file_path,
            document_type=DocumentType.PDF,
            raw_content=cleaned_content,
            structured_content={
                "pages": len(pages_data),
                "chunks_count": len(chunks),
                "total_chars": len(raw_content),
                "tables_count": len(tables),
            },
            metadata=metadata,
            chunks=chunks,
            images=[],  # Could be extended with OCR
            tables=tables,
            code_blocks=[],
            entities=[],
            relationships=[],
            language=language,
            encoding="utf-8",
            file_size=metadata["file_size"],
            created_at=metadata["created_at"],
            modified_at=metadata["modified_at"],
        )
    
    def _map_chunks_to_pages(self, chunk_texts: List[str], pages_data: List[Dict], full_text: str) -> List[Dict]:
        """Map chunk texts to pages and create chunk dictionaries"""
        chunks = []
        
        # Map character positions to pages
        char_to_page = {}
        current_pos = 0
        for page_data in pages_data:
            page_text = page_data.get("text", "")
            page_num = page_data.get("page_number", 0)
            for i in range(len(page_text)):
                char_to_page[current_pos + i] = page_num
            current_pos += len(page_text) + 2  # +2 for "\n\n"
        
        # Map each chunk to its position and page
        current_pos = 0
        for i, chunk_text in enumerate(chunk_texts):
            chunk_start = full_text.find(chunk_text, current_pos)
            if chunk_start == -1:
                chunk_start = current_pos
            chunk_end = chunk_start + len(chunk_text)
            current_pos = chunk_end
            
            # Determine page number for this chunk
            page_num = char_to_page.get(chunk_start, 0)
            
            chunks.append({
                "content": chunk_text,
                "start_char": chunk_start,
                "end_char": chunk_end,
                "chunk_index": i,
                "page": page_num,
            })
        
        return chunks
    
    def _detect_language(self, text: str) -> str:
        """Detect language"""
        return "en"  # Default for PDFs
    
    def supports(self, file_path: str) -> bool:
        """Check if file is a PDF"""
        return file_path.lower().endswith('.pdf')

