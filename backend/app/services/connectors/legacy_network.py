"""Attach network authority to legacy runtime config without trusting its fields.

Only a persistent Workspace ORM object can provide a binding. JSON mappings,
including a caller-supplied workspace_id, cannot grant private network access.
The binding is an in-process dict attribute, absent from JSON and public config.
"""

from contextlib import contextmanager
from functools import wraps
from inspect import signature

from sqlalchemy.orm import object_session

from app.models.workspace import Workspace
from app.services.connectors.network_exceptions import load_grants, network_grants
from app.services.connectors.network_policy import ConnectorNetworkError


class _BoundConfig(dict):
    pass


def bind_config(config, workspace):
    if not isinstance(workspace, Workspace) or object_session(workspace) is None:
        return config
    result = _BoundConfig(config)
    result._workspace = workspace
    return result


@contextmanager
def network_scope(config):
    if not isinstance(config, _BoundConfig):
        yield
        return
    workspace = config._workspace
    db = object_session(workspace)
    if db is None:
        raise ConnectorNetworkError("CONNECTOR_NETWORK_CONTEXT_UNAVAILABLE")
    current = db.get(Workspace, workspace.id, populate_existing=True)
    if current is None or current.deleted_at or not current.is_active:
        raise ConnectorNetworkError("CONNECTOR_WORKSPACE_UNAVAILABLE", 403)
    # Read at each remote call, not once when the config was resolved. Revoking
    # an exception therefore takes effect even for a cached MCP server mapping.
    with network_grants(load_grants(db, current.id)):
        yield


def network_scoped(function):
    parameter = next(iter(signature(function).parameters))

    @wraps(function)
    def call(*args, **kwargs):
        config = args[0] if args else kwargs.get(parameter)
        with network_scope(config):
            return function(*args, **kwargs)

    return call
