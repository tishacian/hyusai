#!/usr/bin/env python3
"""Sign converted TabICL weights for Hyusai's existing offline artifact admission.

The conversion has a distinct immutable derived identity. Source repo/revision
and checkpoint hashes remain explicit provenance, never claims that the converted
files were downloaded from the upstream repository. Import the resulting tar
through the existing workspace offline-import endpoint; activation is separate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def manifest_for(directory: Path, license_text: str):
    from app.resources.ml_tabicl_notice import NOTICE_NAME, prepare_notice
    from app.resources.ml_tabicl_runtime import TABICL_VERSION, sha256, validate_weights
    from app.services.huggingface import policy, registry
    from app.services.huggingface.storage import blob_key

    config = validate_weights(directory)
    prepare_notice(directory, license_text)
    inventory = {
        name: {
            "size_bytes": (directory / name).stat().st_size,
            "upstream_hash": {"algorithm": "sha256", "value": sha256(directory / name)},
        }
        for name in ("config.json", "model.safetensors", NOTICE_NAME)
    }
    conversion = {
        "kind": "tabicl-weights-only-to-safetensors-v1",
        "package": TABICL_VERSION,
        "source_repo_id": "jingang/TabICL",
        "source_revision": config["revision"],
        "source_sha256": config["source_sha256"],
        "task": config["task"],
    }
    revision = registry.digest({"conversion": conversion, "files": inventory})[:40]
    metadata = {
        "hub_endpoint": "https://huggingface.co",
        "kind": "model",
        "repo_id": f"hyusai-converted/tabicl-v2-{config['task']}",
        "revision": revision,
        "requested_ref": revision,
        "license": "bsd-3-clause",
        "license_text": license_text,
        "private": False,
        "gated": False,
        "files": [{"path": name, **entry} for name, entry in inventory.items()],
    }
    files, plan = registry.select_files(
        metadata, {"format": "safetensors", "files": list(inventory)}
    )
    digest = registry.digest({"plan": plan, "files": files})
    identity = registry.digest(
        [metadata["hub_endpoint"], "model", metadata["repo_id"], revision, digest]
    )
    artifact_id = str(uuid5(NAMESPACE_URL, "hyusai:derived-tabicl:" + identity))
    artifact = SimpleNamespace(
        **{key: metadata[key] for key in ("hub_endpoint", "kind", "repo_id", "revision")}
    )
    manifest = {
        **{key: value for key, value in metadata.items() if key != "files"},
        "version": 2,
        "artifact_id": artifact_id,
        "format": "safetensors",
        "variant": None,
        "selection": plan,
        "selection_digest": digest,
        "conversion": conversion,
        "total_bytes": sum(entry["size_bytes"] for entry in files.values()),
        "files": {
            name: {
                **entry,
                "sha256": entry["upstream_hash"]["value"],
                "object_key": blob_key(artifact, name),
            }
            for name, entry in files.items()
        },
    }
    manifest["license_digest"] = policy.license_digest(manifest, license_text)
    return manifest


def main():
    from app.services.huggingface import bundles

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--signing-key-file", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--license-file", required=True, type=Path)
    args = parser.parse_args()
    manifest = manifest_for(args.directory, args.license_file.read_text())

    # The operator's signing key is the authority for this public derived bundle.
    # The receiving server independently checks signature, workspace, licenses,
    # quotas and grants using the standard offline admission transaction.
    def authorize(source, workspace_id):
        return (
            source == manifest
            and workspace_id == args.workspace_id
            and not source["private"]
            and not source["gated"]
        )

    created = False
    try:
        with args.destination.open("xb") as output:
            created = True
            bundles.export_bundle(
                output,
                manifest=manifest,
                open_file=lambda name: (args.directory / name).open("rb"),
                target_workspace_id=args.workspace_id,
                license_digest=manifest["license_digest"],
                signing_key=args.signing_key_file.read_bytes(),
                key_id=args.key_id,
                authorize=authorize,
                max_total_bytes=256 * 1024 * 1024,
                max_file_bytes=128 * 1024 * 1024,
            )
    except Exception:
        if created:
            args.destination.unlink(missing_ok=True)
        raise
    print(
        json.dumps(
            {
                "artifact_id": manifest["artifact_id"],
                "revision": manifest["revision"],
                "source_revision": manifest["conversion"]["source_revision"],
                "bytes": args.destination.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
