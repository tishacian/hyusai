from uuid import UUID

from pydantic import BaseModel, Field


class IngestDocumentsPayload(BaseModel):
    input_documents_bucket: UUID = Field(
        ...,
        description="UUID of the bucket or storage location containing the documents to ingest.",
    )
    knowledge_base_name: str = Field(
        ..., description="The name of the new vector store to be created."
    )
    knowledge_base_description: str = Field(
        "",
        description="Optional description providing context or details about the knowledge base.",
    )
    knowledge_base_creator: str = Field(
        "guest",
        description="Name or identifier of the user creating the knowledge base. ",
    )
    # TODO: add ingestion params related to OCR/VLM for example
