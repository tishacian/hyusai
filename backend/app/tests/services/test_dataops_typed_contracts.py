"""Authored preparation contracts: native types, prefix schemas and bounded previews."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa
import pytest

from app.schemas.data_prep import DataPrepSpec, bind_spec
from app.services.dataops.compiler import compile_prep, expression
from app.services.dataops.contracts import CONTRACTS
from app.services.dataops.types import arrow_type, describe


def execute(table, kind, params, *, operation="prepare", outputs=None):
    spec = bind_spec(
        {
            "version": 1,
            "operation": operation,
            "params": {"steps": [{"id": "golden", "kind": kind, "params": params}]}
            if operation == "prepare"
            else params,
        },
        outputs or [{"port": "out", "name": "Golden"}],
    )
    compiled = compile_prep(
        spec, {"in": describe(table.schema)}, arrow_schemas={"in": table.schema}
    )
    with duckdb.connect(config={"threads": 1}) as conn:
        conn.execute("SET TimeZone='UTC'")
        conn.register("in", table)
        result = conn.execute(compiled.sql, compiled.preview_parameters).to_arrow_table()
    return result, compiled


# Expected values below are independently authored, not generated from the compiler.
# Each contract is exercised with an ordinary row, a NULL row and a zero-row table.
# The zero-row case verifies that aggregate-backed steps do not invent records.
GOLDEN_ROOT = Path(__file__).parents[1] / "dataops" / "golden"
GOLDEN = sorted(GOLDEN_ROOT.glob("*/*/spec.json"))
FUNCTION_GOLDEN = json.loads((GOLDEN_ROOT / "functions.json").read_text())


@pytest.mark.parametrize("case", FUNCTION_GOLDEN, ids=[case["name"] for case in FUNCTION_GOLDEN])
def test_formula_function_golden(case):
    result, compiled = execute(
        pa.table({"a": [2, 4]}), "formula", {"output": "value", "expression": case["expression"]}
    )
    assert len(result) == 2
    for row in result.to_pylist():
        actual = normalize(row)["value"]
        expected = case["expected"]
        assert actual == (pytest.approx(expected) if isinstance(expected, float) else expected)
    assert [f["dtype"] for f in compiled.output_schema] == [str(f.type) for f in result.schema]


def test_function_golden_covers_catalogue():
    from app.services.dataops.formulas import function_catalog

    assert {c["name"] for c in FUNCTION_GOLDEN} == {f["name"] for f in function_catalog()}


def test_type_binding_does_not_evaluate_large_authored_constants():
    spec = bind_spec(
        {
            "operation": "prepare",
            "params": {
                "steps": [
                    {
                        "id": "large",
                        "kind": "formula",
                        "params": {"output": "text", "expression": "lpad('x',1000000000,'x')"},
                    }
                ]
            },
        },
        [{"name": "Output"}],
    )
    compiled = compile_prep(spec, {"in": describe(pa.schema([("a", pa.int64())]))})
    assert compiled.output_schema[-1]["dtype"] == "string"


def test_regex_selector_uses_re2_for_adversarial_names():
    from app.services.dataops.selectors import resolve_selector

    names = ["a" * 254 + "!", "aaa"]
    assert resolve_selector(
        {"mode": "pattern", "regex": "^(a+)+$"}, [{"name": n} for n in names]
    ) == ["aaa"]
    with pytest.raises(ValueError, match="DATAPREP_REGEX_INVALID"):
        resolve_selector({"mode": "pattern", "regex": "(a)\\1"}, [{"name": "aa"}])


def test_legacy_named_unsalted_hash_needs_no_secret_parameter():
    import hashlib

    result, compiled = execute(
        pa.table({"a": ["hello"]}), "hash", {"column": "a", "salt": "none", "output": "digest"}
    )
    # DuckDB embeds a JSON-typed value as an object, not a quoted JSON string.
    expected = hashlib.sha256(
        json.dumps({"salt": "", "value": {"a": "hello"}}, separators=(",", ":")).encode()
    ).hexdigest()
    assert compiled.preview_parameters == {}
    assert result["digest"].to_pylist() == [expected]


def test_native_decimal_formula_and_aggregate_have_explicit_portable_casts():
    table = pa.table({"a": [9223372036854775807, 1]})
    result, compiled = execute(table, "formula", {"output": "total", "expression": "col_sum(a)"})
    assert result["total"].to_pylist() == [Decimal("9223372036854775808")] * 2
    assert result.schema.field("total").type == pa.decimal128(38, 0)
    assert "DECIMAL(38, 0)" in compiled.sql


@pytest.mark.parametrize("rounding", ["truncate", "round_half_up"])
def test_cast_bigint_text_keeps_limits_without_double_roundtrip(rounding):
    values = ["9223372036854775807", "-9223372036854775808", "9223372036854775808", None]
    result, _ = execute(
        pa.table({"a": values}),
        "cast",
        {"columns": ["a"], "to": "bigint", "float_to_int": rounding},
    )
    assert result["a"].to_pylist() == [9223372036854775807, -9223372036854775808, None, None]


def normalize(row):
    return {
        key: value.isoformat()
        if hasattr(value, "isoformat")
        else float(value)
        if isinstance(value, Decimal)
        else value
        for key, value in row.items()
    }


@pytest.mark.parametrize(
    "case", GOLDEN, ids=[str(case.relative_to(GOLDEN_ROOT).parent) for case in GOLDEN]
)
def test_step_golden(case):
    folder = case.parent
    spec = DataPrepSpec.model_validate_json(case.read_text())
    fields = json.loads((folder / "inputs/in.schema.json").read_text())
    schema = pa.schema([pa.field(f["name"], arrow_type(f), nullable=f["nullable"]) for f in fields])
    rows = json.loads((folder / "inputs/in.json").read_text())
    for field in schema:
        if pa.types.is_timestamp(field.type):
            for row in rows:
                if row[field.name] is not None:
                    row[field.name] = datetime.fromisoformat(row[field.name])
    table = pa.Table.from_pylist(rows, schema=schema)
    step = spec.steps[0]
    result, compiled = execute(table, step.action, step.params)
    expected = json.loads((folder / "expected/out.json").read_text())
    assert [normalize(row) for row in result.to_pylist()] == expected
    assert compiled.step_schemas[0]["id"] == "golden"
    assert [f["name"] for f in compiled.output_schema] == result.column_names
    # Authored independently from compilation. DuckDB's Arrow query schema
    # conservatively marks fields nullable, even where this sample has no NULL.
    # Assert that physical contract rather than inferring it from row values.
    expected_schema = json.loads((folder.parent / "ordinary/expected/out.schema.json").read_text())

    def public_schema(fields):
        return [{key: field[key] for key in ("name", "dtype", "nullable")} for field in fields]

    assert public_schema(compiled.output_schema) == expected_schema
    assert public_schema(compiled.step_schemas[0]["schema"]) == expected_schema
    assert public_schema(describe(result.schema)) == expected_schema
    assert "QUALIFY" not in compiled.sql and "OVER ()" not in compiled.sql


def test_golden_covers_every_published_step():
    assert {case.parent.parent.name for case in GOLDEN} == set(CONTRACTS)
    assert all(
        {p.parent.name for p in GOLDEN if p.parent.parent.name == kind}
        == {"ordinary", "null", "empty"}
        for kind in CONTRACTS
    )


def test_step_migration_is_repeatable_and_canonical_config_is_read_without_mutation():
    legacy = {
        "operation": "prepare",
        "steps": [{"action": "trim", "params": {"column": "a"}}],
        "outputs": [{"name": "X"}],
    }
    first, second = DataPrepSpec.model_validate(legacy), DataPrepSpec.model_validate(legacy)
    assert first.steps[0].id == second.steps[0].id
    canonical = first.canonical()
    assert canonical["params"]["steps"][0]["kind"] == "trim" and "steps" not in canonical
    assert bind_spec(canonical, first.outputs) == first
    assert "id" not in legacy["steps"][0]


@pytest.mark.parametrize("malformed", [True, 1, [], "string", None])
def test_invalid_parameter_objects_are_validation_errors(malformed):
    with pytest.raises(ValueError, match="DATAPREP_PARAMS_INVALID"):
        bind_spec({"operation": "prepare", "params": malformed}, [{"name": "Out"}])


def test_disabled_steps_keep_ids_without_binding_columns_and_prefix_schemas_are_native():
    table = pa.table(
        {"a": [Decimal("123.4567")]}, schema=pa.schema([pa.field("a", pa.decimal128(18, 4))])
    )
    spec = bind_spec(
        {
            "operation": "prepare",
            "params": {
                "steps": [
                    {
                        "id": "off",
                        "kind": "drop_columns",
                        "enabled": False,
                        "comment": "Kept in draft",
                        "params": {"columns": ["missing"]},
                    },
                    {"id": "copy", "kind": "copy_column", "params": {"column": "a", "output": "b"}},
                    {"id": "remove", "kind": "drop_columns", "params": {"columns": ["a"]}},
                ]
            },
        },
        [{"name": "Out"}],
    )
    compiled = compile_prep(
        spec, {"in": describe(table.schema)}, arrow_schemas={"in": table.schema}
    )
    assert compiled.step_schemas[0]["enabled"] is False
    assert compiled.step_schemas[1]["schema_diff"]["added"] == ["b"]
    assert compiled.step_schemas[2]["schema_diff"]["removed"] == ["a"]
    assert compiled.output_schema[0]["dtype"] == "decimal128(18, 4)"


def test_new_column_position_and_explicit_replacement_preserve_order():
    table = pa.table({"a": [1], "b": [2], "c": [3]})
    after, _ = execute(
        table, "copy_column", {"column": "a", "output": "new", "position": "after_input"}
    )
    assert after.column_names == ["a", "new", "b", "c"]
    end, _ = execute(table, "copy_column", {"column": "a", "output": "new", "position": "end"})
    assert end.column_names == ["a", "b", "c", "new"]
    replaced, _ = execute(table, "formula", {"output": "b", "expression": "a*10", "replace": True})
    assert replaced.to_pylist() == [{"a": 1, "b": 10, "c": 3}]


@pytest.mark.parametrize(
    "text",
    [
        "random()",
        "read_csv('/tmp/file')",
        "a[1]",
        "a -> a+1",
        "a.*",
        "(SELECT 1)",
        "a; SELECT 1",
        "cast(a AS BLOB)",
        "list_value(a)",
    ],
)
def test_closed_formula_ast_rejects_external_nondeterministic_and_structural_expressions(text):
    with pytest.raises(ValueError):
        expression(text, ["a"])


def test_selector_kinds_follow_current_schema_and_reject_no_match():
    table = pa.table({"a": [1], "b": ["x"], "c": [2.0]})
    result, _ = execute(
        table,
        "select_columns",
        {"columns": {"mode": "kinds", "kinds": ["numeric"], "exclude": ["a"]}},
    )
    assert result.column_names == ["c"]
    with pytest.raises(ValueError, match="COLUMNS_INVALID"):
        execute(table, "select_columns", {"columns": {"mode": "pattern", "regex": "missing"}})


def test_pivot_is_an_aggregate_with_explicit_null_and_other_columns():
    table = pa.table({"key": ["x", None, "z"], "value": [2, 3, 4]})
    result, _ = execute(
        table,
        None,
        {
            "pivot": {
                "column": "key",
                "values": ["x", None],
                "naming": "{value}",
                "others": "column",
                "others_label": "rest",
                "aggregations": [{"op": "sum", "column": "value"}],
            }
        },
        operation="aggregate",
    )
    assert result.to_pylist() == [{"x": Decimal(2), "(vide)": Decimal(3), "rest": Decimal(4)}]


def test_unpivot_refuses_text_numeric_coercion_and_widens_numeric_only():
    table = pa.table({"a": [1], "b": [2.5]})
    result, _ = execute(table, None, {"value_columns": ["a", "b"]}, operation="unpivot")
    assert result.to_pylist() == [{"variable": "a", "value": 1.0}, {"variable": "b", "value": 2.5}]
    with pytest.raises(ValueError, match="UNION_TYPES"):
        execute(
            pa.table({"a": [1], "b": ["2"]}),
            None,
            {"value_columns": ["a", "b"]},
            operation="unpivot",
        )


@pytest.mark.parametrize("size", [{"n": 2}, {"fraction": 0.5}])
def test_stratified_sample_has_exact_global_size_and_is_shuffle_invariant(size):
    table = pa.table({"id": list(range(10)), "group": ["a"] * 7 + ["b"] * 2 + [None]})
    params = {"method": "stratified", "stratify_by": ["group"], "key": ["id"], **size}
    result, compiled = execute(table, None, params, operation="sample")
    assert result.num_rows == (2 if "n" in size else 5)
    reversed_table = table.take(pa.array(list(reversed(range(10)))))
    reversed_result, _ = execute(reversed_table, None, params, operation="sample")
    assert sorted(result.column("id").to_pylist()) == sorted(
        reversed_result.column("id").to_pylist()
    )
    assert "OVER ()" not in compiled.sql


@pytest.mark.parametrize(
    "kind,params",
    [
        ("add_column", {"output": "b", "value": "oops", "type": "integer"}),
        ("fill_nulls", {"columns": ["a"], "method": "constant", "value": "oops"}),
        ("filter_rows", {"conditions": [{"column": "a", "op": "eq", "value": "oops"}]}),
        ("negate_boolean", {"columns": ["a"]}),
    ],
)
def test_invalid_literals_and_boolean_type_are_refused_on_empty_input_with_step_id(kind, params):
    with pytest.raises(ValueError) as error:
        execute(pa.table({"a": pa.array([], type=pa.int64())}), kind, params)
    assert error.value.step_id == "golden"


def test_recursive_preview_selects_split_port_and_keeps_every_leaf_workspace_scoped(
    db_session, monkeypatch, tmp_path
):
    from uuid import uuid4

    from app.core.config import settings
    from app.models.workspace import Workspace
    from app.services.dataops.preparation import preview_preparation
    from app.services.tabular_datasets import register_frame

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    workspace = Workspace(id=str(uuid4()), slug="recursive-preview", name="Preview", settings={})
    db_session.add(workspace)
    db_session.commit()
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Source",
        frame=pl.DataFrame({"a": [1, 2, 3, 4]}),
    )
    db_session.commit()
    inputs = {
        "in": {
            "upstream": {
                "spec": {
                    "operation": "split",
                    "params": {"method": "order", "order_by": ["a"], "ratios": [0.5, 0.5]},
                },
                "outputs": [{"port": "train", "name": "Train"}, {"port": "test", "name": "Test"}],
                "inputs": {"in": {"dataset_id": dataset.id}},
                "output_port": "test",
            }
        }
    }
    spec = bind_spec(
        {
            "operation": "prepare",
            "params": {
                "steps": [
                    {
                        "id": "double",
                        "kind": "formula",
                        "params": {"output": "b", "expression": "a*2"},
                    },
                    {"id": "drop", "kind": "drop_columns", "params": {"columns": ["a"]}},
                ]
            },
        },
        [{"name": "Out"}],
    )
    result = preview_preparation(
        db_session, workspace_id=workspace.id, spec=spec, inputs=inputs, step_id="double"
    )
    assert sorted(result["rows"], key=lambda r: r["a"]) == [{"a": 3, "b": 6}, {"a": 4, "b": 8}]
    assert result["counters"]["outputs"]["out"] == 2
    assert result["stats_scope"] == "sample"
    assert result["stats"]["b"]["mean"] == 7
    with pytest.raises(Exception):
        preview_preparation(db_session, workspace_id="another-workspace", spec=spec, inputs=inputs)


def test_preview_profiles_all_sample_rows_and_counts_only_failed_conversions(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import pyarrow.parquet as pq

    from app.core.config import settings
    from app.services.dataops.preview import preview
    from app.services.dataops.storage import file_digest
    from app.services.object_store import get_object_store

    table = pa.table(
        {"a": ["1", "bad", None, "3"], "b": ["13/10/2026", "invalid", None, "14/10/2026"]}
    )
    spec = bind_spec(
        {
            "operation": "prepare",
            "params": {
                "steps": [
                    {"id": "cast", "kind": "cast", "params": {"columns": ["a"], "to": "integer"}},
                    {
                        "id": "parse",
                        "kind": "parse_date",
                        "params": {
                            "column": "b",
                            "preset": "fr_date",
                            "to": "date",
                            "output": "day",
                        },
                    },
                ]
            },
        },
        [{"name": "Output"}],
    )
    compiled = compile_prep(
        spec, {"in": describe(table.schema)}, arrow_schemas={"in": table.schema}
    )
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    path = tmp_path / "sample.parquet"
    pq.write_table(table, path)
    key = "workspaces/preview-test/sample.parquet"
    get_object_store().write_file(key, path)
    dataset = SimpleNamespace(
        id="profile-sample",
        lineage_json={
            "sample": {
                "key": key,
                "sha256": file_digest(path),
                "method": "reservoir_seeded",
            }
        },
        row_count=1000,
        version=1,
    )
    result = preview(compiled, {"in": dataset}, spec, limit=1)
    assert len(result["rows"]) == 1
    assert result["stats"]["a"]["nulls"] == 2
    assert result["stats"]["a"]["mean"] == 2
    assert result["stats"]["day"]["min"] == "2026-10-13"
    assert result["stats_scope"] == "sample"
    assert result["counters"]["steps"] == {
        "cast": {"conversion_failures": {"a": 1}},
        "parse": {"conversion_failures": {"day": 1}},
    }
