"""Observe SQLAlchemy source DML, including bulk ORM and Core updates.

Projection and journal writes use the very same Connection/transaction as the
source mutation. Errors abort that transaction: an enabled journal must never
silently omit a lifecycle transition. Textual SQL is intentionally not a write
interface for these sources; maintenance backfills are explicit snapshots.
"""

from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.dml import Delete, Insert, Update

from app.core.config import settings

from .projection import SOURCE_FIELDS, SOURCES, project

_GUARD = "activity_observer_busy"
_PENDING = "activity_observer_pending"


def _before(connection, clause, multiparams, params, execution_options):
    if connection.info.get(_GUARD) or not getattr(
        settings, "activity_observability_enabled", False
    ):
        return
    if not isinstance(clause, (Insert, Update, Delete)) or clause.table.name not in SOURCES:
        return
    parameter_sets = list(multiparams) or [params or {}]
    if isinstance(clause, Update):
        changed = {getattr(key, "name", key) for key in (clause._values or {})}
        changed.update(key for parameters in parameter_sets for key in parameters)
        if changed and not changed.intersection(SOURCE_FIELDS):
            return
    connection.info[_GUARD] = True
    try:
        identifiers = set()
        if not isinstance(clause, Insert):
            statement = select(clause.table.c.id)
            if clause.whereclause is not None:
                statement = statement.where(clause.whereclause)
            # Source row locks prevent another mutation from changing the
            # selected identity/state before its matching UPDATE and event.
            statement = statement.with_for_update()
            for parameters in parameter_sets:
                identifiers.update(connection.execute(statement, parameters).scalars())
        connection.info.setdefault(_PENDING, {})[id(clause)] = identifiers
    finally:
        connection.info[_GUARD] = False


def _after(connection, clause, multiparams, params, execution_options, result):
    if connection.info.get(_GUARD):
        return
    pending = connection.info.get(_PENDING, {})
    if id(clause) not in pending:
        return
    identifiers = pending.pop(id(clause))
    connection.info[_GUARD] = True
    try:
        if isinstance(clause, Insert):
            for parameters in result.context.compiled_parameters:
                if parameters.get("id") is not None:
                    identifiers.add(parameters["id"])
        for identifier in sorted(identifiers):
            project(connection, clause.table.name, identifier)
    finally:
        connection.info[_GUARD] = False


def _clear(connection):
    connection.info.pop(_PENDING, None)


def install_observers():
    if not event.contains(Engine, "before_execute", _before):
        event.listen(Engine, "before_execute", _before)
        event.listen(Engine, "after_execute", _after)
        event.listen(Engine, "rollback", _clear)
        event.listen(Engine, "commit", _clear)
