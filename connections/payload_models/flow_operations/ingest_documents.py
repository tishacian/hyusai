from pydantic import BaseModel


class IngestDocumentsPayload(BaseModel):
    knowledge_base_uuid: str
