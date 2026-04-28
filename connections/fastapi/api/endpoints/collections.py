import logging

from fastapi import APIRouter, Depends, HTTPException, status

from connections.database.collections import Collection
from connections.models.collections import (
    CollectionDetail,
    CollectionSummary,
    CreateCollectionPayload,
    DeleteCollectionResponse,
    PatchCollectionPayload,
)
from connections.qdrant import qdrant_client
from connections.storage import (
    KB_INGESTED_FOLDER,
    KB_ORIGINAL_FOLDER,
    KNOWLEDGE_BASE_FOLDER,
    WORKSPACE_UUID,
    fs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collections", tags=["Collections"])


# ---------------------------------------------------------------------------
# Auth stub
# ---------------------------------------------------------------------------


def get_current_user() -> str:
    # TODO: Replace with Keycloak OIDC JWT verification when available.
    # Steps to integrate:
    #   1. Accept Bearer token: token: str = Depends(oauth2_scheme)
    #   2. Decode and verify the JWT against the Keycloak JWKS endpoint
    #   3. Return the preferred_username or sub claim
    return "guest"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dir_size(path: str) -> int | None:
    """Return total size in bytes of all files under path, or None on any error.

    Uses fs.list_files(detail=True) which works for all fsspec backends
    (local filesystem, MinIO/S3, GCS, etc.).
    """
    try:
        files = fs.list_files(path, recursive=True, detail=True)
        return sum(
            info.get("size", 0) for info in files.values() if info.get("type") == "file"
        )
    except Exception:
        return None


def _build_summary(col: Collection) -> CollectionSummary:
    return CollectionSummary.model_validate(col, from_attributes=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[CollectionSummary], status_code=status.HTTP_200_OK)
async def list_collections(
    collection_status: str | None = None,
    current_user: str = Depends(get_current_user),
):
    """List all collections. Optionally filter by status (e.g. status=ready)."""
    collections = Collection.get_all(status=collection_status)
    return [_build_summary(col) for col in collections]


@router.post("/", response_model=CollectionSummary, status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CreateCollectionPayload,
    current_user: str = Depends(get_current_user),
):
    """Create a new empty collection record. Documents are added via /flow_operations/ingest_documents."""
    col = Collection.create(
        name=payload.name,
        created_by=current_user,
        description=payload.description,
    )
    return _build_summary(col)


@router.get("/{uuid}", response_model=CollectionDetail, status_code=status.HTTP_200_OK)
async def get_collection(
    uuid: str,
    current_user: str = Depends(get_current_user),
):
    """Get full details for a collection, enriched with live Qdrant and storage metrics."""
    col = Collection.get_by_uuid(uuid)
    if col is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {uuid!r} not found",
        )

    # Storage sizes
    kb_root = fs.joinpath(WORKSPACE_UUID, KNOWLEDGE_BASE_FOLDER, uuid)
    uploaded_docs_size = _dir_size(fs.joinpath(kb_root, KB_ORIGINAL_FOLDER))
    ingested_docs_size = _dir_size(fs.joinpath(kb_root, KB_INGESTED_FOLDER))

    # Qdrant live metrics — collection name == collection uuid
    qdrant_collection_size: int | None = None
    nb_chunks: int | None = None
    try:
        qdrant_collection_size = qdrant_client.get_collection(uuid).vectors_count
    except Exception:
        pass
    try:
        nb_chunks = qdrant_client.count(uuid).count
    except Exception:
        pass

    return CollectionDetail(
        **_build_summary(col).model_dump(),
        document_names=col.document_names,
        chunking_params=col.chunking_params,
        kb_path=fs.joinpath(KNOWLEDGE_BASE_FOLDER, uuid),
        uploaded_docs_size=uploaded_docs_size,
        ingested_docs_size=ingested_docs_size,
        qdrant_collection_size=qdrant_collection_size,
        nb_chunks=nb_chunks,
    )


@router.patch(
    "/{uuid}", response_model=CollectionSummary, status_code=status.HTTP_200_OK
)
async def patch_collection(
    uuid: str,
    payload: PatchCollectionPayload,
    current_user: str = Depends(get_current_user),
):
    """Update name and/or description of a collection."""
    if payload.name is None and payload.description is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one field (name or description) must be provided",
        )
    col = Collection.update(uuid, name=payload.name, description=payload.description)
    if col is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {uuid!r} not found",
        )
    return _build_summary(col)


@router.delete(
    "/{uuid}", response_model=DeleteCollectionResponse, status_code=status.HTTP_200_OK
)
async def delete_collection(
    uuid: str,
    current_user: str = Depends(get_current_user),
):
    """Delete a collection: removes the DB record, Qdrant collection, and storage files.

    The DB deletion is authoritative — if the collection doesn't exist, returns 404.
    Qdrant and storage deletions are best-effort: failures are logged but never surfaced as errors.
    """
    deleted = Collection.delete(uuid)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {uuid!r} not found",
        )

    # Qdrant — best effort
    try:
        qdrant_client.delete_collection(uuid)
    except Exception as exc:
        logger.warning("Failed to delete Qdrant collection %s: %s", uuid, exc)

    # Storage — best effort
    kb_root = fs.joinpath(WORKSPACE_UUID, KNOWLEDGE_BASE_FOLDER, uuid)
    try:
        if fs.exists(kb_root):
            fs.remove_files(kb_root, recursive=True)
    except Exception as exc:
        logger.warning("Failed to delete storage for collection %s: %s", uuid, exc)

    return DeleteCollectionResponse(
        uuid=uuid, deleted=True, detail="Collection deleted successfully"
    )
