"""Canonical validation for Flow debugger controls.

Debugger configuration is accepted by several HTTP adapters.  Keeping the
validation here prevents a looser adapter from smuggling an unbounded or
runtime-incompatible ``_debug`` envelope into a Run.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_DEBUG_BREAKPOINTS = 256
MAX_DEBUG_BREAKPOINT_LENGTH = 128
_DEBUG_MODES = frozenset({"step", "breakpoints"})
_DEBUG_KEYS = frozenset({"mode", "breakpoints"})


@dataclass(frozen=True, slots=True)
class DebugContractError(ValueError):
    code: str
    message: str
    path: str = "_debug"


def normalize_debug_config(
    raw: Any,
    *,
    runtime_mode: str | None = None,
) -> dict[str, Any]:
    """Return a bounded canonical debugger envelope or fail closed."""

    if not isinstance(raw, Mapping):
        raise DebugContractError(
            "RUN_DEBUG_INVALID",
            "_debug must be an object.",
        )
    unknown = sorted(str(key) for key in raw if key not in _DEBUG_KEYS)
    if unknown:
        raise DebugContractError(
            "RUN_DEBUG_INVALID",
            "_debug contains unsupported fields.",
            "_debug." + unknown[0],
        )
    mode = raw.get("mode")
    if not isinstance(mode, str) or mode not in _DEBUG_MODES:
        raise DebugContractError(
            "RUN_DEBUG_INVALID",
            "_debug.mode must be 'step' or 'breakpoints'.",
            "_debug.mode",
        )
    breakpoints = raw.get("breakpoints", [])
    if not isinstance(breakpoints, list):
        raise DebugContractError(
            "RUN_DEBUG_INVALID",
            "_debug.breakpoints must be a list of node identifiers.",
            "_debug.breakpoints",
        )
    if len(breakpoints) > MAX_DEBUG_BREAKPOINTS:
        raise DebugContractError(
            "RUN_DEBUG_INVALID",
            f"_debug.breakpoints accepts at most {MAX_DEBUG_BREAKPOINTS} entries.",
            "_debug.breakpoints",
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(breakpoints):
        if not isinstance(value, str):
            raise DebugContractError(
                "RUN_DEBUG_INVALID",
                "Every debugger breakpoint must be a string node identifier.",
                f"_debug.breakpoints.{index}",
            )
        node_id = value.strip()
        if not node_id or len(node_id) > MAX_DEBUG_BREAKPOINT_LENGTH:
            raise DebugContractError(
                "RUN_DEBUG_INVALID",
                (
                    "Every debugger breakpoint must contain between 1 and "
                    f"{MAX_DEBUG_BREAKPOINT_LENGTH} characters."
                ),
                f"_debug.breakpoints.{index}",
            )
        if node_id not in seen:
            normalized.append(node_id)
            seen.add(node_id)
    if mode == "breakpoints" and not normalized:
        raise DebugContractError(
            "RUN_DEBUG_INVALID",
            "Breakpoint mode requires at least one breakpoint.",
            "_debug.breakpoints",
        )
    if runtime_mode == "sequential_legacy":
        raise DebugContractError(
            "RUN_DEBUG_REQUIRES_DAG",
            "Flow debugging is unavailable for the sequential legacy runtime.",
        )
    return {"mode": mode, "breakpoints": copy.deepcopy(normalized)}


def normalize_input_debug(
    input_ref: Mapping[str, Any],
    *,
    runtime_mode: str | None = None,
) -> dict[str, Any]:
    """Deep-copy an input envelope and normalize its optional debug control."""

    normalized = copy.deepcopy(dict(input_ref))
    if "_debug" in normalized:
        normalized["_debug"] = normalize_debug_config(
            normalized["_debug"],
            runtime_mode=runtime_mode,
        )
    return normalized
