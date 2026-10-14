"""Build a CTE per active step and bind every prefix against empty native views."""

from __future__ import annotations

from dataclasses import replace

import duckdb
import pyarrow as pa
import sqlglot
from sqlglot import exp

from app.services.dataops.selectors import resolve_params
from app.services.dataops.types import arrow_type, describe, portable_type


class PrepCompileError(ValueError):
    def __init__(self, message, *, step_id=None, position=None):
        super().__init__(message)
        self.step_id, self.position = step_id, position


def _diff(previous, current):
    before = {f["name"]: f for f in previous}
    after = {f["name"]: f for f in current}
    return {
        "added": [n for n in after if n not in before],
        "removed": [n for n in before if n not in after],
        "changed": [
            n for n in after if n in before and after[n].get("dtype") != before[n].get("dtype")
        ],
    }


def _normalize_outputs(sql, schema, names):
    from app.services.dataops.compiler import quote

    terms = []
    for field in schema:
        column = quote(field["name"])
        dtype = portable_type(field) if field["name"] in names else None
        terms.append(f"CAST({column} AS {dtype}) AS {column}" if dtype else column)
    return f"SELECT {','.join(terms)} FROM ({sql}) AS __dp_typed"


def _validate_typed_literals(conn, step, params, schema):
    """Validate literal conversions even when an empty-view plan skips evaluation."""
    from app.services.dataops.types import portable_type

    fields = {f["name"]: f for f in schema}
    pairs = []
    action = step.action
    if action == "add_column":
        pairs.append((params.get("value"), portable_type({"dtype": params["type"]})))
    elif action in {"fill_null", "fill_nulls"} and params.get("method", "constant") == "constant":
        for name in params.get("columns", [params.get("column")]):
            if name in fields:
                pairs.append((params.get("value"), portable_type(fields[name])))
    elif action == "filter_range" and params.get("column") in fields:
        pairs.extend(
            (params[key], portable_type(fields[params["column"]]))
            for key in ("min", "max")
            if params.get(key) is not None
        )
    elif action in {"filter_rows", "flag_rows"}:
        for item in params.get("conditions", []):
            if item.get("column") in fields and item.get("op") in {
                "eq",
                "ne",
                "lt",
                "le",
                "gt",
                "ge",
                "between",
                "in",
                "not_in",
            }:
                dtype = portable_type(fields[item["column"]])
                pairs.extend((value, dtype) for value in item.get("values", [item.get("value")]))
    elif action in {"map_values", "replace_values"} and params.get("match", "exact") == "exact":
        for name in params.get("columns", [params.get("column")]):
            if name in fields:
                dtype = portable_type(fields[name])
                pairs.extend(
                    (pair[key], dtype) for pair in params.get("pairs", []) for key in ("from", "to")
                )
    if action == "negate_boolean" and any(
        fields.get(n, {}).get("kind") != "boolean" for n in params.get("columns", [])
    ):
        raise ValueError("DATAPREP_TYPE_MISMATCH: boolean required")
    for value, dtype in pairs:
        if value is not None and dtype:
            try:
                conn.execute(f"SELECT CAST(? AS {dtype})", [value]).fetchone()
            except duckdb.Error:
                raise ValueError("DATAPREP_LITERAL_TYPE") from None


