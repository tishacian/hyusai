"""
Common metadata extraction functionality.

This module provides functions for extracting common metadata from files.
"""

import mimetypes
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from docmeta.core.types import FileMetaData


def get_file_common_metadata(path: str) -> FileMetaData:
    """
    Extract common metadata from a file.

    Args:
        path: Path to the file

    Returns:
        FileMetaData: Common metadata for the file
    """
    stats = os.stat(path)
    pathlib_path = Path(path)

    # Initialize with required fields
    metadata: dict[str, Any] = {
        "file_path": str(pathlib_path.resolve()),
        "file_name": pathlib_path.name,
        "file_extension": pathlib_path.suffix.lower(),
        "mime_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
        "file_permissions": stat.filemode(stats.st_mode),
        "size": stats.st_size,
        "last_modified_time": datetime.fromtimestamp(stats.st_mtime),
        "last_accessed_time": datetime.fromtimestamp(stats.st_atime),
    }

    # Handle creation time which is platform-dependent
    if hasattr(stats, "st_birthtime"):
        creation_time_in_s = stats.st_birthtime
    else:
        # st_birthtime is not available on Linux platform, st_ctime should be used instead
        creation_time_in_s = stats.st_ctime

    metadata["creation_time"] = datetime.fromtimestamp(creation_time_in_s)

    return metadata
