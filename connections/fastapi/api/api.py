from fastapi import APIRouter

from .endpoints.db import router as router_db
from .endpoints.flow_operations import router as router_flow_operations
from .endpoints.healthcheck import router as router_healthcheck
from .endpoints.sharepoint import router as router_sharepoint

api_router = APIRouter()
api_router.include_router(router_healthcheck, tags=["Healthcheck"])
api_router.include_router(router_flow_operations, tags=["Flow Operations"])
api_router.include_router(router_db, tags=["Database"])
api_router.include_router(router_sharepoint)
