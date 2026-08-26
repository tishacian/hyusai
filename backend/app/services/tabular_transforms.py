"""SQL transforms over datasets: duckdb in the worker, no server, no extension.

Why duckdb and not a warehouse
------------------------------
Datasets already live as Parquet in the ObjectStore, which is the lakehouse
shape duckdb is built for: it reads Parquet natively, and it brings the
analytics SQL a telecom demo needs (``ASOF JOIN``, ``time_bucket``, window
functions) without provisioning anything. The engine runs in the Celery worker
process for the length of one node.

Isolation posture
-----------------
Author-written SQL is untrusted, so three defences stack:

1. **Statement validation** — one read-only statement only. ``ATTACH``,
   ``COPY``, ``INSTALL``, ``PRAGMA``, DDL and DML are refused before duckdb
   ever sees the text.
2. **Eager loading, then a sealed filesystem** — inputs are materialized into
   duckdb tables first, after which local filesystem access is switched off.
   A statement like ``SELECT * FROM read_csv('/etc/passwd')`` therefore fails
   at the engine level even if validation somehow let it through.
3. **Budgets** — memory, thread count and a result row cap, so one query
   cannot take the worker down.

Views are named for the author, not for the plumbing: a single upstream dataset
is always ``input``, and every source is additionally addressable by its
snake_case slug.
"""

from __future__ import annotations

import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tabular import TabularDataset
from app.services.tabular_datasets import (
    TabularError,
    dataset_reference,
    materialize,
    profile_frame,
    register_frame,
    resolve_dataset_ref,
    slugify,
)

logger = get_logger(__name__)

SQL_TRANSFORM_SKILL_SLUG = "sql_transform_v1"
POLARS_TRANSFORM_SKILL_SLUG = "polars_transform_v1"
DBT_TRANSFORM_SKILL_SLUG = "dbt_transform_v1"
TRANSFORM_SKILL_SLUGS = frozenset(
    {SQL_TRANSFORM_SKILL_SLUG, POLARS_TRANSFORM_SKILL_SLUG, DBT_TRANSFORM_SKILL_SLUG}
)

_VIEW_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
# Statement keywords that would escape a read-only query. Checked as whole
# words anywhere in the statement, since a CTE or subquery can hide one.
_FORBIDDEN_TOKENS = frozenset(
    {
        "attach",
        "detach",
        "copy",
        "export",
        "import",
        "install",
        "load",
        "pragma",
        "call",
        "create",
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "vacuum",
        "checkpoint",
        "grant",
        "revoke",
        "set",
        "reset",
    }
)
# Table functions that would reach the filesystem or the network. The sealed
# filesystem also blocks these, but refusing them up front gives the author a
# readable error instead of an engine stack trace.
_FORBIDDEN_FUNCTIONS = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "read_ndjson",
        "read_text",
        "read_blob",
        "glob",
        "parquet_scan",
        "csv_scan",
        "sniff_csv",
        "postgres_scan",
        "mysql_scan",
        "sqlite_scan",
        "iceberg_scan",
        "delta_scan",
        "httpfs",
    }
)
_STARTS_READ_ONLY = ("select", "with", "from", "table", "values", "describe", "summarize")


@dataclass(slots=True)
class TransformSource:
    """One dataset made addressable to the author's SQL under ``view``."""

    view: str
    dataset: TabularDataset


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _strip_sql_noise(sql: str) -> str:
    """Remove comments and string/identifier literals for keyword scanning.

    Keyword checks must not fire on a literal (``WHERE label = 'delete me'``),
    and must not miss a keyword hidden after a comment.
    """

    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    without_line = re.sub(r"--[^\n]*", " ", without_block)
    without_strings = re.sub(r"'(?:''|[^'])*'", "''", without_line)
    return re.sub(r'"(?:""|[^"])*"', '""', without_strings)


def _split_statements(scrubbed: str) -> list[str]:
    return [part.strip() for part in scrubbed.split(";") if part.strip()]


