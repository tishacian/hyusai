"""Workspace-scoped BRD retention using the canonical object store."""
from pathlib import PurePosixPath

from sqlalchemy.exc import IntegrityError

from app.models.brd_document import BrdDocument
from app.services.object_store import ObjectStore


def retain_brd(db, *, workspace_id, user_id, filename, data, extraction):
    digest = extraction["document"]["sha256"]
    query = db.query(BrdDocument).filter_by(
        workspace_id=workspace_id, created_by_user_id=user_id, sha256=digest
    )
    existing = query.first()
    if existing is not None:
        return existing
    store = ObjectStore()
    key = store.key("workspaces", workspace_id, "brd", user_id, digest + ".docx")
    # Identical concurrent uploads write identical bytes to the same object.
    # The unique constraint settles the row race; no shared object is deleted.
    store.write_bytes(key, data)
    row = BrdDocument(
        workspace_id=workspace_id, created_by_user_id=user_id, sha256=digest,
        size_bytes=len(data), storage_key=key, extraction=extraction,
        filename=PurePosixPath((filename or "brd.docx").replace("\\", "/")).name[:255] or "brd.docx",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = query.first()
        if existing is None:
            raise
        return existing
    db.refresh(row)
    return row


def document_payload(row):
    return {
        **row.extraction,
        "document": {
            **row.extraction["document"],
            "id": row.id,
            "filename": row.filename,
            "created_at": row.created_at.isoformat(),
        },
    }
