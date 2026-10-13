"""Tenant/RBAC boundary for service contracts and Work receipt metadata."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.service_contract import (
    ServiceContract,
    ServiceIncident,
    ServiceWindow,
)
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.service_contract import (
    AssetRegister,
    ContractCreate,
    PublishDelivery,
    ReviewDelivery,
)
from app.services import governed_assets as assets
from app.services import service_promises as services

router = APIRouter()


def _access(db, workspace, user, *, admin=False):
    features = (workspace.settings or {}).get("features", {})
    if (
        not getattr(settings, "service_contracts_enabled", False)
        and features.get("service_contracts") is not True
    ):
        raise HTTPException(status_code=404, detail={"code": "SERVICE_CONTRACTS_DISABLED"})
    try:
        return services.require_member(db, workspace.id, user.id, admin=admin)
    except assets.GovernanceError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None


def _call(db, operation, *args, commit=False, **kwargs):
    try:
        result = operation(db, *args, **kwargs)
        if commit:
            db.commit()
        return result
    except assets.GovernanceError as exc:
        if commit:
            db.rollback()
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None


def _page(query, serialize, offset, limit):
    return {
        "items": [serialize(row) for row in query.offset(offset).limit(limit).all()],
        "total": query.count(),
        "offset": offset,
        "limit": limit,
    }


@router.get("")
def list_contracts(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    query = (
        db.query(ServiceContract)
        .filter_by(workspace_id=workspace.id)
        .order_by(ServiceContract.created_at.desc(), ServiceContract.id)
    )
    return _page(query, services.contract_public, offset, limit)


@router.post("")
def create_contract(
    body: ContractCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    row = _call(
        db,
        services.create_contract,
        workspace.id,
        body.system_id,
        body.owner_user_id,
        body.definition.model_dump(mode="json"),
        created_by=user.id,
        logical_key=body.logical_key,
        commit=True,
    )
    return services.contract_public(row)


@router.get("/windows")
def list_windows(
    contract_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    query = db.query(ServiceWindow).filter_by(workspace_id=workspace.id)
    if contract_id:
        query = query.filter_by(contract_id=contract_id)
    return _page(
        query.order_by(ServiceWindow.period_start.desc(), ServiceWindow.id),
        services.window_public,
        offset,
        limit,
    )


@router.get("/incidents")
def list_incidents(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    query = (
        db.query(ServiceIncident)
        .filter_by(workspace_id=workspace.id, owner_user_id=user.id)
        .order_by(ServiceIncident.created_at.desc(), ServiceIncident.id)
    )
    return _page(
        query,
        lambda row: {
            key: getattr(row, key)
            for key in (
                "id",
                "window_id",
                "owner_user_id",
                "code",
                "resolved",
                "created_at",
                "resolved_at",
            )
        },
        offset,
        limit,
    )


@router.get("/receipts")
def list_receipts(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return _call(
        db,
        services.list_receipts,
        workspace.id,
        user_id=user.id,
        offset=offset,
        limit=limit,
        authorize_native=assets.native_authorizer(db, workspace, user),
    )


@router.get("/receipts/{receipt_id}")
def get_receipt(
    receipt_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    row = _call(
        db,
        services.get_receipt,
        workspace.id,
        receipt_id,
        user_id=user.id,
        authorize_native=assets.native_authorizer(db, workspace, user),
    )
    return services.receipt_public(row)


@router.post("/assets")
def register_asset(
    body: AssetRegister,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    manifest_type = str(body.manifest.get("type", ""))
    if (
        manifest_type.startswith("typed_calibration_")
        or manifest_type == "typed_judge_vision_route"
    ):
        raise HTTPException(422, detail={"code": "ASSET_RESERVED_TYPE"})
    try:
        assets._native_refs(
            db, workspace.id, body.manifest, assets.native_authorizer(db, workspace, user)
        )
    except assets.GovernanceError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from None
    row = _call(
        db,
        assets.register_asset,
        workspace.id,
        body.kind,
        body.logical_key,
        body.manifest,
        [ref.model_dump() for ref in body.parents],
        body.run_id,
        commit=True,
    )
    return assets.asset_ref(row)


@router.post("/windows/{window_id}/review")
def review_window(
    window_id: str,
    body: ReviewDelivery,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    row = _call(
        db,
        services.review_delivery,
        workspace.id,
        window_id,
        reviewer_user_id=user.id,
        accept=body.accept,
        expected_fence=body.expected_fence,
        expected_asset_digest=body.expected_asset_digest,
        expected_qualification_digest=body.expected_qualification_digest,
        note=body.note,
        qualify_candidate=body.qualify_candidate,
        commit=True,
    )
    return {
        "id": row.id,
        "status": row.status,
        "binding_digest": row.rationale["binding_digest"],
        "human_confirmed_by": row.human_confirmed_by,
        "human_confirmed_at": row.human_confirmed_at,
    }


@router.get("/windows/{window_id}/candidate")
def get_candidate(
    window_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    window = _call(db, services.get_window, workspace.id, window_id)
    if not window.candidate_ref:
        raise HTTPException(status_code=404, detail={"code": "SERVICE_CANDIDATE_MISSING"})
    asset = _call(
        db,
        assets.resolve_asset_ref,
        workspace.id,
        window.candidate_ref,
        authorize=assets.native_authorizer(db, workspace, user),
    )
    qualification = assets.current_qualification(db, workspace.id, asset.id)
    return {
        "asset_ref": assets.asset_ref(asset),
        "manifest": asset.manifest_json,
        "qualification": None
        if qualification is None
        else {
            "id": qualification.id,
            "version": qualification.version,
            "status": qualification.status,
            "asset_digest": qualification.asset_digest,
            "policy_digest": qualification.policy_digest,
            "evidence_digest": qualification.evidence_digest,
            "digest": qualification.digest,
            "policy": qualification.policy_json,
            "evidence": qualification.evidence_json,
            "confidence": qualification.confidence,
            "created_at": qualification.created_at,
        },
    }


@router.post("/windows/{window_id}/publish")
def publish_window(
    window_id: str,
    body: PublishDelivery,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    window = _call(db, services.get_window, workspace.id, window_id, lock=True)
    # A human caller carries the reviewed generation, not the worker's secret lease.
    # Never replace that caller-supplied fence with the current database value.
    if window.fence != body.fence:
        raise HTTPException(409, detail={"code": "SERVICE_STALE_LEASE"})
    row = _call(
        db,
        services.publish_delivery,
        workspace.id,
        window_id,
        decision_id=body.decision_id,
        fence=body.fence,
        lease_token=window.lease_token,
        commit=True,
    )
    return services.receipt_public(row)


@router.get("/assets")
def list_assets(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.service_contract import AssetVersion

    _access(db, workspace, user)
    query = (
        db.query(AssetVersion)
        .filter_by(workspace_id=workspace.id)
        .order_by(AssetVersion.created_at.desc(), AssetVersion.version.desc())
    )
    items = []
    for row in query.offset(offset).limit(limit):
        try:
            assets.resolve_asset_ref(
                db,
                workspace.id,
                assets.asset_ref(row),
                authorize=assets.native_authorizer(db, workspace, user),
                verify_objects=False,
            )
        except assets.GovernanceError:
            continue
        qualification = assets.current_qualification(db, workspace.id, row.id)
        items.append(
            {
                "asset_ref": assets.asset_ref(row),
                "logical_key": row.logical_key,
                "kind": row.kind,
                "version": row.version,
                "created_at": row.created_at,
                "qualification": None
                if qualification is None
                else {
                    "status": qualification.status,
                    "digest": qualification.digest,
                    "policy_digest": qualification.policy_digest,
                },
            }
        )
    return {"items": items, "total": query.count(), "offset": offset, "limit": limit}


@router.get("/{contract_id}")
def get_contract(
    contract_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return services.contract_public(_call(db, services.get_contract, workspace.id, contract_id))


@router.post("/{contract_id}/publish")
def publish_contract(
    contract_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return services.contract_public(
        _call(
            db, services.publish_contract, workspace.id, contract_id, user_id=user.id, commit=True
        )
    )


@router.get("/receipts/{receipt_id}/download")
def download_receipt(
    receipt_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import shutil
    import tempfile
    from pathlib import Path

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    from app.models.service_contract import AssetVersion
    from app.services.dataops.exports import receipt_bundle

    _access(db, workspace, user)
    receipt = _call(
        db,
        services.get_receipt,
        workspace.id,
        receipt_id,
        user_id=user.id,
        authorize_native=assets.native_authorizer(db, workspace, user),
    )
    asset = db.get(AssetVersion, receipt.asset_id)
    directory = Path(tempfile.mkdtemp(prefix="delivery-export-"))
    try:
        path = receipt_bundle(asset, services.receipt_public(receipt), directory / "delivery.zip")
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(409, detail={"code": "DELIVERY_EXPORT_FAILED"}) from None
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"delivery-{receipt.id}.zip",
        background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
    )


class RequalifyAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ref: dict
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/assets/requalify")
def requalify_asset(
    body: RequalifyAsset,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    count = _call(
        db,
        assets.mark_for_requalification,
        workspace.id,
        body.asset_ref,
        actor=user.id,
        reason=body.reason,
        commit=True,
    )
    return {"status": "needs_requalification", "affected": count}


@router.get("/windows/{window_id}/objects/{index}")
def candidate_object(
    window_id: str,
    index: int,
    expected_asset_digest: str = Query(..., pattern=r"^[0-9a-f]{64}$"),
    expected_fence: int = Query(..., ge=1),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import shutil
    import tempfile
    from pathlib import Path

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    from app.services.dataops.storage import file_digest
    from app.services.object_store import get_object_store

    _access(db, workspace, user)
    window = _call(db, services.get_window, workspace.id, window_id)
    if not window.candidate_ref:
        raise HTTPException(404, detail={"code": "SERVICE_CANDIDATE_MISSING"})
    asset = _call(
        db,
        assets.resolve_asset_ref,
        workspace.id,
        window.candidate_ref,
        authorize=assets.native_authorizer(db, workspace, user),
        verify_objects=False,
    )
    if window.fence != expected_fence or asset.digest != expected_asset_digest:
        raise HTTPException(409, detail={"code": "SERVICE_CANDIDATE_CHANGED"})
    objects = asset.manifest_json.get("objects", [])
    if index < 0 or index >= len(objects):
        raise HTTPException(404, detail={"code": "SERVICE_OBJECT_NOT_FOUND"})
    obj = objects[index]
    if obj["size_bytes"] > 256 * 1024**2:
        raise HTTPException(422, detail={"code": "SERVICE_OBJECT_DOWNLOAD_LIMIT"})
    directory = Path(tempfile.mkdtemp(prefix="service-object-"))
    try:
        path = get_object_store().copy_to_local(
            obj["key"], directory / "object", max_bytes=obj["size_bytes"]
        )
        if path.stat().st_size != obj["size_bytes"] or file_digest(path) != obj["sha256"]:
            raise ValueError("changed")
        with path.open("rb") as source:
            header = source.read(16)
        mime, ext = (
            ("image/png", "png")
            if header.startswith(b"\x89PNG\r\n\x1a\n")
            else ("image/jpeg", "jpg")
            if header.startswith(b"\xff\xd8\xff")
            else ("image/webp", "webp")
            if header.startswith(b"RIFF") and header[8:12] == b"WEBP"
            else ("text/plain", "txt")
            if obj["key"].endswith((".txt", ".md"))
            else ("application/json", "json")
            if obj["key"].endswith(".json")
            else ("application/octet-stream", "bin")
        )
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(409, detail={"code": "SERVICE_OBJECT_INTEGRITY_FAILED"}) from None
    return FileResponse(
        path,
        media_type=mime,
        filename=f"document-{index + 1}.{ext}",
        content_disposition_type="inline"
        if mime.startswith("image/") or mime == "text/plain"
        else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "X-Asset-Digest": asset.digest,
            "X-Service-Fence": str(window.fence),
        },
        background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
    )
