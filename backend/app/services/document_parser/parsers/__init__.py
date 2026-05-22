"""Document parsers"""
from app.services.document_parser.parsers.text_parser import TextParser
from app.services.document_parser.parsers.markdown_parser import MarkdownParser
from app.services.document_parser.parsers.spreadsheet_parser import SpreadsheetParser
from app.services.document_parser.parsers.docx_parser import DocxParser
from app.services.document_parser.parsers.image_parser import ImageParser
from app.services.document_parser.base import DocumentType
from app.services.document_parser.factory import DocumentParserFactory

# Register parsers
DocumentParserFactory.register_parser(DocumentType.TEXT, TextParser)
DocumentParserFactory.register_parser(DocumentType.DOCX, DocxParser)
DocumentParserFactory.register_parser(DocumentType.MARKDOWN, MarkdownParser)
DocumentParserFactory.register_parser(DocumentType.LOG, TextParser)  # Logs use text parser
DocumentParserFactory.register_parser(DocumentType.SPREADSHEET, SpreadsheetParser)
DocumentParserFactory.register_parser(DocumentType.CSV, SpreadsheetParser)
DocumentParserFactory.register_parser(DocumentType.IMAGE, ImageParser)

# Register PDF parsers if available
try:
    from app.services.document_parser.parsers.pdf_parser_advanced import AdvancedPDFParser
    # Advanced parser is preferred and will be used by factory
    DocumentParserFactory.register_parser(DocumentType.PDF, AdvancedPDFParser)
except ImportError:
    try:
        from app.services.document_parser.parsers.pdf_parser import PDFParser
        DocumentParserFactory.register_parser(DocumentType.PDF, PDFParser)
    except ImportError:
        pass  # PDF parser requires pdfplumber/PyPDF2

__all__ = ["TextParser", "DocxParser", "MarkdownParser", "SpreadsheetParser", "ImageParser", "PDFParser"]
