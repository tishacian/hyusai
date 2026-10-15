"""Identifier-only boundary; execution state remains with native authorities."""

from dataclasses import asdict, dataclass
from typing import Literal, Protocol

NativeKind = Literal[
    "run", "recipe_execution", "compute_run", "ml_training", "decision", "delivery_receipt"
]


@dataclass(frozen=True)
class ExecutionScope:
    workspace_id: str
    run_id: str
    actor_id: str
    version_id: str
    flow_digest: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class NativeReference:
    kind: NativeKind
    id: str
    workspace_id: str
    run_id: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class NativeState:
    status: Literal[
        "pending", "running", "waiting", "succeeded", "failed", "cancelled", "timed_out", "lost"
    ]
    reference: NativeReference


class NativePort(Protocol):
    """The future production submitter must atomically enforce its stable key.

    Authorization and frozen-contract checks run on EVERY invocation, including
    retries/resumes. Signals merely wake a graph; they never approve a Decision.
    No production implementation of submit exists until native invocation
    identities and uncertain external effects have passed the same fault corpus.
    """

    async def authorize(self, scope: ExecutionScope) -> None: ...
    async def submit(
        self, scope: ExecutionScope, node_id: str, operation_key: str
    ) -> NativeReference: ...
    async def observe(self, scope: ExecutionScope, reference: NativeReference) -> NativeState: ...


_port: NativePort | None = None


def configure_port(port: NativePort | None):
    global _port
    _port = port


def native_port() -> NativePort:
    if _port is None:
        raise RuntimeError("NATIVE_SUBMISSION_ADAPTER_UNQUALIFIED")
    return _port
