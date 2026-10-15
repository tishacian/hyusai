"""Official LangGraph–Temporal candidate; Temporal owns durable graph replay."""

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from temporalio.common import RetryPolicy
    from temporalio.langgraph import LangGraphPlugin, graph

    from .compositions import COMPOSITIONS, build_graph


@workflow.defn
class ComposedNativeWorkflow:
    def __init__(self):
        self.generation = 0
        self.waiting = False

    @workflow.signal
    def native_changed(self):
        self.generation += 1  # wake only; no caller-supplied approval/state

    @workflow.query
    def awaiting_native(self) -> bool:
        return self.waiting

    @workflow.run
    async def run(self, request: dict) -> dict:
        application = graph(request["composition"]).compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": request["scope"]["run_id"]}}
        payload = {"scope": request["scope"], "references": {}}
        while True:
            generation = self.generation
            result = await application.ainvoke(payload, config)
            if not result.get("__interrupt__"):
                return {"references": result["references"]}
            self.waiting = True
            await workflow.wait_condition(lambda: self.generation > generation)
            self.waiting = False
            payload = Command(resume=True)


def plugin():
    return LangGraphPlugin(
        graphs={name: build_graph(name) for name in COMPOSITIONS},
        default_activity_options={
            "start_to_close_timeout": timedelta(seconds=10),
            "retry_policy": RetryPolicy(
                maximum_attempts=3, initial_interval=timedelta(milliseconds=100)
            ),
        },
    )
