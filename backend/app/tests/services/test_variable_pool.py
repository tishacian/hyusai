"""Pure-logic tests for the P1 typed VariablePool + selector resolution.

No database — these exercise ``variable_pool`` directly: selector
normalisation across the three accepted shapes (dot-path string, typed
``VariableRef``, raw ``[head, *path]`` list), reads/writes, the inputs/outputs
map round-trip, and the critical empty-map byte-identity contract.
"""
from __future__ import annotations

from app.services.run_engine.variable_pool import (
    RESERVED_NAMESPACES,
    VariablePool,
    apply_inputs_map,
    apply_outputs_map,
    resolve_selector,
    selector_segments,
)


# ---------------------------------------------------------------------------
# selector_segments — the three accepted shapes normalise identically
# ---------------------------------------------------------------------------
def test_selector_segments_dot_path_string() -> None:
    assert selector_segments("session.objective") == ["session", "objective"]
    assert selector_segments("turn.audio_ref") == ["turn", "audio_ref"]
    assert selector_segments("solo") == ["solo"]


def test_selector_segments_typed_ref() -> None:
    ref = {"node_id": "n1", "path": ["sources", "0", "id"]}
    assert selector_segments(ref) == ["n1", "sources", "0", "id"]
    # A ref with an empty path is just the node id.
    assert selector_segments({"node_id": "run", "path": []}) == ["run"]


def test_selector_segments_raw_list() -> None:
    assert selector_segments(["capture", "gaps"]) == ["capture", "gaps"]


def test_selector_segments_rejects_malformed() -> None:
    assert selector_segments("") is None
    assert selector_segments(None) is None
    assert selector_segments({"path": ["x"]}) is None  # no node_id
    assert selector_segments({"node_id": "", "path": []}) is None
    assert selector_segments([]) is None


# ---------------------------------------------------------------------------
# VariablePool get / set
# ---------------------------------------------------------------------------
def test_pool_set_get_nested_dot_path() -> None:
    pool = VariablePool()
    pool.set("capture.gaps", ["g1", "g2"])
    assert pool.get("capture.gaps") == ["g1", "g2"]
    assert pool.get(["capture", "gaps"]) == ["g1", "g2"]
    assert pool.get({"node_id": "capture", "path": ["gaps"]}) == ["g1", "g2"]


def test_pool_get_missing_returns_default() -> None:
    pool = VariablePool()
    assert pool.get("nope.nada") is None
    assert pool.get("nope.nada", default="fallback") == "fallback"
    assert pool.has("nope.nada") is False


def test_pool_get_list_index_navigation() -> None:
    pool = VariablePool({"n1": {"sources": [{"id": "a"}, {"id": "b"}]}})
    assert pool.get(["n1", "sources", "0", "id"]) == "a"
    assert pool.get(["n1", "sources", "1", "id"]) == "b"
    assert pool.get(["n1", "sources", "5", "id"]) is None  # out of range


def test_pool_set_namespace_merges() -> None:
    pool = VariablePool()
    pool.set_namespace("system", {"id": "s1", "default_model": "gpt"})
    pool.set_namespace("system", {"default_model": "claude", "extra": 1})
    assert pool.get("system.id") == "s1"
    assert pool.get("system.default_model") == "claude"
    assert pool.get("system.extra") == 1


def test_reserved_namespaces_constant() -> None:
    assert set(RESERVED_NAMESPACES) == {"workspace", "system", "run", "node"}


# ---------------------------------------------------------------------------
# round-trip serialisation
# ---------------------------------------------------------------------------
def test_pool_to_from_dict_round_trip() -> None:
    pool = VariablePool()
    pool.set("run.query", "hello")
    pool.set("n1.answer", {"text": "hi"})
    payload = pool.to_dict()
    restored = VariablePool.from_dict(payload)
    assert restored.get("run.query") == "hello"
    assert restored.get("n1.answer") == {"text": "hi"}
    # to_dict is a deep copy — mutating it must not leak back into the pool.
    payload["run"]["query"] = "mutated"
    assert pool.get("run.query") == "hello"


