from uuid import UUID

from connections.models.flow_operations import BaseTaskResponse


class IngestDocumentsResponse(BaseTaskResponse):
    knowledge_base_uuid: UUID