def validate_sql(sql: Any) -> str:
    """Return the statement, or raise with a reason the author can act on."""

    text = str(sql or "").strip()
    if not text:
        raise TabularError(
            code="SQL_EMPTY", message="Write a SELECT statement to run."
        )
    limit = int(settings.tabular_sql_max_chars)
    if len(text) > limit:
        raise TabularError(
            code="SQL_TOO_LONG",
            message=f"The statement exceeds {limit:,} characters.",
        )
    scrubbed = _strip_sql_noise(text)
    statements = _split_statements(scrubbed)
    if len(statements) > 1:
        raise TabularError(
            code="SQL_MULTIPLE_STATEMENTS",
            message="Run a single statement: a transform produces one table.",
        )
    if not statements:
        raise TabularError(
            code="SQL_EMPTY", message="Write a SELECT statement to run."
        )
    # Keywords first: "DROP TABLE x" deserves "DROP is not allowed", which is
    # more actionable than the generic read-only refusal below.
    words = set(re.findall(r"[a-z_][a-z0-9_]*", scrubbed.lower()))
    forbidden = sorted(words & _FORBIDDEN_TOKENS)
    if forbidden:
        raise TabularError(
            code="SQL_FORBIDDEN_KEYWORD",
            message=(
                f"'{forbidden[0].upper()}' is not allowed: a transform reads its "
                "inputs and returns rows."
            ),
            details={"keywords": forbidden},
        )
    head = statements[0].lstrip("( \t\n").split(None, 1)[0].lower()
    if head not in _STARTS_READ_ONLY:
        raise TabularError(
            code="SQL_NOT_READ_ONLY",
            message="Only read-only statements are allowed (SELECT, WITH, FROM).",
            details={"statement": head[:40]},
        )
    functions = sorted(
        name
        for name in re.findall(r"([a-z_][a-z0-9_]*)\s*\(", scrubbed.lower())
        if name in _FORBIDDEN_FUNCTIONS
    )
    if functions:
        raise TabularError(
            code="SQL_FORBIDDEN_FUNCTION",
            message=(
                f"'{functions[0]}' is not allowed: query the declared inputs "
                "instead of reading files."
            ),
            details={"functions": functions},
        )
    return text


def view_name_for(label: str, taken: Iterable[str]) -> str:
    """A duckdb-safe, author-readable view name derived from a dataset name."""

    candidate = slugify(label, fallback="input").replace("-", "_")[:62]
    if not candidate or not _VIEW_NAME_RE.match(candidate):
        candidate = "input"
    used = set(taken)
    if candidate not in used:
        return candidate
    for suffix in range(2, 100):
        alternative = f"{candidate}_{suffix}"[:63]
        if alternative not in used:
            return alternative
    return f"input_{uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _dataset_refs_in(payload: Any) -> list[Any]:
    """Collect dataset references from a node payload, in a stable order.

    Upstream nodes emit `dataset_reference()` envelopes, and a flow may nest
    them under any key, so both a bare envelope and one level of nesting are
    accepted. Order follows the payload's key order, which is the order the
    author wired the edges.
    """

    refs: list[Any] = []
    if isinstance(payload, dict):
        if payload.get("dataset_id") or payload.get("dataset_slug"):
            refs.append(payload)
        for key, value in payload.items():
            if key.startswith("_"):
                continue
            if isinstance(value, dict) and (
                value.get("dataset_id") or value.get("slug") or value.get("dataset_slug")
            ):
                refs.append(value)
            elif isinstance(value, list):
                refs.extend(
                    item
                    for item in value
                    if isinstance(item, dict) and item.get("dataset_id")
                )
    return refs


