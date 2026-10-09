"""Pinned source plans, bounded Parquet and graph-owned dataset replay."""

import pytest

from app.core.config import settings
from app.services.huggingface.datasets import normalize_plan, read_bounded_parquet, validate_plan
from app.services.huggingface.errors import HFError

pl = pytest.importorskip("polars")
pytest.importorskip("pyarrow")


def metadata():
    return {
        "revision": "a" * 40,
        "requested_ref": "main",
        "files": [
            {"path": "train/part-2.parquet"},
            {"path": "train/part-1.parquet"},
        ],
    }


def test_dataset_plan_freezes_order_projection_limits_and_native_revision():
    plan = normalize_plan(
        metadata(),
        {
            "shards": ["train/part-2.parquet", "train/part-1.parquet"],
            "columns": ["b", "a"],
            "max_rows": 3,
        },
    )
    assert plan["source_revision"] == plan["parquet_revision"] == "a" * 40
    assert plan["shards"] == ["train/part-2.parquet", "train/part-1.parquet"]
    assert plan["columns"] == ["b", "a"] and plan["max_rows"] == 3
    assert validate_plan(metadata(), plan) == plan
    del plan["columns"]
    with pytest.raises(HFError, match="completely pinned"):
        validate_plan(metadata(), plan)


def test_default_selection_never_merges_splits_and_honors_card_config():
    meta = {
        **metadata(),
        "files": [{"path": "data/train-1.parquet"}, {"path": "data/test-1.parquet"}],
    }
    assert normalize_plan(meta, {})["shards"] == ["data/train-1.parquet"]
    with pytest.raises(HFError, match="another config or split"):
        normalize_plan(meta, {"shards": ["data/test-1.parquet"], "split": "train"})
    meta["card_data"] = {
        "configs": [
            {"config_name": "english", "data_files": [{"split": "test", "path": "data/test-*"}]}
        ]
    }
    assert normalize_plan(meta, {"config": "english", "split": "test"})["shards"] == [
        "data/test-1.parquet"
    ]
    with pytest.raises(HFError, match="config is not declared"):
        normalize_plan(meta, {"config": "french", "split": "test"})


@pytest.mark.parametrize(
    "meta,selection",
    [
        ({**metadata(), "requested_ref": "refs/convert/parquet"}, {}),
        (metadata(), {"source_revision": "b" * 40}),
        (metadata(), {"parquet_revision": "main"}),
        (metadata(), {"source_revision": "historical", "conversion_verified": True}),
    ],
)
def test_dataset_conversion_never_trusts_mobile_or_caller_supplied_proof(meta, selection):
    with pytest.raises(HFError) as error:
        normalize_plan(meta, selection)
    assert error.value.code == "HF_DATASET_REVISION_UNVERIFIED"


def test_bounded_reader_respects_shard_then_row_order_and_projection(tmp_path):
    first, second = tmp_path / "2.parquet", tmp_path / "1.parquet"
    pl.DataFrame({"a": [20, 21], "b": ["first", "second"], "ignored": [False, True]}).write_parquet(
        first
    )
    pl.DataFrame({"a": [10, 11], "b": ["third", "fourth"], "ignored": [False, True]}).write_parquet(
        second
    )
    frame = read_bounded_parquet([first, second], {"max_rows": 3, "columns": ["b", "a"]})
    assert frame.columns == ["b", "a"]
    assert frame.rows() == [("first", 20), ("second", 21), ("third", 10)]


@pytest.mark.parametrize("column", ["text", "text.with.dots"])
def test_reader_rejects_decompression_before_polars_materializes(tmp_path, monkeypatch, column):
    path = tmp_path / "bomb.parquet"
    pl.DataFrame({column: ["a" * 10000] * 100}).write_parquet(path)
    monkeypatch.setenv("HF_DATASET_MAX_MEMORY_BYTES", "100")
    monkeypatch.setattr(
        pl, "read_parquet", lambda *a, **kw: pytest.fail("Must reject metadata before decoding")
    )
    with pytest.raises(HFError, match="memory budget"):
        read_bounded_parquet([path], {"max_rows": 1, "columns": [column]})


def test_dataset_import_rejects_model_format():
    with pytest.raises(HFError) as error:
        normalize_plan(metadata(), {"format": "gguf"})
    assert error.value.code == "HF_UNSAFE_FORMAT"


