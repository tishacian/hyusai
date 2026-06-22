"""Document parser factory"""
from typing import Dict, Type
import mimetypes
from pathlib import Path
from app.services.document_parser.base import BaseDocumentParser, DocumentType
from app.core.logging import get_logger

logger = get_logger(__name__)


class DocumentParserFactory:
    """Factory for creating appropriate document parsers"""
    
    _parsers: Dict[DocumentType, Type[BaseDocumentParser]] = {}
    
    @classmethod
    def register_parser(cls, doc_type: DocumentType, parser_class: Type[BaseDocumentParser]):
        """Register a parser for a document type"""
        cls._parsers[doc_type] = parser_class
    
    @classmethod
    def get_parser(cls, file_path: str) -> BaseDocumentParser:
        """Get appropriate parser for file"""
        doc_type = cls._detect_type(file_path)
        parser_class = cls._parsers.get(doc_type)
        
        # For PDFs, prefer advanced parser if available
        if doc_type == DocumentType.PDF:
            try:
                from app.services.document_parser.parsers.pdf_parser_advanced import AdvancedPDFParser
                return AdvancedPDFParser()
            except ImportError:
                logger.debug("Advanced PDF parser not available, using basic parser")
                parser_class = cls._parsers.get(doc_type)
        if doc_type in (DocumentType.SPREADSHEET, DocumentType.CSV):
            from app.services.document_parser.parsers.spreadsheet_parser import SpreadsheetParser

            return SpreadsheetParser()
        
        if not parser_class:
            # Fallback to text parser
            from app.services.document_parser.parsers.text_parser import TextParser
            return TextParser()
        
        return parser_class()
    
    @classmethod
    def _detect_type(cls, file_path: str) -> DocumentType:
        """Detect document type from file extension"""
        ext = Path(file_path).suffix.lower()
        
        type_map = {
            '.pdf': DocumentType.PDF,
            '.doc': DocumentType.DOC,
            '.docx': DocumentType.DOCX,
            '.pptx': DocumentType.PPTX,
            '.md': DocumentType.MARKDOWN,
            '.markdown': DocumentType.MARKDOWN,
            '.txt': DocumentType.TEXT,
            '.log': DocumentType.LOG,
            '.rtf': DocumentType.RTF,
            '.html': DocumentType.HTML,
            '.htm': DocumentType.HTML,
            '.xls': DocumentType.SPREADSHEET,
            '.xlsm': DocumentType.SPREADSHEET,
            '.xlsx': DocumentType.SPREADSHEET,
            '.xltm': DocumentType.SPREADSHEET,
            '.xltx': DocumentType.SPREADSHEET,
            '.odt': DocumentType.ODT,
            '.csv': DocumentType.CSV,
            '.xml': DocumentType.XML,
            '.tex': DocumentType.TEX,
            '.pages': DocumentType.PAGES,
            '.json': DocumentType.JSON,
            '.css': DocumentType.CSS,
            '.yml': DocumentType.YML,
            '.yaml': DocumentType.YAML,
        }
        
        # Code file detection
        code_extensions = {
            '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.hpp',
            '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala',
            '.r', '.m', '.sql', '.sh', '.bash', '.zsh', '.fish',
            '.vue', '.jsx', '.tsx', '.dart', '.lua', '.pl', '.pm'
        }
        if ext in code_extensions:
            return DocumentType.CODE
        
        # Image detection
        image_extensions = {
            '.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp'
        }
        if ext in image_extensions:
            return DocumentType.IMAGE
        
        return type_map.get(ext, DocumentType.UNKNOWN)