def compile_typed(spec, schemas, *, identities=None, arrow_schemas=None):
    from app.services.dataops.compiler import CompiledPrep, _compile_raw, canonical_spec
    from app.services.dataops.secrets import hash_parameters

    if not schemas:
        raise PrepCompileError("DATAPREP_INPUT_PORTS_INVALID")

    # Older pure compiler callers supplied only profile kinds. They can still emit SQL;
    # API/execution always supply native Arrow schemas and receive authoritative types.
    typed = bool(arrow_schemas) or all("dtype" in f for fields in schemas.values() for f in fields)
    conn = duckdb.connect(config={"threads": 1, "memory_limit": "64MB"}) if typed else None
    step_schemas, warnings, step_queries = [], [], {}
    current_schema = list(schemas.get("in", next(iter(schemas.values()))))
    try:
        if conn:
            conn.execute("SET TimeZone='UTC'")
            # Bind types against empty views without evaluating authored constants
            # (e.g. lpad('x', 1_000_000_000, 'x')) in the API process.
            conn.execute("PRAGMA disable_optimizer")
            for port, fields in schemas.items():
                schema = (
                    arrow_schemas[port]
                    if arrow_schemas
                    else pa.schema(
                        [
                            pa.field(f["name"], arrow_type(f), nullable=f.get("nullable", True))
                            for f in fields
                        ]
                    )
                )
                conn.register(port, schema.empty_table())
            conn.execute("SET enable_external_access=false")
            conn.execute("SET lock_configuration=true")

        def infer(sql, fallback):
            if not conn:
                return [{"name": n} for n in fallback]
            parameters = hash_parameters(spec)
            used = {n.name for n in sqlglot.parse_one(sql, read="duckdb").find_all(exp.Placeholder)}
            table = conn.execute(
                f"SELECT * FROM ({sql}) LIMIT 0", {k: v for k, v in parameters.items() if k in used}
            ).to_arrow_table()
            return describe(table.schema)

        if spec.operation != "prepare":
            params = resolve_params(spec.params, current_schema)
            if spec.operation == "join" and isinstance(params.get("select"), dict):
                from app.services.dataops.selectors import resolve_selector

                params["select"] = {
                    port: resolve_selector(value, schemas[port])
                    for port, value in params["select"].items()
                }
            raw = _compile_raw(
                spec.model_copy(update={"params": params}), schemas, identities=identities
            )
            sql, columns = raw.sql, raw.columns
            current_schema = infer(sql, columns)
            if conn and spec.operation == "aggregate":
                names = set(columns) - set(params.get("group_by", []))
                sql = _normalize_outputs(sql, current_schema, names)
                current_schema = infer(sql, columns)
            if spec.operation == "join" and any(
                p.get("op", "eq") != "eq" for p in params.get("on", [])
            ):
                warnings.append({"code": "DATAPREP_JOIN_NON_EQUI", "step_id": None})
        else:
            from app.schemas.data_prep import PrepStep

            _compile_raw(spec.model_copy(update={"steps": []}), schemas)

            columns = tuple(f["name"] for f in current_schema)
            ctes = []
            last = "in"
            sql = 'SELECT * FROM "in"'
            for index, step in enumerate(spec.steps):
                previous = current_schema
                if step.enabled:
                    try:
                        params = resolve_params(step.params, current_schema)
                        from app.services.dataops.contracts import validate_params

                        validate_params(step.action, params)
                        if conn:
                            _validate_typed_literals(conn, step, params, current_schema)
                        output = params.get("output")
                        position = (
                            params.pop("position", None) if step.action != "move_columns" else None
                        )
                        if step.action == "copy_column":
                            params["position"] = position or "after_input"
                        replace_output = params.pop("replace", False)
                        replacing = bool(
                            replace_output and output in columns and step.action != "hash"
                        )
                        if replacing:
                            params["output"] = f"__dp_replace_{index}"
                            if params["output"] in columns:
                                raise ValueError("DATAPREP_RESERVED_COLUMN")
                        # The compiler owns table identifiers; no SQL text replacement is used.
                        one = spec.model_copy(
                            update={
                                "steps": [PrepStep(action=step.action, params=params)],
                                "params": {},
                            }
                        )
                        raw = _compile_raw(one, {"in": current_schema})
                        if replacing:
                            from app.services.dataops.compiler import quote

                            sql = (
                                "SELECT "
                                + ",".join(
                                    (quote(params["output"]) + " AS " + quote(n))
                                    if n == output
                                    else quote(n)
                                    for n in columns
                                )
                                + f" FROM ({raw.sql})"
                            )
                            raw = replace(raw, sql=sql, columns=tuple(columns))
                        elif (
                            position == "after_input"
                            and output in raw.columns
                            and output not in columns
                        ):
                            from app.services.dataops.compiler import quote

                            anchor = params.get("column") or (params.get("columns") or [None])[-1]
                            if anchor in columns:
                                ordered = [n for n in raw.columns if n != output]
                                ordered.insert(ordered.index(anchor) + 1, output)
                                raw = replace(
                                    raw,
                                    sql="SELECT "
                                    + ",".join(quote(n) for n in ordered)
                                    + f" FROM ({raw.sql})",
                                    columns=tuple(ordered),
                                )
                        tree = sqlglot.parse_one(raw.sql, read="duckdb")
                        for table in tree.find_all(exp.Table):
                            if table.name == "in":
                                table.set("this", exp.Identifier(this=last, quoted=True))
                        for parameter in tree.find_all(exp.Placeholder):
                            if parameter.name == "dp_salt_0":
                                parameter.set("this", f"dp_salt_{index}")
                        last = f"__dp_step_{index}"
                        ctes.append(
                            exp.CTE(
                                this=tree,
                                alias=exp.TableAlias(this=exp.Identifier(this=last, quoted=True)),
                            )
                        )
                        query = exp.select("*").from_(
                            exp.Table(this=exp.Identifier(this=last, quoted=True))
                        )
                        query.set("with_", exp.With(expressions=ctes))
                        sql = query.sql(dialect="duckdb")
                        columns = raw.columns
                        current_schema = infer(sql, columns)
                        if conn and step.action in {"formula", "scale", "bin", "bin_numeric"}:
                            names = (
                                [output]
                                if output
                                else params.get("columns", [params.get("column")])
                            )
                            normalized = _normalize_outputs(
                                tree.sql(dialect="duckdb"), current_schema, names
                            )
                            ctes[-1].set("this", sqlglot.parse_one(normalized, read="duckdb"))
                            sql = query.sql(dialect="duckdb")
                            current_schema = infer(sql, columns)
                    except (ValueError, duckdb.Error, sqlglot.errors.SqlglotError) as exc:
                        code = (
                            str(exc)
                            if isinstance(exc, ValueError)
                            else "DATAPREP_TYPE_MISMATCH: " + str(exc).splitlines()[0][:240]
                        )
                        raise PrepCompileError(
                            code, step_id=step.id, position=getattr(exc, "position", None)
                        ) from None
                    if step.action == "sort" and any(s.enabled for s in spec.steps[index + 1 :]):
                        warnings.append({"code": "DATAPREP_SORT_NOT_LAST", "step_id": step.id})
                step_queries[step.id] = sql
                step_schemas.append(
                    {
                        "id": step.id,
                        "index": index,
                        "enabled": step.enabled,
                        "schema": current_schema,
                        "schema_diff": _diff(previous, current_schema),
                    }
                )
        return CompiledPrep(
            sql,
            tuple(sorted(schemas)),
            canonical_spec(spec, identities or schemas),
            tuple(columns),
            tuple(f for f in current_schema if f["name"] != "__dp_output"),
            tuple(step_schemas),
            tuple(warnings),
            step_queries,
            hash_parameters(spec),
            'SELECT * FROM "in"' if spec.operation == "prepare" else "",
        )
    except duckdb.Error as exc:
        raise PrepCompileError(
            "DATAPREP_TYPE_MISMATCH: " + str(exc).splitlines()[0][:240]
        ) from None
    finally:
        if conn:
            conn.close()


def select_step(compiled, step_id):
    if not step_id:
        return compiled
    if step_id not in compiled.step_queries:
        raise PrepCompileError("DATAPREP_STEP_UNKNOWN", step_id=step_id)
    schema = next(s["schema"] for s in compiled.step_schemas if s["id"] == step_id)
    return replace(
        compiled,
        sql=compiled.step_queries[step_id],
        output_schema=tuple(schema),
        columns=tuple(f["name"] for f in schema),
    )
