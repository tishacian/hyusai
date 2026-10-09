"""Pinned Parquet imports and credential-free replay of retained results."""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import Path

from app.core.config import settings
from app.services.huggingface.errors import HFError
from app.services.huggingface.storage import HubStore, safe_path

TRANSFORMATION_VERSION = "agentium-parquet-v1"
_SHA = re.compile(r"[0-9a-f]{40}")


def _split_candidates(metadata: dict, config: str, split: str) -> list[str] | None:
    """Resolve declared native data_files; never silently merge train and test."""
    files = sorted(
        row["path"]
        for row in metadata.get("files", [])
        if str(row.get("path", "")).endswith(".parquet")
    )
    card = metadata.get("card_data") or {}
    configs = card.get("configs") if isinstance(card, dict) else None
    if isinstance(configs, list) and configs:
        descriptor = next(
            (row for row in configs if isinstance(row, dict) and row.get("config_name") == config),
            None,
        )
        if descriptor is None:
            raise HFError(
                "HF_DATASET_SELECTION_INVALID",
                "The requested config is not declared by this dataset.",
            )
        mappings = descriptor.get("data_files")
    else:
        mappings = card.get("data_files") if isinstance(card, dict) else None
    if isinstance(mappings, dict):
        mappings = [{"split": key, "path": value} for key, value in mappings.items()]
    if isinstance(mappings, list) and mappings and all(isinstance(row, dict) for row in mappings):
        patterns = []
        for row in mappings:
            if row.get("split") != split:
                continue
            value = row.get("path")
            patterns.extend(value if isinstance(value, list) else [value])
        candidates = [
            path
            for path in files
            if any(isinstance(pattern, str) and fnmatchcase(path, pattern) for pattern in patterns)
        ]
        if not candidates:
            raise HFError(
                "HF_DATASET_SELECTION_INVALID",
                "The selected config and split declare no native Parquet files.",
            )
        return candidates
    # Common native exports follow data/train-*.parquet or config/train/*.parquet.
    prefixes = (
        [f"{config}/{split}", f"{config}/{split}/"]
        if config != "default"
        else [split, f"data/{split}", f"default/{split}"]
    )
    candidates = [
        path
        for path in files
        if any(
            path == prefix + ".parquet"
            or path.startswith(prefix + "-")
            or path.startswith(prefix.rstrip("/") + "/")
            for prefix in prefixes
        )
    ]
    return candidates or None


