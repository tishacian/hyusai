"""Base document parser classes"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
import uuid
import os
from datetime import datetime


class DocumentType(Enum):
    """Supported document types"""
    PDF = "pdf"
    DOC = "doc"
    DOCX = "docx"
    PPTX = "pptx"
    MARKDOWN = "md"
    TEXT = "txt"
    LOG = "log"
    RTF = "rtf"
    HTML = "html"
    ODT = "odt"
    CSV = "csv"
    SPREADSHEET = "spreadsheet"
    XML = "xml"
    TEX = "tex"
    PAGES = "pages"
    JSON = "json"
    CSS = "css"
    YML = "yml"
    YAML = "yaml"
    CODE = "code"
    IMAGE = "image"
    UNKNOWN = "unknown"


@dataclass
class ParsedDocument:
    """Structured representation of a parsed document"""
    id: str
    filename: str
    file_path: str
    document_type: DocumentType
    raw_content: str
    structured_content: Dict
    metadata: Dict
    chunks: List[Dict]  # Text chunks with positions
    images: List[Dict]  # Extracted images with OCR text
    tables: List[Dict]  # Extracted tables
    code_blocks: List[Dict]  # Code blocks with syntax info
    entities: List[Dict]  # Named entities
    relationships: List[Dict]  # Entity relationships
    language: str
    encoding: str
    file_size: int
    created_at: str
    modified_at: str


class BaseDocumentParser(ABC):
    """Base class for all document parsers"""
    
    @abstractmethod
    async def parse(self, file_path: str, **kwargs) -> ParsedDocument:
        """Parse document and return structured representation"""
        pass
    
    @abstractmethod
    def supports(self, file_path: str) -> bool:
        """Check if parser supports this file type"""
        pass
    
    async def extract_metadata(self, file_path: str) -> Dict:
        """Extract file metadata"""
        stat = os.stat(file_path)
        return {
            "file_size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": os.path.splitext(file_path)[1],
        }
    
    def _generate_id(self, file_path: str) -> str:
        """Generate unique ID for document"""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, file_path))
