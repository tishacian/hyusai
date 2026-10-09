"""Dataset conversion runs on the tabular plane without Hub credentials."""

from app.workers.celery_app import celery_app


@celery_app.task(name="agentium.hf_dataset_materialize", acks_late=True, reject_on_worker_lost=True)
def hf_dataset_materialize(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.datasets import run_dataset_import

    with SessionLocal() as db:
        return run_dataset_import(db, job_id)


@celery_app.task(name="agentium.hf_bundle_dataset_import", acks_late=True)
def hf_bundle_dataset_import(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.offline import run_bundle_job

    with SessionLocal() as db:
        return run_bundle_job(db, job_id)


@celery_app.task(name="agentium.hf_bundle_dataset_export", acks_late=True)
def hf_bundle_dataset_export(job_id: str) -> dict:
    from app.db.base import SessionLocal
    from app.services.huggingface.offline import run_bundle_job

    with SessionLocal() as db:
        return run_bundle_job(db, job_id)
