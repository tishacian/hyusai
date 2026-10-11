"""Canonical Run engine — orchestrates System executions end-to-end.

Turns a persisted `Run` row into a real execution by:

* resolving the System's Capability and bundled Skills,
* invoking each Skill through `skills_registry.resolve`,
* persisting a `SkillInvocation` ledger row per call (latency, cost, status),
* aggregating an `Outcome` block (decision, confidence, value, cost, efficiency),
* applying `ControlPolicy` guardrails (max cost, max latency, HITL floor),
* consulting the `AdaptivePolicy` to decide on soft adjustments,
* writing a `Decision` row when an adaptive action or HITL escalation fires.

The engine is safe to call from a FastAPI BackgroundTask: all work happens in
a fresh DB session, and any failure is captured on the Run row so the UI can
surface it without crashing the request.
"""
from .dag import execute_run_dag, resume_run_dag, resume_run_dag_debug, should_use_dag
from .engine import execute_run, schedule_run

__all__ = [
    "execute_run",
    "execute_run_dag",
    "resume_run_dag",
    "resume_run_dag_debug",
    "schedule_run",
    "should_use_dag",
]
