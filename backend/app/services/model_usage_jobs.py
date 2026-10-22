"""Trusted usage scope for standalone jobs, including eager worker execution."""

from contextlib import contextmanager
from functools import wraps

from app.db.base import SessionLocal
from app.models.knowledge_collection import WorkerJob
from app.models.workspace_job import WorkspaceJob
from app.services.model_usage import UsageContext


@contextmanager
def job_usage_scope(job_id, *, kind="workspace", purpose="generation", traffic="business"):
    from app.services.model_usage_transport import usage_scope

    with SessionLocal() as db:
        row = db.get(WorkspaceJob if kind == "workspace" else WorkerJob, job_id)
        if row is None:
            context = None
        elif kind == "workspace":
            context = UsageContext(
                row.workspace_id,
                system_id=row.system_id,
                run_id=row.run_id,
                job_id=row.id,
                actor_user_id=row.created_by_user_id,
                purpose=purpose,
                traffic=traffic,
            )
        else:
            context = UsageContext(
                row.workspace_id, worker_job_id=row.id, purpose=purpose, traffic=traffic
            )
    if context is None:
        # Native job entrypoints own their missing/deleted-job response. They
        # cannot load inputs or dispatch a provider for a nonexistent job.
        yield
        return
    with usage_scope(context, key=f"{kind}-job:{job_id}"):
        yield


def tracked_job(*, kind="workspace", purpose="generation", traffic="business"):
    def decorate(fn):
        @wraps(fn)
        def execute(job_id, *args, **kwargs):
            with job_usage_scope(job_id, kind=kind, purpose=purpose, traffic=traffic):
                return fn(job_id, *args, **kwargs)

        return execute

    return decorate
