from fastapi import APIRouter

from .endpoints.collections import router as router_collections
from .endpoints.db import router as router_db
from .endpoints.files import router as router_files
from .endpoints.flow_operations import router as router_flow_operations
from .endpoints.healthcheck import router as router_healthcheck
from .endpoints.query import router as router_query
from .endpoints.tasks import router as router_tasks
from .endpoints.users import router as router_users

api_router = APIRouter()
api_router.include_router(router_healthcheck, tags=["Healthcheck"])
api_router.include_router(router_flow_operations, tags=["Flow Operations"])
api_router.include_router(router_db, prefix="/db", tags=["Database"])
api_router.include_router(router_users, prefix="/db", tags=["Database"])
api_router.include_router(router_collections)
api_router.include_router(router_files, prefix="/files", tags=["Files"])
api_router.include_router(router_tasks, prefix="/tasks", tags=["Tasks"])
api_router.include_router(router_query, prefix="/query", tags=["Query"])
