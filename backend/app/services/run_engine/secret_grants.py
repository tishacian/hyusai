"""Flow ``secret`` nodes: grant-by-reference access to the secret registry.

A ``secret`` node carries ``{"secret_ref": "secret://...", "bindings":
{"<task_node_id>": "<slot>"}}``. A data edge ``secret -> task`` plus a binding
for that task grants the task one named slot. The walker never puts the value
in the variable pool: the task receives ``skill_ctx["secrets"]``, a
:class:`SecretGrants` that resolves on demand (audited by the registry) and
only for granted slots.

Every value revealed through a grant is remembered per run so the engine can
redact it from anything it persists or publishes (invocation ledgers,
checkpoints, SSE, walker payloads, LLM prompts). The memory is process-local
and bounded; redaction is a safety net, not a licence to return secrets.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from app.services.secrets import SecretConsumer, SecretRegistryError, SecretValue, parse_ref
from app.services.secrets.values import MASK

SECRET_NODE_KIND = "secret"
CTX_KEY = "secrets"
_MAX_TRACKED_RUNS = 512
_MIN_REDACT_LENGTH = 4

_lock = threading.Lock()
_revealed: OrderedDict[str, set[str]] = OrderedDict()


def _edge_ends(edge: Any) -> tuple[str, str]:
    if not isinstance(edge, Mapping):
        return "", ""
    return (
        str(edge.get("from") or edge.get("source") or "").strip(),
        str(edge.get("to") or edge.get("target") or "").strip(),
    )


def _is_data_edge(edge: Any) -> bool:
    return isinstance(edge, Mapping) and edge.get("kind", "data") in (None, "data")


def is_secret_node(node: Any) -> bool:
    return isinstance(node, Mapping) and node.get("kind") == SECRET_NODE_KIND


def secret_bindings_for(flow: Any, node_id: str | None) -> dict[str, str]:
    """Slots granted to ``node_id`` by wired ``secret`` nodes: ``{slot: ref}``.

    Raises ``SecretRegistryError("SECRET_SLOT_CONFLICT")`` when two secret
    nodes bind the same slot on the same task, rather than picking one.
    """
    if not isinstance(flow, Mapping) or not node_id:
        return {}
    nodes = flow.get("nodes") or []
    secrets = {node.get("id"): node for node in nodes if is_secret_node(node) and node.get("id")}
    if not secrets:
        return {}
    wired = {
        source
        for source, target in (
            _edge_ends(edge) for edge in (flow.get("edges") or []) if _is_data_edge(edge)
        )
        if target == node_id and source in secrets
    }
    grants: dict[str, str] = {}
    for secret_id in sorted(wired):
        config = secrets[secret_id].get("config") or {}
        ref = config.get("secret_ref") if isinstance(config, Mapping) else None
        bindings = config.get("bindings") if isinstance(config, Mapping) else None
        slot = bindings.get(node_id) if isinstance(bindings, Mapping) else None
        if not isinstance(ref, str) or not isinstance(slot, str) or not slot.strip():
            continue
        slot = slot.strip()
        if slot in grants and grants[slot] != ref:
            raise SecretRegistryError("SECRET_SLOT_CONFLICT", f"slot {slot!r} bound twice")
        grants[slot] = ref
    return grants


def granted_slots(node_config: Any) -> list[str]:
    """Pool marker for a ``secret`` node: slot names only, never refs or values."""
    bindings = node_config.get("bindings") if isinstance(node_config, Mapping) else None
    if not isinstance(bindings, Mapping):
        return []
    return sorted(
        {slot.strip() for slot in bindings.values() if isinstance(slot, str) and slot.strip()}
    )


class SecretGrants:
    """On-demand, slot-scoped access to the secrets granted to one task node."""

    __slots__ = ("_db", "_bindings", "_consumer", "_cache")

    def __init__(self, db, bindings: Mapping[str, str], consumer: SecretConsumer) -> None:
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_bindings", dict(bindings))
        object.__setattr__(self, "_consumer", consumer)
        object.__setattr__(self, "_cache", {})

    def __setattr__(self, name, value):  # noqa: ANN001
        raise AttributeError("SecretGrants is immutable")

    def slots(self) -> list[str]:
        return sorted(self._bindings)

    def __contains__(self, slot: object) -> bool:
        return slot in self._bindings

    def __bool__(self) -> bool:
        return bool(self._bindings)

    def get(self, slot: str) -> SecretValue:
        if slot not in self._bindings:
            raise SecretRegistryError("SECRET_NOT_GRANTED", f"slot {slot!r} not granted")
        cached = self._cache.get(slot)
        if cached is not None:
            return cached
        from app.services.secrets import resolve

        value = resolve(self._db, self._bindings[slot], consumer=self._consumer)
        remember(self._consumer.run_id, value)
        self._cache[slot] = value
        return value

    def __repr__(self) -> str:
        return f"SecretGrants(slots={self.slots()})"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("SecretGrants cannot be pickled")

    def __reduce_ex__(self, protocol):  # noqa: ANN001
        raise TypeError("SecretGrants cannot be pickled")

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):  # noqa: ANN001
        return self


def build_grants(
    db,
    flow: Any,
    *,
    node_id: str | None,
    run_id: str | None,
    workspace_id: str | None,
    system_id: str | None,
) -> SecretGrants:
    bindings = secret_bindings_for(flow, node_id)
    for ref in bindings.values():
        parse_ref(ref)
    return SecretGrants(
        db,
        bindings,
        SecretConsumer(
            kind="flow_node",
            id=str(node_id or ""),
            workspace_id=workspace_id,
            system_id=system_id,
            run_id=run_id,
            node_id=node_id,
        ),
    )


# --------------------------------------------------------------------------- redaction


def remember(run_id: str | None, value: SecretValue) -> None:
    clear = value.reveal()
    if len(clear) < _MIN_REDACT_LENGTH:
        return
    key = run_id or ""
    with _lock:
        bucket = _revealed.setdefault(key, set())
        bucket.add(clear)
        _revealed.move_to_end(key)
        while len(_revealed) > _MAX_TRACKED_RUNS:
            _revealed.popitem(last=False)


def forget(run_id: str | None) -> None:
    with _lock:
        _revealed.pop(run_id or "", None)


def _known_values() -> list[str]:
    with _lock:
        values = {value for bucket in _revealed.values() for value in bucket}
    return sorted(values, key=len, reverse=True)


def _redact_str(text: str, values: list[str]) -> str:
    for value in values:
        if value in text:
            text = text.replace(value, MASK)
    return text


def _redact(value: Any, values: list[str]) -> Any:
    if isinstance(value, SecretValue):
        return MASK
    if isinstance(value, SecretGrants):
        return repr(value)
    if isinstance(value, str):
        return _redact_str(value, values) if values else value
    if isinstance(value, dict):
        clean = {
            (_redact_str(k, values) if isinstance(k, str) and values else k): _redact(v, values)
            for k, v in value.items()
        }
        unchanged = len(clean) == len(value) and all(
            k in value and clean[k] is value[k] for k in clean
        )
        return value if unchanged else clean
    if isinstance(value, list | tuple):
        items = [_redact(item, values) for item in value]
        if all(new is old for new, old in zip(items, value)):
            return value
        return items
    return value


def redact(value: Any) -> Any:
    """Copy ``value`` with secret objects masked and revealed values replaced by ``***``."""
    return _redact(value, _known_values())


__all__ = [
    "CTX_KEY",
    "SECRET_NODE_KIND",
    "SecretGrants",
    "build_grants",
    "forget",
    "granted_slots",
    "is_secret_node",
    "redact",
    "remember",
    "secret_bindings_for",
]
