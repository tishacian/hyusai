"""Read a Business Requirements document (DTG-METH-BR) into draft material.

The template states a traceability chain — business outcome BO-x → functional
requirement FR-x (with a MoSCoW priority and the capability it maps to) →
decision D-x → rules R-x and prohibitions N-x. Those are Word tables with
stable headers, so they are parsable; everything else in the document is prose
or a table whose rows describe process steps, qualities or signatures rather
than something a Skill could be drafted from.

Two deliberate limits:

* **Nothing is created.** This module returns rows. The authoring wizard is
  what turns one into a Skill, and only when someone asks it to.
* **Nothing blocks.** A table that is missing, renamed or half filled produces
  an empty list and a sentence in ``problems``, never an exception. Only a file
  that is not a Word document at all is refused, and it is refused by the
  caller, not here.

The Target Operating Model template is intentionally not parsed: its value
streams, RACI and governance are guidance the wizard shows, not rows.
"""
from __future__ import annotations

import io
import hashlib
import re
import zipfile
from collections.abc import Sequence
from typing import Any

# A field left as `‹ … ›` in the template is a placeholder, not an answer.
_PLACEHOLDER = re.compile(r"[‹›]")
_MAX_CELL = 2000
_MAX_ROWS = 200
_MAX_EXPANDED_BYTES = 50 * 1024 * 1024
_MAX_ARCHIVE_PARTS = 1000


class BrdUnreadableError(Exception):
    """The upload is not a Word document this parser can open."""


def parse_business_requirements(data: bytes) -> dict[str, Any]:
    """Extract the traceability chain from a BRD ``.docx``.

    Raises :class:`BrdUnreadableError` when the bytes are not a Word document.
    Every other failure is reported in ``problems`` with the lists left empty.
    """

    # DOCX is a ZIP container: the upload limit alone does not bound its XML.
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = archive.infolist()
            if len(parts) > _MAX_ARCHIVE_PARTS or sum(p.file_size for p in parts) > _MAX_EXPANDED_BYTES:
                raise BrdUnreadableError("The expanded document exceeds the import limits.")
    except zipfile.BadZipFile as exc:
        raise BrdUnreadableError("The file is not a readable .docx archive.") from exc

    try:
        import docx  # imported lazily: the rest of the API does not need it
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise BrdUnreadableError("python-docx is not installed on this server") from exc
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise BrdUnreadableError(f"the file could not be opened as a .docx ({exc})") from exc

    problems: list[str] = []
    tables = [_table_rows(table, problems, index) for index, table in enumerate(document.tables, 1)]

    outcomes = _rows(
        tables,
        problems,
        section="business outcomes",
        match=lambda header: header[:2] == ["id", "business outcome"],
        fields=("id", "outcome", "why", "signal"),
        prefix="BO",
    )
    requirements = _rows(
        tables,
        problems,
        section="functional requirements",
        match=lambda header: header[:2] == ["id", "requirement"],
        fields=("id", "requirement", "priority", "capability"),
        prefix="FR",
    )
    decisions = _rows(
        tables,
        problems,
        section="decisions",
        match=lambda header: header[:2] == ["id", "decision"],
        fields=("id", "decision", "inputs", "outcomes", "threshold", "escalation"),
        prefix="D",
    )
    rules = _rows(
        tables,
        problems,
        section="business rules",
        match=lambda header: len(header) > 1 and header[0] == "id" and header[1].startswith("rule"),
        fields=("id", "text", "source"),
        prefix="R",
    )
    prohibitions = _rows(
        tables,
        problems,
        section="prohibitions",
        match=lambda header: len(header) > 1 and header[0] == "id" and "never" in header[1],
        fields=("id", "text"),
        prefix="N",
    )

    guardrails = [
        {"id": row["id"], "text": row["text"], "kind": "rule"} for row in rules
    ] + [
        {"id": row["id"], "text": row["text"], "kind": "prohibition"} for row in prohibitions
    ]

    return {
        "document": {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)},
        "context": _context(document),
        "outcomes": outcomes,
        "requirements": requirements,
        "decisions": decisions,
        "guardrails": guardrails,
        "problems": problems,
    }


def _clean(text: str) -> str:
    """Trim, collapse whitespace, and treat a template placeholder as blank."""

    collapsed = " ".join((text or "").split())
    if not collapsed or _PLACEHOLDER.search(collapsed):
        return ""
    return collapsed[:_MAX_CELL]


def _table_rows(table: Any, problems: list[str], index: int) -> list[list[str]]:
    rows: list[list[str]] = []
    if len(table.rows) > _MAX_ROWS + 1:
        problems.append(f"Table {index} exceeds {_MAX_ROWS} data rows; remaining rows were not imported.")
    for row in table.rows[: _MAX_ROWS + 1]:
        values = [" ".join((cell.text or "").split()) for cell in row.cells]
        if any(len(value) > _MAX_CELL for value in values):
            problems.append(f"Table {index}, row {len(rows) + 1} contains text longer than {_MAX_CELL} characters; imported text is truncated.")
        rows.append(values)
    return rows


def _rows(
    tables: Sequence[list[list[str]]],
    problems: list[str],
    *,
    section: str,
    match: Any,
    fields: Sequence[str],
    prefix: str,
) -> list[dict[str, str]]:
    """Read one table, identified by its header rather than by its position.

    Position would break the moment someone inserts a section; the headers are
    what the template actually pins down.
    """

    found = None
    for rows in tables:
        if not rows:
            continue
        header = [cell.strip().lower() for cell in rows[0]]
        if match(header):
            found = rows
            break
    if found is None:
        problems.append(f"No {section} table was found; its rows were skipped.")
        return []

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, cells in enumerate(found[1:], start=1):
        values = [_clean(cell) for cell in cells]
        # The reference column alone carries no requirement: a row that only
        # has its pre-filled `FR-1` is an empty line of the blank template.
        if not any(values[1:]):
            continue
        entry = {name: (values[position] if position < len(values) else "")
                 for position, name in enumerate(fields)}
        if not entry.get("id"):
            entry["id"] = f"{prefix}-{index}"
            problems.append(f"A reference was missing in {section}, row {index}; {entry['id']} was assigned for review.")
        if entry["id"] in seen:
            problems.append(f"Duplicate reference {entry['id']} in {section}; resolve it before mapping requirements.")
        seen.add(entry["id"])
        if not entry.get(fields[1]):
            problems.append(f"Reference {entry['id']} in {section} has no description; it cannot define a requirement or control.")
        out.append(entry)
    return out


def _context(document: Any) -> list[dict[str, str]]:
    """The `label : value` lines of section 1, once someone has filled them in."""

    entries: list[dict[str, str]] = []
    inside = False
    for paragraph in document.paragraphs:
        text = " ".join((paragraph.text or "").split())
        style = getattr(paragraph.style, "name", "") or ""
        if style.startswith("Heading 1"):
            inside = bool(re.match(r"^1\b", text)) and "context" in text.lower()
            continue
        if not inside or not text:
            continue
        label, separator, value = text.partition(":")
        if not separator:
            continue
        cleaned = _clean(value)
        if not cleaned:
            continue
        entries.append({"label": " ".join(label.split()), "value": cleaned})
    return entries