def test_reader_rejects_unbounded_columns_and_nested_values(tmp_path, monkeypatch):
    path = tmp_path / "wide.parquet"
    pl.DataFrame({"a": [1], "b": [2]}).write_parquet(path)
    monkeypatch.setattr(settings, "tabular_max_columns", 1)
    with pytest.raises(HFError, match="column limit"):
        read_bounded_parquet([path], {"max_rows": 1})
    nested = tmp_path / "nested.parquet"
    pl.DataFrame({"a": [[1, 2]]}).write_parquet(nested)
    with pytest.raises(HFError, match="Nested"):
        read_bounded_parquet([nested], {"max_rows": 1})


def test_flow_has_bound_catalog_claim_and_rejects_caller_overrides():
    import jsonschema

    from app.services.run_engine.dag import (
        _GRAPH_OWNED_BLOCKS,
        DagNode,
        _apply_graph_owned_config,
        _passthrough_without_recipe,
    )
    from app.services.run_engine.execution_contract import resolve_flow_execution
    from app.services.skills_registry import wrappers
    from app.services.skills_registry.seed import SEED_CAPABILITIES, SEED_SKILLS

    slug = "hf_dataset_import_v1"
    skill = next(row for row in SEED_SKILLS if row["slug"] == slug)
    assert wrappers._REGISTRY[slug][0] is wrappers._hf_dataset_import_v1
    assert any(slug in row["skill_slugs"] for row in SEED_CAPABILITIES)
    params = {"artifact_id": "trusted", "selection_digest": "a" * 64, "output_name": "pin"}
    node = DagNode("hf", "skill", "task", None, {"params": params}, slug, {})
    key, slugs, keys = next(row for row in _GRAPH_OWNED_BLOCKS if row[0] == "_hf_dataset")
    assert set(keys) == set(skill["input_schema"]["properties"])
    incoming = {
        "_hf_dataset": {"artifact_id": "forged"},
        "artifact_id": "forged",
        "workspace_id": "forged",
    }
    _apply_graph_owned_config(node, incoming, key=key, slugs=slugs, param_keys=keys)
    assert incoming["_hf_dataset"]["artifact_id"] == "trusted"
    jsonschema.validate(incoming, skill["input_schema"])
    assert "artifact_id" not in incoming and "_hf_dataset" not in _passthrough_without_recipe(
        incoming
    )
    assert resolve_flow_execution(
        {"schema_version": 3, "nodes": [{"kind": "task", "config": {"skill_slug": slug}}]}
    ).uses_dag


@pytest.mark.asyncio
async def test_flow_requires_workspace_context():
    from app.services.huggingface.datasets import flow_import

    with pytest.raises(HFError) as error:
        await flow_import(
            {
                "workspace_id": "forged",
                "_hf_dataset": {"artifact_id": "x", "selection_digest": "a"},
            },
            {},
        )
    assert error.value.code == "HF_WORKSPACE_REQUIRED"


