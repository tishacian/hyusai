# Import all extractors
# Register extractors with the factory
from ..core.factory import register_extractor
from .image import extract_image_metadata
from .markup import extract_markup_metadata
from .office import extract_office_metadata
from .opendocument import extract_opendocument_metadata
from .pdf import extract_pdf_metadata
from .structured_data import extract_structured_data_metadata
from .text import extract_text_metadata

# Register PDF extractor
register_extractor(
    extensions=[".pdf"], mime_types=["application/pdf"], extractor=extract_pdf_metadata
)

# Register image extractors
register_extractor(
    extensions=[".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"],
    mime_types=[
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/webp",
    ],
    extractor=extract_image_metadata,
)

# Register Microsoft Office extractors
register_extractor(
    extensions=[".docx", ".xlsx", ".pptx"],
    mime_types=[
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ],
    extractor=extract_office_metadata,
)

# Register OpenDocument extractors
register_extractor(
    extensions=[".odt", ".ods", ".odp"],
    mime_types=[
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
    ],
    extractor=extract_opendocument_metadata,
)

# Register text extractors
register_extractor(
    extensions=[".txt", ".md", ".rst", ".log"],
    mime_types=[
        "text/plain",
        "text/markdown",
        "text/x-rst",
        "text/x-log",
    ],
    extractor=extract_text_metadata,
)

# Register markup extractors
register_extractor(
    extensions=[".html", ".htm", ".xml", ".xhtml"],
    mime_types=[
        "text/html",
        "application/xml",
        "text/xml",
        "application/xhtml+xml",
    ],
    extractor=extract_markup_metadata,
)

# Register structured data extractors
register_extractor(
    extensions=[".csv", ".json", ".yaml", ".yml", ".toml", ".ini"],
    mime_types=[
        "text/csv",
        "application/json",
        "application/x-yaml",
        "text/yaml",
        "application/toml",
        "text/plain",  # For .ini files
    ],
    extractor=extract_structured_data_metadata,
)

__all__ = [
    "extract_pdf_metadata",
    "extract_image_metadata",
    "extract_office_metadata",
    "extract_opendocument_metadata",
    "extract_text_metadata",
    "extract_markup_metadata",
    "extract_structured_data_metadata",
]
