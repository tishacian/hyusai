"""Closed step parameter schemas exposed to authors and enforced by the compiler."""

from functools import lru_cache

from jsonschema import Draft202012Validator


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def array(items, minimum=0, maximum=1000):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def enum(*values):
    return {"enum": list(values)}


NAME = {"type": "string", "minLength": 1, "maxLength": 255}
TEXT = {"type": "string", "maxLength": 4000}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}
NUMBER = {"type": "number"}
VALUE = {"type": ["null", "boolean", "number", "string"], "maxLength": 4000}
NAMES = array(NAME, 1, 500)
SELECTOR = {
    "oneOf": [
        NAMES,
        obj(
            {
                "mode": enum("names", "pattern", "kinds", "all"),
                "names": NAMES,
                "regex": TEXT,
                "match": enum("full", "contains"),
                "kinds": NAMES,
                "exclude": array(NAME),
            },
            ["mode"],
        ),
    ]
}
ORDER = array(
    {
        "oneOf": [
            NAME,
            obj(
                {"column": NAME, "direction": enum("asc", "desc"), "nulls": enum("first", "last")},
                ["column"],
            ),
        ]
    },
    1,
    500,
)
POSITION = enum("after_input", "end")
PAIRS = array(obj({"from": VALUE, "to": VALUE}, ["from", "to"]), 1)
CONDITIONS = array(
    obj(
        {
            "column": NAME,
            "op": enum(
                "eq",
                "ne",
                "lt",
                "le",
                "gt",
                "ge",
                "between",
                "in",
                "not_in",
                "is_null",
                "is_not_null",
                "contains",
                "starts_with",
                "ends_with",
                "matches",
                "is_true",
                "is_false",
            ),
            "value": VALUE,
            "values": array(VALUE, 1),
            "case_sensitive": BOOL,
            "normalize_accents": BOOL,
        },
        ["column", "op"],
    ),
    1,
)


def contract(group, properties, required=()):
    return {"group": group, "params_schema": obj(properties, required)}


