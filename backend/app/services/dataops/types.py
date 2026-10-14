"""Native, portable preparation types and canonical values (compiler contract v1)."""

from __future__ import annotations

import re

import pyarrow as pa


def kind(dtype):
    if pa.types.is_integer(dtype):
        return "integer"
    if pa.types.is_floating(dtype) or pa.types.is_decimal(dtype):
        return "float"
    if pa.types.is_boolean(dtype):
        return "boolean"
    if pa.types.is_date(dtype):
        return "date"
    if pa.types.is_timestamp(dtype):
        return "datetime"
    return "string" if pa.types.is_string(dtype) or pa.types.is_large_string(dtype) else "other"


def describe(schema):
    return [
        dict(name=f.name, dtype=str(f.type), nullable=f.nullable, kind=kind(f.type)) for f in schema
    ]


def arrow_type(field):
    value = field.get("dtype")
    if not value:
        value = {
            "integer": "int64",
            "float": "double",
            "boolean": "bool",
            "date": "date32",
            "datetime": "timestamp[us]",
        }.get(field.get("kind"), "string")
    aliases = {
        "text": "string",
        "varchar": "string",
        "bigint": "int64",
        "integer": "int32",
        "boolean": "bool",
        "date": "date32",
        "date32[day]": "date32",
        "date64[ms]": "date64",
        "float64": "double",
        "timestamp": "timestamp[us]",
        "timestamp_tz": "timestamp[us, tz=UTC]",
    }
    value = aliases.get(value.lower(), value)
    timestamp = re.fullmatch(r"timestamp\[(s|ms|us|ns)(?:, tz=([^\]]+))?\]", value)
    if timestamp:
        return pa.timestamp(timestamp[1], timestamp[2])
    decimal = re.fullmatch(r"decimal(?:128|256)?\((\d+),\s*(\d+)\)", value)
    if decimal:
        precision, scale = int(decimal[1]), int(decimal[2])
        if not 1 <= precision <= 38 or not 0 <= scale <= precision:
            raise ValueError("DATAPREP_TYPE_INVALID")
        return pa.decimal128(precision, scale)
    try:
        return pa.type_for_alias(value.lower())
    except (ValueError, TypeError):
        raise ValueError("DATAPREP_TYPE_UNSUPPORTED: " + str(value)[:100]) from None


def portable_type(field):
    dtype = arrow_type(field)
    if pa.types.is_null(dtype):
        return None
    if pa.types.is_boolean(dtype):
        return "BOOLEAN"
    if pa.types.is_integer(dtype):
        if pa.types.is_uint64(dtype):
            return "DECIMAL(20,0)"
        return (
            "INTEGER"
            if dtype.bit_width < 32 or dtype.bit_width == 32 and pa.types.is_signed_integer(dtype)
            else "BIGINT"
        )
    if pa.types.is_floating(dtype):
        return "DOUBLE"
    if pa.types.is_decimal(dtype):
        return f"DECIMAL({dtype.precision},{dtype.scale})"
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        return "VARCHAR"
    if pa.types.is_date(dtype):
        return "DATE"
    if pa.types.is_timestamp(dtype):
        return "TIMESTAMPTZ" if dtype.tz else "TIMESTAMP"
    raise ValueError("DATAPREP_TYPE_UNSUPPORTED")


def common_type(fields):
    types = {portable_type(f) for f in fields} - {None}
    if not types:
        return "VARCHAR"
    if len(types) == 1:
        return next(iter(types))
    numeric = all(t in {"INTEGER", "BIGINT", "DOUBLE"} or t.startswith("DECIMAL(") for t in types)
    if numeric:
        if "DOUBLE" in types:
            return "DOUBLE"
        if any(t.startswith("DECIMAL(") for t in types):
            widths = [
                (10, 0)
                if t == "INTEGER"
                else (19, 0)
                if t == "BIGINT"
                else tuple(map(int, re.findall(r"\d+", t)))
                for t in types
            ]
            scale = max(s for _, s in widths)
            precision = max(p - s for p, s in widths) + scale
            if precision > 38:
                raise ValueError("DATAPREP_DECIMAL_PRECISION_LOSS")
            return f"DECIMAL({precision},{scale})"
        return "BIGINT"
    if types <= {"DATE", "TIMESTAMP", "TIMESTAMPTZ"}:
        return "TIMESTAMPTZ" if "TIMESTAMPTZ" in types else "TIMESTAMP"
    raise ValueError("DATAPREP_UNION_TYPES")


def canonical_value(name, field=None):
    from app.services.dataops.compiler import quote

    column = quote(name)
    dtype = portable_type(field) if field else None
    if dtype == "DOUBLE":
        value = f"printf('%.17g',CAST({column} AS DOUBLE))"
    elif dtype == "BOOLEAN":
        value = f"CASE WHEN {column} THEN 'true' ELSE 'false' END"
    elif dtype == "DATE":
        value = f"strftime({column},'%Y-%m-%d')"
    elif dtype in {"TIMESTAMP", "TIMESTAMPTZ"}:
        value = f"strftime({column},'%Y-%m-%dT%H:%M:%S.%fZ')"
    else:
        value = f"CAST({column} AS VARCHAR)"
    return f"CASE WHEN {column} IS NULL THEN '\\N' ELSE {value} END"


def fingerprint(columns, schema=None):
    fields = {f["name"]: f for f in schema or []}
    return (
        "md5(concat_ws(chr(31),"
        + ",".join(canonical_value(n, fields.get(n)) for n in columns)
        + "))"
    )
