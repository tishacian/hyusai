"""Canonical structural identities for Flow graph primitives.

The identity is encoded as canonical JSON instead of a delimiter-joined
string.  User-controlled node ids, port names and branch labels may contain
any delimiter, so concatenation cannot be used safely for duplicate detection
or semantic diff keys.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def edge_identity_payload(edge: Mapping[str, Any]) -> dict[str, str]:
    """Return the runtime-relevant, alias-normalized identity of an edge."""

    source = edge.get("from") if "from" in edge else edge.get("source")
    target = edge.get("to") if "to" in edge else edge.get("target")
    branch_label = edge.get("branch_label")
    if branch_label is None:
        branch_label = edge.get("label")
    return {
        "branch_label": "" if branch_label is None else str(branch_label),
        "from": "" if source is None else str(source),
        "from_port": "" if edge.get("from_port") is None else str(edge.get("from_port")),
        "kind": str(edge.get("kind") or "data"),
        "to": "" if target is None else str(target),
        "to_port": "" if edge.get("to_port") is None else str(edge.get("to_port")),
    }


def edge_identity(edge: Mapping[str, Any]) -> str:
    """Return an unambiguous, deterministic JSON identity for ``edge``."""

    return json.dumps(
        edge_identity_payload(edge),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
