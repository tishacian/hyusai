"""
Metadata Extractors Package

This package contains extractors for different file types.
"""

# Import all extractors
from docmeta.extractors.pdf import extract_pdf_metadata
from docmeta.extractors.image import extract_image_metadata
from docmeta.extractors.document import extract_document_metadata

# Register extractors with the factory
from docmeta.core.factory import register_extractor

# Register PDF extractor
register_extractor(
    extensions=['.pdf'],
    mime_types=['application/pdf'],
    extractor=extract_pdf_metadata
)

# Register image extractors
register_extractor(
    extensions=['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'],
    mime_types=[
        'image/jpeg', 'image/png', 'image/gif', 
        'image/bmp', 'image/tiff', 'image/webp'
    ],
    extractor=extract_image_metadata
)

# Register document extractors
register_extractor(
    extensions=['.docx', '.doc', '.odt', '.ods', '.odp'],
    mime_types=[
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword',
        'application/vnd.oasis.opendocument.text',
        'application/vnd.oasis.opendocument.spreadsheet',
        'application/vnd.oasis.opendocument.presentation',
    ],
    extractor=extract_document_metadata
)

__all__ = [
    'extract_pdf_metadata',
    'extract_image_metadata',
    'extract_document_metadata',
]
