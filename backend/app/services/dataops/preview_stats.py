"""Profiles and conversion counters for the already bounded preview connection."""

import math

from app.resources.dataops_storage import _json_scalar
from app.services.dataops.compiler import quote
from app.services.dataops.types import describe


def profile(conn, schema, predicate):
    source = f"(SELECT * FROM __preview_output{predicate})"
    count = conn.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
    stats = {}
    for field in describe(schema):
        column, kind = quote(field["name"]), field["kind"]
        if kind == "date":
            kind = "datetime"
        nulls, distinct = conn.execute(
            f"SELECT count(*)-count({column}),count(DISTINCT {column}) FROM {source}"
        ).fetchone()
        info = {
            "kind": kind,
            "nulls": nulls,
            "null_ratio": round(nulls / count, 4) if count else 0.0,
            "distinct": distinct + int(nulls > 0),
        }
        numeric = column
        if kind == "float":
            # Preserve native null/distinct counts, but do not feed IEEE
            # NaN/infinities to stddev (DuckDB raises instead of returning NULL).
            numeric = f"CASE WHEN isfinite({column}) THEN {column} END"
            non_finite = conn.execute(
                f"SELECT count({column})-count({numeric}) FROM {source}"
            ).fetchone()[0]
            if non_finite:
                info["non_finite"] = non_finite
        if kind in {"integer", "float", "datetime"}:
            low, high = conn.execute(
                f"SELECT min({numeric}),max({numeric}) FROM {source}"
            ).fetchone()
            info.update(min=_json_scalar(low), max=_json_scalar(high))
        if kind in {"integer", "float"}:
            values = conn.execute(
                f"SELECT avg({numeric}),stddev_samp({numeric}),quantile_cont({numeric},0.25),quantile_cont({numeric},0.5),quantile_cont({numeric},0.75) FROM {source}"
            ).fetchone()
            info.update(zip(("mean", "std", "q25", "q50", "q75"), map(_json_scalar, values)))
            width = (float(high) - float(low)) / 12 if low is not None and high is not None else 0
            if width > 0 and math.isfinite(width):
                bins = dict(
                    conn.execute(
                        f"SELECT least(11,greatest(0,ceil(({numeric}-?)/?)-1))::INT AS bin,count(*) FROM {source} WHERE ({numeric}) IS NOT NULL GROUP BY bin",
                        [float(low), width],
                    ).fetchall()
                )
                info["histogram"] = [
                    {"upper": float(low) + (i + 1) * width, "count": bins.get(i, 0)}
                    for i in range(12)
                ]
        if kind in {"string", "boolean"}:
            values = conn.execute(
                f"SELECT {column},count(*) AS n FROM {source} GROUP BY {column} ORDER BY n DESC,{column} NULLS LAST LIMIT 6"
            ).fetchall()
            info["top_values"] = [{"value": _json_scalar(v), "count": n} for v, n in values]
        if kind == "string":
            info["mean_length"] = _json_scalar(
                conn.execute(f"SELECT avg(length({column})) FROM {source}").fetchone()[0]
            )
        stats[field["name"]] = info
    return stats


def conversion_counters(conn, compiled, spec, execute):
    """NULL input is not a failure; these conversions preserve row count."""
    from app.services.dataops.selectors import resolve_params

    counters = {}
    previous = compiled.input_query
    steps = {step.id: step for step in spec.steps}
    for metadata in compiled.step_schemas:
        step = steps[metadata["id"]]
        query = compiled.step_queries[step.id]
        if step.enabled and step.action in {"cast", "parse_date", "parse_number"}:
            schema = execute(f"SELECT * FROM ({previous}) LIMIT 0").to_arrow_table().schema
            params = resolve_params(step.params, describe(schema))
            names = params.get("columns", [params.get("column")])
            outputs = names if step.action == "cast" else [params.get("output") or names[0]]
            before = execute(
                f"SELECT {','.join(f'count({quote(n)})' for n in names)} FROM ({previous})"
            ).fetchone()
            after = execute(
                f"SELECT {','.join(f'count({quote(n)})' for n in outputs)} FROM ({query})"
            ).fetchone()
            counters[step.id] = {
                "conversion_failures": {
                    name: max(0, a - b) for name, a, b in zip(outputs, before, after)
                }
            }
        previous = query
    return counters
