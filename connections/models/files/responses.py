from typing import Literal

from pydantic import BaseModel


class FileEntry(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int | None = None


class DirectoryListingResponse(BaseModel):
    path: str
    type: Literal["directory"] = "directory"
    entries: list[FileEntry]


class FileUploadResponse(BaseModel):
    path: str
    size: int


class FileDeleteResponse(BaseModel):
    path: str
    deleted: bool
