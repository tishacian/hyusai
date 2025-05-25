"""
Metadata Extractors Package

This package contains extractors for different file types.
"""

# Import all extractors
from docmeta.extractors.pdf import extract_pdf_metadata
from docmeta.extractors.image import extract_image_metadata
from docmeta.extractors.office import extract_office_metadata
from docmeta.extractors.opendocument import extract_opendocument_metadata
from docmeta.extractors.text import extract_text_metadata
from docmeta.extractors.markup import extract_markup_metadata
from docmeta.extractors.structured_data import extract_structured_data_metadata
from docmeta.extractors.generic import extract_generic_metadata

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

# Register Microsoft Office extractors
register_extractor(
    extensions=['.docx', '.xlsx', '.pptx'],
    mime_types=[
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ],
    extractor=extract_office_metadata
)

# Register OpenDocument extractors
register_extractor(
    extensions=['.odt', '.ods', '.odp'],
    mime_types=[
        'application/vnd.oasis.opendocument.text',
        'application/vnd.oasis.opendocument.spreadsheet',
        'application/vnd.oasis.opendocument.presentation',
    ],
    extractor=extract_opendocument_metadata
)

# Register text extractors
register_extractor(
    extensions=['.txt', '.md', '.rst', '.log'],
    mime_types=[
        'text/plain',
        'text/markdown',
        'text/x-rst',
        'text/x-log',
    ],
    extractor=extract_text_metadata
)

# Register markup extractors
register_extractor(
    extensions=['.html', '.htm', '.xml', '.xhtml'],
    mime_types=[
        'text/html',
        'application/xml',
        'text/xml',
        'application/xhtml+xml',
    ],
    extractor=extract_markup_metadata
)

# Register structured data extractors
register_extractor(
    extensions=['.csv', '.json', '.yaml', '.yml', '.toml', '.ini'],
    mime_types=[
        'text/csv',
        'application/json',
        'application/x-yaml',
        'text/yaml',
        'application/toml',
        'text/plain',  # For .ini files
    ],
    extractor=extract_structured_data_metadata
)

__all__ = [
    'extract_pdf_metadata',
    'extract_image_metadata',
    'extract_office_metadata',
    'extract_opendocument_metadata',
    'extract_text_metadata',
    'extract_markup_metadata',
    'extract_structured_data_metadata',
    'extract_generic_metadata',
]
