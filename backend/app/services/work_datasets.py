"""Bounded dataset projection for a component in an immutable Work release.

Neither dataset ids nor column names come from the HTTP caller. A released
component names its producing action and columns; the selected, readable Run
must have produced the dataset itself. Echoing another dataset id is not a
grant to read it.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.models.run import Run
from app.models.tabular import TabularDataset
from app.services.experience.bindings import BINDING_KEY_RE
from app.services.experience.lifecycle import ExperienceError
from app.services.object_store import get_object_store
from app.services.run_access import readable_runs
from app.services.tabular_datasets import _json_scalar, model_provenance

MAX_ROWS = 1000
MAX_COLUMNS = 8
_SELECTOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_MAPPING_FIELDS = frozenset({"time", "value", "actual", "lower", "upper", "series"})


def _refuse(code: str, message: str, status: int = 422) -> None:
    raise ExperienceError(code=code, message=message, status_code=status)


def _chart_contract(
    pages: Mapping[str, Any],
    page_id: str,
    component_id: str,
    *,
    bindings_snapshot: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    page = next(
        (p for p in pages.get("pages", []) if isinstance(p, Mapping) and p.get("id") == page_id),
        None,
    )
    components = page.get("components", []) if page else []
    component = next(
        (c for c in components if isinstance(c, Mapping) and c.get("id") == component_id), None
    )
    props = component.get("props", {}) if component else {}
    if (
        not component
        or component.get("type") != "chart"
        or not isinstance(props, Mapping)
        or props.get("kind") != "timeseries"
    ):
        _refuse(
            "WORK_DATASET_COMPONENT_NOT_FOUND", "This released component has no dataset chart.", 404
        )
    source = props.get("datasetSource")
    mapping = props.get("mapping")
    if "dataBinding" in props or "queryBinding" in props:
        _refuse(
            "WORK_DATASET_CONFIG_INVALID", "A dataset chart must use datasetSource exclusively."
        )
    if (
        not isinstance(source, Mapping)
        or set(source) - {"source", "selector", "componentId"}
        or source.get("source") != "run-output"
    ):
        _refuse("WORK_DATASET_CONFIG_INVALID", "The dataset source must reference a Run output.")
    selector = source.get("selector")
    if (
        not isinstance(selector, str)
        or len(selector) > 240
        or not _SELECTOR.fullmatch(selector)
        or {"__proto__", "prototype", "constructor"}.intersection(selector.split("."))
    ):
        _refuse("WORK_DATASET_CONFIG_INVALID", "The dataset selector is invalid.")
    if not isinstance(source.get("componentId"), str) or not source["componentId"].strip():
        _refuse(
            "WORK_DATASET_CONFIG_INVALID", "The dataset source must name a producing component."
        )
    action = next(
        (c for c in components if isinstance(c, Mapping) and c.get("id") == source["componentId"]),
        None,
    )
    action_props = action.get("props", {}) if action else {}
    if not isinstance(action_props, Mapping):
        _refuse("WORK_DATASET_CONFIG_INVALID", "The producing action has invalid properties.")
    query = action_props.get("queryBinding") if isinstance(action_props, Mapping) else None
    binding_key = (
        action_props.get("bindingKey")
        if action and action.get("type") in {"form", "action_button"}
        else query.get("bindingKey")
        if isinstance(query, Mapping) and query.get("source") == "system-binding"
        else None
    )
    snapshot = next(
        (
            b
            for b in bindings_snapshot or []
            if isinstance(b, Mapping) and b.get("binding_key") == binding_key
        ),
        None,
    )
    if (
        not isinstance(binding_key, str)
        or not BINDING_KEY_RE.fullmatch(binding_key)
        or (bindings_snapshot is not None and (not snapshot or not snapshot.get("system_id")))
    ):
        _refuse(
            "WORK_DATASET_CONFIG_INVALID",
            "The dataset source must name a released action on this page.",
        )
    if (
        not isinstance(mapping, Mapping)
        or set(mapping) - _MAPPING_FIELDS
        or not mapping.get("time")
        or not mapping.get("value")
    ):
        _refuse("WORK_DATASET_CONFIG_INVALID", "The chart needs time and value column mappings.")
    if any(not isinstance(value, str) or len(value) > 200 for value in mapping.values()):
        _refuse("WORK_DATASET_CONFIG_INVALID", "Chart columns must be non-empty column names.")
    if bool(mapping.get("lower")) != bool(mapping.get("upper")):
        _refuse(
            "WORK_DATASET_CONFIG_INVALID", "An uncertainty band needs both lower and upper columns."
        )
    columns = list(dict.fromkeys(value for value in mapping.values() if value))
    limit = props.get("maxRows", MAX_ROWS)
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_ROWS
        or len(columns) > MAX_COLUMNS
    ):
        _refuse("WORK_DATASET_CONFIG_INVALID", "A chart may read at most 1000 rows and 8 columns.")
    return {
        "source": source,
        "columns": columns,
        "limit": limit,
        "binding_key": binding_key,
        "system_id": snapshot["system_id"] if snapshot else None,
    }


def component_contract(release: Any, page_id: str, component_id: str) -> dict[str, Any]:
    return _chart_contract(
        release.pages if isinstance(release.pages, Mapping) else {},
        page_id,
        component_id,
        bindings_snapshot=release.bindings_snapshot or [],
    )


def validate_dataset_chart_configuration(pages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Ready-check blockers; incomplete drafts can still be saved and edited."""
    issues = []
    for page in pages.get("pages", []):
        if not isinstance(page, Mapping):
            continue
        for component in page.get("components", []):
            if not isinstance(component, Mapping) or component.get("type") != "chart":
                continue
            props = component.get("props")
            if (
                not isinstance(props, Mapping)
                or props.get("kind") != "timeseries"
                or props.get("datasetSource") is None
            ):
                continue
            try:
                _chart_contract(pages, page.get("id"), component.get("id"), bindings_snapshot=None)
            except ExperienceError as exc:
                issues.append(
                    {
                        "code": exc.code,
                        "message": exc.message,
                        "page_id": page.get("id"),
                        "component_id": component.get("id"),
                    }
                )
    return issues


