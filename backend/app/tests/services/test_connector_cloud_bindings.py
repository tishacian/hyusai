"""Cloud query binding never interprets a bound value as another placeholder."""

import pytest
import sqlglot

from app.services.connectors.adapters.sql import AdapterError
from app.services.connectors.adapters.sql_cloud import _bind


@pytest.mark.parametrize(
    "dialect,parser",
    [("snowflake", "snowflake"), ("bigquery", "bigquery"), ("databricks_sql", "databricks")],
)
def test_binding_does_not_rescan_placeholder_inside_untrusted_literal(dialect, parser):
    first, second = "%s' OR 1=1;--", "x' ; DROP TABLE secret; --"
    query = _bind("SELECT %s AS a, %s AS b", [first, second], dialect)
    parsed = sqlglot.parse(query, dialect=parser)
    assert len(parsed) == 1
    assert [cast.this.this.this for cast in parsed[0].expressions] == [first, second]


def test_placeholder_in_quoted_identifier_or_literal_is_not_bound():
    assert (
        _bind("SELECT \"%s\", 'literal%s', %s", ["bound"]) == "SELECT \"%s\", 'literal%s', 'bound'"
    )


@pytest.mark.parametrize(
    "sql,args", [("SELECT %s", []), ("SELECT 1", ["extra"]), ('SELECT "unterminated', [])]
)
def test_placeholder_count_and_template_quoting_fail_closed(sql, args):
    with pytest.raises(AdapterError, match="CONNECTOR_PARAMETERS_INVALID"):
        _bind(sql, args)
