"""The redistributable TabICL notice survives admission and cannot be omitted."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.resources.ml_tabicl_notice import NOTICE_NAME, notice_document
from app.resources.ml_tabicl_runtime import CHECKPOINTS, REVISION, expected_config
from app.services.huggingface.adapters import validate_layout
from app.services.huggingface.cache import ArtifactCache, ArtifactError, Snapshot
from app.services.ml.local_models import resolve_artifact_model


@pytest.fixture
def packaged(tmp_path):
    script = Path(__file__).resolve().parents[3] / "scripts" / "package_tabicl_bundle.py"
    spec = importlib.util.spec_from_file_location("package_tabicl_notice_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "source"
    source.mkdir()
    # These tests stop before tensor loading; only provenance and transport run.
    weight_bytes = b"notice-admission-fixture"
    (source / "model.safetensors").write_bytes(weight_bytes)
    config = {
        "schema": 1,
        "tabicl": "2.2.0",
        "architectures": ["AgentiumTabICLv2"],
        "task": "classification",
        "config": expected_config("classification"),
        "revision": REVISION,
        "source_sha256": CHECKPOINTS["classification"][1],
        "weights_sha256": hashlib.sha256(weight_bytes).hexdigest(),
    }
    (source / "config.json").write_text(json.dumps(config))
    return module, source


def test_packaging_refuses_incomplete_notice_before_writing_manifest(packaged):
    module, source = packaged
    with pytest.raises(ValueError, match="complete pinned"):
        module.manifest_for(source, "BSD-3-Clause")
    assert not (source / NOTICE_NAME).exists()


def test_legacy_bundle_without_notice_cannot_be_resolved_for_training(packaged, tmp_path):
    module, source = packaged
    manifest = module.manifest_for(source, notice_document()["license_text"])
    legacy = copy.deepcopy(manifest)
    legacy["total_bytes"] -= legacy["files"].pop(NOTICE_NAME)["size_bytes"]
    legacy["selection"]["files"].remove(NOTICE_NAME)
    cache = ArtifactCache(tmp_path / "legacy-cache", min_free_bytes=0)
    cache.materialize(legacy, lambda name, entry: (source / name).open("rb"))
    with pytest.raises(ArtifactError) as caught:
        resolve_artifact_model(
            legacy["artifact_id"],
            kind="tabular_foundation",
            cache_dir=cache.root,
            manifest=legacy,
        )
    assert caught.value.code == "HF_TABICL_LICENSE_REQUIRED"


@pytest.mark.parametrize("mutation", ["text", "provenance", "extra"])
def test_layout_refuses_unqualified_license_even_in_an_authorized_snapshot(packaged, mutation):
    module, source = packaged
    manifest = module.manifest_for(source, notice_document()["license_text"])
    changed = notice_document()
    if mutation == "text":
        changed["license_text"] = "BSD-3-Clause"
    elif mutation == "provenance":
        changed["provenance"]["weights"]["revision"] = "0" * 40
    else:
        changed["additional_terms"] = "Noncommercial only"
    (source / NOTICE_NAME).write_text(json.dumps(changed))
    with pytest.raises(ArtifactError) as caught:
        validate_layout(Snapshot(source, manifest), "tabular_foundation")
    assert caught.value.code == "HF_TABICL_LICENSE_INVALID"
