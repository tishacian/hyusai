"""Lazy dispatch: native drivers are loaded only inside the connector child."""

from importlib import import_module

_MODULES = {
    "dbapi": "sql",
    "sqlalchemy": "sql",
    "adbc": "sql",
    "object_store": "object_store",
    "document": "nosql",
    "search": "nosql",
    "wide_column": "nosql",
    "uc_rest": "lakehouse",
    "delta_sharing": "lakehouse",
    "iceberg_rest": "lakehouse",
    "mcp": "tools",
    "openapi": "tools",
}


def execute(
    operation,
    config,
    credentials,
    parameters,
    deadline_at,
    output_dir,
    *,
    family,
    dialect,
    access=None,
    limits=None,
    execution=None,
):
    from app.services.connectors.adapters.sql import AdapterError

    module = _MODULES.get(family)
    if operation == "write_preview" and family in {"object_store", "document", "search"}:
        module = "write_preview"
    if module is None:
        raise AdapterError("CONNECTOR_ADAPTER_UNAVAILABLE")
    required = parameters.get("require_consistency")
    if required is not None and (
        operation not in ("import", "preview")
        or required not in ("snapshot", "per_partition", "none")
    ):
        raise AdapterError("CONNECTOR_CONSISTENCY_UNAVAILABLE")
    parameters = {k: v for k, v in parameters.items() if k != "require_consistency"}
    adapter = import_module(f"app.services.connectors.adapters.{module}")
    output = adapter.execute(
        operation,
        config,
        credentials,
        parameters,
        deadline_at,
        output_dir,
        dialect=dialect,
        access=access,
        limits=limits,
        **({"execution": execution} if execution is not None else {}),
    )

    levels = {"none": 0, "per_partition": 1, "snapshot": 2}
    if required and levels.get(output.get("consistency", "none"), 0) < levels[required]:
        raise AdapterError("CONNECTOR_CONSISTENCY_UNAVAILABLE")
    return output
