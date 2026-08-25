"""Standalone dbt transform harness executed BY THE VENV PYTHON.

A dbt node is not a statement, it is a *project*: several models referring to
one another through ``ref()``, reading declared ``source()`` tables, and
guarded by data tests. So this harness assembles a complete, minimal dbt
project in the scratch directory, points it at a duckdb file holding the node's
inputs, and runs ``dbt build`` — which is ``dbt run`` followed by ``dbt test``,
i.e. exactly the "transform, then prove it" gesture the node is for.

Contract with the manifest the worker writes:
  * ``models`` — ``[{"name": ..., "sql": ...}]``, written to ``models/<name>.sql``
    and therefore addressable as ``{{ ref('<name>') }}``;
  * ``tests_yml`` — optional ``models/schema.yml`` body, where the author
    declares dbt tests (``not_null``, ``unique``, ``accepted_values``, …);
  * ``sources`` — addressable name → Parquet path. Each becomes a real table in
    the duckdb database, reachable both as ``{{ source('inputs', name) }}`` and
    as a bare relation, so the SQL habits of the single-statement node carry
    over unchanged;
  * ``output_model`` — the model whose table is published as the dataset.

Only ``dbt-duckdb`` is assumed present — it is pinned into the managed venv by
the node's environment spec. The result Parquet is written by duckdb itself
rather than by a dataframe library, so the venv stays as small as the engine.

The summary JSON is written **before** the exit code is decided, because a
failing data test is a verdict the author must be able to read, not just a
non-zero status.

Exit codes are the machine contract with the supervising worker:
  0 success · 1 dbt build failed · 2 data tests failed · 3 output model missing ·
  4 result empty · 5 result unwritable · 6 harness/manifest error
"""
from __future__ import annotations

import json
import os
import sys


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr, flush=True)
    return code


def _project_yml() -> str:
    return (
        "name: agentium\n"
        'version: "1.0"\n'
        "config-version: 2\n"
        "profile: agentium\n"
        'model-paths: ["models"]\n'
        'target-path: "target"\n'
        'clean-targets: ["target"]\n'
        "flags:\n"
        "  send_anonymous_usage_stats: false\n"
        "models:\n"
        "  agentium:\n"
        "    +materialized: table\n"
    )


def _profiles_yml(db_path: str, threads: int) -> str:
    return (
        "agentium:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: duckdb\n"
        f"      path: {db_path}\n"
        f"      threads: {threads}\n"
        "      schema: main\n"
    )


def _sources_yml(names: list[str]) -> str:
    lines = ["version: 2", "sources:", "  - name: inputs", "    schema: main", "    tables:"]
    lines.extend(f"      - name: {name}" for name in names)
    return "\n".join(lines) + "\n"


def _load_inputs(duckdb, db_path: str, sources: dict) -> list[str]:
    """Materialize every declared source as a relation in the duckdb file.

    Distinct paths become tables; a name pointing at an already-loaded path
    becomes a view, so the aliases (``input``, ``input_1``) cost nothing.
    """

    names: list[str] = []
    table_by_path: dict[str, str] = {}
    connection = duckdb.connect(db_path)
    try:
        for name, path in sources.items():
            relation = str(name)
            location = str(path)
            existing = table_by_path.get(location)
            if existing is None:
                quoted = location.replace("'", "''")
                connection.execute(
                    f'CREATE OR REPLACE TABLE main."{relation}" AS '
                    f"SELECT * FROM read_parquet('{quoted}')"
                )
                table_by_path[location] = relation
            else:
                connection.execute(
                    f'CREATE OR REPLACE VIEW main."{relation}" AS '
                    f'SELECT * FROM main."{existing}"'
                )
            names.append(relation)
    finally:
        connection.close()
    return names


