"""A closed, typed SQL compiler. All data enters via authorized Arrow views."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

from app.schemas.data_prep import DataPrepSpec


def quote(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 256 or "\x00" in name:
        raise ValueError("DATAPREP_IDENTIFIER_INVALID")
    return '"' + name.replace('"', '""') + '"'


def literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    if type(value) in {int, float}:
        if not math.isfinite(value):
            raise ValueError("DATAPREP_NONFINITE_LITERAL")
        return str(value)
    if isinstance(value, str) and len(value) <= 4096:
        return "'" + value.replace("'", "''") + "'"
    raise ValueError("DATAPREP_LITERAL_INVALID")


_FUNCTIONS = {
    "ABS",
    "ROUND",
    "CEIL",
    "FLOOR",
    "COALESCE",
    "NULLIF",
    "LOWER",
    "UPPER",
    "TRIM",
    "LTRIM",
    "RTRIM",
    "LENGTH",
    "CHAR_LENGTH",
    "CONCAT",
    "SUBSTRING",
    "REPLACE",
    "STRFTIME",
    "DATE_TRUNC",
    "EXTRACT",
    "GREATEST",
    "LEAST",
    "POWER",
    "SQRT",
    "LN",
    "LOG",
    "EXP",
    "CAST",
    "TRY_CAST",
    "CASE",
    "IF",
    "STRPOS",
    "SPLIT_PART",
    "REGEXP_REPLACE",
    "REGEXP_MATCHES",
}
_TYPES = {
    "VARCHAR",
    "DOUBLE",
    "BIGINT",
    "INTEGER",
    "BOOLEAN",
    "DATE",
    "TIMESTAMP",
    "TIMESTAMPTZ",
    "DECIMAL",
}


def expression(text: str, columns: list[str]) -> str:
    if not isinstance(text, str) or not text or len(text) > 4096:
        raise ValueError("DATAPREP_EXPRESSION_INVALID")
    trees = sqlglot.parse(text, read="duckdb")
    if len(trees) != 1 or trees[0] is None:
        raise ValueError("DATAPREP_SINGLE_EXPRESSION_REQUIRED")
    tree = trees[0]
    if sum(1 for _ in tree.walk()) > 256:
        raise ValueError("DATAPREP_EXPRESSION_TOO_COMPLEX")
    for node in tree.walk():
        if isinstance(
            node, (exp.Query, exp.DDL, exp.DML, exp.Table, exp.Window, exp.Command, exp.Placeholder)
        ):
            raise ValueError("DATAPREP_EXPRESSION_FORBIDDEN")
        if isinstance(node, exp.Column) and (node.name not in columns or node.table):
            raise ValueError(f"DATAPREP_COLUMN_UNKNOWN: {node.name}")
        if isinstance(node, exp.Func):
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name().upper()
            if name not in _FUNCTIONS:
                raise ValueError(f"DATAPREP_FUNCTION_FORBIDDEN: {name}")
        if isinstance(node, exp.Column):
            node.set("this", exp.Identifier(this=node.name, quoted=True))
    return tree.sql(dialect="duckdb")


def canonical_spec(spec: DataPrepSpec, inputs: dict[str, Any]) -> str:
    data = {"spec": spec.model_dump(mode="json"), "inputs": inputs}
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _columns(schema) -> list[str]:
    names = [field["name"] for field in schema]
    if len({n.casefold() for n in names}) != len(names):
        raise ValueError("DATAPREP_COLUMN_COLLISION")
    return names


def _require(params: dict, allowed: set[str], required: set[str] = frozenset()):
    if not isinstance(params, dict) or set(params) - allowed or required - set(params):
        raise ValueError("DATAPREP_PARAMS_INVALID")


def _names(values, columns):
    if (
        not isinstance(values, list)
        or not values
        or any(v not in columns for v in values)
        or len(values) != len(set(values))
    ):
        raise ValueError("DATAPREP_COLUMNS_INVALID")
    return values


@dataclass(frozen=True)
class CompiledPrep:
    sql: str
    port_inputs: tuple[str, ...]
    fingerprint: str
    columns: tuple[str, ...]


def compile_prep(
    spec: DataPrepSpec, schemas: dict[str, list[dict]], *, identities: dict | None = None
) -> CompiledPrep:
    operation, params = spec.operation, spec.params
    required = (
        {"left", "right"}
        if operation == "join"
        else set(schemas)
        if operation == "union"
        else {"in"}
    )
    if set(schemas) != required or not required:
        raise ValueError("DATAPREP_INPUT_PORTS_INVALID")
    columns = _columns(schemas["left" if operation == "join" else sorted(schemas)[0]])
    sql = f"SELECT * FROM {quote(sorted(required)[0])}"
    if operation == "prepare":
        _require(params, set())
    elif operation in {"join", "union", "aggregate", "sample", "split"}:
        from app.services.dataops.operations import relational

        sql, columns = relational(spec, schemas)
    elif operation == "pivot":
        _require(
            params,
            {"group_by", "column", "values", "value_column", "function"},
            {"column", "values", "value_column"},
        )
        groups = params.get("group_by", [])
        for name in [*groups, params["column"], params["value_column"]]:
            if name not in columns:
                raise ValueError("DATAPREP_COLUMN_UNKNOWN")
        function = params.get("function", "sum")
        if function not in {"sum", "avg", "min", "max", "count"}:
            raise ValueError("DATAPREP_AGGREGATE_INVALID")
        values = params["values"]
        if not isinstance(values, list) or not 1 <= len(values) <= 100:
            raise ValueError("DATAPREP_PIVOT_VALUES_INVALID")
        aliases = [str(v) for v in values]
        if len(set(n.casefold() for n in [*groups, *aliases])) != len(groups) + len(aliases):
            raise ValueError("DATAPREP_COLUMN_COLLISION")
        projection = [quote(n) for n in groups] + [
            f"{function.upper()}(CASE WHEN {quote(params['column'])} IS NOT DISTINCT FROM {literal(v)} THEN {quote(params['value_column'])} END) AS {quote(str(v))}"
            for v in values
        ]
        sql = f'SELECT {",".join(projection)} FROM "in"' + (
            f" GROUP BY {','.join(quote(n) for n in groups)}" if groups else ""
        )
        columns = groups + aliases
    elif operation == "unpivot":
        _require(params, {"columns", "name_column", "value_column"}, {"columns"})
        melting = _names(params["columns"], columns)
        name_column, value_column = (
            params.get("name_column", "variable"),
            params.get("value_column", "value"),
        )
        keep = [n for n in columns if n not in melting]
        if name_column in keep or value_column in keep or name_column == value_column:
            raise ValueError("DATAPREP_COLUMN_COLLISION")
        sql = " UNION ALL ".join(
            f'SELECT {",".join([*(quote(n) for n in keep), literal(n) + " AS " + quote(name_column), quote(n) + " AS " + quote(value_column)])} FROM "in"'
            for n in melting
        )
        columns = keep + [name_column, value_column]
    for step_index, step in enumerate(spec.steps):
        p, action = step.params, step.action
        from app.services.dataops.steps import EXTENDED_STEPS, apply_step

        if action in EXTENDED_STEPS:
            sql, columns = apply_step(sql, columns, action, p)
            continue
        source = f"({sql}) AS data"
        if action == "hash":
            from app.services.dataops.secrets import hash_parameters

            _require(
                p,
                {"columns", "column", "name", "output", "salt_secret_ref", "algorithm"},
                {"salt_secret_ref"},
            )
            if p.get("algorithm", "sha256") != "sha256":
                raise ValueError("DATAPREP_HASH_ALGORITHM_UNSUPPORTED")
            hash_parameters(spec)
            names = _names(p.get("columns") or [p.get("column")], columns)
            target = p.get("output", p.get("name"))
            if not target or target.casefold() in {n.casefold() for n in columns}:
                raise ValueError("DATAPREP_COLUMN_COLLISION")
            packed = (
                "to_json(struct_pack(" + ",".join(quote(n) + ":=" + quote(n) for n in names) + "))"
            )
            sql = f"SELECT *,sha256(to_json(struct_pack(salt:=$dp_salt_{step_index},value:={packed}))) AS {quote(target)} FROM {source}"
            columns.append(target)
            continue
        if action in {"select", "drop", "drop_null", "deduplicate"}:
            _require(p, {"columns"}, {"columns"})
            names = _names(p["columns"], columns)
            if action in {"select", "drop"}:
                columns = names if action == "select" else [n for n in columns if n not in names]
                if not columns:
                    raise ValueError("DATAPREP_NO_COLUMNS")
                sql = f"SELECT {','.join(quote(n) for n in columns)} FROM {source}"
            elif action == "drop_null":
                sql = f"SELECT * FROM {source} WHERE " + " AND ".join(
                    f"{quote(n)} IS NOT NULL" for n in names
                )
            else:
                order = ",".join(quote(n) for n in columns)
                sql = f"SELECT * FROM {source} QUALIFY row_number() OVER(PARTITION BY {','.join(quote(n) for n in names)} ORDER BY {order})=1"
        elif action == "rename":
            _require(p, {"mapping"}, {"mapping"})
            mapping = p["mapping"]
            if not isinstance(mapping, dict) or any(n not in columns for n in mapping):
                raise ValueError("DATAPREP_RENAME_INVALID")
            new = [mapping.get(n, n) for n in columns]
            if len({n.casefold() for n in new}) != len(new):
                raise ValueError("DATAPREP_COLUMN_COLLISION")
            sql = f"SELECT {','.join(quote(n) + ' AS ' + quote(mapping.get(n, n)) for n in columns)} FROM {source}"
            columns = new
        elif action == "filter":
            _require(p, {"expression"}, {"expression"})
            sql = f"SELECT * FROM {source} WHERE {expression(p['expression'], columns)}"
        elif action == "derive":
            _require(p, {"name", "expression"}, {"name", "expression"})
            if p["name"].casefold() in {n.casefold() for n in columns}:
                raise ValueError("DATAPREP_COLUMN_COLLISION")
            sql = f"SELECT *,{expression(p['expression'], columns)} AS {quote(p['name'])} FROM {source}"
            columns.append(p["name"])
        elif action == "sort":
            _require(p, {"columns", "descending"}, {"columns"})
            names = _names(p["columns"], columns)
            sql = f"SELECT * FROM {source} ORDER BY " + ",".join(
                quote(n) + (" DESC" if p.get("descending", False) else " ASC") + " NULLS LAST"
                for n in names
            )
        else:
            allowed = {"column", "value", "type", "old", "new", "format", "name"}
            _require(p, allowed, {"column"})
            name = p["column"]
            if name not in columns:
                raise ValueError("DATAPREP_COLUMN_UNKNOWN")
            q = quote(name)
            if action == "cast":
                kind = str(p.get("type", "")).upper()
                if kind not in _TYPES:
                    raise ValueError("DATAPREP_TYPE_INVALID")
                term = f"CAST({q} AS {kind})"
            elif action == "fill_null":
                term = f"COALESCE({q},{literal(p.get('value'))})"
            elif action in {"trim", "upper", "lower"}:
                term = f"{action.upper()}({q})"
            elif action == "replace":
                term = f"REPLACE({q},{literal(p.get('old'))},{literal(p.get('new'))})"
            elif action == "date_format":
                if not isinstance(p.get("format"), str) or not p["format"].strip():
                    raise ValueError("DATAPREP_DATE_FORMAT_REQUIRED")
                term = f"STRFTIME({q},{literal(p.get('format'))})"
            elif action == "hash":
                term = f"SHA256(to_json(struct_pack(value:={q})))"
            else:
                raise ValueError("DATAPREP_STEP_UNSUPPORTED")
            target = p.get("name", name)
            if target != name and target in columns:
                raise ValueError("DATAPREP_COLUMN_COLLISION")
            sql = f"SELECT {','.join(term + ' AS ' + quote(target) if n == name else quote(n) for n in columns)} FROM {source}"
            columns = [target if n == name else n for n in columns]
    return CompiledPrep(
        sql, tuple(sorted(required)), canonical_spec(spec, identities or schemas), tuple(columns)
    )


def catalog() -> dict:
    return {
        "version": 1,
        "operations": [
            "prepare",
            "join",
            "union",
            "aggregate",
            "pivot",
            "unpivot",
            "split",
            "sample",
        ],
        "steps": list(
            dict.fromkeys(
                [
                    *PrepStepActions,
                    *__import__(
                        "app.services.dataops.steps", fromlist=["EXTENDED_STEPS"]
                    ).EXTENDED_STEPS,
                ]
            )
        ),
        "spec_schema": DataPrepSpec.model_json_schema(),
        "placements": ["local"],
    }


PrepStepActions = [
    "select",
    "drop",
    "rename",
    "cast",
    "fill_null",
    "drop_null",
    "filter",
    "derive",
    "sort",
    "deduplicate",
    "trim",
    "upper",
    "lower",
    "replace",
    "date_format",
    "hash",
]
