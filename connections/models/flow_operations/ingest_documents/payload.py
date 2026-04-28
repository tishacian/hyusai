from uuid import UUID

from pydantic import BaseModel, Field

from .pdf_options import PDFIngestOptions


class IngestDocumentsPayload(BaseModel):
    input_documents_bucket: UUID = Field(
        ...,
        description="UUID of the temporary upload bucket containing the files to ingest.",
    )
    collection_name: str = Field(
        ...,
        description="Name of the collection these documents will be attached to.",
    )
    collection_description: str = Field(
        "",
        description="Optional human-readable description of this collection.",
    )
    created_by: str = Field(
        "guest",
        description="Username or identifier of the user creating the collection.",
    )
    pdf_options: PDFIngestOptions = Field(
        default_factory=PDFIngestOptions,
        description="PDF processing strategy and options. Applies to all PDF files in this batch.",
    )
