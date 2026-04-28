import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from connections.models.files.responses import (
    DirectoryListingResponse,
    FileDeleteResponse,
    FileEntry,
    FileUploadResponse,
)
from connections.storage import WORKSPACE_UUID, fs

router = APIRouter()


def _full_path(relative_path: str) -> str:
    """Prepend WORKSPACE_UUID to a client-supplied relative path."""
    return fs.joinpath(WORKSPACE_UUID, relative_path)


@router.get("/{path:path}")
async def get_file_or_directory(
    path: str,
    recursive: bool = False,
):
    """List a directory or download a file.

    If *path* resolves to a directory, returns a JSON directory listing.
    If *path* resolves to a file, streams the file content with an inferred
    content-type header.
    Returns 404 when the path does not exist.
    """
    full = _full_path(path)

    if not fs.exists(full):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Path not found: {path}"
        )

    if fs.isdir(full):
        raw_entries = fs.list_files(full, recursive=recursive, detail=True)
        entries: list[FileEntry] = []
        for entry in raw_entries:
            if isinstance(entry, dict):
                entry_path = entry.get("name", "")
                entry_type = "directory" if entry.get("type") == "directory" else "file"
                entry_size = entry.get("size")
            else:
                entry_path = str(entry)
                entry_type = "file"
                entry_size = None
            entries.append(
                FileEntry(
                    name=Path(entry_path).name,
                    path=entry_path,
                    type=entry_type,
                    size=entry_size,
                )
            )
        return DirectoryListingResponse(path=path, entries=entries)

    content_type, _ = mimetypes.guess_type(path)
    content_type = content_type or "application/octet-stream"

    def _iter():
        with fs.open_for_reading(full) as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(_iter(), media_type=content_type)


@router.post(
    "/{path:path}",
    status_code=status.HTTP_201_CREATED,
    response_model=list[FileUploadResponse],
)
async def upload_files(path: str, files: list[UploadFile]):
    """Upload one or more files into *path* (treated as a directory).

    Each file is stored at *path*/<original_filename> relative to WORKSPACE_UUID.
    Returns the list of stored paths and their sizes.
    """
    results = []
    for file in files:
        content = await file.read()
        file_path = f"{path}/{file.filename}"
        fs.write_to_file(_full_path(file_path), content)
        results.append(FileUploadResponse(path=file_path, size=len(content)))
    return results


@router.delete("/{path:path}", response_model=FileDeleteResponse)
async def delete_file_or_directory(path: str, recursive: bool = False):
    """Delete a file or directory.

    Returns 404 when the path does not exist.
    Pass ``recursive=true`` to delete a non-empty directory.
    """
    full = _full_path(path)

    if not fs.exists(full):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Path not found: {path}"
        )

    fs.remove_files(full, recursive=recursive)
    return FileDeleteResponse(path=path, deleted=True)
