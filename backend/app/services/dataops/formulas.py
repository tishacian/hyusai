"""Formula shims and explicit column aggregates shared by preview and execution."""

import sqlglot
from sqlglot import exp

COL_AGGREGATES = {
    "col_mean": "avg",
    "col_sum": "sum",
    "col_min": "min",
    "col_max": "max",
    "col_std": "stddev_samp",
    "col_median": "median",
    "col_count": "count",
}
_INITCAP_DELIMITERS = sqlglot.parse_one("initcap('')", read="duckdb").expression


def apply_shims(tree):
    def rewrite(node):
        if not isinstance(node, exp.Func):
            return node
        name = node.name.lower() if isinstance(node, exp.Anonymous) else node.sql_name().lower()
        args = [a for a in node.iter_expressions()]
        if isinstance(node, exp.Initcap):
            # sqlglot supplies a second, synthetic delimiter literal for DuckDB.
            # The portable initcap contract capitalizes space-delimited words.
            if node.expression != _INITCAP_DELIMITERS:
                raise ValueError("DATAPREP_FUNCTION_ARITY")
            args = [node.this]
        values = [a.sql(dialect="duckdb") for a in args]
        if name in COL_AGGREGATES:
            if len(args) != 1 or not isinstance(args[0], exp.Column):
                raise ValueError("DATAPREP_COLUMN_AGGREGATE_ARGUMENT")
        sql = None
        if name in {"remove_accents", "initcap", "iso_week", "iso_day_of_week"}:
            if len(values) != 1:
                raise ValueError("DATAPREP_FUNCTION_ARITY")
            value = values[0]
            sql = {
                "remove_accents": f"strip_accents({value})",
                "initcap": f"array_to_string(list_transform(string_split(lower({value}),' '),word -> upper(left(word,1)) || substring(word,2)),' ')",
                "iso_week": f"date_part('week',{value})",
                "iso_day_of_week": f"date_part('isodow',{value})",
            }[name]
        elif name in {"parse_date", "format_date"}:
            if len(values) != 2:
                raise ValueError("DATAPREP_FUNCTION_ARITY")
            sql = (
                f"try_strptime({values[0]},{values[1]})"
                if name == "parse_date"
                else f"strftime({values[0]},{values[1]})"
            )
        elif name == "datediff":
            unit = node.args.get("unit")
            from app.services.dataops.compiler import literal

            sql = f"date_sub({literal(unit.name.lower())},{node.expression.sql(dialect='duckdb')},{node.this.sql(dialect='duckdb')})"
        elif name == "regexp_extract":
            from app.services.dataops.steps import _regex

            pattern = node.args.get("expression")
            if not isinstance(pattern, exp.Literal) or not pattern.is_string:
                raise ValueError("DATAPREP_REGEX_LITERAL_REQUIRED")
            _regex(pattern.this)
            value = node.this.sql(dialect="duckdb")
            sql = f"CASE WHEN regexp_matches({value},{pattern.sql(dialect='duckdb')}) THEN {node.sql(dialect='duckdb')} ELSE NULL END"
        elif name == "split_part":
            value, delimiter, part = (
                node.args.get(key) for key in ("this", "delimiter", "part_index")
            )
            if value is not None and delimiter is not None and part is not None:
                sql = f"list_extract(string_split({value.sql(dialect='duckdb')},{delimiter.sql(dialect='duckdb')}),{part.sql(dialect='duckdb')})"
        return sqlglot.parse_one(sql, read="duckdb") if sql else node

    return tree.transform(rewrite)


def formula_source(text, columns, source):
    """Lift col_* into a CROSS JOIN, never an unpartitioned window."""
    from app.services.dataops.compiler import expression, quote

    tree = sqlglot.parse_one(expression(text, columns), read="duckdb")
    aggregates = {}

    def lift(node):
        if isinstance(node, exp.Anonymous) and node.name.lower() in COL_AGGREGATES:
            key = node.sql(dialect="duckdb")
            if key not in aggregates:
                alias = f"__dp_col_agg_{len(aggregates)}"
                aggregates[key] = (
                    alias,
                    COL_AGGREGATES[node.name.lower()]
                    + "("
                    + node.expressions[0].sql(dialect="duckdb")
                    + ")",
                )
            return exp.column(aggregates[key][0], table="__dp_stats", quoted=True)
        return node

    tree = tree.transform(lift)
    if aggregates:
        projection = ",".join(term + " AS " + quote(alias) for alias, term in aggregates.values())
        source += f" CROSS JOIN (SELECT {projection} FROM {source}) AS __dp_stats"
    return tree.sql(dialect="duckdb"), source


def function_catalog():
    groups = {
        "number": "abs round floor ceil trunc sqrt cbrt power exp ln log10 log2 sign mod greatest least pi sin cos tan asin acos atan atan2",
        "text": "lower upper trim ltrim rtrim length substr left right replace concat concat_ws lpad rpad strpos starts_with ends_with contains regexp_matches regexp_extract regexp_replace split_part remove_accents initcap",
        "date": "date_trunc date_part date_diff date_add make_date parse_date format_date year month day hour iso_week iso_day_of_week",
        "conditional": "coalesce nullif ifnull if cast try_cast",
        "aggregate": "col_mean col_sum col_min col_max col_std col_median col_count",
    }
    arities = {
        "pi": [0, 0],
        "round": [1, 2],
        "trunc": [1, 2],
        "power": [2, 2],
        "mod": [2, 2],
        "atan2": [2, 2],
        "greatest": [2, None],
        "least": [2, None],
        "coalesce": [2, None],
        "concat": [1, None],
        "concat_ws": [2, None],
        "substr": [2, 3],
        "left": [2, 2],
        "right": [2, 2],
        "replace": [3, 3],
        "lpad": [2, 3],
        "rpad": [2, 3],
        "strpos": [2, 2],
        "starts_with": [2, 2],
        "ends_with": [2, 2],
        "contains": [2, 2],
        "regexp_matches": [2, 3],
        "regexp_extract": [2, 3],
        "regexp_replace": [3, 4],
        "split_part": [3, 3],
        "date_trunc": [2, 2],
        "date_part": [2, 2],
        "date_diff": [3, 3],
        "date_add": [3, 3],
        "make_date": [3, 3],
        "parse_date": [2, 2],
        "format_date": [2, 2],
        "nullif": [2, 2],
        "ifnull": [2, 2],
        "if": [3, 3],
        "cast": [2, 2],
        "try_cast": [2, 2],
    }
    return [
        {
            "name": name,
            "group": group,
            "arity": arities.get(name, [1, 1]),
            "label_key": f"flow.dataprep.function.{name}.label",
            "return_rule": "native_portable",
            "arguments": "column" if group == "aggregate" else group,
        }
        for group, names in groups.items()
        for name in names.split()
    ]
