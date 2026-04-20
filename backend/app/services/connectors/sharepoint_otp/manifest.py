"""Per-folder sync manifest used to turn the SharePoint ingester into an
incremental sync: on each run, we download only the files that are new or
have a newer ``TimeLastModified`` than on the previous run.

The manifest is a small JSON file stored at the root of the ingestion output
directory (``<output_dir>/.sharepoint_manifest.json``). It is intentionally
detached from the session/token stores because it contains no secrets and
must survive re-authentications.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".sharepoint_manifest.json"
MANIFEST_VERSION = 1


@dataclasses.dataclass
class ManifestEntry:
    server_relative_url: str
    modified_iso: str
    size_bytes: int
    local_path: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "ManifestEntry":
        return cls(
            server_relative_url=payload["server_relative_url"],
            modified_iso=payload.get("modified_iso", ""),
            size_bytes=int(payload.get("size_bytes", 0)),
            local_path=payload.get("local_path", ""),
        )


class SyncManifest:
    """In-memory view of a folder's sync manifest."""

    def __init__(self, entries: dict[str, ManifestEntry] | None = None) -> None:
        self._entries: dict[str, ManifestEntry] = dict(entries or {})

    # ---- IO -------------------------------------------------------------

    @classmethod
    def load(cls, output_dir: Path) -> "SyncManifest":
        path = output_dir / MANIFEST_FILENAME
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except Exception as exc:  # pragma: no cover - corrupted file
            logger.warning("Ignoring unreadable manifest %s: %s", path, exc)
            return cls()
        if not isinstance(raw, dict) or raw.get("v") != MANIFEST_VERSION:
            logger.warning(
                "Manifest at %s has unsupported version; starting fresh.", path
            )
            return cls()
        entries = {
            k: ManifestEntry.from_dict(v) for k, v in raw.get("entries", {}).items()
        }
        return cls(entries)

    def save(self, output_dir: Path) -> None:
        path = output_dir / MANIFEST_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "v": MANIFEST_VERSION,
            "entries": {k: v.to_dict() for k, v in self._entries.items()},
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    # ---- public API -----------------------------------------------------

    def should_download(self, file) -> bool:
        """Return True if ``file`` (a :class:`SharePointFile`) was never
        downloaded or has been modified since the last sync.
        """
        prev = self._entries.get(file.server_relative_url)
        if prev is None:
            return True
        if prev.modified_iso != file.modified_iso:
            return True
        if prev.size_bytes != file.size_bytes:
            return True
        return False

    def record(self, file, local_path: Path) -> None:
        self._entries[file.server_relative_url] = ManifestEntry(
            server_relative_url=file.server_relative_url,
            modified_iso=file.modified_iso,
            size_bytes=file.size_bytes,
            local_path=str(local_path),
        )

    def prune(self, known_urls: Iterable[str]) -> list[ManifestEntry]:
        """Remove manifest entries that no longer exist remotely; returns the
        pruned entries so the caller can optionally delete their local files.
        """
        known = set(known_urls)
        stale_keys = [k for k in self._entries if k not in known]
        pruned = [self._entries.pop(k) for k in stale_keys]
        return pruned

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, server_relative_url: str) -> bool:
        return server_relative_url in self._entries

    def entries(self) -> list[ManifestEntry]:
        return list(self._entries.values())
