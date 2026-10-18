"""Export the exact verified producer bundle, without deserializing the estimator."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from app.core.config import settings
from app.services.ml.artifacts import artifact_fingerprint, verify_model_bundle
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import download_model_dir

README = """# Agentium MLflow export

This archive contains one exact model version, its producer artifact contract,
and SHA-256 inventories. It has no connection to the Agentium database, object
store or registry. Treat model files as executable code: obtain this archive
from your administrator and keep its independently supplied archive SHA-256.
The JSON contract is provenance, not an independent signature of trust.

The model/ directory is unchanged from the verified producer bundle. Its
input_example.json is a real training example and may contain business data.
No prediction journal, dataset or credentials are added to this archive.

## Serve locally

Use the same Python major/minor and package versions recorded in
artifact-contract.json. In your isolated Python environment install the pinned
model/requirements.txt dependencies, then:

```sh
cd model
mlflow models serve -m . --env-manager local --host 127.0.0.1 --port 5001
```

From another terminal, if model/serving_input_example.json is present:

```sh
curl -H 'Content-Type: application/json' --data-binary @model/serving_input_example.json http://127.0.0.1:5001/invocations
```

MLflow's pyfunc endpoint returns the native MLflow prediction, not Agentium's
prediction envelope or its probability/interval decoration. The signature in
model/MLmodel defines the accepted input. Nothing is installed at service startup
with --env-manager local. Optional image packaging, in that qualified environment:

```sh
mlflow models build-docker -m model -n exported-model
```

This export does not import external models or deploy a service. Agentium
refuses export when the producer runtime/trust profile cannot be verified in its
reader environment. A portable tabular sklearn/skops model has been exercised
via a real MLflow HTTP server; that does not qualify every model family.

## Runtime attestations

The archive runs under the producer runtime recorded in artifact-contract.json
(model/requirements.txt pins it), OR under a reader runtime listed in
runtime-attestations.json when that file is present. Each attestation records
that Agentium replayed the model's reference predictions under that reader
runtime and found them within the stated tolerances. It covers exactly the
listed package versions for this exact artifact, nothing else; install those
versions instead of model/requirements.txt to use it. An attestation revoked
after this export is not reflected in the archive.
"""


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _attestation_record(item: dict) -> dict:
    return {
        key: item.get(key)
        for key in (
            "id",
            "artifact_fingerprint",
            "producer_runtime",
            "reader_runtime",
            "reference_sha256",
            "rows_compared",
            "metrics",
            "tolerances",
            "created_at",
        )
    }


def build_export(model, destination: Path, attested=()):
    """Return a bounded archive and non-sensitive audit metadata.

    ``destination`` is a fresh, private temporary directory owned by the caller.
    The caller authorizes and audits before sending any bytes. ``attested`` are
    the row's active qualified runtime attestations (M4.2): they let the gate
    accept an attested reader and are shipped as runtime-attestations.json.
    """
    if model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY", message="The model is not ready.", status_code=409
        )
    artifact = (model.metrics_json or {}).get("artifact") or {}
    budget = int(settings.ml_train_artifact_limit_mb) * 1024**2
    contents = destination / "contents"
    bundle = download_model_dir(model, contents / "model")
    verify_model_bundle(bundle, artifact, family=model.family, max_bytes=budget, attested=attested)
    if not {"requirements.txt", "input_example.json"} <= artifact["files"].keys():
        raise TabularError(
            code="ML_EXPORT_INCOMPLETE",
            message="The producer bundle lacks dependencies or an input example.",
            status_code=409,
        )
    _write_json(contents / "artifact-contract.json", artifact)
    fingerprint = artifact_fingerprint(artifact)
    attestations = [
        _attestation_record(item)
        for item in attested
        if item.get("artifact_fingerprint") == fingerprint
        and item.get("producer_runtime") == artifact.get("runtime")
    ]
    if attestations:
        _write_json(
            contents / "runtime-attestations.json",
            {"format": "agentium-runtime-attestations-v1", "attestations": attestations},
        )
    (contents / "README.md").write_text(README)
    inventory = {
        path.relative_to(contents).as_posix(): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(contents.rglob("*"))
        if path.is_file()
    }
    _write_json(
        contents / "export-manifest.json",
        {
            "format": "agentium-mlflow-export-v1",
            "model": {
                "id": model.id,
                "version": model.version,
                "family": model.family,
                "task": model.task,
            },
            "artifact_fingerprint": fingerprint,
            "files": inventory,
        },
    )
    archive = destination / "model.zip"
    # ZIP_STORED avoids expensive recompression of already compressed skops files.
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for path in sorted(contents.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(contents).as_posix())
    return archive, {
        "artifact_fingerprint": fingerprint,
        "archive_sha256": _sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "model_version": model.version,
        "attestations": sorted(item["id"] for item in attestations),
    }
