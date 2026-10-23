"""Closed catalog of the commands a runner may execute.

A command is registered in code, reviewed like any other code, and a runner
lists the keys it accepts. A job carries a key and parameters validated by the
command's pydantic model; ``build`` turns them into an argv list. No shell
string ever comes from a workspace: the transport quotes each argument.

Conventions a command may follow, inside its own job directory:

* ``result.json``: a JSON object read back as the job result (bounded size);
* any path listed in ``artifacts`` is copied to the object store after success.

Where a program lives on the machine (a checkout, an interpreter) is runner
configuration, not job input: a command lists the runner labels it needs in
``runner_paths`` and ``build`` receives them, checked as absolute paths.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Risk = Literal["read", "compute", "write"]
Mode = Literal["sync", "detached"]

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")


class CatalogError(ValueError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        super().__init__(detail or code)


@dataclass(frozen=True)
class CommandSpec:
    key: str
    title: str
    risk: Risk
    mode: Mode
    params: type[BaseModel]
    build: Callable[[BaseModel, dict[str, str]], list[str]]
    artifacts: tuple[str, ...] = ()
    runner_paths: tuple[str, ...] = ()
    timeout_s: int = 3600
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def view(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "risk": self.risk,
            "mode": self.mode,
            "timeout_s": self.timeout_s,
            "artifacts": list(self.artifacts),
            "description": self.description,
            "tags": list(self.tags),
            "runner_paths": list(self.runner_paths),
            "params_schema": self.params.model_json_schema(),
        }


_REGISTRY: dict[str, CommandSpec] = {}


def register(spec: CommandSpec) -> CommandSpec:
    if not _KEY_RE.match(spec.key):
        raise CatalogError("REMOTE_COMMAND_KEY_INVALID", spec.key)
    existing = _REGISTRY.get(spec.key)
    if existing is not None and existing is not spec:
        raise CatalogError("REMOTE_COMMAND_DUPLICATE", spec.key)
    for path in spec.artifacts:
        _check_relative(path)
    _REGISTRY[spec.key] = spec
    return spec


def get(key: str) -> CommandSpec:
    spec = _REGISTRY.get(key)
    if spec is None:
        raise CatalogError("REMOTE_COMMAND_UNKNOWN", key)
    return spec


def all_commands() -> list[CommandSpec]:
    return sorted(_REGISTRY.values(), key=lambda spec: spec.key)


def validate(
    key: str, params: dict | None, labels: dict | None = None
) -> tuple[CommandSpec, BaseModel, list[str]]:
    """Return the spec, the validated parameters and the argv they build."""

    spec = get(key)
    paths = runner_paths(spec, labels or {})
    if params is not None and not isinstance(params, dict):
        raise CatalogError("REMOTE_COMMAND_PARAMS_INVALID", "params must be an object")
    try:
        model = spec.params.model_validate(params or {})
    except Exception as exc:  # pydantic ValidationError, kept generic for the API
        raise CatalogError("REMOTE_COMMAND_PARAMS_INVALID", str(exc)) from None
    argv = spec.build(model, paths)
    if not argv or not all(isinstance(item, str) and "\x00" not in item for item in argv):
        raise CatalogError("REMOTE_COMMAND_ARGV_INVALID", key)
    return spec, model, argv


def runner_paths(spec: CommandSpec, labels: dict) -> dict[str, str]:
    """The runner labels a command needs, each an absolute path without ``..``."""

    out = {}
    for name in spec.runner_paths:
        value = labels.get(name)
        if (
            not isinstance(value, str)
            or not value.startswith("/")
            or ".." in value.split("/")
            or any(ord(c) < 32 for c in value)
        ):
            raise CatalogError("REMOTE_RUNNER_PATH_LABEL_MISSING", name)
        out[name] = value
    return out


def _check_relative(path: str) -> None:
    parts = path.split("/")
    if not path or path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise CatalogError("REMOTE_COMMAND_ARTIFACT_INVALID", path)


# ---------------------------------------------------------------------------
# Built-in commands, available to every runner that lists them.
# ---------------------------------------------------------------------------


class _NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SleepParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seconds: int = Field(default=5, ge=0, le=86400)


PROBE = register(
    CommandSpec(
        key="agentium.probe",
        title="Probe the runner",
        risk="read",
        mode="sync",
        params=_NoParams,
        # nvidia-smi is optional: its absence leaves an empty GPU list, not a failure.
        build=lambda _p, _r: [
            "sh",
            "-c",
            "uname -srm; nproc 2>/dev/null || echo 0; "
            "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu "
            "--format=csv,noheader,nounits 2>/dev/null || true",
        ],
        timeout_s=30,
        description="Kernel, CPU count and GPU usage, read without side effects.",
    )
)

SLEEP = register(
    CommandSpec(
        key="agentium.sleep",
        title="Sleep (qualification)",
        risk="compute",
        mode="detached",
        params=_SleepParams,
        build=lambda p, _r: ["sleep", str(p.seconds)],
        timeout_s=86400,
        description="A detached job that does nothing for a while; used to qualify a runner.",
        tags=("qualification",),
    )
)


def parse_probe(stdout: str) -> dict:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    kernel = lines[0] if lines else ""
    try:
        cpus = int(lines[1]) if len(lines) > 1 else 0
    except ValueError:
        cpus = 0
    gpus = []
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) != 5:
            continue
        try:
            gpus.append(
                {
                    "index": int(cells[0]),
                    "name": cells[1],
                    "memory_used_mb": int(float(cells[2])),
                    "memory_total_mb": int(float(cells[3])),
                    "utilization_pct": int(float(cells[4])),
                }
            )
        except ValueError:
            continue
    return {"kernel": kernel, "cpus": cpus, "gpus": gpus}
