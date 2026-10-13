"""Schema selectors resolve in declared order, never against profile guesses."""

from app.services.dataops.steps import _regex


def resolve_selector(value, schema):
    names = [f["name"] for f in schema]
    if isinstance(value, list):
        result = value
    elif isinstance(value, dict):
        if set(value) - {"mode", "names", "regex", "match", "kinds", "exclude"}:
            raise ValueError("DATAPREP_SELECTOR_INVALID")
        mode = value.get("mode")
        if mode == "all":
            result = list(names)
        elif mode == "names":
            result = value.get("names", [])
        elif mode == "pattern":
            pattern = value.get("regex")
            _regex(pattern)
            match = value.get("match", "full")
            if match not in {"full", "contains"}:
                raise ValueError("DATAPREP_SELECTOR_INVALID")
            # Python's backtracking engine can hold the API's GIL on a hostile
            # pattern. DuckDB evaluates these bound names with linear-time RE2.
            import duckdb

            function = "regexp_full_match" if match == "full" else "regexp_matches"
            with duckdb.connect(config={"threads": 1, "memory_limit": "32MB"}) as conn:
                conn.execute("SET enable_external_access=false")
                conn.execute("SET lock_configuration=true")
                try:
                    result = [
                        row[0]
                        for row in conn.execute(
                            f"SELECT name FROM unnest(?) AS cols(name) WHERE {function}(name, ?)",
                            [names, pattern],
                        ).fetchall()
                    ]
                except duckdb.Error:
                    raise ValueError("DATAPREP_REGEX_INVALID") from None
        elif mode == "kinds":
            kinds = value.get("kinds")
            if (
                not isinstance(kinds, list)
                or not kinds
                or set(kinds)
                - {
                    "integer",
                    "float",
                    "number",
                    "numeric",
                    "string",
                    "text",
                    "boolean",
                    "date",
                    "datetime",
                    "timestamp",
                    "other",
                }
            ):
                raise ValueError("DATAPREP_SELECTOR_INVALID")
            accepted = set(kinds)
            if accepted & {"number", "numeric"}:
                accepted |= {"integer", "float"}
            if "text" in accepted:
                accepted.add("string")
            if "timestamp" in accepted:
                accepted.add("datetime")
            result = [f["name"] for f in schema if f.get("kind") in accepted]
        else:
            raise ValueError("DATAPREP_SELECTOR_INVALID")
        exclude = value.get("exclude", [])
        if not isinstance(exclude, list) or any(n not in names for n in exclude):
            raise ValueError("DATAPREP_COLUMN_UNKNOWN")
        result = [n for n in result if n not in exclude]
    else:
        raise ValueError("DATAPREP_SELECTOR_INVALID")
    if (
        not isinstance(result, list)
        or not result
        or any(n not in names for n in result)
        or len(result) != len(set(result))
    ):
        raise ValueError("DATAPREP_COLUMNS_INVALID")
    return list(result)


def resolve_params(params, schema):
    value = dict(params)
    for key in ("columns", "id_columns", "value_columns"):
        if key in value and isinstance(value[key], dict):
            value[key] = resolve_selector(value[key], schema)
    return value
