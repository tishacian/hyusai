"""Read-only connector catalogue, served even while the connector framework is off.

`/connections` stays closed (404) when the framework is disabled; this route only
describes what can be connected, so the Connectors page can show the catalogue
in every deployment without opening a connection, a test or an import.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.endpoints.connections import _access as require_workspace_member
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.connectors.catalog import public_catalog

router = APIRouter()


@router.get("")
def connector_catalog(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(db, workspace, user)
    return public_catalog(framework_enabled=settings.connector_framework_enabled)
