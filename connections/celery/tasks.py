from connections.celery.app import app
from connections.celery.custom_task_class import CustomTask
from connections.payload_models.flow_operations import (
    IngestDocumentsPayload,
    SharePointSyncPayload,
    SharePointSyncResult,
)


@app.task(name="ingest_documents", bind=True)
def ingest_documents(self: CustomTask, payload: dict):
    from src.services.ingest_documents import IngestDocumentsService

    validated_payload = IngestDocumentsPayload.model_validate(payload)
    IngestDocumentsService(celery_task=self).call(validated_payload)


@app.task(name="sharepoint_otp_sync", bind=True)
def sharepoint_otp_sync(self: CustomTask, payload: dict) -> dict:
    """Run an incremental sync of a SharePoint shared folder.

    Returns a :class:`SharePointSyncResult` as dict. When the worker cannot
    authenticate silently it returns ``status="login_required"`` (the UI is
    expected to invite the user to rerun the interactive flow from the
    frontend) rather than retrying the task, which would just waste cycles.
    """
    from backend.app.services.connectors.sharepoint_otp.celery_service import (
        run_sync_from_payload,
    )

    validated_payload = SharePointSyncPayload.model_validate(payload)
    self.update_progress(
        f"sharepoint_otp_sync start key={validated_payload.session_key}"
    )

    outcome = run_sync_from_payload(
        validated_payload,
        progress=self.update_progress,
    )

    if outcome.status == "login_required":
        result = SharePointSyncResult(
            status="login_required",
            login_required_detail=outcome.login_required_detail,
        )
    elif outcome.status == "completed":
        ingestion = outcome.result
        assert ingestion is not None
        result = SharePointSyncResult(
            status="completed",
            files_total=ingestion.files_total,
            files_downloaded=ingestion.files_downloaded,
            bytes_total=ingestion.bytes_total,
            downloaded_paths=[str(p) for p in ingestion.downloaded_paths],
            skipped_paths=[str(p) for p in ingestion.skipped_paths],
            pruned_paths=[str(p) for p in ingestion.pruned_paths],
        )
    else:
        result = SharePointSyncResult(status="failed", error=outcome.error)

    return result.model_dump(mode="json")
