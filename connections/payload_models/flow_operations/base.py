from uuid import UUID

from pydantic import BaseModel


class BaseTaskResponse(BaseModel):
    task_id: UUID
