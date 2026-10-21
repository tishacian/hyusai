# Durable mission executions

The UI/UX plan (20 October 2026, lot 7) separates composing a mission from starting it. The previous streaming request owned the execution and overwrote the last deliverable when relaunched.

Each explicit launch creates a `task_executions` row containing the frozen objective, historical agent reference when present, creator, progress, steps and artifacts. Historical task rows remain readable; their old `running` state is unverified because no durable execution can attest it. Existing artifacts are retained on the task and each new attempt keeps its own artifact snapshot. An interrupted execution is resumed explicitly under the same identifier, continuing after completed steps. A new launch is a separate attempt and requires confirmation when earlier work exists.

The database is the dispatch ledger. Queued rows are sent to the general Celery queue and periodically redispatched until claimed. Workers claim with a fenced lease, renew it while the model responds, and persist each event before exposing it. Duplicate delivery cannot claim a live lease. Expiry changes the execution to interrupted, preserving its last checkpoint; the recovery task does not silently rerun it. A previous worker loses permission to write after its lease expires or a new owner claims it.

The HTTP stream only observes persisted events. Disconnecting the browser cannot cancel the worker. Task and execution endpoints require the current workspace and user membership; every lookup includes the workspace identifier. Streams recheck membership on each poll, so revocation stops disclosure. Payloads are not sent to Celery: dispatch contains only the execution identifier.

Migration 143 creates one table after 142; it does not rewrite existing task rows. Rollback removes the execution history, so export it before downgrading. Deployment requires applying the migration and restarting both the general worker and scheduler. Until the worker claims a queued execution, the interface says queued, never running or completed.

Validation covers claim duplication, expired fences, interrupted resumption, separate attempts, checkpoint preservation, workspace isolation and missing-task 404. Model calls are mocked; no paid model or production workspace is used by the tests.


## Lease and external-effect limits

Heartbeat renewal now checks membership and write eligibility as well as the fence and unexpired lease. Revocation increments the fence, fails both the attempt and its parent task, and preserves completed checkpoints. A response from an older worker cannot publish an artifact afterward.

This is persistence fencing, not exactly-once provider execution. The existing mission engine generates text through model calls; it does not execute the selected System flow or invoke external connector actions. A worker can die after a model provider processed a request but before its checkpoint is committed. Explicit resume can repeat that unfinished model call and its billing. Completed checkpoints are skipped. A provider call already in flight cannot be retracted on permission revocation. External mutating tools must not be added to this engine without a separate durable per-step idempotency and receipt contract.

The UI explicitly presents an LLM drafting assistant and no longer offers a System selector. Creation rejects a non-null `agent_id` with `MISSION_SYSTEM_EXECUTION_UNSUPPORTED`; legacy agent references are labelled historical. This keeps review aligned with what the engine actually executes. PostgreSQL concurrency, real Celery dispatch/worker termination and browser disconnection are deployment checks still required; the current tests exercise SQLite lifecycle transitions and mocked model output.
