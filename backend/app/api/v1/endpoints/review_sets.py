"""Review sets API (Experience Lot 10): queue, claims, decisions, export.

Members review; a set may restrict its reviewers. Opening, closing, moving a
deadline and exporting are administrator actions. The routes do not exist
while the feature is disabled.
"""

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.v1.endpoints.connections import _access
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.review_set import ReviewSet
from app.services import review_sets as rs
from app.services.huggingface.access import is_workspace_admin


def _enabled():
    if not settings.review_sets_enabled:
        raise HTTPException(status_code=404, detail={"code": "REVIEW_SETS_DISABLED"})


router = APIRouter(dependencies=[Depends(_enabled)])


def _call(db: Session, fn, *, announce: bool = False):
    try:
        value = fn()
        db.commit()
    except rs.ReviewError as exc:
        db.rollback()
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": str(exc)}
        ) from None
    if announce:
        try:
            rs.announce_completed(db)
        except Exception:  # noqa: BLE001 - the next completion or close retries
            db.rollback()
    return value


def _reviewer(db, workspace, user, review_set: ReviewSet) -> None:
    _access(db, workspace, user)
    try:
        rs.check_reviewer(review_set, user.id, admin=is_workspace_admin(db, user, workspace))
    except rs.ReviewError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


def _set(db, workspace, set_id):
    try:
        return rs.get_set(db, workspace.id, set_id)
    except rs.ReviewError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


def _item(db, workspace, item_id):
    try:
        return rs.get_item(db, workspace.id, item_id)
    except rs.ReviewError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None


def _deadline(value):
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(400, detail={"code": "REVIEW_DEADLINE_INVALID"}) from None


@router.get("")
def list_sets(
    namespace: str | None = None,
    status: str | None = Query(None, pattern="^(open|closed)$"),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    q = db.query(ReviewSet).filter_by(workspace_id=workspace.id)
    if namespace:
        q = q.filter_by(namespace=namespace)
    if status:
        q = q.filter_by(status=status)
    admin = is_workspace_admin(db, user, workspace)
    rows = [
        row
        for row in q.order_by(ReviewSet.created_at.desc()).limit(500).all()
        if admin or row.reviewers is None or user.id in row.reviewers
    ]
    return [rs.set_view(row) for row in rows]


@router.post("", status_code=201)
def open_set(
    body: dict = Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    allowed = {
        "namespace",
        "group_key",
        "group_labels",
        "title",
        "items",
        "taxonomy",
        "policy",
        "reviewers",
        "deadline_at",
        "source",
    }
    if not isinstance(body, dict) or set(body) - allowed or not isinstance(body.get("items"), list):
        raise HTTPException(400, detail={"code": "REVIEW_SET_INVALID"})
    deadline = _deadline(body.get("deadline_at"))
    return _call(
        db,
        lambda: rs.set_view(
            rs.open_set(
                db,
                workspace_id=workspace.id,
                namespace=body.get("namespace"),
                group_key=body.get("group_key"),
                title=body.get("title"),
                items=body["items"],
                group_labels=body.get("group_labels"),
                taxonomy=body.get("taxonomy"),
                policy=body.get("policy"),
                reviewers=body.get("reviewers"),
                deadline_at=deadline,
                source=body.get("source") if isinstance(body.get("source"), dict) else None,
                user_id=user.id,
            )
        ),
    )


@router.get("/{set_id}")
def get_set(
    set_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    review_set = _set(db, workspace, set_id)
    _reviewer(db, workspace, user, review_set)
    packages = [
        {k: v for k, v in pack.items() if k != "item_ids"} for pack in rs.packages(db, review_set)
    ]
    return {**rs.set_view(review_set), "stats": rs.stats(db, review_set), "packages": packages}


@router.get("/{set_id}/items")
def list_items(
    set_id: str,
    status: str | None = None,
    tier: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    q: str | None = None,
    package: str | None = None,
    sort: str = "position",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    review_set = _set(db, workspace, set_id)
    _reviewer(db, workspace, user, review_set)
    return _call(
        db,
        lambda: rs.list_items(
            db,
            review_set,
            status=status,
            tier=tier,
            category=category,
            severity=severity,
            query=q,
            package=package,
            sort=sort,
            offset=offset,
            limit=limit,
        ),
    )


@router.get("/items/{item_id}")
def get_item(
    item_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    review_set, item = _item(db, workspace, item_id)
    _reviewer(db, workspace, user, review_set)
    return {**rs.item_view(item), "set_id": review_set.id, "history": rs.history(db, item)}


@router.post("/items/{item_id}/claim")
def claim(
    item_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    review_set, item = _item(db, workspace, item_id)
    _reviewer(db, workspace, user, review_set)
    return _call(db, lambda: rs.claim(db, review_set, item, user_id=user.id))


@router.post("/items/{item_id}/release")
def release(
    item_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    review_set, item = _item(db, workspace, item_id)
    _reviewer(db, workspace, user, review_set)
    return _call(db, lambda: rs.release(db, item, user_id=user.id) or {"released": True})


@router.post("/items/{item_id}/decide")
def decide(
    item_id: str,
    body: dict = Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    review_set, item = _item(db, workspace, item_id)
    _reviewer(db, workspace, user, review_set)
    allowed = {"revision", "decision", "value", "annotations", "comment", "duration_ms"}
    if not isinstance(body, dict) or set(body) - allowed:
        raise HTTPException(400, detail={"code": "REVIEW_DECISION_INVALID"})
    return _call(
        db,
        lambda: rs.item_view(
            rs.decide(
                db,
                review_set,
                item,
                user_id=user.id,
                revision=body.get("revision"),
                decision=body.get("decision"),
                value=body.get("value"),
                annotations=body.get("annotations"),
                comment=body.get("comment"),
                duration_ms=body.get("duration_ms", 0),
            )
        ),
        announce=True,
    )


@router.post("/{set_id}/bulk-approve")
def bulk_approve(
    set_id: str,
    body: dict = Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    review_set = _set(db, workspace, set_id)
    _reviewer(db, workspace, user, review_set)
    return _call(
        db,
        lambda: rs.bulk_approve(db, review_set, body.get("item_ids"), user_id=user.id),
        announce=True,
    )


@router.post("/{set_id}/close")
def close(
    set_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    review_set = _set(db, workspace, set_id)
    return _call(
        db, lambda: rs.set_view(rs.close_set(db, review_set, user_id=user.id)), announce=True
    )


@router.post("/{set_id}/deadline")
def move_deadline(
    set_id: str,
    body: dict = Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    review_set = _set(db, workspace, set_id)
    deadline = _deadline(body.get("deadline_at"))

    def move():
        review_set.deadline_at = deadline
        rs._audit(
            db,
            workspace.id,
            "review_set.deadline_moved",
            user.id,
            {"set_id": review_set.id, "deadline_at": body.get("deadline_at")},
        )
        return rs.set_view(review_set)

    return _call(db, move)


@router.get("/{set_id}/export.csv")
def export(
    set_id: str,
    fields: str | None = None,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    review_set = _set(db, workspace, set_id)
    text = _call(
        db,
        lambda: rs.export_csv(
            db, review_set, subject_fields=fields.split(",") if fields else None, user_id=user.id
        ),
    )
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="review-{review_set.id}.csv"'},
    )
