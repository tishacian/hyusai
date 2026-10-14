"""Fetch the pinned cross-encoder files into a models directory, verified.

usage: python fetch_rag_models.py --manifest rag_models.lock.json --dest DIR
       python fetch_rag_models.py --manifest rag_models.lock.json --dest DIR --verify-only

Runs at image build time, before the application is installed, so it uses the
standard library only. Every file is downloaded at the manifest's revision and
must match its sha256 before it is moved into place; an existing file with the
right digest is kept, so a rebuild with a warm layer does no network I/O.
``RAG_MODELS_BASE_URL`` points at a mirror for hosts without Hugging Face access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://huggingface.co"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, target: Path, expected: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".partial-")
    try:
        with os.fdopen(handle, "wb") as out, urllib.request.urlopen(url, timeout=120) as response:
            while block := response.read(1 << 20):
                out.write(block)
        actual = _sha256(Path(temporary))
        if actual != expected:
            raise SystemExit(f"sha256 mismatch for {url}: expected {expected}, got {actual}")
        # mkstemp creates 0600 files; the images run as a non-root user.
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    base_url = os.environ.get("RAG_MODELS_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    missing = []
    for model in manifest["models"]:
        for relative, expected in model["files"].items():
            target = args.dest / model["name"] / relative
            if target.is_file() and _sha256(target) == expected:
                continue
            if args.verify_only:
                missing.append(str(target))
                continue
            url = f"{base_url}/{model['repo']}/resolve/{model['revision']}/{relative}"
            print(f"fetching {model['name']}/{relative}", flush=True)
            _download(url, target, expected)
    if missing:
        print("missing or altered model files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