def resolve_sources(
    db: DBSession,
    *,
    workspace_id: str,
    payload: dict[str, Any] | None = None,
    declared: Iterable[dict[str, Any]] | None = None,
) -> list[TransformSource]:
    """Resolve the tables a transform can read, named for the author.

    ``declared`` sources (pinned on the node) come first and keep their author
    chosen view name; upstream payload datasets follow. A single source is
    always reachable as ``input``, whatever its slug, so a one-input transform
    has a name the author can type without looking it up.
    """

    sources: list[TransformSource] = []
    names: list[str] = []

    for entry in declared or []:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("dataset_id") or entry.get("dataset_slug") or entry.get("slug")
        if not ref:
            continue
        dataset = resolve_dataset_ref(
            db,
            workspace_id=workspace_id,
            ref=(
                {"dataset_id": entry["dataset_id"]}
                if entry.get("dataset_id")
                else {"slug": str(ref)}
            ),
        )
        requested = str(entry.get("view") or entry.get("name") or dataset.slug)
        view = view_name_for(requested, names)
        names.append(view)
        sources.append(TransformSource(view=view, dataset=dataset))

    seen_ids = {source.dataset.id for source in sources}
    for ref in _dataset_refs_in(payload):
        dataset = resolve_dataset_ref(db, workspace_id=workspace_id, ref=ref)
        if dataset.id in seen_ids:
            continue
        seen_ids.add(dataset.id)
        view = view_name_for(dataset.slug, names)
        names.append(view)
        sources.append(TransformSource(view=view, dataset=dataset))

    if not sources:
        raise TabularError(
            code="TRANSFORM_NO_INPUT",
            message=(
                "Connect a dataset upstream or pin one on the node before running "
                "the transform."
            ),
        )
    return sources


def source_catalog(sources: Iterable[TransformSource]) -> list[dict[str, Any]]:
    """Editor-facing catalog: what the author can type, with its columns.

    This is what drives schema-aware autocompletion, so it must describe the
    views as the SQL sees them, aliases included.
    """

    catalog: list[dict[str, Any]] = []
    for index, source in enumerate(sources):
        aliases = [f"input_{index + 1}"]
        if index == 0:
            aliases.append("input")
        catalog.append(
            {
                "view": source.view,
                "aliases": [alias for alias in aliases if alias != source.view],
                "dataset_id": source.dataset.id,
                "name": source.dataset.name,
                "rows": int(source.dataset.row_count or 0),
                "columns": list(source.dataset.schema_json or []),
            }
        )
    return catalog


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def execute_sql(
    sources: list[TransformSource],
    sql: str,
    *,
    row_limit: int | None = None,
    truncate: bool = False,
) -> Any:
    """Run one validated statement over the sources and return a polars frame.

    ``truncate`` distinguishes the two callers: a workshop preview wants the
    first N rows, while a persisted transform must refuse an oversized result
    rather than silently store a partial table.
    """

    import duckdb
    import polars as pl

    validated = validate_sql(sql)
    cap = int(row_limit or settings.tabular_transform_max_rows)
    with tempfile.TemporaryDirectory(prefix="agentium-sql-") as tmp:
        root = Path(tmp)
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute("SET threads TO 2")
            connection.execute("SET memory_limit = '1GB'")
            for index, source in enumerate(sources):
                local = materialize(source.dataset, root / f"{source.view}.parquet")
                # Eager load: after this loop the filesystem is sealed, so the
                # author's statement cannot reach any path.
                connection.execute(
                    f'CREATE TABLE "{source.view}" AS '
                    f"SELECT * FROM read_parquet('{_quote_path(local)}')"
                )
                connection.execute(
                    f'CREATE VIEW "input_{index + 1}" AS SELECT * FROM "{source.view}"'
                )
                if index == 0 and source.view != "input":
                    connection.execute(
                        f'CREATE VIEW "input" AS SELECT * FROM "{source.view}"'
                    )
            _seal_filesystem(connection)
            try:
                # One row past the cap so an oversized result is detectable
                # rather than silently trimmed.
                relation = connection.sql(validated).limit(cap if truncate else cap + 1)
                table = relation.arrow()
            except TabularError:
                raise
            except Exception as exc:  # noqa: BLE001 - the engine message is the value
                raise TabularError(
                    code="SQL_EXECUTION_FAILED",
                    message=_readable_engine_error(exc),
                    details=_positioned_failure(connection, validated, exc),
                ) from exc
        finally:
            connection.close()
    frame = pl.from_arrow(table)
    if isinstance(frame, pl.Series):  # pragma: no cover - arrow always yields a table
        frame = frame.to_frame()
    if not truncate and frame.height > cap:
        raise TabularError(
            code="SQL_RESULT_TOO_LARGE",
            message=f"The result exceeds {cap:,} rows; narrow the query.",
            details={"row_limit": cap},
        )
    if frame.width == 0:
        raise TabularError(
            code="SQL_NO_COLUMNS", message="The statement returned no columns."
        )
    return frame