def normalize_plan(metadata: dict, selection: dict) -> dict:
    """Close every dataset input before its identity digest is computed.

    Hub conversions are deliberately refused unless the metadata resolver
    produced a verified correspondence. A caller-provided proof is never used.
    The current resolver returns only native pinned Parquet, which also means
    historical requests cannot accidentally consume today's conversion.
    """
    plan = dict(selection)
    if plan.get("format", "parquet") != "parquet":
        raise HFError("HF_UNSAFE_FORMAT", "Datasets support only pinned Parquet files.")
    for field in ("config", "split"):
        value = plan.get(field) or ("default" if field == "config" else "train")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
            raise HFError("HF_DATASET_SELECTION_INVALID", "Invalid dataset config or split.")
        plan[field] = value
    revision = metadata.get("revision")
    source = plan.get("source_revision") or revision
    parquet = plan.get("parquet_revision") or revision
    if not _SHA.fullmatch(str(source)) or not _SHA.fullmatch(str(parquet)) or parquet != revision:
        raise HFError(
            "HF_DATASET_REVISION_UNVERIFIED",
            "Dataset source and Parquet revisions must be pinned commits.",
        )
    if source != parquet or str(metadata.get("requested_ref", "")).startswith("refs/convert/"):
        # Conversion provenance is not asserted by dataset-viewer's mobile URL.
        # Add a server verifier before supporting such a branch.
        raise HFError(
            "HF_DATASET_REVISION_UNVERIFIED",
            "A conversion matching this source commit could not be verified.",
        )
    paths = plan.get("shards") or plan.get("paths") or plan.get("files")
    candidates = _split_candidates(metadata, plan["config"], plan["split"])
    if paths is None:
        paths = candidates
        if paths is None:
            raise HFError(
                "HF_DATASET_SELECTION_INVALID",
                "Select explicit Parquet shards: the dataset does not declare files for this config and split.",
            )
    if (
        not isinstance(paths, list)
        or not paths
        or len(paths) > 10000
        or any(not isinstance(path, str) for path in paths)
        or len(set(paths)) != len(paths)
    ):
        raise HFError(
            "HF_DATASET_SELECTION_INVALID",
            "Choose a nonempty, ordered list of distinct Parquet shards.",
        )
    available = {row["path"] for row in metadata.get("files", [])}
    for path in paths:
        safe_path(path)
        if path not in available or not path.endswith(".parquet"):
            raise HFError(
                "HF_UNSAFE_FORMAT",
                "Every dataset shard must be a Parquet file at the pinned commit.",
            )
        if candidates is not None and path not in candidates:
            raise HFError(
                "HF_DATASET_SELECTION_INVALID",
                "A selected shard belongs to another config or split.",
            )
    columns = plan.get("columns")
    if columns is not None and (
        not isinstance(columns, list)
        or not columns
        or len(columns) > int(settings.tabular_max_columns)
        or any(not isinstance(column, str) or not column or len(column) > 512 for column in columns)
        or len(set(columns)) != len(columns)
    ):
        raise HFError(
            "HF_DATASET_SELECTION_INVALID",
            "Choose distinct column names within the platform limit.",
        )
    max_rows = plan.get("max_rows")
    max_rows = int(settings.tabular_transform_max_rows) if max_rows is None else max_rows
    if (
        not isinstance(max_rows, int)
        or isinstance(max_rows, bool)
        or not 1 <= max_rows <= int(settings.tabular_transform_max_rows)
    ):
        raise HFError("HF_TOO_LARGE", "The row limit exceeds the platform dataset limit.")
    version = plan.get("transformation_version") or TRANSFORMATION_VERSION
    if version != TRANSFORMATION_VERSION:
        raise HFError(
            "HF_DATASET_SELECTION_INVALID",
            "The requested dataset transformation version is unsupported.",
        )
    plan.update(
        source_revision=source,
        parquet_revision=parquet,
        shards=paths,
        columns=columns,
        max_rows=max_rows,
        transformation_version=version,
        format="parquet",
        paths=sorted(paths),
    )
    return plan


def validate_plan(metadata: dict, selection: dict):
    normalized = normalize_plan(metadata, selection)
    for key in (
        "source_revision",
        "parquet_revision",
        "shards",
        "columns",
        "max_rows",
        "transformation_version",
        "config",
        "split",
    ):
        if key not in selection or selection[key] != normalized[key]:
            raise HFError(
                "HF_DATASET_SELECTION_INVALID",
                "The dataset import plan was not completely pinned at admission.",
            )
    return normalized


