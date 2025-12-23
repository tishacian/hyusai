"""Markdown document parser"""
import asyncio
from typing import List, Dict
import re
from app.services.document_parser.base import BaseDocumentParser, ParsedDocument, DocumentType
from app.services.document_parser.chunker import DocumentChunker, ChunkingMethod


class MarkdownParser(BaseDocumentParser):
    """Parser for Markdown files"""
    
    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        """Parse markdown document"""
        chunk_size = kwargs.get('chunk_size', 1000)
        chunk_overlap = kwargs.get('chunk_overlap', 200)
        chunking_method = kwargs.get('chunking_method', ChunkingMethod.RECURSIVE_CHARACTER)
        
        metadata = await self.extract_metadata(file_path)
        
        loop = asyncio.get_event_loop()
        
        def _read_file():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            return content
        
        raw_content = await loop.run_in_executor(None, _read_file)
        
        # Extract markdown structure (before cleaning to preserve structure)
        structured_content = self._extract_structure(raw_content)
        
        # Extract code blocks (before cleaning)
        code_blocks = self._extract_code_blocks(raw_content)
        
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
        
        language = self._detect_language(cleaned_content)
        
        return ParsedDocument(
            id=self._generate_id(file_path),
            filename=file_path.split('/')[-1],
            file_path=file_path,
            document_type=DocumentType.MARKDOWN,
            raw_content=cleaned_content,
            structured_content=structured_content,
            metadata=metadata,
            chunks=chunks,
            images=self._extract_images(raw_content),
            tables=self._extract_tables(raw_content),
            code_blocks=code_blocks,
            entities=[],
            relationships=[],
            language=language,
            encoding="utf-8",
            file_size=metadata["file_size"],
            created_at=metadata["created_at"],
            modified_at=metadata["modified_at"],
        )
    
    def _extract_structure(self, content: str) -> Dict:
        """Extract markdown structure"""
        headings = []
        links = []
        
        # Extract headings
        heading_pattern = r'^(#{1,6})\s+(.+)$'
        for line in content.split('\n'):
            match = re.match(heading_pattern, line)
            if match:
                level = len(match.group(1))
                text = match.group(2)
                headings.append({"level": level, "text": text})
        
        # Extract links
        link_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
        for match in re.finditer(link_pattern, content):
            links.append({
                "text": match.group(1),
                "url": match.group(2),
            })
        
        return {
            "headings": headings,
            "links": links,
            "heading_count": len(headings),
            "link_count": len(links),
        }
    
    def _extract_code_blocks(self, content: str) -> List[Dict]:
        """Extract code blocks from markdown"""
        code_blocks = []
        pattern = r'```(\w+)?\n(.*?)```'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            language = match.group(1) or "unknown"
            code = match.group(2)
            
            code_blocks.append({
                "language": language,
                "content": code,
                "start_char": match.start(),
                "end_char": match.end(),
            })
        
        return code_blocks
    
    def _extract_images(self, content: str) -> List[Dict]:
        """Extract image references from markdown"""
        images = []
        pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'
        
        for match in re.finditer(pattern, content):
            images.append({
                "alt": match.group(1),
                "url": match.group(2),
                "start_char": match.start(),
                "end_char": match.end(),
            })
        
        return images
    
    def _extract_tables(self, content: str) -> List[Dict]:
        """Extract tables from markdown"""
        tables = []
        lines = content.split('\n')
        current_table = []
        
        for i, line in enumerate(lines):
            if '|' in line and line.strip().startswith('|'):
                current_table.append(line)
            elif current_table:
                # End of table
                if len(current_table) >= 2:  # Header + separator
                    table_data = self._parse_table(current_table)
                    if table_data:
                        tables.append({
                            "data": table_data,
                            "rows": len(table_data),
                            "cols": len(table_data[0]) if table_data else 0,
                        })
                current_table = []
        
        return tables
    
    def _parse_table(self, table_lines: List[str]) -> List[List[str]]:
        """Parse markdown table into list of rows"""
        if len(table_lines) < 2:
            return []
        
        rows = []
        for line in table_lines:
            if '---' in line:  # Skip separator
                continue
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            if cells:
                rows.append(cells)
        
        return rows
    
    
    def _detect_language(self, text: str) -> str:
        """Detect language"""
        return "en"  # Markdown is typically English
    
    def supports(self, file_path: str) -> bool:
        """Check if file is markdown"""
        return file_path.lower().endswith(('.md', '.markdown'))

