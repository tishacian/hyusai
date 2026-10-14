"""Merge a bounded increment with its last complete version inside the runner."""

import hashlib
from pathlib import Path

from app.services.connectors.adapters.sql import AdapterError, _remaining


def merge_incremental(output, directory, deadline, checkpoint, key_column):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    previous = checkpoint.get("previous_files", [])
    if not previous:
        return {**output, "deletions_captured": False, "incremental": True}
    current = directory / "data.parquet"
    files = [Path(p) for p in previous]
    if any(
        p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(directory.resolve())
        for p in files
    ):
        raise AdapterError("CONNECTOR_ARTIFACT_INVALID")
    schema = pq.read_schema(current)
    previous_schemas = [pq.read_schema(p) for p in files]
    # Empty typed streams have column names but no values from which to infer
    # types. Reuse the previous schema only for a genuinely empty null schema
    # with the exact same ordered names. Nonempty or typed drift still fails.
    if (
        output.get("row_count") == 0
        and pq.read_metadata(current).num_rows == 0
        and all(pa.types.is_null(field.type) for field in schema)
        and schema.names == previous_schemas[0].names
        and all(previous == previous_schemas[0] for previous in previous_schemas)
    ):
        schema = previous_schemas[0]
        pq.write_table(pa.Table.from_batches([], schema=schema), current, compression="zstd")
    if key_column not in schema.names or any(previous != schema for previous in previous_schemas):
        raise AdapterError("CONNECTOR_SCHEMA_CHANGED")
    key = '"' + key_column.replace('"', '""') + '"'
    cols = ", ".join('"' + name.replace('"', '""') + '"' for name in schema.names)
    # Reserved aliases exist only inside this query and cannot shadow columns.
    aliases = {"__agentium_new", "__agentium_rank"}
    if aliases.intersection(schema.names):
        raise AdapterError("CONNECTOR_SCHEMA_INVALID")
    temporary = directory / "merged.parquet"
    with duckdb.connect() as conn:
        conn.execute("SET memory_limit='512MB'")
        conn.execute("SET threads=1")
        conn.execute("SET temp_directory=?", [str(directory / "merge-spill")])
        conn.execute("SET max_temp_directory_size='4GB'")
        conn.from_parquet([str(p) for p in files]).create_view("old_data")
        conn.from_parquet(str(current)).create_view("new_data")
        query = f"SELECT {cols} FROM (SELECT *,row_number() OVER(PARTITION BY {key} ORDER BY __agentium_new DESC) AS __agentium_rank FROM (SELECT *,0 AS __agentium_new FROM old_data UNION ALL SELECT *,1 AS __agentium_new FROM new_data)) WHERE __agentium_rank=1"
        reader = conn.execute(query).fetch_record_batch(1000)
        count = 0
        with pq.ParquetWriter(temporary, reader.schema, compression="zstd") as writer:
            for batch in reader:
                _remaining(deadline)
                count += batch.num_rows
                if count > 10000000 or temporary.stat().st_size > 1024**3:
                    raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
                writer.write_batch(batch)
    temporary.replace(current)
    digest = hashlib.sha256()
    with current.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            _remaining(deadline)
            digest.update(block)
    return {
        **output,
        "row_count": count,
        "bytes": current.stat().st_size,
        "sha256": digest.hexdigest(),
        "deletions_captured": False,
        "incremental": True,
        "increment_rows": output["row_count"],
    }