def read_bounded_parquet(paths: list[Path], plan: dict):
    """Project and limit before decoding, reject oversized row groups first.

    Arrow's footer exposes decompressed column sizes before Polars loads any
    values. We conservatively budget full selected row groups even when only
    their first rows are needed, then check actual frame size after each shard.
    Nested values are rejected: these are tabular imports, not a script loader.
    """
    import polars as pl
    import pyarrow as pa
    import pyarrow.parquet as pq

    ceiling = int(os.getenv("HF_DATASET_MAX_MEMORY_BYTES", str(512 * 1024**2)))
    max_columns = int(settings.tabular_max_columns)
    remaining, used, budget = int(plan["max_rows"]), 0, 0
    frames, expected_schema = [], None
    for path in paths:
        if remaining <= 0:
            break
        parquet = pq.ParquetFile(path)
        names = parquet.schema_arrow.names
        if len(names) != len(set(names)):
            raise HFError(
                "HF_DATASET_SELECTION_INVALID", "Duplicate Parquet column names are unsupported."
            )
        columns = plan.get("columns") or names
        if len(columns) > max_columns or any(column not in names for column in columns):
            raise HFError(
                "HF_DATASET_SELECTION_INVALID",
                "A selected column is missing or the column limit was exceeded.",
            )
        if any(pa.types.is_nested(parquet.schema_arrow.field(column).type) for column in columns):
            raise HFError(
                "HF_INCOMPATIBLE_USAGE",
                "Nested Parquet columns cannot be imported as tabular datasets.",
            )
        selected = set(columns)
        planned_rows = 0
        for group_index in range(parquet.metadata.num_row_groups):
            if planned_rows >= remaining:
                break
            group = parquet.metadata.row_group(group_index)
            budget += sum(
                group.column(index).total_uncompressed_size
                for index in range(group.num_columns)
                if group.column(index).path_in_schema in selected
                or group.column(index).path_in_schema.split(".", 1)[0] in selected
            )
            if budget > ceiling:
                raise HFError(
                    "HF_TOO_LARGE",
                    "The selected Parquet row groups exceed the dataset memory budget.",
                )
            planned_rows += group.num_rows
        frame = pl.read_parquet(
            path,
            columns=columns,
            n_rows=remaining,
            low_memory=True,
            parallel="none",
            use_statistics=True,
        )
        if expected_schema is not None and frame.schema != expected_schema:
            raise HFError(
                "HF_DATASET_SELECTION_INVALID",
                "The selected shards have inconsistent column schemas.",
            )
        expected_schema = frame.schema
        used += frame.estimated_size()
        if used > ceiling:
            raise HFError("HF_TOO_LARGE", "The selected dataset exceeds the memory budget.")
        remaining -= frame.height
        frames.append(frame)
    if not frames:
        raise HFError("HF_DATASET_SELECTION_INVALID", "No Parquet shards were selected.")
    return pl.concat(frames, how="vertical", rechunk=False)


def _lineage(artifact) -> dict:
    plan = artifact.selection_json
    return {
        "huggingface": {
            "artifact_id": artifact.id,
            "selection_digest": artifact.selection_digest,
            "source": f"hf://{artifact.repo_id}@{plan['source_revision']}/{plan['config']}/{plan['split']}",
            "hub_endpoint": artifact.hub_endpoint,
            "repo_id": artifact.repo_id,
            **{
                key: plan[key]
                for key in (
                    "source_revision",
                    "parquet_revision",
                    "config",
                    "split",
                    "shards",
                    "columns",
                    "max_rows",
                    "transformation_version",
                )
            },
        }
    }