def _seal_filesystem(connection: Any) -> None:
    """Switch off external and local access once the inputs are loaded.

    Order matters, and the wrong way round is quiet: the inputs have already
    been read from disk by the time this runs, and once ``LocalFileSystem`` is
    disabled the *next* ``SET`` raises — duckdb touches the filesystem while
    applying it — so only one of the two guards ends up on and the log says
    "unsupported" as if the engine were old. The half left standing is the
    weaker one: ``disabled_filesystems = 'LocalFileSystem'`` says nothing about
    an httpfs or S3 filesystem, so an already-loaded extension could still
    reach the network. ``enable_external_access = false`` is the one that closes
    remote reads, attaches and extension installs, so it goes first.
    """

    for statement in (
        "SET enable_external_access = false",
        "SET disabled_filesystems = 'LocalFileSystem'",
    ):
        try:
            connection.execute(statement)
        except Exception as exc:  # noqa: BLE001 - older engines lack one or the other
            # The reason travels with the warning. Without it the line reads as
            # "your duckdb is too old" whichever the cause, which is how the
            # ordering above stayed wrong without anyone noticing.
            logger.warning(
                "tabular_transforms: seal unsupported",
                statement=statement,
                error=str(exc).splitlines()[0][:200],
            )


_ERROR_LINE = re.compile(r"^LINE (\d+):[ ]?(.*)$")


def _error_position(exc: Exception, statement: str) -> dict[str, Any] | None:
    """Where in the author's statement duckdb stopped, if it says.

    duckdb already knows: every parser, binder, catalog and conversion error
    carries a ``LINE n:`` echo and a ``^`` under the offending token. Throwing
    that away and keeping only the sentence is what makes an editor error a
    scavenger hunt — the author reads "Referenced column not found" and then
    counts the lines by hand.

    The echo is checked against ``statement`` before the coordinate is trusted,
    and that check is the point rather than a formality: duckdb's relational API
    reports positions against its own *rewritten* SQL, so an error in
    ``WHERE a > 'x'`` can come back measured against
    ``SELECT a FROM "input" WHERE (a > 'x') LIMIT 5`` — a coordinate that would
    move the author's cursor to a place in a text they never wrote. A position
    that does not line up with what they typed is worse than none, so it is
    dropped.
    """

    lines = statement.splitlines()
    line_no: int | None = None
    source = ""
    prefix = 0
    for raw in str(exc).splitlines():
        matched = _ERROR_LINE.match(raw.strip())
        if matched is not None:
            line_no = int(matched.group(1))
            source = matched.group(2)
            prefix = len(raw) - len(source)
            continue
        if line_no is None:
            continue
        if not (1 <= line_no <= len(lines)) or lines[line_no - 1].rstrip() != source.rstrip():
            # The echo is of some other text than the author's. See above.
            return None
        if set(raw.strip()) == {"^"}:
            # The caret sits under the token, indented to match the echo above.
            return {
                "position": {
                    "line": line_no,
                    "column": max(1, raw.index("^") - prefix + 1),
                    "excerpt": source[:200],
                }
            }
    return None


