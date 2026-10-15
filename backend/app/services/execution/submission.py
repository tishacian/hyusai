"""Freeze execution policy at an already-authorized Run ingress."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException

from app.core.config import settings

from .contracts import ExecutionPolicy
from .dispatch import stage
from .rollout import durable_for, enabled_for


def stage_run(db, run, system, *, business_deadline=None):
    profile = system.execution_profile if isinstance(system.execution_profile, dict) else {}
    orchestration = profile.get("orchestration")
    if orchestration is not None:
        if not (
            isinstance(orchestration, dict)
            and orchestration.get("engine") == "temporal"
            and enabled_for(db, run.workspace_id, "execution_temporal_enabled")
            and durable_for(db, run.workspace_id)
        ):
            raise HTTPException(409, detail="EXECUTION_NATIVE_CANDIDATE_UNAVAILABLE")
        from .runtimes.native_profile import freeze_profile

        try:
            frozen = freeze_profile(run, {k: v for k, v in orchestration.items() if k != "engine"})
            timeout = min(
                float(frozen["max_runtime_s"]),
                float(profile.get("max_runtime_s") or frozen["max_runtime_s"]),
            )
            if not 1 <= timeout <= 86400:
                raise ValueError("deadline outside the candidate limit")
        except (TypeError, ValueError) as exc:
            raise HTTPException(409, detail="EXECUTION_NATIVE_PROFILE_INVALID") from exc
        digest = sha256(
            json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        deadline = datetime.now(UTC) + timedelta(seconds=timeout)
        if business_deadline is not None:
            deadline = min(
                deadline,
                business_deadline.replace(tzinfo=UTC)
                if business_deadline.tzinfo is None
                else business_deadline.astimezone(UTC),
            )
        if deadline <= datetime.now(UTC):
            raise HTTPException(409, detail="EXECUTION_NATIVE_DEADLINE_EXCEEDED")
        policy = ExecutionPolicy(
            engine="temporal",
            runtime_revision=settings.agentium_image_revision,
            deadline_at=deadline,
            attempt_timeout_s=timeout,
            response_wait_s=settings.execution_http_wait_s,
            native_profile=frozen,
            native_profile_digest=digest,
        )
        run.execution_policy = policy.model_dump(mode="json")
        stage(db, "run", run, deadline_at=policy.deadline_at.replace(tzinfo=None))
        return True
    if not durable_for(db, run.workspace_id):
        return False
    try:
        timeout = float(profile.get("max_runtime_s") or 40)
    except (TypeError, ValueError):
        timeout = 40
    # Existing walker retains its bounded execution semantics. Long durable
    # waits require the qualified runtime, never an inflated in-process timeout.
    timeout = max(1, min(44, timeout))
    policy = ExecutionPolicy(
        runtime_revision=settings.agentium_image_revision,
        deadline_at=datetime.now(UTC) + timedelta(seconds=timeout),
        attempt_timeout_s=timeout,
        response_wait_s=settings.execution_http_wait_s,
    )
    run.execution_policy = policy.model_dump(mode="json")
    stage(db, "run", run, deadline_at=policy.deadline_at.replace(tzinfo=None))
    return True