# ---------------------------------------------------------------------------
# apply_inputs_map — empty maps are byte-identical; present maps overlay
# ---------------------------------------------------------------------------
def test_apply_inputs_map_empty_returns_predecessor_verbatim() -> None:
    merge = {"answer": "x", "n": 3}
    assert apply_inputs_map({}, VariablePool(), merge) == merge
    assert apply_inputs_map({"inputs_map": {}}, VariablePool(), merge) == merge
    assert apply_inputs_map(None, VariablePool(), merge) == merge
    # A copy is returned (caller can't corrupt the predecessor merge).
    out = apply_inputs_map({}, VariablePool(), merge)
    out["answer"] = "mutated"
    assert merge["answer"] == "x"


def test_apply_inputs_map_overlays_resolved_selectors() -> None:
    pool = VariablePool()
    pool.set("session.objective", "ship it")
    pool.set("capture.gaps", ["g1"])
    config = {
        "inputs_map": {
            "objective": "session.objective",
            "gaps": "capture.gaps",
        }
    }
    resolved = apply_inputs_map(config, pool, {"context": "base"})
    assert resolved["objective"] == "ship it"
    assert resolved["gaps"] == ["g1"]
    # Unmapped predecessor fields still flow through.
    assert resolved["context"] == "base"


def test_apply_inputs_map_typed_ref_selector() -> None:
    pool = VariablePool()
    pool.set_namespace("n1", {"answer": "typed-hit"})
    config = {"inputs_map": {"answer": {"node_id": "n1", "path": ["answer"]}}}
    assert apply_inputs_map(config, pool, {})["answer"] == "typed-hit"


def test_apply_inputs_map_missing_selector_does_not_clobber_merge() -> None:
    # A selector that doesn't resolve must leave the predecessor value intact
    # rather than overwriting it with None.
    config = {"inputs_map": {"answer": "ghost.path"}}
    resolved = apply_inputs_map(config, VariablePool(), {"answer": "kept"})
    assert resolved["answer"] == "kept"


# ---------------------------------------------------------------------------
# apply_outputs_map — empty is a no-op; present writes namespaced slices
# ---------------------------------------------------------------------------
def test_apply_outputs_map_empty_is_noop() -> None:
    pool = VariablePool()
    apply_outputs_map({}, {"gaps": ["g1"]}, pool)
    apply_outputs_map({"outputs_map": {}}, {"gaps": ["g1"]}, pool)
    assert pool.to_dict() == {}


def test_apply_outputs_map_writes_targets() -> None:
    pool = VariablePool()
    config = {"outputs_map": {"gaps": "capture.gaps", "plan": "capture.plan"}}
    apply_outputs_map(config, {"gaps": ["g1", "g2"], "plan": "P"}, pool)
    assert pool.get("capture.gaps") == ["g1", "g2"]
    assert pool.get("capture.plan") == "P"


def test_apply_outputs_map_skips_absent_ports() -> None:
    pool = VariablePool()
    config = {"outputs_map": {"gaps": "capture.gaps", "missing": "capture.missing"}}
    apply_outputs_map(config, {"gaps": ["g1"]}, pool)
    assert pool.get("capture.gaps") == ["g1"]
    assert pool.has("capture.missing") is False


# ---------------------------------------------------------------------------
# end-to-end maps round-trip (write then read through the pool)
# ---------------------------------------------------------------------------
def test_outputs_then_inputs_map_round_trip() -> None:
    pool = VariablePool()
    # Producer node writes its output via outputs_map.
    apply_outputs_map({"outputs_map": {"gaps": "capture.gaps"}}, {"gaps": ["g1"]}, pool)
    # Consumer node reads it back via inputs_map.
    resolved = apply_inputs_map(
        {"inputs_map": {"gaps": "capture.gaps"}}, pool, {}
    )
    assert resolved["gaps"] == ["g1"]


def test_resolve_selector_helper() -> None:
    pool = VariablePool({"run": {"query": "q"}})
    assert resolve_selector("run.query", pool) == "q"
    assert resolve_selector(["run", "query"], pool) == "q"
    assert resolve_selector({"node_id": "run", "path": ["query"]}, pool) == "q"
    assert resolve_selector("run.missing", pool, default="d") == "d"
