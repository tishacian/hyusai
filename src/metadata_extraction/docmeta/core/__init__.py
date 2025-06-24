# Import for convenience
from .factory import extract_metadata
from .defaults import (create_image_metadata,
                                   create_markup_metadata,
                                   create_office_metadata,
                                   create_opendocument_metadata,
                                   create_pdf_metadata,
                                   create_structured_data_metadata,
                                   create_text_metadata)
from .types import (FileMetaData, ImageMetaData, MarkupMetaData,
                                MetadataType, OfficeMetaData,
                                OpenDocumentMetaData, PDFMetaData,
                                StructuredDataMetaData, TextMetaData)

__all__ = [
    "extract_metadata",
    "FileMetaData",
    "PDFMetaData",
    "ImageMetaData",
    "OfficeMetaData",
    "OpenDocumentMetaData",
    "TextMetaData",
    "MarkupMetaData",
    "StructuredDataMetaData",
    "MetadataType",
    "create_pdf_metadata",
    "create_image_metadata",
    "create_office_metadata",
    "create_opendocument_metadata",
    "create_text_metadata",
    "create_markup_metadata",
    "create_structured_data_metadata",
]
