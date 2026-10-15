"""Temporal SDK-only candidate. No LangGraph/plugin and no legacy DAG Activity."""

import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError


class NativeActivities:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def _call(self, name, request, role=None):
        from . import native_port

        try:
            with self.session_factory() as db:
                function = getattr(native_port, name)
                if name == "submit":
                    return await function(db, request, role)
                return function(db, request, role) if role is not None else function(db, request)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider/config/input exception details stay outside Temporal's
            # history. Native ledgers contain their redacted, scoped evidence.
            raise ApplicationError("NATIVE_AUTHORITY_REFUSED", non_retryable=True) from None

    @activity.defn(name="agentium.native.begin.v1")
    async def begin(self, request: dict) -> dict:
        return await self._call("begin", request)

    @activity.defn(name="agentium.native.submit.v1")
    async def submit(self, arguments: dict) -> dict:
        return await self._call("submit", arguments["request"], arguments["role"])

    @activity.defn(name="agentium.native.observe.v1")
    async def observe(self, arguments: dict) -> dict:
        return await self._call("observe", arguments["request"], arguments["role"])

    @activity.defn(name="agentium.native.uncertain.v1")
    async def uncertain(self, arguments: dict) -> dict:
        return await self._call("uncertain", arguments["request"], arguments["role"])

    @activity.defn(name="agentium.native.fail.v1")
    async def fail(self, request: dict) -> dict:
        return await self._call("fail", request)

    def registered(self):
        return [self.begin, self.submit, self.observe, self.uncertain, self.fail]


@workflow.defn(name="AgentiumNativeWorkflowV1")
class NativeWorkflow:
    def __init__(self):
        self.generation = 0

    @workflow.signal
    def native_change(self):
        # No approval, output or state can be supplied through a signal.
        self.generation += 1

    async def _read(self, operation, arguments):
        return await workflow.execute_activity(
            f"agentium.native.{operation}.v1",
            arguments,
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    @workflow.run
    async def run(self, request: dict, start_index: int = 0) -> dict:
        polls = 0
        try:
            configuration = await self._read("begin", request)
            roles = configuration["roles"]
            result = None
            for index in range(start_index, len(roles)):
                arguments = {"request": request, "role": roles[index]}
                try:
                    result = await workflow.execute_activity(
                        "agentium.native.submit.v1",
                        arguments,
                        start_to_close_timeout=timedelta(seconds=300),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except ActivityError:
                    # A lost provider reply never causes a second invocation.
                    result = await self._read("uncertain", arguments)
                while result["status"] in {"pending", "running", "waiting"}:
                    generation = self.generation
                    try:
                        await workflow.wait_condition(
                            lambda: self.generation != generation,
                            timeout=timedelta(seconds=configuration["poll_interval_s"]),
                        )
                    except TimeoutError:
                        pass
                    result = await self._read("observe", arguments)
                    polls += 1
                    if polls >= 400 and result["status"] in {"pending", "running", "waiting"}:
                        # Bound history without carrying context, outputs, or
                        # secrets. Re-entry reauthorizes and reads native IDs.
                        workflow.continue_as_new(args=[request, index])
                if result["status"] != "succeeded":
                    raise ApplicationError("NATIVE_STEP_FAILED", non_retryable=True)
            return result
        except (Exception, asyncio.CancelledError):
            await asyncio.shield(self._read("fail", request))
            raise
