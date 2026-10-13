"""Closed relational operators, shared by compilation and the sealed worker."""

from __future__ import annotations

import math

from app.services.dataops.compiler import (
    _columns,
    _names,
    _require,
    expression,
)
from app.services.dataops.compiler import (
    literal as lit,
)
from app.services.dataops.compiler import (
    quote as q,
)


def ordering(items, columns):
    if not isinstance(items, list) or not items:
        raise ValueError("DATAPREP_ORDER_REQUIRED")
    terms = []
    for item in items:
        item = {"column": item} if isinstance(item, str) else item
        _require(item, {"column", "direction", "nulls"}, {"column"})
        if (
            item["column"] not in columns
            or item.get("direction", "asc") not in {"asc", "desc"}
            or item.get("nulls", "last") not in {"first", "last"}
        ):
            raise ValueError("DATAPREP_ORDER_INVALID")
        terms.append(
            f"{q(item['column'])} {item.get('direction', 'asc').upper()} NULLS {item.get('nulls', 'last').upper()}"
        )
    return ",".join(terms)


def _type(fields):
    kinds = {f.get("kind") for f in fields}
    if len(kinds - {None}) > 1 and not kinds <= {"integer", "float"}:
        raise ValueError("DATAPREP_UNION_TYPES")
    kind = next(iter(kinds)) if len(kinds) == 1 else "float"
    return {
        "integer": "BIGINT",
        "float": "DOUBLE",
        "string": "VARCHAR",
        "boolean": "BOOLEAN",
        "datetime": "TIMESTAMP",
        "date": "DATE",
    }.get(kind, "VARCHAR")


def aggregate(item, columns, *, value_override=None):
    _require(item, {"function", "op", "column", "name", "output", "p", "sep", "order_by"})
    op = item.get("op", item.get("function"))
    op = {"avg": "mean", "stddev_samp": "std", "count_distinct": "count_distinct"}.get(op, op)
    column = item.get("column")
    if op not in {
        "count_rows",
        "count",
        "count_distinct",
        "sum",
        "mean",
        "min",
        "max",
        "std",
        "std_pop",
        "var",
        "median",
        "quantile",
        "mode",
        "string_agg",
        "first",
        "last",
    }:
        raise ValueError("DATAPREP_AGGREGATE_INVALID")
    if column is not None and column not in columns:
        raise ValueError("DATAPREP_COLUMN_UNKNOWN")
    if column is None and op not in {"count", "count_rows"}:
        raise ValueError("DATAPREP_COLUMN_REQUIRED")
    value = value_override or (q(column) if column else "*")
    name = item.get("output", item.get("name"))
    if not isinstance(name, str) or not name:
        raise ValueError("DATAPREP_OUTPUT_REQUIRED")
    if op in {"count", "count_rows", "count_distinct"}:
        term = f"count({'DISTINCT ' if op == 'count_distinct' else ''}{value})"
        term = f"CAST({term} AS BIGINT)"
    elif op == "quantile":
        p = item.get("p")
        if type(p) not in {float, int} or not 0 <= p <= 1:
            raise ValueError("DATAPREP_QUANTILE_INVALID")
        term = f"CAST(quantile_cont({value},{p}) AS DOUBLE)"
    elif op in {"first", "last", "string_agg"}:
        order = ordering(item.get("order_by"), columns)
        term = f"{op}({value}{',' + lit(item.get('sep', ',')) if op == 'string_agg' else ''} ORDER BY {order})"
    elif op == "mode":
        term = f"mode({value} ORDER BY {value})"
    else:
        function = {
            "mean": "avg",
            "std": "stddev_samp",
            "std_pop": "stddev_pop",
            "var": "var_samp",
        }.get(op, op)
        term = f"{function}({value})"
        if op in {"mean", "std", "std_pop", "var", "median"}:
            term = f"CAST({term} AS DOUBLE)"
    return term, name