def _positioned_failure(
    connection: Any, statement: str, exc: Exception
) -> dict[str, Any] | None:
    """The coordinate for a refused statement, asking twice if the first is mute.

    The relational API (``connection.sql``) is what runs the author's statement,
    because it composes the row cap without string surgery. But it drops the
    ``LINE n:`` echo for exactly the two mistakes authors make most — a column
    that does not exist and a table that does not exist — so on failure the
    statement is offered once more to ``execute``, whose message keeps it.

    Re-running is safe here and nowhere else: the statement is already validated
    read-only, the filesystem is sealed by this point, and it has just failed,
    so there is no result to lose and nothing to write twice.
    """

    found = _error_position(exc, statement)
    if found is not None:
        return found
    try:
        connection.execute(statement)
    except Exception as retried:  # noqa: BLE001 - the message is the whole point
        return _error_position(retried, statement)
    return None


def _readable_engine_error(exc: Exception) -> str:
    """First meaningful line of a duckdb error, which is the part authors read."""

    text = str(exc).strip()
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:400]
    return "The statement could not be executed."


def preview_sql(
    db: DBSession,
    *,
    workspace_id: str,
    sql: str,
    declared: Iterable[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    row_limit: int = 50,
) -> dict[str, Any]:
    """Run a transform without persisting it — the workshop's Test button.

    Returns the same profile shape the dataset pages render, so the preview
    table in the editor is literally the table the dataset will show.
    """

    sources = resolve_sources(
        db, workspace_id=workspace_id, payload=payload, declared=declared
    )
    started = time.monotonic()
    frame = execute_sql(
        sources, sql, row_limit=max(1, int(row_limit)), truncate=True
    )
    elapsed_ms = (time.monotonic() - started) * 1000
    profile = profile_frame(frame)
    return {
        "row_count": profile["row_count"],
        "column_count": profile["column_count"],
        "schema": profile["schema"],
        "preview": profile["preview"],
        "stats": profile["stats"],
        "duration_ms": round(elapsed_ms, 1),
        "sources": source_catalog(sources),
    }


def run_sql_transform(
    db: DBSession,
    *,
    workspace_id: str,
    sql: str,
    output_name: str,
    declared: Iterable[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
    produced_by: str = SQL_TRANSFORM_SKILL_SLUG,
) -> dict[str, Any]:
    """Execute a transform and persist its result as a new dataset version."""

    sources = resolve_sources(
        db, workspace_id=workspace_id, payload=payload, declared=declared
    )
    started = time.monotonic()
    frame = execute_sql(sources, sql)
    elapsed_ms = (time.monotonic() - started) * 1000
    dataset = register_frame(
        db,
        workspace_id=workspace_id,
        name=output_name or "sql result",
        frame=frame,
        source="transform",
        produced_by=produced_by,
        parent_ids=[source.dataset.id for source in sources],
        run_id=run_id,
        node_id=node_id,
        lineage={
            "engine": "duckdb",
            "sql": str(sql)[:4000],
            "sources": [
                {"view": source.view, "dataset_id": source.dataset.id}
                for source in sources
            ],
            "duration_ms": round(elapsed_ms, 1),
        },
    )
    db.commit()
    logger.info(
        "tabular_transforms: sql settled",
        dataset_id=dataset.id,
        rows=dataset.row_count,
        duration_ms=round(elapsed_ms, 1),
    )
    return {
        **dataset_reference(dataset),
        "duration_ms": round(elapsed_ms, 1),
        "sources": [source.view for source in sources],
    }


__all__ = [
    "DBT_TRANSFORM_SKILL_SLUG",
    "POLARS_TRANSFORM_SKILL_SLUG",
    "SQL_TRANSFORM_SKILL_SLUG",
    "TRANSFORM_SKILL_SLUGS",
    "TransformSource",
    "execute_sql",
    "preview_sql",
    "resolve_sources",
    "run_sql_transform",
    "source_catalog",
    "validate_sql",
    "view_name_for",
]
