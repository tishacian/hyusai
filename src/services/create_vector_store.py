from connections.celery.custom_task_class import CustomTask
from connections.celery.task_response import TaskResponse
from connections.models.flow_operations import CreateVectorStorePayload


class CreateVectorStoreService:
    def __init__(self, celery_task: CustomTask | None = None):
        self.celery_task = celery_task

    def call(self, payload: CreateVectorStorePayload) -> TaskResponse:
        return {"status": "success"}
