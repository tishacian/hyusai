"""Bounded, secret-free per-file progress for one SharePoint synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_RECEIPT_FILES = 500
STATES = frozenset(
    {
        "downloading",
        "downloaded",
        "download_failed",
        "unchanged",
        "ingesting",
        "ingested",
        "ingest_failed",
    }
)


@dataclass
class FileOutcomeLog:
    """Keep a bounded sample; never suggest omitted files were successful."""

    entries: dict[str, dict[str, str]] = field(default_factory=dict)
    truncated: bool = False

    def record(self, filename: str, state: str) -> dict[str, Any]:
        if state not in STATES:
            raise ValueError("Unknown SharePoint file outcome")
        name = str(filename)[:512]
        if name in self.entries or len(self.entries) < MAX_RECEIPT_FILES:
            self.entries[name] = {"filename": name, "state": state}
        else:
            self.truncated = True
        return {"items": list(self.entries.values()), "truncated": self.truncated}


def relative_filename(path: Path, output_dir: Path) -> str:
    """Do not expose server filesystem paths in a user receipt."""
    try:
        return str(path.resolve().relative_to(output_dir.resolve()))
    except ValueError:
        return path.name
