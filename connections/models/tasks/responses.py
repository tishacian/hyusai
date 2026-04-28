from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None
    logs: str | None = None
    progress: str | None = None
