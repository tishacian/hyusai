"""Arrow upload ingestion and generated datasets share the bounded writer."""

from pathlib import Path

from app.core.config import settings
from app.services.dataops.storage import settle_files, write_batches
from app.services.tabular_datasets import TabularError


def register_batches(db, dataset, batches, *, schema, directory: Path, delta=None, progress=None):
    if len(schema) > settings.tabular_max_columns:
        raise TabularError(code="DATASET_TOO_WIDE", message="Too many columns.")
    count = 0

    def bounded():
        nonlocal count
        for batch in batches:
            count += batch.num_rows
            if count > settings.ml_score_streaming_max_rows:
                raise TabularError(
                    code="DATASET_TOO_MANY_ROWS", message="Ingest row budget exceeded."
                )
            yield batch

    delta = settings.dataops_write_delta_enabled if delta is None else delta
    paths = write_batches(directory, bounded(), schema=schema, delta=delta)
    if count == 0:
        raise TabularError(code="DATASET_EMPTY", message="The file has no data rows.")
    if progress is not None:
        progress("profiling", count)
    settle_files(
        db,
        dataset,
        paths,
        delta_root=directory if delta else None,
        on_profile=(lambda _: progress("writing", count)) if progress is not None else None,
    )
    if dataset.row_count != count:
        raise TabularError(
            code="DATASET_CARDINALITY_MISMATCH", message="Ingest cardinality changed."
        )
    return dataset


def ingest_arrow(db, dataset, path: Path, fmt: str, directory: Path):
    import pyarrow.csv as csv
    import pyarrow.dataset as ds

    if fmt == "csv":
        reader = csv.open_csv(
            path, read_options=csv.ReadOptions(block_size=1024**2, use_threads=False)
        )
        schema = reader.schema
    else:
        reader = ds.dataset(str(path), format="parquet").scanner(
            batch_size=settings.dataops_batch_rows,
            use_threads=False,
            batch_readahead=0,
            fragment_readahead=0,
        )
        schema = reader.projected_schema
        reader = reader.to_batches()
    from app.services.tabular_datasets import mark_step

    return register_batches(
        db,
        dataset,
        reader,
        schema=schema,
        directory=directory,
        progress=lambda step, count: mark_step(db, dataset, step, rows=count),
    )
