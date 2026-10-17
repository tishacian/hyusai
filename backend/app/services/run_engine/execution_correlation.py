"""Task-local observation identities. These never dispatch or retry work."""

from contextvars import ContextVar

# Async siblings must never borrow one another's node/passages.
passage_context: ContextVar[dict | None] = ContextVar("execution_passage", default=None)


def current_passage(run_id: str, node_id: str | None) -> dict:
    value = passage_context.get()
    if value and value["run_id"] == run_id and value["node_id"] == node_id:
        return {"passage_id": value["passage_id"]}
    return {}


def persisted_passage(run, node_id):
    """Restore correlation after a durable wait; no process memory is required."""
    for checkpoint in reversed(run.checkpoints or []):
        if (
            isinstance(checkpoint, dict)
            and checkpoint.get("node_id") == node_id
            and checkpoint.get("passage_id")
        ):
            return checkpoint["passage_id"]
    return None


def resumable_passage(run, node_id):
    for checkpoint in reversed(run.checkpoints or []):
        if isinstance(checkpoint, dict) and checkpoint.get("node_id") == node_id:
            return (
                checkpoint.get("passage_id")
                if checkpoint.get("kind")
                in {"hitl_resume", "subflow_wait", "subflow_resume", "debug_resume"}
                else None
            )
    return None
