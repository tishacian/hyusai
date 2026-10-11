"""Point-in-time features compiled onto the existing, sealed SQL transform engine.

This is a deterministic preparation operation, never a learned feature store.
The reference dataset is immutable and pinned. Every output row retains its base
identity, key and decision timestamp; these and the contract identify exactly
which source rows contributed without materializing a quadratic lineage table.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.services.tabular_datasets import (
    TabularError,
    dataset_reference,
    profile_frame,
    register_frame,
    resolve_dataset_ref,
)
from app.services.tabular_transforms import TransformSource, execute_sql, source_catalog

Column = Annotated[str, Field(min_length=1, max_length=128)]


class DatasetPin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str = Field(min_length=1, max_length=36)
    version: int = Field(ge=1)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class HistoricalAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["count", "sum", "mean", "min", "max"]
    column: Column | None = None
    output: Column

    @model_validator(mode="after")
    def column_required(self):
        if (self.operation == "count") != (self.column is None):
            raise ValueError(
                "count counts events without a column; numeric aggregates require a column"
            )
        return self


class HistoricalEnrichmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    operation: Literal["historical_aggregates"] = "historical_aggregates"
    base: DatasetPin
    history: DatasetPin
    base_row_id: Column
    history_row_id: Column
    base_key: Column
    history_key: Column
    decision_time: Column
    available_time: Column
    # Only explicitly known-at-decision fields are carried to the result.
    base_features: list[Column] = Field(default_factory=list, max_length=100)
    target_columns: list[Column] = Field(min_length=1, max_length=10)
    unavailable_columns: list[Column] = Field(default_factory=list, max_length=100)
    aggregates: list[HistoricalAggregate] = Field(min_length=1, max_length=20)
    cardinality: Literal["many_to_one"] = "many_to_one"
    max_base_rows: int = Field(default=50_000, ge=1, le=100_000)
    max_history_rows: int = Field(default=100_000, ge=1, le=500_000)
    max_input_bytes: int = Field(default=64_000_000, ge=1, le=128_000_000)
    max_unmatched_fraction: float = Field(default=1.0, ge=0.0, le=1.0)
    timeout_s: int = Field(default=30, ge=1, le=60)

    @model_validator(mode="after")
    def safe_columns(self):
        inputs = [
            self.base_row_id,
            self.history_row_id,
            self.base_key,
            self.history_key,
            self.decision_time,
            self.available_time,
            *self.base_features,
            *self.target_columns,
            *self.unavailable_columns,
        ]
        outputs = [a.output for a in self.aggregates]
        aggregate_inputs = [a.column for a in self.aggregates if a.column]
        if any(
            c.startswith("__hy_enrich_") or "\x00" in c for c in inputs + outputs + aggregate_inputs
        ):
            raise ValueError("reserved column name")
        forbidden = set(self.target_columns + self.unavailable_columns)
        feature_inputs = set(
            self.base_features
            + aggregate_inputs
            + [self.base_key, self.history_key, self.decision_time, self.available_time]
        )
        if forbidden & feature_inputs or forbidden & set(outputs):
            raise ValueError("targets and unavailable columns cannot contribute features")
        if len(set(outputs)) != len(outputs) or set(outputs) & set(inputs):
            raise ValueError("aggregate output names must be distinct from source columns")
        if self.base.dataset_id == self.history.dataset_id:
            raise ValueError("base and history must be distinct pinned datasets")
        return self


def _error(code: str, message: str) -> TabularError:
    return TabularError(code=f"ENRICHMENT_{code}", message=message)


def _quote(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def _parse(spec: Any) -> HistoricalEnrichmentSpec:
    try:
        return HistoricalEnrichmentSpec.model_validate(spec)
    except ValidationError as exc:
        raise _error("SPEC_INVALID", str(exc)[:800]) from exc


def _resolve(db: DBSession, workspace_id: str, spec: HistoricalEnrichmentSpec):
    sources = []
    for name, pin, cap in (
        ("base", spec.base, spec.max_base_rows),
        ("history", spec.history, spec.max_history_rows),
    ):
        dataset = resolve_dataset_ref(
            db, workspace_id=workspace_id, ref={"dataset_id": pin.dataset_id}
        )
        if int(dataset.version) != pin.version:
            raise _error(
                "VERSION_MISMATCH", "The pinned dataset version does not match its identity."
            )
        if int(dataset.row_count or 0) > cap or int(dataset.size_bytes or 0) > spec.max_input_bytes:
            raise _error("INPUT_TOO_LARGE", "A source exceeds the declared input budget.")
        sources.append(TransformSource(view=name, dataset=dataset))
    return sources


def _compile(spec: HistoricalEnrichmentSpec, base_columns: list[str]) -> str:
    """Collapse equal timestamps before the ASOF so the answer has no tie order."""
    q = _quote
    grouped = [
        f"{q(spec.history_key)} AS __hy_enrich_key",
        f"TRY_CAST({q(spec.available_time)} AS TIMESTAMPTZ) AS __hy_enrich_time",
        "COUNT(*) AS __hy_enrich_events",
    ]
    cumulative = [
        "__hy_enrich_key",
        "__hy_enrich_time",
        "SUM(__hy_enrich_events) OVER w AS __hy_enrich_matches",
    ]
    projected = [f"b.{q(c)}" for c in base_columns]
    for i, aggregate in enumerate(spec.aggregates):
        col = q(aggregate.column) if aggregate.column else None
        alias = f"__hy_enrich_a{i}"
        out = q(aggregate.output)
        if aggregate.operation == "count":
            expression = "SUM(__hy_enrich_events) OVER w"
            projected.append(f"COALESCE(h.{out}, 0)::BIGINT AS {out}")
        else:
            op = aggregate.operation
            if op == "mean":
                grouped += [f"SUM({col}) AS {alias}", f"COUNT({col}) AS {alias}_n"]
                expression = f"(SUM({alias}) OVER w) / NULLIF(SUM({alias}_n) OVER w, 0)"
            else:
                grouped.append(f"{op.upper()}({col}) AS {alias}")
                expression = f"{op.upper()}({alias}) OVER w"
            projected.append(f"h.{out}")
        cumulative.append(f"{expression} AS {out}")
    return f"""WITH grouped AS (
        SELECT {", ".join(grouped)} FROM history GROUP BY 1, 2
    ), cumulative AS (
        SELECT {", ".join(cumulative)} FROM grouped
        WINDOW w AS (PARTITION BY __hy_enrich_key ORDER BY __hy_enrich_time
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
    )
    SELECT {", ".join(projected)}, COALESCE(h.__hy_enrich_matches, 0)::BIGINT AS __hy_enrich_matches
    FROM base b ASOF LEFT JOIN cumulative h
      ON b.{q(spec.base_key)} = h.__hy_enrich_key
     AND TRY_CAST(b.{q(spec.decision_time)} AS TIMESTAMPTZ) > h.__hy_enrich_time
    ORDER BY b.{q(spec.base_row_id)}"""


def _evaluate(db: DBSession, *, workspace_id: str, spec: HistoricalEnrichmentSpec):
    sources = _resolve(db, workspace_id, spec)
    base_names = [str(c["name"]) for c in (sources[0].dataset.schema_json or [])]
    base_columns = list(
        dict.fromkeys(
            [
                spec.base_row_id,
                spec.base_key,
                spec.decision_time,
                *spec.base_features,
                *[c for c in spec.target_columns if c in base_names],
            ]
        )
    )
    evidence: dict[str, Any] = {}

    def prepare(connection):
        # This callback is platform code. The graph never supplies SQL here.
        for source in sources:
            pin = getattr(spec, source.view)
            if pin.sha256 is not None and pin.sha256 != source_evidence[source.view]["sha256"]:
                raise _error(
                    "SOURCE_CHANGED",
                    "A pinned source no longer matches its qualified content digest.",
                )
        connection.execute("SET TimeZone='UTC'")
        for view, row_id, key, timestamp, limit, required in (
            (
                "base",
                spec.base_row_id,
                spec.base_key,
                spec.decision_time,
                spec.max_base_rows,
                base_columns,
            ),
            (
                "history",
                spec.history_row_id,
                spec.history_key,
                spec.available_time,
                spec.max_history_rows,
                [a.column for a in spec.aggregates if a.column],
            ),
        ):
            columns = dict(
                (row[0], row[1]) for row in connection.execute(f"DESCRIBE {view}").fetchall()
            )
            if not set([row_id, key, timestamp, *required]) <= set(columns):
                raise _error("COLUMN_MISSING", f"A required column is absent from {view}.")
            if set(a.output for a in spec.aggregates) & set(columns):
                raise _error(
                    "COLUMN_COLLISION",
                    "An aggregate output would replace an existing source column.",
                )
            if columns[key] not in {
                "VARCHAR",
                "BIGINT",
                "INTEGER",
                "SMALLINT",
                "TINYINT",
                "UBIGINT",
                "UINTEGER",
                "USMALLINT",
                "UTINYINT",
            }:
                raise _error("KEY_INVALID", "Join keys must be non-null strings or integers.")
            evidence[f"{view}_key_type"] = columns[key]
            q = _quote
            count, unique, missing_id, missing_key, bad_time = connection.execute(f"""
                SELECT COUNT(*), COUNT(DISTINCT {q(row_id)}), COUNT(*) FILTER (WHERE {q(row_id)} IS NULL),
                COUNT(*) FILTER (WHERE {q(key)} IS NULL OR CAST({q(key)} AS VARCHAR) = ''),
                COUNT(*) FILTER (WHERE TRY_CAST({q(timestamp)} AS TIMESTAMPTZ) IS NULL
                                       OR NOT ISFINITE(TRY_CAST({q(timestamp)} AS TIMESTAMPTZ)))
                FROM {view}""").fetchone()
            if count > limit:
                raise _error("INPUT_TOO_LARGE", "A materialized source exceeds its row budget.")
            if unique != count or missing_id or missing_key:
                raise _error(
                    "KEY_INVALID",
                    "Each source needs unique row identities and non-null, non-empty entity keys.",
                )
            if bad_time:
                raise _error(
                    "TIME_INVALID",
                    "All timestamps must be finite and parseable; naive timestamps mean UTC.",
                )
            if view == "base" and not count:
                raise _error("BASE_EMPTY", "The base dataset must contain decision rows.")
            if view == "history":
                for column in required:
                    numeric = columns[column].split("(")[0]
                    if numeric not in {
                        "BIGINT",
                        "INTEGER",
                        "SMALLINT",
                        "TINYINT",
                        "UBIGINT",
                        "UINTEGER",
                        "USMALLINT",
                        "UTINYINT",
                        "HUGEINT",
                        "UHUGEINT",
                        "FLOAT",
                        "DOUBLE",
                        "DECIMAL",
                    }:
                        raise _error(
                            "AGGREGATE_TYPE",
                            "Historical numeric aggregates require numeric columns.",
                        )
                    if connection.execute(
                        f"SELECT COUNT(*) FROM history WHERE {q(column)} IS NOT NULL AND NOT ISFINITE({q(column)})"
                    ).fetchone()[0]:
                        raise _error(
                            "AGGREGATE_TYPE", "Historical numeric values must be finite or null."
                        )
            evidence[f"{view}_rows"] = count
        if evidence["base_key_type"] != evidence["history_key_type"]:
            raise _error(
                "KEY_TYPE_MISMATCH", "Join key types must match; implicit coercion is not allowed."
            )

    started = time.monotonic()
    source_evidence: dict[str, Any] = {}
    frame = execute_sql(
        sources,
        _compile(spec, base_columns),
        row_limit=min(spec.max_base_rows, int(settings.tabular_transform_max_rows)),
        prepare=prepare,
        max_input_rows=max(spec.max_base_rows, spec.max_history_rows),
        max_input_bytes=spec.max_input_bytes,
        timeout_s=spec.timeout_s,
        source_evidence=source_evidence,
    )
    if frame.height != evidence["base_rows"]:
        raise _error("CARDINALITY", "Enrichment must preserve exactly one row per base decision.")
    unmatched = frame.filter(frame["__hy_enrich_matches"] == 0).height
    fraction = unmatched / frame.height
    if fraction > spec.max_unmatched_fraction:
        raise _error(
            "UNMATCHED", "The fraction of decisions without available history exceeds the contract."
        )
    frame = frame.drop("__hy_enrich_matches")
    contract = spec.model_dump(mode="json")
    for source in sources:
        actual_digest = source_evidence[source.view]["sha256"]
        contract[source.view]["sha256"] = actual_digest
    digest = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence.update(
        {
            "contract": contract,
            "contract_sha256": digest,
            "sources": [
                {
                    "role": source.view,
                    "dataset_id": source.dataset.id,
                    "version": source.dataset.version,
                    "rows": evidence[f"{source.view}_rows"],
                    **source_evidence[source.view],
                }
                for source in sources
            ],
            "row_lineage": {
                "output_identity": spec.base_row_id,
                "base_identity": spec.base_row_id,
                "history_identity": spec.history_row_id,
                "selection": "history.key = base.key AND history.available_time < base.decision_time",
                "timezone": "UTC",
                "same_timestamp": "excluded",
                "source_versions_pinned": True,
            },
            "unmatched_rows": unmatched,
            "unmatched_fraction": fraction,
            "output_rows": frame.height,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
            "added_columns": [a.output for a in spec.aggregates],
            "feature_columns": list(
                dict.fromkeys([*spec.base_features, *[a.output for a in spec.aggregates]])
            ),
            "comparison_independence": "not_established_by_enrichment",
        }
    )
    return frame, sources, evidence


def preview_enrichment(
    db: DBSession, *, workspace_id: str, spec: Any, row_limit: int = 50
) -> dict[str, Any]:
    frame, sources, evidence = _evaluate(db, workspace_id=workspace_id, spec=_parse(spec))
    # Validate the complete result even for a small preview; no silent truncation
    # of the input history or of the unmatched fraction decision.
    profile = profile_frame(frame.head(max(1, min(int(row_limit), 500))))
    return {
        "row_count": frame.height,
        "column_count": frame.width,
        "schema": profile["schema"],
        "preview": profile["preview"],
        "enrichment": evidence,
        "stats": profile["stats"],
        "duration_ms": evidence["duration_ms"],
        "sources": source_catalog(sources),
    }


def run_enrichment_transform(
    db: DBSession,
    *,
    workspace_id: str,
    spec: Any,
    output_name: str = "historical features",
    run_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    frame, sources, evidence = _evaluate(db, workspace_id=workspace_id, spec=_parse(spec))
    dataset = register_frame(
        db,
        workspace_id=workspace_id,
        name=output_name,
        frame=frame,
        source="transform",
        produced_by="sql_transform_v1",
        parent_ids=[source.dataset.id for source in sources],
        run_id=run_id,
        node_id=node_id,
        lineage={
            "engine": "duckdb",
            "enrichment": evidence,
            "added_columns": evidence["added_columns"],
            "duration_ms": evidence["duration_ms"],
        },
    )
    db.commit()
    return {
        **dataset_reference(dataset),
        "enrichment": evidence,
        "duration_ms": evidence["duration_ms"],
    }
