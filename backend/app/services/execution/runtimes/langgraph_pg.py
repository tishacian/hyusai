"""Autonomous LangGraph candidate: PostgreSQL is the only checkpoint authority."""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from .compositions import build_graph
from .contracts import ExecutionScope


async def invoke(dsn: str, composition: str, scope: ExecutionScope, *, resume=False, recover=False):
    # This deliberately does not introduce an Agentium scheduler. A persistent
    # checkpoint alone does not arrange dispatch/recovery after worker failure.
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        graph = build_graph(composition).compile(checkpointer=saver)
        config = {"configurable": {"thread_id": scope.run_id, "checkpoint_ns": ""}}
        payload = (
            None
            if recover
            else Command(resume=True)
            if resume
            else {"scope": scope.to_dict(), "references": {}}
        )
        return await graph.ainvoke(payload, config)