CONTRACTS = {
    "select_columns": contract("columns", {"columns": SELECTOR}, ["columns"]),
    "drop_columns": contract("columns", {"columns": SELECTOR}, ["columns"]),
    "rename_columns": contract(
        "columns",
        {
            "mapping": {
                "oneOf": [
                    array(obj({"from": NAME, "to": NAME}, ["from", "to"]), 1),
                    {"type": "object", "additionalProperties": NAME},
                ]
            }
        },
        ["mapping"],
    ),
    "move_columns": contract(
        "columns",
        {"columns": SELECTOR, "position": enum("start", "end", "before", "after"), "anchor": NAME},
        ["columns", "position"],
    ),
    "copy_column": contract(
        "columns", {"column": NAME, "output": NAME, "position": POSITION}, ["column", "output"]
    ),
    "concat_columns": contract(
        "columns",
        {
            "columns": SELECTOR,
            "output": NAME,
            "separator": TEXT,
            "nulls": enum("skip", "propagate", "empty"),
        },
        ["columns", "output"],
    ),
    "normalize_column_names": contract(
        "columns",
        {"style": enum("snake", "lower", "ascii", "papai"), "dedupe": enum("suffix", "fail")},
        ["style"],
    ),
    "add_column": contract(
        "columns",
        {"output": NAME, "value": VALUE, "type": NAME, "position": POSITION},
        ["output", "value", "type"],
    ),
    "cast": contract(
        "types",
        {
            "columns": SELECTOR,
            "column": NAME,
            "to": NAME,
            "type": NAME,
            "on_error": enum("null", "fail"),
            "float_to_int": enum("round_half_up", "truncate"),
        },
    ),
    "parse_date": contract(
        "types",
        {
            "column": NAME,
            "format": TEXT,
            "preset": enum(
                "iso_date",
                "iso_datetime",
                "iso_datetime_tz",
                "fr_date",
                "fr_datetime",
                "us_date",
                "compact",
                "rfc2822",
            ),
            "to": enum("date", "timestamp", "timestamp_tz", "auto"),
            "output": NAME,
        },
        ["column"],
    ),
    "format_date": contract(
        "types", {"column": NAME, "format": TEXT, "output": NAME}, ["column", "format"]
    ),
    "from_epoch": contract(
        "types", {"column": NAME, "unit": enum("s", "ms", "us"), "output": NAME}, ["column"]
    ),
    "parse_number": contract(
        "types",
        {
            "column": NAME,
            "decimal_separator": enum(".", ","),
            "thousands_separator": TEXT,
            "output": NAME,
        },
        ["column"],
    ),
    "to_boolean": contract(
        "types",
        {
            "columns": SELECTOR,
            "true_values": array(VALUE, 1),
            "false_values": array(VALUE, 1),
            "case_sensitive": BOOL,
        },
        ["columns"],
    ),
    "drop_nulls": contract(
        "missing",
        {"columns": SELECTOR, "how": enum("any", "all"), "nan_as_null": BOOL},
        ["columns"],
    ),
    "fill_nulls": contract(
        "missing",
        {
            "columns": SELECTOR,
            "method": enum("constant", "mean", "median", "min", "max", "mode", "ffill", "bfill"),
            "value": VALUE,
            "order_by": ORDER,
            "partition_by": array(NAME),
        },
        ["columns", "method"],
    ),
    "deduplicate": contract(
        "rows",
        {
            "columns": SELECTOR,
            "keep": enum("first", "last", "smallest_fp", "none"),
            "order_by": ORDER,
        },
    ),
    "filter_rows": contract(
        "rows",
        {"conditions": CONDITIONS, "combine": enum("and", "or"), "keep_nulls_on_ne": BOOL},
        ["conditions"],
    ),
    "filter_range": contract(
        "rows",
        {"column": NAME, "min": VALUE, "max": VALUE, "min_inclusive": BOOL, "max_inclusive": BOOL},
        ["column"],
    ),
    "filter_expression": contract("rows", {"expression": TEXT}, ["expression"]),
    "flag_rows": contract(
        "rows",
        {
            "conditions": CONDITIONS,
            "combine": enum("and", "or"),
            "keep_nulls_on_ne": BOOL,
            "output": NAME,
            "flag_when": enum("match", "no_match"),
        },
        ["conditions", "output"],
    ),
    "text_transform": contract(
        "text",
        {
            "columns": SELECTOR,
            "operation": enum(
                "trim",
                "ltrim",
                "rtrim",
                "lower",
                "upper",
                "title",
                "remove_accents",
                "collapse_spaces",
            ),
        },
        ["columns", "operation"],
    ),
    "replace_values": contract(
        "text",
        {
            "columns": SELECTOR,
            "column": NAME,
            "pairs": PAIRS,
            "match": enum("exact", "substring", "regex"),
            "case_sensitive": BOOL,
            "normalize_accents": BOOL,
            "default": enum("keep", "null", "value"),
            "value": VALUE,
            "output": NAME,
        },
        ["pairs"],
    ),
    "split_column": contract(
        "text",
        {
            "column": NAME,
            "separator": TEXT,
            "regex": TEXT,
            "outputs": NAMES,
            "remainder": enum("last", "drop"),
        },
        ["column", "outputs"],
    ),
    "extract_regex": contract(
        "text",
        {
            "column": NAME,
            "pattern": TEXT,
            "outputs": array(
                obj({"group": {"type": "integer", "minimum": 0}, "name": NAME}, ["group", "name"]),
                1,
                50,
            ),
        },
        ["column", "pattern", "outputs"],
    ),
    "count_occurrences": contract(
        "text",
        {
            "column": NAME,
            "pattern": TEXT,
            "match": enum("substring", "regex"),
            "case_sensitive": BOOL,
            "output": NAME,
        },
        ["column", "pattern", "output"],
    ),
    "substring": contract(
        "text",
        {
            "column": NAME,
            "start": {"type": "integer", "minimum": 1},
            "length": {"type": "integer", "minimum": 0},
            "output": NAME,
        },
        ["column"],
    ),
    "pad": contract(
        "text",
        {
            "column": NAME,
            "length": {"type": "integer", "minimum": 0, "maximum": 10000},
            "char": {"type": "string", "minLength": 1, "maxLength": 1},
            "side": enum("left", "right"),
            "output": NAME,
        },
        ["column", "length"],
    ),
    "length": contract("text", {"column": NAME, "output": NAME}, ["column"]),
    "extract_date_parts": contract(
        "dates",
        {
            "column": NAME,
            "parts": array(
                enum(
                    "year",
                    "quarter",
                    "month",
                    "iso_week",
                    "day",
                    "iso_day_of_week",
                    "day_of_year",
                    "hour",
                    "minute",
                    "second",
                    "epoch_seconds",
                ),
                1,
                12,
            ),
            "naming": TEXT,
        },
        ["column", "parts"],
    ),
    "date_diff": contract(
        "dates",
        {"start": NAME, "end": NAME, "unit": NAME, "output": NAME},
        ["start", "end", "unit", "output"],
    ),
    "date_add": contract(
        "dates",
        {"column": NAME, "amount": INT, "unit": NAME, "output": NAME},
        ["column", "amount", "unit"],
    ),
    "truncate_date": contract(
        "dates", {"column": NAME, "unit": NAME, "output": NAME}, ["column", "unit"]
    ),
    "convert_timezone": contract(
        "dates",
        {"column": NAME, "from": NAME, "to": NAME, "output": NAME},
        ["column", "from", "to"],
    ),
    "round": contract(
        "numeric",
        {
            "columns": SELECTOR,
            "decimals": INT,
            "mode": enum("half_up", "half_even", "floor", "ceil", "truncate"),
        },
        ["columns"],
    ),
    "bin": contract(
        "numeric",
        {
            "column": NAME,
            "mode": enum("fixed_width", "edges", "quantiles"),
            "width": NUMBER,
            "min": NUMBER,
            "max": NUMBER,
            "edges": array(NUMBER, 2, 201),
            "n": {"type": "integer", "minimum": 2, "maximum": 200},
            "labels": NAMES,
            "output": NAME,
        },
        ["column", "mode", "output"],
    ),
    "scale": contract(
        "numeric",
        {"columns": SELECTOR, "method": enum("zscore", "minmax", "robust"), "output_suffix": NAME},
        ["columns", "method"],
    ),
    "negate_boolean": contract("numeric", {"columns": SELECTOR}, ["columns"]),
    "math": contract(
        "numeric",
        {
            "columns": SELECTOR,
            "function": enum("abs", "sqrt", "ln", "log10", "exp", "sign", "ceil", "floor"),
        },
        ["columns", "function"],
    ),
    "formula": contract(
        "compute",
        {"output": NAME, "expression": TEXT, "position": POSITION},
        ["output", "expression"],
    ),
    "conditional_column": contract(
        "compute",
        {
            "output": NAME,
            "cases": array(obj({"when": TEXT, "then": VALUE}, ["when", "then"]), 1, 200),
            "else": VALUE,
        },
        ["output", "cases"],
    ),
    "map_values": contract(
        "compute",
        {
            "column": NAME,
            "pairs": PAIRS,
            "default": enum("keep", "null", "value"),
            "value": VALUE,
            "output": NAME,
        },
        ["column", "pairs"],
    ),
    "window": contract(
        "compute",
        {
            "output": NAME,
            "function": enum(
                "row_number",
                "rank",
                "dense_rank",
                "percent_rank",
                "lag",
                "lead",
                "cumulative_sum",
                "cumulative_count",
                "cumulative_mean",
                "moving_mean",
                "moving_sum",
                "first_value",
                "last_value",
                "ntile",
                "count",
                "sum",
            ),
            "column": NAME,
            "partition_by": array(NAME),
            "order_by": ORDER,
            "offset": INT,
            "size": INT,
            "n": INT,
        },
        ["output", "function"],
    ),
    "hash": contract(
        "privacy",
        {
            "columns": SELECTOR,
            "column": NAME,
            "salt": enum("workspace", "none"),
            "salt_version": INT,
            "salt_secret_ref": NAME,
            "output": NAME,
            "name": NAME,
            "algorithm": enum("sha256"),
            "suffix": NAME,
        },
    ),
    "mask": contract(
        "privacy",
        {
            "columns": SELECTOR,
            "keep_first": INT,
            "keep_last": INT,
            "char": {"type": "string", "minLength": 1, "maxLength": 1},
        },
        ["columns"],
    ),
    "sort": contract("rows", {"keys": ORDER, "columns": NAMES, "descending": BOOL}),
}