def _node_results(result) -> list[dict]:
    """Flatten a dbt run result into rows the workshop can render."""

    rows: list[dict] = []
    for item in getattr(getattr(result, "result", None), "results", []) or []:
        node = getattr(item, "node", None)
        resource = str(getattr(node, "resource_type", "") or "")
        rows.append(
            {
                "kind": "test" if resource == "test" else "model",
                "name": str(getattr(node, "name", "") or ""),
                "status": str(getattr(item, "status", "") or ""),
                "failures": int(getattr(item, "failures", 0) or 0),
                "duration_ms": round(float(getattr(item, "execution_time", 0.0)) * 1000, 1),
                "message": str(getattr(item, "message", "") or "")[:400],
            }
        )
    return rows


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return _fail(6, "usage: dbt_harness.py MANIFEST_JSON RESULT_JSON")
    manifest_path, result_path = argv[1:3]
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return _fail(6, f"dbt_manifest_unreadable: {exc}")
    if not isinstance(manifest, dict):
        return _fail(6, "dbt_manifest_not_object")

    models = manifest.get("models")
    sources = manifest.get("sources")
    output_model = manifest.get("output_model")
    output_path = manifest.get("output_path")
    if (
        not isinstance(models, list)
        or not models
        or not isinstance(sources, dict)
        or not isinstance(output_model, str)
        or not isinstance(output_path, str)
    ):
        return _fail(6, "dbt_manifest_incomplete")
    threads = int(manifest.get("threads") or 2)

    try:
        import duckdb
    except ImportError as exc:
        return _fail(6, f"duckdb_missing_in_env: {exc}")
    try:
        from dbt.cli.main import dbtRunner
    except ImportError as exc:
        return _fail(6, f"dbt_missing_in_env: {exc}")

    project = os.path.join(os.getcwd(), "project")
    models_dir = os.path.join(project, "models")
    db_path = os.path.join(project, "warehouse.duckdb")
    try:
        os.makedirs(models_dir, exist_ok=True)
        source_names = _load_inputs(duckdb, db_path, sources)
        with open(os.path.join(project, "dbt_project.yml"), "w", encoding="utf-8") as h:
            h.write(_project_yml())
        with open(os.path.join(project, "profiles.yml"), "w", encoding="utf-8") as h:
            h.write(_profiles_yml(db_path, threads))
        with open(
            os.path.join(models_dir, "_agentium_sources.yml"), "w", encoding="utf-8"
        ) as h:
            h.write(_sources_yml(source_names))
        for entry in models:
            if not isinstance(entry, dict):
                return _fail(6, "dbt_model_not_object")
            name = str(entry.get("name") or "")
            sql = str(entry.get("sql") or "")
            with open(
                os.path.join(models_dir, f"{name}.sql"), "w", encoding="utf-8"
            ) as h:
                h.write(sql if sql.endswith("\n") else sql + "\n")
        tests_yml = manifest.get("tests_yml")
        if isinstance(tests_yml, str) and tests_yml.strip():
            with open(
                os.path.join(models_dir, "schema.yml"), "w", encoding="utf-8"
            ) as h:
                h.write(tests_yml if tests_yml.endswith("\n") else tests_yml + "\n")
    except OSError as exc:
        return _fail(6, f"dbt_project_unwritable: {exc}")
    except Exception as exc:  # noqa: BLE001 - a bad input is ours, not the author's
        return _fail(6, f"dbt_input_unreadable: {exc}")

    # dbt writes the author-facing log to stdout; flush ours first so the two
    # streams do not interleave inside a single buffer.
    sys.stdout.flush()
    sys.stderr.flush()
    invocation = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            project,
            "--profiles-dir",
            project,
            "--target",
            "dev",
            "--no-use-colors",
        ]
    )
    sys.stdout.flush()

    nodes = _node_results(invocation)
    tests = [row for row in nodes if row["kind"] == "test"]
    failed_tests = [row for row in tests if row["status"] not in ("pass", "success")]
    summary = {
        "nodes": nodes,
        "tests_total": len(tests),
        "tests_failed": len(failed_tests),
        "models_total": len([row for row in nodes if row["kind"] == "model"]),
        "selected": output_model,
        "rows": 0,
        "columns": [],
    }

    def _write_summary() -> None:
        try:
            with open(result_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(summary, ensure_ascii=False))
        except OSError:
            pass

    if not getattr(invocation, "success", False):
        _write_summary()
        if failed_tests:
            return _fail(
                2,
                "dbt_tests_failed: "
                + ", ".join(
                    f"{row['name']} ({row['failures']})" for row in failed_tests[:4]
                ),
            )
        exception = getattr(invocation, "exception", None)
        if exception is not None:
            return _fail(1, f"dbt_build_failed: {exception}")
        broken = [
            row
            for row in nodes
            if row["kind"] == "model" and row["status"] not in ("success", "skipped")
        ]
        detail = broken[0]["message"] if broken else "see the dbt log"
        return _fail(1, f"dbt_build_failed: {detail}")

    connection = duckdb.connect(db_path)
    try:
        known = {
            str(row[0])
            for row in connection.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'main'"
            ).fetchall()
        }
        if output_model not in known:
            _write_summary()
            return _fail(
                3,
                f"dbt_output_model_missing: '{output_model}' is not a model of this "
                "project",
            )
        columns = [
            str(row[0])
            for row in connection.execute(
                'select column_name from information_schema.columns '
                "where table_schema = 'main' and table_name = ? "
                "order by ordinal_position",
                [output_model],
            ).fetchall()
        ]
        rows = int(
            connection.execute(
                f'select count(*) from main."{output_model}"'
            ).fetchone()[0]
        )
        summary["rows"] = rows
        summary["columns"] = columns
        if not columns:
            _write_summary()
            return _fail(4, "dbt_result_no_columns: the published model has no column")
        row_limit = manifest.get("row_limit")
        selection = f'select * from main."{output_model}"'
        if isinstance(row_limit, int) and row_limit > 0:
            selection += f" limit {row_limit}"
        quoted = output_path.replace("'", "''")
        try:
            connection.execute(
                f"copy ({selection}) to '{quoted}' (format parquet)"
            )
        except Exception as exc:  # noqa: BLE001
            _write_summary()
            return _fail(5, f"dbt_result_unwritable: {exc}")
    finally:
        connection.close()

    _write_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
