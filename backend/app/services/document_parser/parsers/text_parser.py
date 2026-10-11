"""Text document parser"""
import asyncio
from typing import List, Dict
from app.services.document_parser.base import BaseDocumentParser, ParsedDocument, DocumentType
from app.services.document_parser.chunker import DocumentChunker, ChunkingMethod


class TextParser(BaseDocumentParser):
    """Parser for plain text files"""
    
    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        """Parse text document"""
        chunk_size = kwargs.get('chunk_size', 1000)
        chunk_overlap = kwargs.get('chunk_overlap', 200)
        chunking_method = kwargs.get('chunking_method', ChunkingMethod.RECURSIVE_CHARACTER)
        
        # Read file content
        metadata = await self.extract_metadata(file_path)
        
        loop = asyncio.get_event_loop()
        
        def _read_file():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Try with different encoding
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            
            return content
        
        raw_content = await loop.run_in_executor(None, _read_file)
        
        # Clean text (preserves paragraph breaks)
        from app.services.document_parser.text_processor import TextProcessor
        cleaned_content = TextProcessor.clean_text(raw_content)
        if not cleaned_content:
            cleaned_content = raw_content  # Fallback to original if cleaning removes everything
        
        # Use chunker service for consistent chunking
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
            })
        
        # Detect language (simple detection)
        language = self._detect_language(cleaned_content)
        
        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=file_path.split('/')[-1],
            file_path=file_path,
            document_type=DocumentType.TEXT,
            raw_content=cleaned_content,
            structured_content={
                "chunks_count": len(chunks),
                "total_chars": len(cleaned_content),
            },
            metadata=metadata,
            chunks=chunks,
            images=[],
            tables=[],
            code_blocks=[],
            entities=[],
            relationships=[],
            language=language,
            encoding="utf-8",
            file_size=metadata["file_size"],
            created_at=metadata["created_at"],
            modified_at=metadata["modified_at"],
        )
    
    def _detect_language(self, text: str) -> str:
        """Simple language detection (can be improved)"""
        # Simple heuristic - check for common English words
        common_words = ['the', 'be', 'to', 'of', 'and', 'a', 'in', 'that', 'have']
        text_lower = text.lower()
        
        english_score = sum(1 for word in common_words if word in text_lower)
        
        if english_score > 3:
            return "en"
        return "unknown"
    
    def supports(self, file_path: str) -> bool:
        """Check if file is a text file"""
        return file_path.lower().endswith(('.txt', '.log', '.text'))

