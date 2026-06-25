"""Typed variable pool + selector resolution for the DAG walker (P1).

The Orchestration editor authors flows whose ``task`` nodes carry an
``inputs_map`` / ``outputs_map`` (FlowSerializer v2 scaffolding, typed in
v3). Until now the run engine never *read* those maps — it threaded a flat
merge of predecessor outputs (``ctx`` / ``last_output``). This module adds a
typed store so the graph can resolve its own IO:

* :class:`VariablePool` — a nested dict keyed by a *head* segment (either a
  reserved namespace or a node id) followed by an arbitrary path.
* :func:`resolve_selector` — read one selector out of the pool. A selector is
  one of three interchangeable shapes:
    1. a legacy **dot-path string** ``"session.objective"`` (v2),
    2. a typed **VariableRef** ``{"node_id": "n1", "path": ["sources", "0"]}`` (v3),
    3. a raw ``[head, *path]`` **list/tuple**.
* :func:`apply_inputs_map` — resolve ``config.inputs_map`` into a skill input.
* :func:`apply_outputs_map` — write a node output into the pool per
  ``config.outputs_map``.

Reserved namespaces (``workspace`` / ``system`` / ``run`` / ``node``) resolve
outside the node graph; any other head segment is treated as a node id or a
free-form logical bucket (the seeded capture flow uses ``session`` / ``capture``
/ ``turn`` / ``context`` buckets, for instance).

**Backward-compat contract (critical):** when ``inputs_map`` / ``outputs_map``
are empty or absent, :func:`apply_inputs_map` returns the predecessor merge
verbatim and :func:`apply_outputs_map` is a no-op — so the DAG walker is
byte-identical to the pre-P1 flat-merge path.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# Reserved namespaces addressable from any node (mirrors the frontend
# ``RESERVED_VARIABLE_NAMESPACES`` in flow-serializer.service.ts).
RESERVED_NAMESPACES: Tuple[str, ...] = ("workspace", "system", "run", "node")

# Sentinel distinguishing "selector absent from the pool" from "selector
# present but holds None" — only the former should fall back to the merge.
_MISSING = object()

Selector = Union[str, Sequence[str], Dict[str, Any]]


def selector_segments(selector: Selector) -> Optional[List[str]]:
    """Normalise any accepted selector shape to ``[head, *path]``.

    Returns ``None`` when the selector is unusable (empty string, malformed
    ref, …) so callers can cleanly skip it.
    """
    if selector is None:
        return None
    # Typed VariableRef: {"node_id": str, "path": [str, ...]}.
    if isinstance(selector, dict):
        node_id = selector.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            return None
        path = selector.get("path") or []
        if not isinstance(path, (list, tuple)):
            return None
        return [node_id, *[str(p) for p in path]]
    # Raw [head, *path] sequence (but not a bare string).
    if isinstance(selector, (list, tuple)):
        segs = [str(s) for s in selector if s is not None and str(s) != ""]
        return segs or None
    # Legacy dot-path string.
    if isinstance(selector, str):
        segs = [s for s in selector.split(".") if s != ""]
        return segs or None
    return None


class VariablePool:
    """Nested-dict typed store keyed by ``[head, *path]`` selectors."""

    def __init__(self, store: Optional[Dict[str, Any]] = None) -> None:
        self._store: Dict[str, Any] = dict(store) if isinstance(store, dict) else {}

    # -- reads ---------------------------------------------------------------
    def get(self, selector: Selector, default: Any = None) -> Any:
        segs = selector_segments(selector)
        if not segs:
            return default
        cur: Any = self._store
        for seg in segs:
            if isinstance(cur, dict):
                if seg in cur:
                    cur = cur[seg]
                    continue
                return default
            if isinstance(cur, (list, tuple)):
                idx = _as_index(seg)
                if idx is not None and -len(cur) <= idx < len(cur):
                    cur = cur[idx]
                    continue
                return default
            return default
        return cur

    def has(self, selector: Selector) -> bool:
        return self.get(selector, _MISSING) is not _MISSING

    # -- writes --------------------------------------------------------------
    def set(self, selector: Selector, value: Any) -> None:
        segs = selector_segments(selector)
        if not segs:
            return
        cur: Dict[str, Any] = self._store
        for seg in segs[:-1]:
            nxt = cur.get(seg)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[seg] = nxt
            cur = nxt
        cur[segs[-1]] = value

    def set_namespace(self, name: str, mapping: Dict[str, Any]) -> None:
        """Shallow-merge ``mapping`` into the ``name`` head bucket."""
        if not name or not isinstance(mapping, dict):
            return
        existing = self._store.get(name)
        if isinstance(existing, dict):
            existing.update(mapping)
        else:
            self._store[name] = dict(mapping)

    # -- (de)serialisation ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        # Deep copy so callers can't mutate the pool through the payload.
        return copy.deepcopy(self._store)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "VariablePool":
        return cls(data if isinstance(data, dict) else {})


def _as_index(seg: str) -> Optional[int]:
    try:
        return int(seg)
    except (TypeError, ValueError):
        return None


def resolve_selector(
    selector: Selector, pool: VariablePool, default: Any = None
) -> Any:
    """Read one selector out of ``pool`` (accepts string / ref / list)."""
    return pool.get(selector, default)


def apply_inputs_map(
    config: Optional[Dict[str, Any]],
    pool: VariablePool,
    predecessor_merge: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve ``config.inputs_map`` into a skill input dict.

    The predecessor merge is the base (so unmapped upstream fields still flow
    through). Each ``port → selector`` entry overlays the resolved value on
    top — but only when the selector actually resolves to a non-``None`` value
    in the pool, so a typo'd selector never clobbers real upstream data.

    When ``inputs_map`` is empty/absent the predecessor merge is returned
    verbatim (byte-identical to the pre-P1 path).
    """
    base: Dict[str, Any] = dict(predecessor_merge or {})
    inputs_map = (config or {}).get("inputs_map") if isinstance(config, dict) else None
    if not isinstance(inputs_map, dict) or not inputs_map:
        return base
    for port, selector in inputs_map.items():
        value = resolve_selector(selector, pool, default=_MISSING)
        if value is not _MISSING and value is not None:
            base[str(port)] = value
    return base


def apply_outputs_map(
    config: Optional[Dict[str, Any]],
    output: Optional[Dict[str, Any]],
    pool: VariablePool,
) -> None:
    """Write a node ``output`` into ``pool`` per ``config.outputs_map``.

    ``outputs_map`` maps ``output_port → target dot-path`` (e.g.
    ``{"gaps": "capture.gaps"}``). No-op when the map is empty/absent so the
    pool is untouched on legacy flows.
    """
    outputs_map = (config or {}).get("outputs_map") if isinstance(config, dict) else None
    if not isinstance(outputs_map, dict) or not outputs_map:
        return
    if not isinstance(output, dict):
        return
    for port, target in outputs_map.items():
        if port in output:
            pool.set(target, output[port])
