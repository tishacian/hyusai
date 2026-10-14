"""Hash the shipped certification recipes, not an operator-supplied version."""

import hashlib
import json
from pathlib import Path


def kit_identity():
    root = Path(__file__).resolve().parents[2] / "tests" / "connectors" / "kit"
    manifest = json.loads((root / "manifest.json").read_text())
    digest = hashlib.sha256()
    for path in sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix in (".py", ".json") and "__pycache__" not in p.parts
    ):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {"version": manifest["version"], "sha256": digest.hexdigest()}