for _kind in (
    "copy_column",
    "concat_columns",
    "add_column",
    "parse_date",
    "format_date",
    "from_epoch",
    "parse_number",
    "flag_rows",
    "count_occurrences",
    "substring",
    "pad",
    "length",
    "date_diff",
    "date_add",
    "truncate_date",
    "convert_timezone",
    "bin",
    "formula",
    "conditional_column",
    "map_values",
    "window",
):
    CONTRACTS[_kind]["params_schema"]["properties"].update(position=POSITION, replace=BOOL)


@lru_cache(maxsize=100)
def validator(kind):
    return Draft202012Validator(CONTRACTS[kind]["params_schema"])


def validate_params(kind, params):
    kind = {"dedup": "deduplicate"}.get(kind, kind)
    if kind in CONTRACTS:
        error = next(validator(kind).iter_errors(params), None)
        if error:
            # Never echo authored literal values, patterns or secret refs in diagnostics.
            path = ".".join(str(p) for p in error.absolute_path)
            raise ValueError("DATAPREP_PARAMS_INVALID" + (": " + path if path else ""))


def step_catalog():
    return [
        {
            "kind": kind,
            "group": value["group"],
            "label_key": f"flow.dataprep.step.{kind}.label",
            "params_schema": value["params_schema"],
            "fields": [
                {
                    "name": name,
                    "key": name,
                    "label_key": f"flow.dataprep.step.{kind}.params.{name}",
                    "schema": schema,
                    "required": name in value["params_schema"]["required"],
                }
                for name, schema in value["params_schema"]["properties"].items()
            ],
        }
        for kind, value in CONTRACTS.items()
    ]
