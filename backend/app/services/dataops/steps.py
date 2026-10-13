"""Preparation step catalogue with explicit NULL, ordering and text semantics."""

from __future__ import annotations

import re
import unicodedata

EXTENDED_STEPS = (
    "select_columns",
    "drop_columns",
    "rename_columns",
    "move_columns",
    "copy_column",
    "concat_columns",
    "normalize_column_names",
    "add_column",
    "parse_date",
    "format_date",
    "from_epoch",
    "parse_number",
    "to_boolean",
    "drop_nulls",
    "fill_nulls",
    "filter_rows",
    "filter_range",
    "filter_expression",
    "flag_rows",
    "text_transform",
    "replace_values",
    "split_column",
    "extract_regex",
    "count_occurrences",
    "substring",
    "pad",
    "length",
    "negate_boolean",
    "bin_numeric",
    "formula",
    "conditional_column",
    "map_values",
    "window",
    "mask",
    "cast",
    "deduplicate",
    "dedup",
    "sort",
    "round",
    "math",
    "extract_date_parts",
    "date_diff",
    "date_add",
    "truncate_date",
    "convert_timezone",
    "scale",
)


def _regex(pattern):
    if (
        not isinstance(pattern, str)
        or not pattern
        or len(pattern) > 1024
        or re.search(r"\(\?[=!<]|\\[1-9]", pattern)
    ):
        raise ValueError("DATAPREP_REGEX_INVALID")
    try:
        return re.compile(pattern)
    except re.error:
        raise ValueError("DATAPREP_REGEX_INVALID") from None