def _select(output: Any, selector: str) -> Any:
    value = output
    for name in selector.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(name)
    return value


def read_projected_rows(
    dataset: TabularDataset, columns: list[str], limit: int
) -> tuple[list[dict[str, Any]], int]:
    """Read only projected Parquet columns and one bounded batch.

    Remote stores expose a seekable file with range reads. In particular, this
    does not use materialize/read_bytes, which copy the entire dataset first.
    """
    import pyarrow.parquet as pq

    if not dataset.storage_key:
        _refuse("WORK_DATASET_NOT_READY", "The dataset has no materialized rows.", 409)
    store = get_object_store()
    with ExitStack() as stack:
        if store.backend == "local":
            source = stack.enter_context(store._local_path(dataset.storage_key).open("rb"))
        else:
            source = stack.enter_context(
                store._fsspec().open(
                    store._remote_key(dataset.storage_key),
                    "rb",
                    block_size=65536,
                    cache_type="none",
                )
            )
        parquet = pq.ParquetFile(source)
        if set(columns) - set(parquet.schema_arrow.names):
            _refuse(
                "WORK_DATASET_COLUMN_MISSING",
                "A configured chart column is missing from the produced dataset.",
                409,
            )
        total = parquet.metadata.num_rows
        batch = next(
            parquet.iter_batches(batch_size=limit, columns=columns, use_threads=False), None
        )
        raw = batch.to_pylist() if batch is not None else []
    return [{name: _json_scalar(value) for name, value in row.items()} for row in raw], total


def work_dataset(
    db: Session,
    *,
    workspace: Any,
    user: Any,
    experience: Any,
    release: Any,
    page_id: str,
    component_id: str,
    run_id: str,
) -> dict[str, Any]:
    contract = component_contract(release, page_id, component_id)
    run = db.query(Run).filter(Run.id == run_id, Run.workspace_id == workspace.id).one_or_none()
    if run is None:
        _refuse("WORK_DATASET_RUN_NOT_FOUND", "Run not found for this component.", 404)
    ingress = run.input_ref.get("_ingress", {}) if isinstance(run.input_ref, Mapping) else {}
    adapter = ingress.get("adapter", {}) if isinstance(ingress, Mapping) else {}
    expected = {
        "experience_id": experience.id,
        "experience_release_id": release.id,
        "binding_key": contract["binding_key"],
        "page_id": page_id,
        "component_id": contract["source"]["componentId"],
    }
    if (
        not isinstance(adapter, Mapping)
        or any(adapter.get(key) != value for key, value in expected.items())
        or run.system_id != contract["system_id"]
    ):
        _refuse("WORK_DATASET_RUN_NOT_FOUND", "Run not found for this component.", 404)
    if not readable_runs(db, runs=[run], user=user, workspace=workspace):
        _refuse("WORK_DATASET_RUN_NOT_FOUND", "Run not found for this component.", 404)
    if run.status != "completed":
        _refuse("WORK_DATASET_RUN_NOT_COMPLETE", "The producing Run has not completed.", 409)
    dataset_id = _select(run.output_ref, contract["source"]["selector"])
    if not isinstance(dataset_id, str) or not dataset_id or len(dataset_id) > 36:
        _refuse(
            "WORK_DATASET_OUTPUT_MISSING",
            "The Run did not produce the configured dataset reference.",
            409,
        )
    dataset = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.id == dataset_id,
            TabularDataset.workspace_id == workspace.id,
            TabularDataset.run_id == run.id,
            TabularDataset.status != "deleted",
        )
        .one_or_none()
    )
    if dataset is None:
        _refuse("WORK_DATASET_NOT_FOUND", "Dataset not found for this Run.", 404)
    if dataset.status != "ready":
        _refuse("WORK_DATASET_NOT_READY", "The produced dataset is not ready.", 409)
    try:
        rows, total = read_projected_rows(dataset, contract["columns"], contract["limit"])
    except ExperienceError:
        raise
    except (OSError, ValueError) as exc:
        raise ExperienceError(
            code="WORK_DATASET_READ_FAILED",
            message="The produced dataset could not be read.",
            status_code=503,
        ) from exc
    model = model_provenance(db, dataset)
    return {
        "rows": rows,
        "columns": contract["columns"],
        "total_rows": total,
        "returned_rows": len(rows),
        "truncated": total > len(rows),
        "provenance": {
            "dataset_id": dataset.id,
            "dataset_version": dataset.version,
            "dataset_name": dataset.name,
            "run_id": run.id,
            "run_completed_at": run.completed_at,
            "model_id": model.get("model_id") if model else None,
            "model": model,
        },
        "freshness": {
            "dataset_created_at": dataset.created_at,
            "run_completed_at": run.completed_at,
        },
    }
