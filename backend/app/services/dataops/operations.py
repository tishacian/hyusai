"""Closed relational operators, shared by compilation and the sealed worker."""

from __future__ import annotations

import math
import re

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
    from app.services.dataops.types import common_type

    return common_type(fields)


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
        from app.services.dataops.types import fingerprint

        order = ordering(item.get("order_by"), columns)
        order += "," + fingerprint(columns)
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
        if keys and how == "cross":
            raise ValueError("DATAPREP_CROSS_JOIN_KEYS_FORBIDDEN")
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
        ports = sorted(
            schemas, key=lambda p: (int(p[3:]) if re.fullmatch(r"in_\d+", p) else 1000, p)
        )
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
                sources = b["sources"]
                if isinstance(sources, list):
                    if any(
                        not isinstance(s, dict) or set(s) != {"port", "column"} for s in sources
                    ) or len({s["port"] for s in sources}) != len(sources):
                        raise ValueError("DATAPREP_UNION_BINDINGS_INVALID")
                    sources = {s["port"]: s["column"] for s in sources}
                if (
                    not isinstance(sources, dict)
                    or set(sources) - set(ports)
                    or b["output"] in bindings
                ):
                    raise ValueError("DATAPREP_UNION_BINDINGS_INVALID")
                bindings[b["output"]] = sources
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
        _require(p, {"group_by", "aggregates", "aggregations", "pivot"})
        groups = p.get("group_by", [])
        if groups:
            _names(groups, columns)
        pivot = p.get("pivot")
        items = p.get("aggregations", p.get("aggregates", []))
        if pivot:
            _require(
                pivot,
                {
                    "column",
                    "values",
                    "aggregations",
                    "naming",
                    "null_label",
                    "others",
                    "others_label",
                },
                {"column", "values"},
            )
            if pivot["column"] not in columns:
                raise ValueError("DATAPREP_COLUMN_UNKNOWN")
            items = pivot.get("aggregations", items)
        if not isinstance(items, list) or not items:
            raise ValueError("DATAPREP_AGGREGATES_REQUIRED")
        projection = [q(n) for n in groups]
        result = list(groups)
        for item in items:
            if not pivot:
                terms = [aggregate(item, columns)]
            else:
                import sqlglot
                from sqlglot import exp

                values = pivot["values"]
                from app.core.config import settings

                if (
                    not isinstance(values, list)
                    or not 1 <= len(values) <= settings.dataops_max_pivot_values
                    or len({(type(v).__name__, str(v)) for v in values}) != len(values)
                ):
                    raise ValueError("DATAPREP_PIVOT_VALUES_INVALID")
                predicates = [
                    (
                        str(v) if v is not None else pivot.get("null_label", "(vide)"),
                        f"{q(pivot['column'])} IS NOT DISTINCT FROM {lit(v)}",
                    )
                    for v in values
                ]
                if pivot.get("others", "drop") not in {"drop", "column"}:
                    raise ValueError("DATAPREP_PIVOT_OTHERS_INVALID")
                if pivot.get("others") == "column":
                    predicates.append(
                        (
                            pivot.get("others_label", "others"),
                            "NOT (" + " OR ".join(predicate for _, predicate in predicates) + ")",
                        )
                    )
                terms = []
                for label, predicate in predicates:
                    naming = pivot.get("naming", "{value}_{op}_{column}")
                    name = (
                        naming.replace("{value}", label)
                        .replace("{op}", item.get("op", item.get("function", "")))
                        .replace("{column}", item.get("column") or "rows")
                    )
                    term, _ = aggregate({**item, "output": name}, columns)
                    tree = sqlglot.parse_one(term, read="duckdb")
                    condition = sqlglot.parse_one(predicate, read="duckdb")
                    tree = tree.transform(
                        lambda node: (
                            exp.Filter(
                                this=node.copy(), expression=exp.Where(this=condition.copy())
                            )
                            if isinstance(node, exp.AggFunc)
                            else node
                        )
                    )
                    terms.append((tree.sql(dialect="duckdb"), name))
            for term, name in terms:
                if name.casefold() in {n.casefold() for n in result}:
                    raise ValueError("DATAPREP_COLUMN_COLLISION")
                projection.append(term + " AS " + q(name))
                result.append(name)
        return f'SELECT {",".join(projection)} FROM "in"' + (
            " GROUP BY " + ",".join(q(n) for n in groups) if groups else ""
        ), result
    if op == "unpivot":
        _require(
            p,
            {"columns", "id_columns", "value_columns", "name_column", "value_column", "drop_nulls"},
        )
        melting = _names(p.get("value_columns", p.get("columns")), columns)
        keep = (
            _names(p["id_columns"], columns)
            if p.get("id_columns")
            else [n for n in columns if n not in melting]
        )
        if set(keep) & set(melting):
            raise ValueError("DATAPREP_UNPIVOT_COLUMNS_OVERLAP")
        name_column, value_column = p.get("name_column", "variable"), p.get("value_column", "value")
        names = [*keep, name_column, value_column]
        if len(set(n.casefold() for n in names)) != len(names):
            raise ValueError("DATAPREP_COLUMN_COLLISION")
        dtype = _type([f for f in schemas["in"] if f["name"] in melting])
        sql = " UNION ALL ".join(
            f'SELECT {",".join([*(q(n) for n in keep), lit(n) + " AS " + q(name_column), "CAST(" + q(n) + " AS " + dtype + ") AS " + q(value_column)])} FROM "in"'
            + (f" WHERE {q(n)} IS NOT NULL" if p.get("drop_nulls") else "")
            for n in melting
        )
        return sql, names
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

        from app.services.dataops.types import fingerprint

        def pack(names):
            return fingerprint(names, schemas["in"])

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
        if strata:
            ranked = f'SELECT *,row_number() OVER({partition}ORDER BY {order}) AS __dp_rank,count(*) OVER({partition.strip()}) AS __dp_total FROM "in"'
        else:
            ranked = f'SELECT data.*,row_number() OVER(ORDER BY {order}) AS __dp_rank,stats.__dp_total FROM "in" data CROSS JOIN (SELECT count(*) AS __dp_total FROM "in") stats'
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
            if strata:
                # Largest remainders preserve proportional strata AND the exact global
                # sample size, including tiny strata and n smaller than their count.
                groups = ",".join(q(name) for name in strata)
                counts = f'SELECT {groups},count(*) AS __dp_n FROM "in" GROUP BY {groups}'
                target = (
                    f"least({n},__dp_global_n)"
                    if n is not None
                    else f"round(__dp_global_n*{fraction})"
                )
                bases = f'SELECT counts.*,CAST(floor(__dp_n*({target})/nullif(__dp_global_n,0)) AS BIGINT) AS __dp_base,(__dp_n*({target}))%nullif(__dp_global_n,0) AS __dp_remainder,CAST({target} AS BIGINT) AS __dp_target FROM ({counts}) counts CROSS JOIN (SELECT count(*) AS __dp_global_n FROM "in") totals'
                total_base = f"SELECT sum(__dp_base) AS __dp_base_total FROM ({bases})"
                quotas = f"SELECT bases.*,__dp_base+CASE WHEN row_number() OVER(ORDER BY __dp_remainder DESC,{fingerprint(strata, schemas['in'])})<=__dp_target-__dp_base_total THEN 1 ELSE 0 END AS __dp_quota FROM ({bases}) bases CROSS JOIN ({total_base}) totals"
                predicate = " AND ".join(
                    f"data.{q(name)} IS NOT DISTINCT FROM quotas.{q(name)}" for name in strata
                )
                return (
                    f"SELECT {','.join('data.' + q(name) for name in columns)} FROM ({ranked}) data JOIN ({quotas}) quotas ON {predicate} WHERE data.__dp_rank<=quotas.__dp_quota",
                    columns,
                )
            limit = str(n) if n is not None else f"round(__dp_total*{fraction})"
            return (
                f"SELECT {','.join(q(n) for n in columns)} FROM ({ranked}) WHERE __dp_rank<={limit}",
                columns,
            )
        ratios = p.get("ratios")
        if ratios is None and p.get("outputs"):
            if len({o.get("port") for o in p["outputs"]}) != len(p["outputs"]) or {
                o.get("port") for o in p["outputs"]
            } != {o.port for o in spec.outputs}:
                raise ValueError("DATAPREP_OUTPUT_PORT_INVALID")
            by_port = {o["port"]: o.get("ratio") for o in p["outputs"]}
            ratios = [by_port[o.port] for o in spec.outputs]
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
