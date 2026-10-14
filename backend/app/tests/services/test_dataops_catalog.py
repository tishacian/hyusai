"""Golden semantic cases: NULLs, ordering, ties, type widening and dates."""

from datetime import datetime

import duckdb
import pyarrow as pa
import pytest

from app.schemas.data_prep import DataPrepSpec
from app.services.dataops.compiler import compile_prep


def execute(rows, steps, *, operation="prepare", params=None, other=None, outputs=None):
    con = duckdb.connect()
    table = pa.Table.from_pylist(rows)
    con.register("left" if operation == "join" else "a" if operation == "union" else "in", table)
    schemas = {
        "left" if operation == "join" else "a" if operation == "union" else "in": [
            {
                "name": f.name,
                "kind": "integer"
                if pa.types.is_integer(f.type)
                else "float"
                if pa.types.is_floating(f.type)
                else "string",
            }
            for f in table.schema
        ]
    }
    if other is not None:
        right = pa.Table.from_pylist(other)
        name = "right" if operation == "join" else "b"
        con.register(name, right)
        schemas[name] = [
            {
                "name": f.name,
                "kind": "integer"
                if pa.types.is_integer(f.type)
                else "float"
                if pa.types.is_floating(f.type)
                else "string",
            }
            for f in right.schema
        ]
    spec = DataPrepSpec(
        operation=operation,
        steps=steps,
        params=params or {},
        outputs=outputs or [{"name": "Output"}],
    )
    compiled = compile_prep(spec, schemas)
    try:
        return con.execute(compiled.sql).to_arrow_table().to_pylist()
    finally:
        con.close()


@pytest.mark.parametrize(
    "action,params,expected",
    [
        (
            "cast",
            {"columns": ["value"], "to": "integer", "on_error": "null", "float_to_int": "truncate"},
            [1, -1, None],
        ),
        (
            "cast",
            {
                "columns": ["value"],
                "to": "integer",
                "on_error": "null",
                "float_to_int": "round_half_up",
            },
            [2, -2, None],
        ),
        ("round", {"columns": ["value"], "decimals": 0, "mode": "half_even"}, [2.0, -2.0, None]),
        (
            "fill_nulls",
            {"columns": ["value"], "method": "ffill", "order_by": ["id"]},
            [1.5, -1.5, -1.5],
        ),
        ("fill_nulls", {"columns": ["value"], "method": "mean"}, [1.5, -1.5, 0.0]),
        ("scale", {"columns": ["value"], "method": "minmax"}, [1.0, 0.0, None]),
        ("math", {"columns": ["value"], "function": "abs"}, [1.5, 1.5, None]),
    ],
)
def test_numeric_and_null_semantics(action, params, expected):
    result = execute(
        [{"id": 1, "value": 1.5}, {"id": 2, "value": -1.5}, {"id": 3, "value": None}],
        [{"action": action, "params": params}],
    )
    assert [r["value"] for r in result] == expected


@pytest.mark.parametrize(
    "action,params,key,expected",
    [
        ("text_transform", {"columns": ["text"], "operation": "title"}, "text", "Été Bonjour"),
        (
            "replace_values",
            {
                "columns": ["text"],
                "pairs": [{"from": "ete BONJOUR", "to": "ok"}],
                "case_sensitive": False,
                "normalize_accents": True,
            },
            "text",
            "ok",
        ),
        (
            "count_occurrences",
            {"column": "text", "pattern": "BON", "case_sensitive": False, "output": "n"},
            "n",
            1.0,
        ),
        ("mask", {"columns": ["text"], "keep_first": 1, "keep_last": 1}, "text", "é*********r"),
        (
            "extract_regex",
            {"column": "text", "pattern": "(bonjour)", "outputs": [{"group": 1, "name": "word"}]},
            "word",
            "bonjour",
        ),
    ],
)
def test_text_semantics(action, params, key, expected):
    rows = execute([{"text": "été bonjour"}], [{"action": action, "params": params}])
    assert rows[0][key] == expected


def test_dedup_none_and_last_have_meaningful_order():
    data = [{"id": 1, "time": 1}, {"id": 1, "time": 2}, {"id": 2, "time": 3}]
    last = execute(
        data,
        [{"action": "dedup", "params": {"columns": ["id"], "keep": "last", "order_by": ["time"]}}],
    )
    assert sorted(last, key=lambda r: r["id"]) == [{"id": 1, "time": 2}, {"id": 2, "time": 3}]
    assert execute(data, [{"action": "dedup", "params": {"columns": ["id"], "keep": "none"}}]) == [
        {"id": 2, "time": 3}
    ]


def test_date_diff_counts_complete_units_and_iso_weekday():
    result = execute(
        [{"start": datetime(2026, 1, 31, 12), "end": datetime(2026, 2, 1, 11)}],
        [
            {
                "action": "date_diff",
                "params": {"start": "start", "end": "end", "unit": "day", "output": "days"},
            },
            {
                "action": "extract_date_parts",
                "params": {"column": "end", "parts": ["iso_day_of_week"]},
            },
        ],
    )
    assert result[0]["days"] == 0 and result[0]["end_iso_day_of_week"] == 7


def test_union_widens_numeric_and_preserves_missing_column():
    rows = execute(
        [{"id": 1, "label": "a"}], [], operation="union", other=[{"id": 2.5, "extra": "b"}]
    )
    assert rows == [
        {"id": 1.0, "label": "a", "extra": None},
        {"id": 2.5, "label": None, "extra": "b"},
    ]
    with pytest.raises(ValueError, match="UNION_TYPES"):
        execute([{"id": 1}], [], operation="union", other=[{"id": "text"}])


@pytest.mark.parametrize("how,expected", [("semi", [1]), ("anti", [2]), ("cross", [1, 2])])
def test_join_semijoin_anti_and_cross(how, expected):
    rows = execute(
        [{"id": 1}, {"id": 2}],
        [],
        operation="join",
        other=[{"id": 1}],
        params={"how": how, **({} if how == "cross" else {"on": [{"left": "id", "right": "id"}]})},
    )
    assert [r["id"] for r in rows] == expected


def test_sample_fraction_and_condition_split_are_complete():
    data = [{"id": i, "group": i % 2} for i in range(20)]
    rows = execute(
        data,
        [],
        operation="sample",
        params={"fraction": 0.3, "stratify_by": ["group"], "method": "stratified"},
    )
    assert len(rows) == 6 and sum(r["group"] == 0 for r in rows) == 3
    rows = execute(
        data,
        [],
        operation="split",
        params={
            "method": "condition",
            "outputs": [{"port": "small", "filter": "id<3"}],
            "else_port": "rest",
        },
        outputs=[{"port": "small", "name": "Small"}, {"port": "rest", "name": "Rest"}],
    )
    assert len(rows) == 20 and sum(r["__dp_output"] == "small" for r in rows) == 3


def test_drop_nulls_preserves_text_nan_but_removes_numeric_nan():
    rows = [
        {"id": 1, "text": "NaN", "number": 1.0},
        {"id": 2, "text": "NaN", "number": float("nan")},
        {"id": 3, "text": None, "number": 2.0},
    ]
    assert [r["id"] for r in execute(rows, [{
        "action": "drop_nulls", "params": {"columns": ["text"]},
    }])] == [1, 2]
    assert [r["id"] for r in execute(rows, [{
        "action": "drop_nulls", "params": {"columns": ["text", "number"]},
    }])] == [1]