def apply_step(sql, columns, action, p):
    from app.services.dataops.compiler import _names, _require, expression
    from app.services.dataops.compiler import literal as lit
    from app.services.dataops.compiler import quote as q

    source = f"({sql}) AS data"

    def ensure(name):
        if name not in columns:
            raise ValueError("DATAPREP_COLUMN_UNKNOWN")
        return q(name)

    def project(values, *, extras=None):
        nonlocal columns
        extra = extras or {}
        additions = list(extra)
        if any(n.casefold() in {c.casefold() for c in columns} for n in additions):
            raise ValueError("DATAPREP_COLUMN_COLLISION")
        projection = [f"{values.get(n, q(n))} AS {q(n)}" for n in columns] + [
            f"{v} AS {q(k)}" for k, v in extra.items()
        ]
        columns = [*columns, *additions]
        return f"SELECT {','.join(projection)} FROM {source}"

    def put(column, term, output=None):
        ensure(column)
        return (
            project({column: term})
            if not output or output == column
            else project({}, extras={output: term})
        )

    def order(params):
        names = params.get("order_by", [])
        if not names:
            raise ValueError("DATAPREP_ORDER_REQUIRED")
        parts = []
        for key in names:
            name = key if isinstance(key, str) else key.get("column")
            ensure(name)
            direction = "ASC" if isinstance(key, str) else str(key.get("direction", "asc")).upper()
            if direction not in {"ASC", "DESC"}:
                raise ValueError("DATAPREP_ORDER_INVALID")
            parts.append(f"{q(name)} {direction} NULLS LAST")
        packed = "struct_pack(" + ",".join(f"{q(n)}:={q(n)}" for n in columns) + ")"
        return ",".join([*parts, f"sha256(to_json({packed}))"])

    def condition(params):
        terms = []
        for item in params.get("conditions", []):
            _require(
                item,
                {"column", "op", "value", "values", "case_sensitive", "normalize_accents"},
                {"column", "op"},
            )
            value = ensure(item["column"])
            op = item["op"]
            target = item.get("value")
            if item.get("normalize_accents"):
                value = f"strip_accents(CAST({value} AS VARCHAR))"
                if isinstance(target, str):
                    target = "".join(
                        c
                        for c in unicodedata.normalize("NFKD", target)
                        if not unicodedata.combining(c)
                    )
            if item.get("case_sensitive") is False:
                value = f"lower(CAST({value} AS VARCHAR))"
                if isinstance(target, str):
                    target = target.lower()
            operators = {"eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
            if op in operators:
                term = f"{value} {operators[op]} {lit(target)}"
                if op == "ne" and params.get("keep_nulls_on_ne"):
                    term = f"({term} OR {value} IS NULL)"
            elif op in {"is_null", "is_not_null", "is_true", "is_false"}:
                term = (
                    f"{value} IS "
                    + {
                        "is_null": "NULL",
                        "is_not_null": "NOT NULL",
                        "is_true": "TRUE",
                        "is_false": "FALSE",
                    }[op]
                )
            elif op in {"in", "not_in"}:
                values = item.get("values")
                if not isinstance(values, list) or not 1 <= len(values) <= 1000:
                    raise ValueError("DATAPREP_FILTER_VALUES_INVALID")
                term = f"{value} {'NOT IN' if op == 'not_in' else 'IN'} ({','.join(lit(v) for v in values)})"
            elif op == "between":
                values = item.get("values")
                if not isinstance(values, list) or len(values) != 2:
                    raise ValueError("DATAPREP_RANGE_INVALID")
                term = f"{value} BETWEEN {lit(values[0])} AND {lit(values[1])}"
            elif op in {"contains", "starts_with", "ends_with"}:
                function = {
                    "contains": "contains",
                    "starts_with": "starts_with",
                    "ends_with": "ends_with",
                }[op]
                term = f"{function}(CAST({value} AS VARCHAR),{lit(target)})"
            elif op == "matches":
                _regex(target)
                term = f"regexp_matches(CAST({value} AS VARCHAR),{lit(target)})"
            else:
                raise ValueError("DATAPREP_FILTER_OPERATOR_INVALID")
            terms.append(f"({term})")
        combine = params.get("combine", "and")
        if not terms or combine not in {"and", "or"}:
            raise ValueError("DATAPREP_FILTER_INVALID")
        return f" {combine.upper()} ".join(terms)

    if action in {"select_columns", "drop_columns"}:
        _require(p, {"columns"}, {"columns"})
        names = _names(p["columns"], columns)
        columns = names if action == "select_columns" else [n for n in columns if n not in names]
        if not columns:
            raise ValueError("DATAPREP_NO_COLUMNS")
        sql = f"SELECT {','.join(q(n) for n in columns)} FROM {source}"
    elif action == "rename_columns":
        _require(p, {"mapping"}, {"mapping"})
        mapping = p["mapping"]
        if isinstance(mapping, list):
            mapping = {item["from"]: item["to"] for item in mapping}
        if not isinstance(mapping, dict) or any(n not in columns for n in mapping):
            raise ValueError("DATAPREP_RENAME_INVALID")
        new = [mapping.get(n, n) for n in columns]
        if len(set(n.casefold() for n in new)) != len(new):
            raise ValueError("DATAPREP_COLUMN_COLLISION")
        sql = f"SELECT {','.join(q(n) + ' AS ' + q(mapping.get(n, n)) for n in columns)} FROM {source}"
        columns = new
    elif action == "move_columns":
        _require(p, {"columns", "position", "anchor"}, {"columns", "position"})
        names = _names(p["columns"], columns)
        rest = [n for n in columns if n not in names]
        position = p["position"]
        if position == "start":
            index = 0
        elif position == "end":
            index = len(rest)
        elif position in {"before", "after"} and p.get("anchor") in rest:
            index = rest.index(p["anchor"]) + int(position == "after")
        else:
            raise ValueError("DATAPREP_POSITION_INVALID")
        columns = rest[:index] + names + rest[index:]
        sql = f"SELECT {','.join(q(n) for n in columns)} FROM {source}"
    elif action == "copy_column":
        _require(p, {"column", "output", "position"}, {"column", "output"})
        sql = project({}, extras={p["output"]: ensure(p["column"])})
    elif action == "concat_columns":
        _require(p, {"columns", "separator", "output", "nulls"}, {"columns", "output"})
        names = _names(p["columns"], columns)
        mode = p.get("nulls", "skip")
        sep = lit(p.get("separator", ""))
        terms = [f"CAST({q(n)} AS VARCHAR)" for n in names]
        if mode == "skip":
            term = f"concat_ws({sep},{','.join(terms)})"
        elif mode == "empty":
            coalesced = ",".join("coalesce(" + v + ",'')" for v in terms)
            term = f"concat_ws({sep},{coalesced})"
        elif mode == "propagate":
            term = " || " + sep + " || "
            term = term.join(terms)
        else:
            raise ValueError("DATAPREP_NULL_MODE_INVALID")
        sql = project({}, extras={p["output"]: term})
    elif action == "normalize_column_names":
        _require(p, {"style", "dedupe"}, {"style"})
        mapping = {}
        used = set()
        for name in columns:
            value = name
            if p["style"] == "lower":
                value = value.lower()
            elif p["style"] in {"snake", "ascii"}:
                value = (
                    re.sub(
                        r"[^a-zA-Z0-9]+",
                        "_",
                        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode(),
                    )
                    .strip("_")
                    .lower()
                )
            elif p["style"] == "papai":
                value = re.sub(r"[$ ,;{}()\n\t=]", "_", value)
            else:
                raise ValueError("DATAPREP_NAME_STYLE_INVALID")
            value = value or "column"
            if value[0].isdigit():
                value = "_" + value
            base = value
            suffix = 2
            while value.casefold() in used:
                if p.get("dedupe", "fail") != "suffix":
                    raise ValueError("DATAPREP_COLUMN_COLLISION")
                value = f"{base}_{suffix}"
                suffix += 1
            mapping[name] = value
            used.add(value.casefold())
        return apply_step(sql, columns, "rename_columns", {"mapping": mapping})
    elif action == "add_column":
        _require(p, {"output", "value", "type", "position"}, {"output", "value", "type"})
        types = {
            "integer": "INTEGER",
            "bigint": "BIGINT",
            "double": "DOUBLE",
            "text": "VARCHAR",
            "boolean": "BOOLEAN",
            "date": "DATE",
            "timestamp": "TIMESTAMP",
            "timestamp_tz": "TIMESTAMPTZ",
        }
        if p["type"] not in types:
            raise ValueError("DATAPREP_TYPE_INVALID")
        sql = project({}, extras={p["output"]: f"CAST({lit(p['value'])} AS {types[p['type']]})"})
    elif action in {
        "parse_date",
        "format_date",
        "from_epoch",
        "parse_number",
        "substring",
        "pad",
        "length",
    }:
        _require(
            p,
            {
                "column",
                "format",
                "preset",
                "to",
                "output",
                "unit",
                "decimal_separator",
                "thousands_separator",
                "start",
                "length",
                "char",
                "side",
            },
            {"column"},
        )
        value = ensure(p["column"])
        if action == "parse_date":
            presets = {
                "iso_date": "%Y-%m-%d",
                "iso_datetime": "%Y-%m-%dT%H:%M:%S",
                "iso_datetime_tz": "%Y-%m-%dT%H:%M:%S%z",
                "fr_date": "%d/%m/%Y",
                "fr_datetime": "%d/%m/%Y %H:%M:%S",
                "us_date": "%m/%d/%Y",
                "compact": "%Y%m%d",
                "rfc2822": "%a, %d %b %Y %H:%M:%S %z",
            }
            fmt = p.get("format") or presets.get(p.get("preset"))
            if not fmt:
                raise ValueError("DATAPREP_DATE_FORMAT_REQUIRED")
            term = f"try_strptime(CAST({value} AS VARCHAR),{lit(fmt)})"
            to = p.get("to", "auto")
            if to not in {"date", "timestamp", "timestamp_tz", "auto"}:
                raise ValueError("DATAPREP_TYPE_INVALID")
            if to != "auto":
                term = f"CAST({term} AS {'TIMESTAMPTZ' if to == 'timestamp_tz' else to.upper()})"
        elif action == "format_date":
            if not isinstance(p.get("format"), str) or not p["format"].strip():
                raise ValueError("DATAPREP_DATE_FORMAT_REQUIRED")
            term = f"strftime({value},{lit(p.get('format'))})"
        elif action == "from_epoch":
            unit = p.get("unit", "s")
            if unit not in {"s", "ms", "us"}:
                raise ValueError("DATAPREP_EPOCH_UNIT_INVALID")
            term = f"to_timestamp(CAST({value} AS DOUBLE)/{dict(s=1, ms=1000, us=1000000)[unit]})"
        elif action == "parse_number":
            value = f"CAST({value} AS VARCHAR)"
            if p.get("thousands_separator"):
                value = f"replace({value},{lit(p['thousands_separator'])},'')"
            separator = p.get("decimal_separator", ".")
            if separator not in {".", ","}:
                raise ValueError("DATAPREP_DECIMAL_SEPARATOR_INVALID")
            term = f"try_cast(replace({value},{lit(separator)},'.') AS DOUBLE)"
        elif action == "substring":
            start = p.get("start", 1)
            length = p.get("length")
            if (
                type(start) is not int
                or start < 1
                or (length is not None and (type(length) is not int or length < 0))
            ):
                raise ValueError("DATAPREP_SUBSTRING_INVALID")
            term = f"substr({value},{start}" + (f",{length})" if length is not None else ")")
        elif action == "length":
            term = f"length({value})"
        else:
            size = p.get("length")
            char = p.get("char", " ")
            side = p.get("side", "left")
            if (
                type(size) is not int
                or not 0 <= size <= 10000
                or not isinstance(char, str)
                or len(char) != 1
                or side not in {"left", "right"}
            ):
                raise ValueError("DATAPREP_PAD_INVALID")
            term = f"{'lpad' if side == 'left' else 'rpad'}({value},{size},{lit(char)})"
        sql = put(p["column"], term, p.get("output"))
    elif action == "to_boolean":
        _require(p, {"columns", "true_values", "false_values", "case_sensitive"}, {"columns"})
        names = _names(p["columns"], columns)
        true = p.get("true_values", ["true", "t", "yes", "y", "1", "oui"])
        false = p.get("false_values", ["false", "f", "no", "n", "0", "non"])
        if not true or not false or set(true) & set(false):
            raise ValueError("DATAPREP_BOOLEAN_VALUES_INVALID")
        values = {}
        for name in names:
            term = f"CAST({q(name)} AS VARCHAR)"
            if not p.get("case_sensitive", False):
                term = f"lower({term})"
                true = [str(v).lower() for v in true]
                false = [str(v).lower() for v in false]
            values[name] = (
                f"CASE WHEN {term} IN ({','.join(lit(v) for v in true)}) THEN TRUE WHEN {term} IN ({','.join(lit(v) for v in false)}) THEN FALSE ELSE NULL END"
            )
        sql = project(values)
    elif action == "drop_nulls":
        _require(p, {"columns", "how", "nan_as_null"}, {"columns"})
        names = _names(p["columns"], columns)
        how = p.get("how", "any")
        if how not in {"any", "all"}:
            raise ValueError("DATAPREP_NULL_MODE_INVALID")
        # isnan accepts numeric columns; textual NULL checks stay type-safe.
        conditions = [
            f"({q(n)} IS NOT NULL AND CASE WHEN typeof({q(n)}) IN ('DOUBLE','FLOAT') "
            f"THEN NOT coalesce(isnan(try_cast({q(n)} AS DOUBLE)),false) ELSE TRUE END)"
            if p.get("nan_as_null", True)
            else f"{q(n)} IS NOT NULL"
            for n in names
        ]
        sql = f"SELECT * FROM {source} WHERE " + (" AND " if how == "any" else " OR ").join(
            conditions
        )
    elif action == "fill_nulls":
        _require(
            p, {"columns", "method", "value", "order_by", "partition_by"}, {"columns", "method"}
        )
        names = _names(p["columns"], columns)
        method = p["method"]
        partitions = p.get("partition_by", [])
        if partitions:
            _names(partitions, columns)
        if method == "constant":
            sql = project({n: f"coalesce({q(n)},{lit(p.get('value'))})" for n in names})
        elif method in {"ffill", "bfill"}:
            window = (
                ("PARTITION BY " + ",".join(q(n) for n in partitions) + " " if partitions else "")
                + "ORDER BY "
                + order(p)
            )
            func, frame = (
                ("last_value", "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW")
                if method == "ffill"
                else ("first_value", "ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING")
            )
            sql = project({n: f"{func}({q(n)} IGNORE NULLS) OVER({window} {frame})" for n in names})
        elif method in {"mean", "median", "min", "max", "mode"}:
            func = {"mean": "avg", "median": "median", "min": "min", "max": "max", "mode": "mode"}[
                method
            ]
            aggs = ",".join(
                [
                    *(q(n) for n in partitions),
                    *(
                        f"{func}({q(n)}{' ORDER BY ' + q(n) if method == 'mode' else ''}) AS {q('__fill_' + str(i))}"
                        for i, n in enumerate(names)
                    ),
                ]
            )
            summary = f"SELECT {aggs} FROM {source}" + (
                " GROUP BY " + ",".join(q(n) for n in partitions) if partitions else ""
            )
            projection = ",".join(
                f"coalesce(data.{q(n)},agg.{q('__fill_' + str(names.index(n)))}) AS {q(n)}"
                if n in names
                else f"data.{q(n)}"
                for n in columns
            )
            join = " LEFT JOIN " if partitions else " CROSS JOIN "
            predicate = (
                " ON "
                + " AND ".join(f"data.{q(n)} IS NOT DISTINCT FROM agg.{q(n)}" for n in partitions)
                if partitions
                else ""
            )
            sql = f"SELECT {projection} FROM {source}{join}({summary}) agg{predicate}"
        else:
            raise ValueError("DATAPREP_FILL_METHOD_INVALID")
    elif action in {"filter_rows", "flag_rows", "filter_range", "filter_expression"}:
        if action == "filter_expression":
            _require(p, {"expression"}, {"expression"})
            term = expression(p["expression"], columns)
        elif action == "filter_range":
            _require(p, {"column", "min", "max", "min_inclusive", "max_inclusive"}, {"column"})
            value = ensure(p["column"])
            terms = []
            if p.get("min") is not None:
                terms.append(
                    f"{value}{'>=' if p.get('min_inclusive', True) else '>'}{lit(p['min'])}"
                )
            if p.get("max") is not None:
                terms.append(
                    f"{value}{'<=' if p.get('max_inclusive', True) else '<'}{lit(p['max'])}"
                )
            if not terms:
                raise ValueError("DATAPREP_RANGE_REQUIRED")
            term = " AND ".join(terms)
        else:
            _require(
                p,
                {"conditions", "combine", "keep_nulls_on_ne", "output", "flag_when"},
                {"conditions"},
            )
            term = condition(p)
        if action == "flag_rows":
            if p.get("flag_when", "match") not in {"match", "no_match"}:
                raise ValueError("DATAPREP_FLAG_MODE_INVALID")
            sql = project(
                {},
                extras={
                    p["output"]: ("NOT " if p.get("flag_when") == "no_match" else "")
                    + f"coalesce(({term}),false)"
                },
            )
        else:
            sql = f"SELECT * FROM {source} WHERE {term}"
    elif action == "text_transform":
        _require(p, {"columns", "operation"}, {"columns", "operation"})
        names = _names(p["columns"], columns)
        op = p["operation"]
        function = {
            "trim": "trim",
            "ltrim": "ltrim",
            "rtrim": "rtrim",
            "lower": "lower",
            "upper": "upper",
            "remove_accents": "strip_accents",
        }
        values = {}
        for name in names:
            if op in function:
                values[name] = f"{function[op]}({q(name)})"
            elif op == "collapse_spaces":
                values[name] = f"regexp_replace({q(name)},'\\s+',' ','g')"
            elif op == "title":
                values[name] = (
                    f"array_to_string(list_transform(string_split(lower({q(name)}),' '),word -> upper(left(word,1)) || substring(word,2)),' ')"
                )
            else:
                raise ValueError("DATAPREP_TEXT_OPERATION_INVALID")
        sql = project(values)
    elif action in {"replace_values", "map_values"}:
        _require(
            p,
            {
                "columns",
                "column",
                "pairs",
                "match",
                "case_sensitive",
                "normalize_accents",
                "default",
                "value",
                "output",
            },
            {"pairs"},
        )
        names = _names(p.get("columns") or [p.get("column")], columns)
        pairs = p["pairs"]
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 1000:
            raise ValueError("DATAPREP_MAPPING_INVALID")
        mode = p.get("match", "exact")
        values = {}
        for name in names:
            value = q(name)
            target = value

            def normalize(term):
                if p.get("normalize_accents", False):
                    term = f"strip_accents({term})"
                return f"lower({term})" if not p.get("case_sensitive", True) else term

            compared = normalize(value)
            if mode == "exact":
                cases = []
                for pair in pairs:
                    _require(pair, {"from", "to"}, {"from", "to"})
                    cases.append(
                        f"WHEN {compared} IS NOT DISTINCT FROM {normalize(lit(pair['from']))} THEN {lit(pair['to'])}"
                    )
                default = p.get("default", "keep")
                if default not in {"keep", "null", "value"}:
                    raise ValueError("DATAPREP_MAPPING_DEFAULT_INVALID")
                target = f"CASE {' '.join(cases)} ELSE {value if default == 'keep' else 'NULL' if default == 'null' else lit(p.get('value'))} END"
            elif mode in {"substring", "regex"}:
                if p.get("normalize_accents", False):
                    raise ValueError("DATAPREP_ACCENT_REPLACE_REQUIRES_EXACT")
                for pair in pairs:
                    _require(pair, {"from", "to"}, {"from", "to"})
                    if mode == "regex":
                        _regex(pair["from"])
                    if not p.get("case_sensitive", True):
                        pattern = re.escape(pair["from"]) if mode == "substring" else pair["from"]
                        target = f"regexp_replace({target},{lit(pattern)},{lit(pair['to'])},'gi')"
                        continue
                    target = (
                        f"{'replace' if mode == 'substring' else 'regexp_replace'}({target},{lit(pair['from'])},{lit(pair['to'])}"
                        + (",'g')" if mode == "regex" else ")")
                    )
            else:
                raise ValueError("DATAPREP_REPLACE_MODE_INVALID")
            values[name] = target
        sql = (
            put(names[0], values[names[0]], p.get("output"))
            if len(names) == 1 and p.get("output")
            else project(values)
        )
    elif action in {"split_column", "extract_regex", "count_occurrences"}:
        _require(
            p,
            {
                "column",
                "separator",
                "regex",
                "outputs",
                "remainder",
                "pattern",
                "match",
                "case_sensitive",
                "output",
            },
            {"column"},
        )
        value = ensure(p["column"])
        if action == "split_column":
            outputs = p.get("outputs", [])
            if not outputs or len(outputs) > 50 or len(set(outputs)) != len(outputs):
                raise ValueError("DATAPREP_SPLIT_COLUMNS_INVALID")
            if p.get("regex"):
                _regex(p["regex"])
                split = f"regexp_split_to_array({value},{lit(p['regex'])})"
            else:
                split = f"string_split({value},{lit(p.get('separator'))})"
            extras = {}
            for i, name in enumerate(outputs, 1):
                term = f"list_extract({split},{i})"
                if i == len(outputs) and p.get("remainder", "last") == "last":
                    term = f"array_to_string(list_slice({split},{i},1000000),{lit(p.get('separator', ''))})"
                extras[name] = f"CASE WHEN len({split})>={i} THEN {term} ELSE NULL END"
            sql = project({}, extras=extras)
        elif action == "extract_regex":
            compiled = _regex(p.get("pattern"))
            outputs = p.get("outputs", [])
            extras = {}
            for output in outputs:
                if (
                    set(output) != {"group", "name"}
                    or type(output["group"]) is not int
                    or not 0 <= output["group"] <= compiled.groups
                ):
                    raise ValueError("DATAPREP_REGEX_GROUP_INVALID")
                extras[output["name"]] = (
                    f"CASE WHEN regexp_matches({value},{lit(p['pattern'])}) THEN regexp_extract({value},{lit(p['pattern'])},{output['group']}) ELSE NULL END"
                )
            if not extras:
                raise ValueError("DATAPREP_REGEX_OUTPUT_REQUIRED")
            sql = project({}, extras=extras)
        else:
            pattern = p.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                raise ValueError("DATAPREP_PATTERN_EMPTY")
            if not p.get("case_sensitive", True):
                value, pattern = f"lower({value})", pattern.lower()
            if p.get("match", "substring") == "regex":
                _regex(pattern)
                term = f"len(regexp_extract_all({value},{lit(pattern)}))"
            else:
                term = (
                    f"(length({value})-length(replace({value},{lit(pattern)},'')))/{len(pattern)}"
                )
            sql = project({}, extras={p["output"]: term})
    elif action in {"negate_boolean", "mask"}:
        _require(p, {"columns", "keep_first", "keep_last", "char"}, {"columns"})
        names = _names(p["columns"], columns)
        if action == "negate_boolean":
            sql = project({n: f"NOT {q(n)}" for n in names})
        else:
            first, last = p.get("keep_first", 0), p.get("keep_last", 0)
            char = p.get("char", "*")
            if (
                type(first) is not int
                or type(last) is not int
                or min(first, last) < 0
                or max(first, last) > 10000
                or len(char) != 1
            ):
                raise ValueError("DATAPREP_MASK_INVALID")
            sql = project(
                {
                    n: f"substr({q(n)},1,{first}) || repeat({lit(char)},greatest(0,length({q(n)})-{first}-{last})) || {'right(' + q(n) + ',' + str(last) + ')' if last else chr(39) + chr(39)}"
                    for n in names
                }
            )
    elif action == "bin_numeric":
        _require(p, {"column", "breaks", "labels", "output"}, {"column", "breaks", "output"})
        value = ensure(p["column"])
        breaks = p["breaks"]
        if (
            not isinstance(breaks, list)
            or len(breaks) < 2
            or any(type(v) not in {int, float} for v in breaks)
            or any(a >= b for a, b in zip(breaks, breaks[1:]))
        ):
            raise ValueError("DATAPREP_BINS_INVALID")
        labels = p.get("labels") or [f"[{a};{b}[" for a, b in zip(breaks, breaks[1:])]
        if len(labels) != len(breaks) - 1:
            raise ValueError("DATAPREP_BIN_LABELS_INVALID")
        cases = [
            f"WHEN {value}>={lit(a)} AND {value}<{lit(b)} THEN {lit(label)}"
            for a, b, label in zip(breaks, breaks[1:], labels)
        ]
        sql = project({}, extras={p["output"]: f"CASE {' '.join(cases)} ELSE NULL END"})
    elif action == "formula":
        _require(p, {"output", "expression", "position"}, {"output", "expression"})
        sql = project({}, extras={p["output"]: expression(p["expression"], columns)})
    elif action == "conditional_column":
        _require(p, {"output", "cases", "else"}, {"output", "cases"})
        cases = []
        for case in p["cases"]:
            _require(case, {"when", "then"}, {"when", "then"})
            cases.append(f"WHEN {expression(case['when'], columns)} THEN {lit(case['then'])}")
        if not cases:
            raise ValueError("DATAPREP_CASES_REQUIRED")
        sql = project(
            {}, extras={p["output"]: f"CASE {' '.join(cases)} ELSE {lit(p.get('else'))} END"}
        )
    elif action == "cast":
        _require(p, {"columns", "column", "to", "type", "on_error", "float_to_int"})
        names = _names(p.get("columns") or [p.get("column")], columns)
        target = str(p.get("to", p.get("type", ""))).lower()
        types = {
            "integer": "INTEGER",
            "bigint": "BIGINT",
            "double": "DOUBLE",
            "text": "VARCHAR",
            "varchar": "VARCHAR",
            "boolean": "BOOLEAN",
            "date": "DATE",
            "timestamp": "TIMESTAMP",
            "timestamp_tz": "TIMESTAMPTZ",
            "float": "DOUBLE",
            "decimal": "DECIMAL(38,6)",
        }
        if re.fullmatch(r"decimal\((\d+),(\d+)\)", target):
            precision, scale = map(int, re.findall(r"\d+", target))
            if not 1 <= precision <= 38 or not 0 <= scale <= precision:
                raise ValueError("DATAPREP_TYPE_INVALID")
            dtype = target.upper()
        else:
            dtype = types.get(target)
        if dtype is None:
            raise ValueError("DATAPREP_TYPE_INVALID")
        mode = p.get("on_error", "fail" if "column" in p else "null")
        rounding = p.get("float_to_int", "round_half_up")
        if mode not in {"null", "fail"} or rounding not in {"round_half_up", "truncate"}:
            raise ValueError("DATAPREP_CAST_MODE_INVALID")
        values = {}
        cast = "try_cast" if mode == "null" else "cast"
        for name in names:
            term = q(name)
            if dtype in {"INTEGER", "BIGINT"}:
                term = f"{'round' if rounding == 'round_half_up' else 'trunc'}({cast}({term} AS DOUBLE))"
            values[name] = f"{cast}({term} AS {dtype})"
        sql = project(values)
    elif action in {"deduplicate", "dedup"}:
        _require(p, {"columns", "keep", "order_by"})
        names = _names(p.get("columns", columns), columns)
        keep = p.get("keep", "first")
        if keep not in {"first", "last", "none"}:
            raise ValueError("DATAPREP_DEDUP_MODE_INVALID")
        partition = ",".join(q(n) for n in names)
        if keep == "none":
            sql = f"SELECT * FROM {source} QUALIFY count(*) OVER(PARTITION BY {partition})=1"
        else:
            ordering = order(p) if p.get("order_by") else ",".join(q(n) for n in columns)
            if keep == "last":
                ordering = (
                    ordering.replace(" ASC", " __REV")
                    .replace(" DESC", " ASC")
                    .replace(" __REV", " DESC")
                )
            sql = f"SELECT * FROM {source} QUALIFY row_number() OVER(PARTITION BY {partition} ORDER BY {ordering})=1"
    elif action == "sort":
        _require(p, {"keys", "columns", "descending"})
        from app.services.dataops.operations import ordering

        items = p.get("keys") or [
            {"column": n, "direction": "desc" if p.get("descending", False) else "asc"}
            for n in p.get("columns", [])
        ]
        sql = f"SELECT * FROM {source} ORDER BY {ordering(items, columns)}"
    elif action in {"round", "math"}:
        _require(p, {"columns", "decimals", "mode", "function"}, {"columns"})
        names = _names(p["columns"], columns)
        values = {}
        if action == "math":
            function = p.get("function")
            if function not in {"abs", "sqrt", "ln", "log10", "exp", "sign", "ceil", "floor"}:
                raise ValueError("DATAPREP_MATH_FUNCTION_INVALID")
            values = {n: f"{function}({q(n)})" for n in names}
        else:
            decimals = p.get("decimals", 0)
            mode = p.get("mode", "half_up")
            if (
                type(decimals) is not int
                or not -12 <= decimals <= 12
                or mode not in {"half_up", "half_even", "floor", "ceil", "truncate"}
            ):
                raise ValueError("DATAPREP_ROUND_MODE_INVALID")
            for n in names:
                if mode in {"half_up", "half_even"}:
                    term = f"{'round' if mode == 'half_up' else 'round_even'}({q(n)},{decimals})"
                else:
                    term = f"{'trunc' if mode == 'truncate' else mode}({q(n)}*pow(10,{decimals}))/pow(10,{decimals})"
                values[n] = term
        sql = project(values)
    elif action in {
        "extract_date_parts",
        "date_diff",
        "date_add",
        "truncate_date",
        "convert_timezone",
    }:
        _require(
            p,
            {"column", "start", "end", "unit", "amount", "output", "parts", "naming", "from", "to"},
        )
        units = {
            "microsecond",
            "millisecond",
            "second",
            "minute",
            "hour",
            "day",
            "week",
            "month",
            "quarter",
            "year",
        }
        if action == "extract_date_parts":
            value = ensure(p.get("column"))
            parts = p.get("parts", [])
            supported = {
                "year": "year",
                "quarter": "quarter",
                "month": "month",
                "iso_week": "week",
                "day": "day",
                "iso_day_of_week": "isodow",
                "day_of_year": "doy",
                "hour": "hour",
                "minute": "minute",
                "second": "second",
                "epoch_seconds": "epoch",
            }
            if (
                not parts
                or len(set(parts)) != len(parts)
                or any(part not in supported for part in parts)
            ):
                raise ValueError("DATAPREP_DATE_PART_INVALID")
            naming = p.get("naming", "{column}_{part}")
            sql = project(
                {},
                extras={
                    naming.replace("{column}", p["column"]).replace(
                        "{part}", part
                    ): f"date_part({lit(supported[part])},{value})"
                    for part in parts
                },
            )
        elif action == "convert_timezone":
            from zoneinfo import ZoneInfo

            try:
                ZoneInfo(p.get("from"))
                ZoneInfo(p.get("to"))
            except (ValueError, TypeError, KeyError):
                raise ValueError("DATAPREP_TIMEZONE_INVALID") from None
            value = ensure(p.get("column"))
            term = f"timezone({lit(p['to'])},timezone({lit(p['from'])},{value}))"
            sql = put(p["column"], term, p.get("output"))
        else:
            unit = p.get("unit")
            if unit not in units:
                raise ValueError("DATAPREP_DATE_UNIT_INVALID")
            if action == "date_diff":
                start, end = ensure(p.get("start")), ensure(p.get("end"))
                sql = project({}, extras={p["output"]: f"date_sub({lit(unit)},{start},{end})"})
            else:
                value = ensure(p.get("column"))
                if action == "date_add":
                    amount = p.get("amount")
                    if type(amount) is not int or abs(amount) > 1000000:
                        raise ValueError("DATAPREP_DATE_AMOUNT_INVALID")
                    term = f"({value}+({amount} * INTERVAL '1 {unit}'))"
                else:
                    term = f"date_trunc({lit(unit)},{value})"
                sql = put(p["column"], term, p.get("output"))
    elif action == "scale":
        _require(p, {"columns", "method", "output_suffix"}, {"columns", "method"})
        names = _names(p["columns"], columns)
        method = p["method"]
        if method not in {"zscore", "minmax", "robust"}:
            raise ValueError("DATAPREP_SCALE_METHOD_INVALID")
        summaries = []
        terms = {}
        for i, n in enumerate(names):
            lo = (
                f"min({q(n)})"
                if method == "minmax"
                else f"avg({q(n)})"
                if method == "zscore"
                else f"median({q(n)})"
            )
            width = (
                f"max({q(n)})-min({q(n)})"
                if method == "minmax"
                else f"stddev_samp({q(n)})"
                if method == "zscore"
                else f"quantile_cont({q(n)},0.75)-quantile_cont({q(n)},0.25)"
            )
            summaries.extend(
                [
                    lo + " AS " + q("__scale_lo_" + str(i)),
                    width + " AS " + q("__scale_width_" + str(i)),
                ]
            )
            terms[n] = (
                f"(data.{q(n)}-agg.{q('__scale_lo_' + str(i))})/nullif(agg.{q('__scale_width_' + str(i))},0)"
            )
        summary = "SELECT " + ",".join(summaries) + f" FROM {source}"
        suffix = p.get("output_suffix")
        projection = [
            (terms[n] + " AS " + q(n) if n in terms and not suffix else "data." + q(n))
            for n in columns
        ]
        if suffix:
            new = [n + suffix for n in names]
            if any(n.casefold() in {c.casefold() for c in columns} for n in new):
                raise ValueError("DATAPREP_COLUMN_COLLISION")
            projection.extend(terms[n] + " AS " + q(n + suffix) for n in names)
            columns.extend(new)
        sql = "SELECT " + ",".join(projection) + f" FROM {source} CROSS JOIN ({summary}) agg"
    elif action == "window":
        _require(
            p,
            {"output", "function", "column", "partition_by", "order_by", "offset", "size", "n"},
            {"output", "function"},
        )
        function = p["function"]
        partitions = p.get("partition_by", [])
        if partitions:
            _names(partitions, columns)
        window = (
            ("PARTITION BY " + ",".join(q(n) for n in partitions) + " " if partitions else "")
            + "ORDER BY "
            + order(p)
        )
        column = ensure(p["column"]) if p.get("column") else None
        if function in {"row_number", "rank", "dense_rank", "percent_rank"}:
            term = f"{function}()"
        elif function in {"lag", "lead"}:
            offset = p.get("offset", 1)
            if type(offset) is not int or not 1 <= offset <= 10000:
                raise ValueError("DATAPREP_OFFSET_INVALID")
            term = f"{function}({column},{offset})"
        elif function == "ntile":
            n = p.get("n", p.get("size", 2))
            if type(n) is not int or not 1 <= n <= 10000:
                raise ValueError("DATAPREP_NTILE_INVALID")
            term = f"ntile({n})"
        elif function in {"first_value", "last_value"}:
            term = f"{function}({column})"
        elif function in {
            "cumulative_sum",
            "cumulative_mean",
            "cumulative_count",
            "moving_mean",
            "moving_sum",
        }:
            func = {
                "cumulative_sum": "sum",
                "cumulative_mean": "avg",
                "cumulative_count": "count",
                "moving_mean": "avg",
                "moving_sum": "sum",
            }[function]
            term = f"{func}({column or '*'})"
            if function.startswith("moving"):
                size = p.get("size")
                if type(size) is not int or not 1 <= size <= 100000:
                    raise ValueError("DATAPREP_WINDOW_SIZE_INVALID")
                window += f" ROWS BETWEEN {size - 1} PRECEDING AND CURRENT ROW"
            else:
                window += " ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW"
        else:
            raise ValueError("DATAPREP_WINDOW_FUNCTION_INVALID")
        if "None" in term:
            raise ValueError("DATAPREP_COLUMN_REQUIRED")
        sql = project({}, extras={p["output"]: f"{term} OVER({window})"})
    else:
        raise ValueError("DATAPREP_STEP_UNSUPPORTED")
    return sql, columns
