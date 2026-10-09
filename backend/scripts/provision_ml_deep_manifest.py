#!/usr/bin/env python3
"""Register already-provisioned local model bytes; this script never downloads."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ml.local_models import MODEL_SPECS, _inside, _inventory, file_hash, resolve_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=Path("/data/models"))
    parser.add_argument("--model-id", choices=sorted(MODEL_SPECS), required=True)
    parser.add_argument("--path", required=True, help="Existing directory relative to --models-dir")
    parser.add_argument("--revision", required=True, help="Immutable upstream commit, 40–64 lowercase hex digits")
    args = parser.parse_args()
    root = args.models_dir.resolve()
    path = _inside(root, args.path)
    if not path.is_dir() or path.is_symlink():
        parser.error("--path must name an existing regular directory")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"version": 1, "models": {}}
    if manifest.get("version") != 1 or not isinstance(manifest.get("models"), dict):
        parser.error("existing manifest must use version 1")
    spec = MODEL_SPECS[args.model_id]
    entry = {
        **spec, "path": args.path, "revision": args.revision,
        "files": {name: file_hash(file) for name, file in sorted(_inventory(path).items())},
    }
    manifest["models"][args.model_id] = entry
    temporary = manifest_path.with_name(f".manifest.{os.getpid()}.json")
    try:
        temporary.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        # Validate before replacing an operator's existing manifest. The same
        # checks are applied by resolve_model when the worker opens it.
        import re
        if not entry["files"] or re.fullmatch(r"[0-9a-f]{40,64}", args.revision) is None:
            parser.error("model files and an immutable hexadecimal revision are required")
        temporary.replace(manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    model = resolve_model(args.model_id, kind=spec["kind"], models_dir=root)
    print(json.dumps(model.public(), sort_keys=True))


if __name__ == "__main__":
    main()