def materialize_dataset(
    db, artifact, job, *, store: HubStore | None = None, result_store: HubStore | None = None
) -> dict:
    """Run on the existing dataset worker; no Hub client or credential needed."""
    from app.services.huggingface.fetch import base_manifest
    from app.services.huggingface.registry import touch_import
    from app.services.tabular_datasets import register_frame

    store = store or HubStore(use_hub_credentials=False)
    result_store = result_store or HubStore(use_hub_credentials=False)
    acquisition = (job.result or {}).get("acquisition") or {}
    files = acquisition.get("source_files")
    if not isinstance(files, dict) or set(files) != set(artifact.selection_json["shards"]):
        raise HFError(
            "HF_DATASET_RESULT_MISSING", "Verified temporary dataset sources are missing."
        )
    metadata = dict(artifact.metadata_json or {})
    metadata.update(revision=artifact.revision)
    plan = validate_plan(metadata, artifact.selection_json)
    lease_owner = (job.result or {}).get("lease_owner")
    touch_import(db, job.id, "materializing", 87, lease_owner=lease_owner)
    with tempfile.TemporaryDirectory(prefix="agentium-hf-dataset-") as temporary:
        root, paths = Path(temporary), []
        for number, name in enumerate(plan["shards"]):
            entry = files[name]
            key = entry.get("object_key")
            if key != f"hub/tmp/{job.id}/{safe_path(name)}":
                raise HFError(
                    "HF_PATH_INVALID",
                    "Dataset acquisition points outside this job's temporary prefix.",
                )
            path = root / f"{number}.parquet"
            store.copy_verified(key, path, entry, max_bytes=int(settings.tabular_upload_max_bytes))
            paths.append(path)
            touch_import(db, job.id, "materializing", 88, lease_owner=lease_owner)
        with _renew_during_read(job.id, lease_owner):
            frame = read_bounded_parquet(paths, plan)
        touch_import(db, job.id, "publishing_dataset", 92, lease_owner=lease_owner)
        # The archive is independent from any user-visible output's lifecycle.
        # This publication precedes register_frame so the final manifest can
        # always refer to a complete retained result.
        retained = root / "result.parquet"
        frame.write_parquet(retained, compression="zstd")
        key = f"workspaces/{job.workspace_id}/tabular/hub-artifacts/{artifact.id}/result.parquet"
        result = result_store.publish_file(
            key,
            retained,
            max_bytes=int(os.getenv("HF_DATASET_MAX_MEMORY_BYTES", str(512 * 1024**2))),
        )
        result.update(
            row_count=frame.height, column_count=frame.width, owner_workspace_id=job.workspace_id
        )
        touch_import(db, job.id, "registering_dataset", 95, lease_owner=lease_owner)
        dataset = register_frame(
            db,
            workspace_id=job.workspace_id,
            name=((job.input_ref or {}).get("selection") or {}).get("name")
            or artifact.repo_id.rsplit("/", 1)[-1],
            frame=frame,
            source="huggingface",
            produced_by="hf_dataset_import_v1",
            created_by=(job.input_ref or {}).get("actor_id"),
            lineage=_lineage(artifact),
        )
        job.result = {**(job.result or {}), "dataset_id": dataset.id}
        manifest = base_manifest(artifact)
        manifest.update(
            source_files={
                name: {k: v for k, v in entry.items() if k != "object_key"}
                for name, entry in files.items()
            },
            files={},
            dataset_result=result,
            total_bytes=result["size_bytes"],
        )
        # The tabular role may publish dataset manifests through its explicitly
        # granted hub/artifacts prefix; it cannot publish hub/blobs model files.
        result_store.publish_manifest(artifact.id, manifest)
        # complete_import deliberately refreshes the row before checking its
        # lease; persist the output link inside this still-uncommitted unit.
        db.flush()
        return manifest


