from datetime import datetime

from pydantic import BaseModel, computed_field


class CollectionSummary(BaseModel):
    uuid: str
    name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: str
    embedding_model_name: str | None
    chunking_method: str | None
    nb_docs: int  # from Collection.nb_docs @property

    @computed_field
    @property
    def is_embedded(self) -> bool:
        """Derived from status for backward compatibility."""
        return self.status == "ready"

    model_config = {"from_attributes": True}


class CollectionDetail(CollectionSummary):
    document_names: list[str]
    chunking_params: dict | None
    kb_path: str
    uploaded_docs_size: int | None
    ingested_docs_size: int | None
    qdrant_collection_size: int | None
    nb_chunks: int | None


class DeleteCollectionResponse(BaseModel):
    uuid: str
    deleted: bool
    detail: str