def relational(spec, schemas):
    op, p = spec.operation, spec.params
    columns = _columns(schemas["left" if op == "join" else sorted(schemas)[0]])
    if op == "join":
        _require(p, {"keys", "on", "how", "null_equal", "select", "suffix", "merge_keys"})
        right = _columns(schemas["right"])
        how = p.get("how", "left")
        if how not in {"inner", "left", "right", "full", "cross", "semi", "anti"}:
            raise ValueError("DATAPREP_JOIN_TYPE_INVALID")
        keys = p.get("on", p.get("keys", []))
        if not keys and how != "cross":
            raise ValueError("DATAPREP_JOIN_KEYS_REQUIRED")
        conditions = []
        for pair in keys:
            _require(pair, {"left", "right", "op"}, {"left", "right"})
            if pair["left"] not in columns or pair["right"] not in right:
                raise ValueError("DATAPREP_JOIN_KEY_INVALID")
            a, b = f"l.{q(pair['left'])}", f"r.{q(pair['right'])}"
            operator = pair.get("op", "eq")
            if operator in {"contains", "starts_with"}:
                term = f"{operator}({a},{b})"
            else:
                symbol = {
                    "eq": "IS NOT DISTINCT FROM" if p.get("null_equal", False) else "=",
                    "ne": "<>",
                    "lt": "<",
                    "le": "<=",
                    "gt": ">",
                    "ge": ">=",
                }.get(operator)
                if symbol is None:
                    raise ValueError("DATAPREP_JOIN_OPERATOR_INVALID")
                term = f"{a} {symbol} {b}"
            conditions.append(term)
        select = p.get("select", {})
        _require(select, {"left", "right"})
        left = _names(select.get("left", columns), columns)
        rights = _names(select.get("right", right), right)
        if how in {"semi", "anti"}:
            sql = f'SELECT {",".join("l." + q(n) for n in left)} FROM "left" l WHERE {"NOT " if how == "anti" else ""}EXISTS(SELECT 1 FROM "right" r WHERE {" AND ".join(conditions)})'
            return sql, left
        projection = []
        suffix = p.get("suffix", {})
        _require(suffix, {"right"})
        merge = (
            {pair["left"]: pair["right"] for pair in keys if pair.get("op", "eq") == "eq"}
            if p.get("merge_keys", False)
            else {}
        )
        for n in left:
            projection.append(
                f"coalesce(l.{q(n)},r.{q(merge[n])}) AS {q(n)}" if n in merge else f"l.{q(n)}"
            )
        result = list(left)
        # Legacy keys kept their historical merged-key behavior.
        omitted = set(merge.values()) | (
            {pair["right"] for pair in keys} if "keys" in p and "on" not in p else set()
        )
        for n in rights:
            if n in omitted:
                continue
            alias = (
                n
                if n.casefold() not in {c.casefold() for c in result}
                else n + suffix.get("right", "_right")
            )
            if alias.casefold() in {c.casefold() for c in result}:
                raise ValueError("DATAPREP_COLUMN_COLLISION")
            projection.append(f"r.{q(n)} AS {q(alias)}")
            result.append(alias)
        sql = f'SELECT {",".join(projection)} FROM "left" l {how.upper()} JOIN "right" r' + (
            " ON " + " AND ".join(conditions) if how != "cross" else ""
        )
        return sql, result
    if op == "union":
        _require(p, {"distinct", "mode", "allow_missing", "bindings"})
        mode = p.get("mode", "by_name")
        ports = sorted(schemas)
        if mode not in {"by_name", "by_position", "bindings"}:
            raise ValueError("DATAPREP_UNION_MODE_INVALID")
        if mode == "by_position":
            if any(len(schemas[port]) != len(columns) for port in ports):
                raise ValueError("DATAPREP_UNION_SCHEMA_MISMATCH")
            bindings = {
                n: {port: schemas[port][i]["name"] for port in ports} for i, n in enumerate(columns)
            }
        elif mode == "bindings":
            bindings = {}
            for b in p.get("bindings", []):
                _require(b, {"output", "sources"}, {"output", "sources"})
                if not isinstance(b["sources"], dict) or set(b["sources"]) - set(ports):
                    raise ValueError("DATAPREP_UNION_BINDINGS_INVALID")
                bindings[b["output"]] = b["sources"]
            columns = list(bindings)
            if not columns:
                raise ValueError("DATAPREP_UNION_BINDINGS_INVALID")
        else:
            columns = list(dict.fromkeys(f["name"] for port in ports for f in schemas[port]))
            bindings = {
                n: {port: n for port in ports if n in _columns(schemas[port])} for n in columns
            }
        if len({n.casefold() for n in columns}) != len(columns):
            raise ValueError("DATAPREP_COLUMN_COLLISION")
        types = {}
        for n, sources in bindings.items():
            fields = []
            if not p.get("allow_missing", True) and set(sources) != set(ports):
                raise ValueError("DATAPREP_UNION_SCHEMA_MISMATCH")
            for port, col in sources.items():
                found = next((f for f in schemas[port] if f["name"] == col), None)
                if found is None:
                    raise ValueError("DATAPREP_COLUMN_UNKNOWN")
                fields.append(found)
            types[n] = _type(fields)
        sql = " UNION ALL ".join(
            f"SELECT {','.join('CAST(' + (q(bindings[n][port]) if port in bindings[n] else 'NULL') + ' AS ' + types[n] + ') AS ' + q(n) for n in columns)} FROM {q(port)}"
            for port in ports
        )
        return (f"SELECT DISTINCT * FROM ({sql})" if p.get("distinct") else sql), columns
    if op == "aggregate":
        _require(p, {"group_by", "aggregates", "aggregations"})
        groups = p.get("group_by", [])
        if groups:
            _names(groups, columns)
        items = p.get("aggregations", p.get("aggregates", []))
        if not isinstance(items, list) or not items:
            raise ValueError("DATAPREP_AGGREGATES_REQUIRED")
        projection = [q(n) for n in groups]
        result = list(groups)
        for item in items:
            term, name = aggregate(item, columns)
            if name.casefold() in {n.casefold() for n in result}:
                raise ValueError("DATAPREP_COLUMN_COLLISION")
            projection.append(term + " AS " + q(name))
            result.append(name)
        return f'SELECT {",".join(projection)} FROM "in"' + (
            " GROUP BY " + ",".join(q(n) for n in groups) if groups else ""
        ), result
    if op in {"sample", "split"}:
        _require(
            p,
            {
                "keys",
                "key",
                "rows",
                "n",
                "ratios",
                "stratify",
                "stratify_by",
                "method",
                "order_by",
                "fraction",
                "outputs",
                "else_port",
            },
        )
        method = p.get(
            "method", "stratified" if p.get("stratify") or p.get("stratify_by") else "random"
        )
        if op == "split" and method == "condition":
            outputs = p.get("outputs", [])
            fallback = p.get("else_port")
            valid = {o.port for o in spec.outputs}
            if fallback not in valid:
                raise ValueError("DATAPREP_ELSE_PORT_REQUIRED")
            cases = []
            for output in outputs:
                _require(output, {"port", "filter"}, {"port", "filter"})
                if output["port"] not in valid:
                    raise ValueError("DATAPREP_OUTPUT_PORT_INVALID")
                cases.append(
                    "WHEN " + expression(output["filter"], columns) + " THEN " + lit(output["port"])
                )
            if not cases:
                raise ValueError("DATAPREP_SPLIT_FILTER_REQUIRED")
            return (
                f'SELECT *,CASE {" ".join(cases)} ELSE {lit(fallback)} END AS __dp_output FROM "in"',
                columns,
            )
        if method not in {"random", "stratified", "order", "first"}:
            raise ValueError("DATAPREP_SAMPLE_METHOD_INVALID")
        keys = p.get("keys", p.get("key", columns))
        keys = [keys] if isinstance(keys, str) else keys
        _names(keys, columns)
        strata = p.get("stratify_by", p.get("stratify", []))
        if strata:
            _names(strata, columns)
        if method == "stratified" and not strata:
            raise ValueError("DATAPREP_STRATA_REQUIRED")
        if any(n.startswith("__dp_") for n in columns):
            raise ValueError("DATAPREP_RESERVED_COLUMN")

        def pack(names):
            return "to_json(struct_pack(" + ",".join(q(n) + ":=" + q(n) for n in names) + "))"

        row_fp = pack(columns)
        order = (
            (
                ordering(p.get("order_by"), columns)
                if method in {"order", "first"}
                else f"md5({lit(str(spec.seed))} || {pack(keys)})"
            )
            + ","
            + row_fp
        )
        partition = "PARTITION BY " + ",".join(q(n) for n in strata) + " " if strata else ""
        ranked = f'SELECT *,row_number() OVER({partition}ORDER BY {order}) AS __dp_rank,count(*) OVER({partition.strip()}) AS __dp_total FROM "in"'
        if op == "sample":
            n = p.get("n", p.get("rows"))
            fraction = p.get("fraction")
            if (n is None) == (fraction is None):
                raise ValueError("DATAPREP_SAMPLE_SIZE_REQUIRED")
            if n is not None and (type(n) is not int or n < 0):
                raise ValueError("DATAPREP_SAMPLE_ROWS_INVALID")
            if fraction is not None and (
                type(fraction) not in {float, int} or not 0 <= fraction <= 1
            ):
                raise ValueError("DATAPREP_SAMPLE_FRACTION_INVALID")
            limit = str(n) if n is not None else f"round(__dp_total*{fraction})"
            return (
                f"SELECT {','.join(q(n) for n in columns)} FROM ({ranked}) WHERE __dp_rank<={limit}",
                columns,
            )
        ratios = p.get("ratios")
        if ratios is None and p.get("outputs"):
            ratios = [o.get("ratio") for o in p["outputs"]]
        if (
            not isinstance(ratios, list)
            or len(ratios) != len(spec.outputs)
            or any(type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in ratios)
            or abs(sum(ratios) - 1) > 1e-9
        ):
            raise ValueError("DATAPREP_SPLIT_RATIOS_INVALID")
        cumulative = 0
        cases = []
        for i, ratio in enumerate(ratios[:-1]):
            cumulative += ratio
            cases.append(
                f"WHEN __dp_rank<=floor(__dp_total*{cumulative}) THEN {lit(spec.outputs[i].port)}"
            )
        return (
            f"SELECT {','.join(q(n) for n in columns)},CASE {' '.join(cases)} ELSE {lit(spec.outputs[-1].port)} END AS __dp_output FROM ({ranked})",
            columns,
        )
    return None