@contextmanager
def _renew_during_read(job_id: str, lease_owner: str):
    """Decoding a large shard never silently expires its publication lease."""
    import threading

    from app.db.base import SessionLocal
    from app.services.huggingface.registry import touch_import

    done, errors = threading.Event(), []
    interval = max(1, min(30, int(settings.hf_import_lease_seconds) // 3))

    def renew():
        while not done.wait(interval):
            try:
                with SessionLocal() as heartbeat:
                    touch_import(heartbeat, job_id, "materializing", 90, lease_owner=lease_owner)
            except Exception as exc:
                errors.append(exc)
                return

    thread = threading.Thread(target=renew, name="hf-dataset-lease", daemon=True)
    thread.start()
    try:
        yield
        if errors:
            raise errors[0]
    finally:
        done.set()
        thread.join(timeout=5)


def run_dataset_import(db, job_id: str):
    from app.services.huggingface.registry import claim_import, complete_import, fail_import

    try:
        claimed = claim_import(db, job_id)
    except HFError as exc:
        if exc.code in {"HF_JOB_BUSY", "HF_JOB_INACTIVE"}:
            db.rollback()
            return {"job_id": job_id, "status": "busy_or_settled"}
        fail_import(db, job_id, exc.code, exc.message)
        raise
    artifact, job = claimed
    lease_owner = (job.result or {}).get("lease_owner")
    try:
        manifest = materialize_dataset(db, artifact, job)
        complete_import(db, job_id, manifest, lease_owner=lease_owner)
        db.commit()
    except Exception as exc:
        db.rollback()
        fail_import(
            db,
            job_id,
            getattr(exc, "code", "HF_DATASET_IMPORT_FAILED"),
            getattr(exc, "message", "Dataset materialization failed."),
            lease_owner=lease_owner,
        )
        db.commit()
        raise
    finally:
        # The Hub worker owns temporary deletion; no deletion capability is
        # granted to the dataset processing identity.
        from app.workers.hub_fetch import cleanup_temporary

        try:
            cleanup_temporary.apply_async(args=(job_id,), queue="hub_fetch")
        except Exception:
            pass  # Periodic Hub recovery also cleans terminal jobs.
    return {"job_id": job_id, "artifact_id": artifact.id, "status": "ready"}


def replay_dataset(
    db,
    *,
    workspace_id: str,
    artifact_id: str,
    selection_digest: str,
    name: str = "Hugging Face dataset",
    run_id: str | None = None,
    node_id: str | None = None,
    created_by: str | None = None,
    result_store: HubStore | None = None,
):
    from app.services.huggingface.registry import require_artifact
    from app.services.tabular_datasets import register_frame

    artifact = require_artifact(db, workspace_id, artifact_id)
    if artifact.kind != "dataset" or artifact.selection_digest != selection_digest:
        raise HFError(
            "HF_DATASET_SELECTION_INVALID",
            "The Flow must pin the dataset artifact's exact selection digest.",
        )
    result = (artifact.manifest_json or {}).get("dataset_result") or {}
    key = result.get("object_key")
    owner = result.get("owner_workspace_id")
    if not key or key != f"workspaces/{owner}/tabular/hub-artifacts/{artifact.id}/result.parquet":
        raise HFError("HF_DATASET_RESULT_MISSING", "The immutable dataset result is missing.", 409)
    store = result_store or HubStore(use_hub_credentials=False)
    if not store.exists(key):
        raise HFError(
            "HF_DATASET_RESULT_MISSING", "The retained dataset result is no longer available.", 409
        )
    with tempfile.TemporaryDirectory(prefix="agentium-hf-replay-") as temporary:
        path = Path(temporary) / "result.parquet"
        store.copy_verified(
            key,
            path,
            result,
            max_bytes=int(os.getenv("HF_DATASET_MAX_MEMORY_BYTES", str(512 * 1024**2))),
        )
        frame = read_bounded_parquet([path], artifact.selection_json)
        # Authorization can change while an object is copied or decoded.
        require_artifact(db, workspace_id, artifact_id)
        return register_frame(
            db,
            workspace_id=workspace_id,
            name=name,
            frame=frame,
            source="huggingface",
            produced_by="hf_dataset_import_v1",
            run_id=run_id,
            node_id=node_id,
            created_by=created_by,
            lineage=_lineage(artifact),
        )


async def flow_import(payload: dict, ctx: dict) -> dict:
    """Graph-owned artifact+selection pin, authorization from execution context."""
    import asyncio

    from app.db.base import SessionLocal
    from app.services.tabular_datasets import dataset_reference

    if not ctx or not ctx.get("workspace_id"):
        raise HFError(
            "HF_WORKSPACE_REQUIRED", "The dataset block requires an authorized Flow workspace.", 403
        )
    block = payload.get("_hf_dataset")
    if (
        not isinstance(block, dict)
        or not block.get("artifact_id")
        or not block.get("selection_digest")
    ):
        raise HFError(
            "HF_DATASET_SELECTION_INVALID",
            "Pin an imported dataset and its selection digest in the Flow.",
        )

    def execute():
        with SessionLocal() as db:
            dataset = replay_dataset(
                db,
                workspace_id=str(ctx["workspace_id"]),
                artifact_id=block["artifact_id"],
                selection_digest=block["selection_digest"],
                name=block.get("output_name") or "Hugging Face dataset",
                run_id=ctx.get("run_id"),
                node_id=block.get("node_id"),
                created_by=ctx.get("user_id"),
            )
            db.commit()
            return {
                **dataset_reference(dataset),
                "artifact_id": block["artifact_id"],
                "selection_digest": block["selection_digest"],
            }

    return await asyncio.to_thread(execute)