@pytest.fixture()
def materialized(db_session, tmp_path, monkeypatch):
    import hashlib
    from uuid import uuid4

    import httpx

    from app.models.user import User
    from app.models.workspace import Workspace
    from app.services.huggingface import registry
    from app.services.huggingface.client import HFClient
    from app.services.huggingface.connection import Connection
    from app.services.huggingface.datasets import materialize_dataset
    from app.services.huggingface.fetch import execute_import
    from app.services.huggingface.storage import HubStore

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "hf_cache_dir", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "hf_disk_min_free_bytes", 0)
    workspace = Workspace(
        id=str(uuid4()), name="HF Dataset", slug="hf-" + uuid4().hex[:12], settings={}
    )
    db_session.add(workspace)
    db_session.add(
        User(
            id="actor",
            username="hf-dataset-admin",
            email="hf-dataset-admin@example.test",
            role="admin",
            is_active=True,
        )
    )
    db_session.commit()
    source = tmp_path / "train.parquet"
    pl.DataFrame(
        {"text": ["one", "two", "three"], "label": [1, 2, 3], "drop": [4, 5, 6]}
    ).write_parquet(source)
    content = source.read_bytes()
    meta = {
        "hub_endpoint": "https://huggingface.co",
        "kind": "dataset",
        "repo_id": "test/data-" + uuid4().hex[:12],
        "revision": "a" * 40,
        "requested_ref": "historic",
        "license": "mit",
        "license_text": "MIT License",
        "files": [
            {
                "path": "train.parquet",
                "size_bytes": len(content),
                "upstream_hash": {
                    "algorithm": "sha256",
                    "value": hashlib.sha256(content).hexdigest(),
                },
            }
        ],
    }
    artifact, job = registry.request_import(
        db_session,
        workspace_id=workspace.id,
        actor_id="actor",
        metadata=meta,
        selection={"shards": ["train.parquet"], "columns": ["label", "text"], "max_rows": 2},
        dispatch=False,
    )
    artifact, job = registry.claim_import(db_session, job.id)
    client = HFClient(
        Connection(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content)),
    )
    store = HubStore()
    acquisition = execute_import(db_session, artifact, job, client=client, store=store)
    assert acquisition["pending_dataset"]
    assert not list((tmp_path / "store" / "hub" / "blobs").glob("**/*"))
    job.result = {**job.result, "acquisition": acquisition}
    db_session.commit()
    manifest = materialize_dataset(db_session, artifact, job, store=store)
    assert manifest["files"] == {}
    assert "object_key" not in manifest["source_files"]["train.parquet"]
    registry.complete_import(db_session, job.id, manifest, lease_owner=job.result["lease_owner"])
    store.delete_temporary(job.id)
    return workspace, artifact, job, store


def test_import_replay_survives_original_output_deletion_and_changed_hub(
    materialized, db_session, monkeypatch
):
    from app.models.tabular import TabularDataset
    from app.services.huggingface.client import HFClient
    from app.services.huggingface.datasets import replay_dataset
    from app.services.tabular_datasets import read_frame, soft_delete

    workspace, artifact, job, store = materialized
    initial = db_session.query(TabularDataset).filter_by(workspace_id=workspace.id).one()
    assert job.result["dataset_id"] == initial.id
    assert initial.source == "huggingface"
    assert read_frame(initial).rows() == [(1, "one"), (2, "two")]
    soft_delete(db_session, initial)
    monkeypatch.setattr(
        HFClient, "_request", lambda *a, **kw: pytest.fail("Replay must never contact the Hub")
    )
    replayed = replay_dataset(
        db_session,
        workspace_id=workspace.id,
        artifact_id=artifact.id,
        selection_digest=artifact.selection_digest,
    )
    db_session.commit()
    assert replayed.id != initial.id and replayed.status == "ready"
    assert read_frame(replayed).rows() == [(1, "one"), (2, "two")]
    assert replayed.lineage_json["huggingface"]["columns"] == ["label", "text"]
    assert store.exists(artifact.manifest_json["dataset_result"]["object_key"])


def test_replay_detects_missing_or_modified_retained_result(materialized, db_session):
    from app.services.huggingface.datasets import replay_dataset

    workspace, artifact, _, store = materialized
    args = {
        "workspace_id": workspace.id,
        "artifact_id": artifact.id,
        "selection_digest": artifact.selection_digest,
    }
    key = artifact.manifest_json["dataset_result"]["object_key"]
    store.store._local_path(key).write_bytes(b"corrupt")
    with pytest.raises(HFError) as error:
        replay_dataset(db_session, **args)
    assert error.value.code == "HF_CHECKSUM_MISMATCH"
    store.delete(key)
    with pytest.raises(HFError) as error:
        replay_dataset(db_session, **args)
    assert error.value.code == "HF_DATASET_RESULT_MISSING"


def test_replay_requires_current_workspace_authorization(materialized, db_session):
    from datetime import datetime

    from app.models.huggingface import HubArtifactGrant
    from app.services.huggingface.datasets import replay_dataset

    workspace, artifact, _, _ = materialized
    grant = db_session.get(HubArtifactGrant, (workspace.id, artifact.id))
    grant.revoked_at = datetime.utcnow()
    db_session.commit()
    with pytest.raises(HFError) as error:
        replay_dataset(
            db_session,
            workspace_id=workspace.id,
            artifact_id=artifact.id,
            selection_digest=artifact.selection_digest,
        )
    assert error.value.code == "HF_ACCESS_REVOKED"
