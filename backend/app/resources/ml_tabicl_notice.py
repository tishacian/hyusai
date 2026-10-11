"""Pinned upstream notice carried with every admitted TabICL weight snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RESOURCE = Path(__file__).resolve().parent / "tabicl"
NOTICE_NAME = "license.json"
MAX_NOTICE_BYTES = 128 * 1024


def notice_document(license_text: str | None = None) -> dict:
    provenance = json.loads((RESOURCE / "provenance.json").read_text(encoding="utf-8"))
    original = (RESOURCE / "LICENSE").read_bytes()
    if hashlib.sha256(original).hexdigest() != provenance["source"]["sha256"]:
        raise ValueError("The pinned TabICL license resource has changed")
    text = original.decode("utf-8")
    if license_text is not None and license_text != text:
        raise ValueError("Include the complete pinned TabICL upstream license without changes")
    return {"schema": 1, "provenance": provenance, "license_text": text}


def validate_notice(document: object) -> None:
    if document != notice_document():
        raise ValueError("TabICL requires its complete pinned license notice and provenance")


def prepare_notice(directory: Path, license_text: str) -> dict:
    """Add the notice to converted files before their immutable identity is signed."""
    document = notice_document(license_text)
    path = directory / NOTICE_NAME
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_NOTICE_BYTES:
            raise ValueError("Invalid TabICL license file")
        validate_notice(json.loads(path.read_text(encoding="utf-8")))
    else:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(document, sort_keys=True, ensure_ascii=False) + "\n")
    return document
