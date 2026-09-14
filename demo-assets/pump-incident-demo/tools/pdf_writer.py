"""Minimal, dependency-free, deterministic PDF writer for the demo kit.

Produces a single-file PDF with a real, selectable text layer using the two
standard Type1 fonts every viewer already has (Helvetica and Helvetica-Bold)
with WinAnsi encoding. No third-party package is required and no byte of the
output depends on the clock, the host or the filesystem, so the generator can
be run with ``--check`` to prove the committed PDF has not drifted.

Only the small Markdown subset used by ``source/*.source.md`` is supported:
``#`` title, ``##`` heading, ``- `` bullet, ``| a | b |`` tables (first row is
the header, no separator row) and plain paragraphs with ``**bold**`` runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Adobe Core-14 advance widths, per 1000 units of text space.
_HELVETICA = {
    " ": 278,
    "!": 278,
    '"': 355,
    "#": 556,
    "$": 556,
    "%": 889,
    "&": 667,
    "'": 191,
    "(": 333,
    ")": 333,
    "*": 389,
    "+": 584,
    ",": 278,
    "-": 333,
    ".": 278,
    "/": 278,
    ":": 278,
    ";": 278,
    "<": 584,
    "=": 584,
    ">": 584,
    "?": 556,
    "@": 1015,
    "A": 667,
    "B": 667,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 500,
    "K": 667,
    "L": 556,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "[": 278,
    "\\": 278,
    "]": 278,
    "^": 469,
    "_": 556,
    "`": 333,
    "a": 556,
    "b": 556,
    "c": 500,
    "d": 556,
    "e": 556,
    "f": 278,
    "g": 556,
    "h": 556,
    "i": 222,
    "j": 222,
    "k": 500,
    "l": 222,
    "m": 833,
    "n": 556,
    "o": 556,
    "p": 556,
    "q": 556,
    "r": 333,
    "s": 500,
    "t": 278,
    "u": 556,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 500,
    "{": 334,
    "|": 260,
    "}": 334,
    "~": 584,
}
_HELVETICA_BOLD = {
    " ": 278,
    "!": 333,
    '"': 474,
    "#": 556,
    "$": 556,
    "%": 889,
    "&": 722,
    "'": 238,
    "(": 333,
    ")": 333,
    "*": 389,
    "+": 584,
    ",": 278,
    "-": 333,
    ".": 278,
    "/": 278,
    ":": 333,
    ";": 333,
    "<": 584,
    "=": 584,
    ">": 584,
    "?": 611,
    "@": 975,
    "A": 722,
    "B": 722,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 556,
    "K": 722,
    "L": 611,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "[": 333,
    "\\": 278,
    "]": 333,
    "^": 584,
    "_": 556,
    "`": 333,
    "a": 556,
    "b": 611,
    "c": 556,
    "d": 611,
    "e": 556,
    "f": 333,
    "g": 611,
    "h": 611,
    "i": 278,
    "j": 278,
    "k": 556,
    "l": 278,
    "m": 889,
    "n": 611,
    "o": 611,
    "p": 611,
    "q": 611,
    "r": 389,
    "s": 556,
    "t": 333,
    "u": 611,
    "v": 556,
    "w": 778,
    "x": 556,
    "y": 556,
    "z": 500,
    "{": 389,
    "|": 280,
    "}": 389,
    "~": 584,
}
for _digit in "0123456789":
    _HELVETICA[_digit] = 556
    _HELVETICA_BOLD[_digit] = 556

_FALLBACK_WIDTH = 556

# Page geometry: ISO A4 in points, rounded to whole units so the layout is
# reproducible without floating-point drift.
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_LEFT = 56
MARGIN_RIGHT = 56
MARGIN_TOP = 58
MARGIN_BOTTOM = 62
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT


def text_width(text: str, size: float, bold: bool) -> float:
    table = _HELVETICA_BOLD if bold else _HELVETICA
    total = sum(table.get(char, _FALLBACK_WIDTH) for char in text)
    return total * size / 1000.0


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _encode(text: str) -> str:
    """Map to WinAnsi (cp1252) so accented French copy survives extraction."""
    return text.encode("cp1252", errors="replace").decode("cp1252")


@dataclass
class Run:
    text: str
    bold: bool = False


def _merge_runs(runs: list["Run"]) -> list["Run"]:
    """Collapse adjacent runs that share a weight into one show-text operator."""
    merged: list[Run] = []
    for run in runs:
        if merged and merged[-1].bold == run.bold:
            merged[-1] = Run(merged[-1].text + run.text, run.bold)
        else:
            merged.append(Run(run.text, run.bold))
    return merged


@dataclass
class Draw:
    """One positioned piece of ink on a page."""

    kind: str  # "text" | "rule"
    x: float = 0.0
    y: float = 0.0
    runs: list[Run] = field(default_factory=list)
    size: float = 10.5
    gray: float = 0.0
    width: float = 0.0
    height: float = 0.0


def split_bold_runs(text: str) -> list[Run]:
    """``a **b** c`` -> [Run('a ', False), Run('b', True), Run(' c', False)]."""
    parts = text.split("**")
    return [Run(part, index % 2 == 1) for index, part in enumerate(parts) if part]


def wrap_runs(runs: list[Run], size: float, max_width: float) -> list[list[Run]]:
    """Greedy word wrap that keeps each word's bold flag."""
    words: list[Run] = []
    for run in runs:
        chunks = run.text.split(" ")
        for index, chunk in enumerate(chunks):
            if chunk == "" and index not in (0, len(chunks) - 1):
                continue
            if chunk:
                words.append(Run(chunk, run.bold))
    lines: list[list[Run]] = []
    current: list[Run] = []
    current_width = 0.0
    space = text_width(" ", size, False)
    for word in words:
        word_width = text_width(word.text, size, word.bold)
        candidate = word_width if not current else current_width + space + word_width
        if current and candidate > max_width:
            lines.append(current)
            current = [word]
            current_width = word_width
        else:
            if current:
                current.append(Run(" ", current[-1].bold))
                current.append(word)
                current_width = candidate
            else:
                current = [word]
                current_width = word_width
    if current:
        lines.append(current)
    return lines or [[Run("", False)]]


class PdfDocument:
    """Accumulates pages of ``Draw`` items and serialises them."""

    def __init__(self, title: str, footer: str) -> None:
        self.title = title
        self.footer = footer
        self.pages: list[list[Draw]] = [[]]
        self.y = PAGE_HEIGHT - MARGIN_TOP

    # --- layout -------------------------------------------------------
    def new_page(self) -> None:
        self.pages.append([])
        self.y = PAGE_HEIGHT - MARGIN_TOP

    def ensure(self, height: float) -> None:
        if self.y - height < MARGIN_BOTTOM:
            self.new_page()

    def space(self, height: float) -> None:
        self.y -= height

    def text_line(
        self, runs: list[Run], size: float, x: float, gray: float = 0.0
    ) -> None:
        self.ensure(size * 1.35)
        self.y -= size * 1.35
        self.pages[-1].append(
            Draw("text", x=x, y=self.y, runs=runs, size=size, gray=gray)
        )

    def rule(
        self, x: float, width: float, gray: float = 0.75, height: float = 0.6
    ) -> None:
        self.ensure(height + 2)
        self.y -= height + 2
        self.pages[-1].append(
            Draw("rule", x=x, y=self.y, width=width, gray=gray, height=height)
        )

    # --- serialisation ------------------------------------------------
    def _page_content(
        self, draws: list[Draw], page_number: int, page_total: int
    ) -> str:
        out: list[str] = []
        for draw in draws:
            if draw.kind == "rule":
                out.append(
                    f"q {draw.gray:.2f} g {draw.x:.2f} {draw.y:.2f} "
                    f"{draw.width:.2f} {draw.height:.2f} re f Q"
                )
                continue
            out.append("BT")
            out.append(f"{draw.gray:.2f} g")
            cursor = draw.x
            # Adjacent runs of the same weight are merged into one show-text
            # operator. One `Tj` per word would still *render* correctly, but
            # text extractors rebuild words from operator boundaries, so the
            # extracted layer (and therefore retrieval and the source preview)
            # would come back shredded.
            for run in _merge_runs(draw.runs):
                if not run.text:
                    continue
                font = "/F2" if run.bold else "/F1"
                out.append(f"{font} {draw.size:.2f} Tf")
                out.append(f"1 0 0 1 {cursor:.2f} {draw.y:.2f} Tm")
                out.append(f"({_escape(_encode(run.text))}) Tj")
                cursor += text_width(run.text, draw.size, run.bold)
            out.append("ET")
        footer = f"{self.footer}  |  Page {page_number} of {page_total}"
        out.append(
            "BT 0.55 g /F1 8.00 Tf "
            f"1 0 0 1 {MARGIN_LEFT:.2f} {MARGIN_BOTTOM - 26:.2f} Tm "
            f"({_escape(_encode(footer))}) Tj ET"
        )
        return "\n".join(out)

    def to_bytes(self) -> bytes:
        pages = [page for page in self.pages if page] or [[]]
        total = len(pages)
        objects: list[bytes] = []

        def add(body: str) -> int:
            objects.append(body.encode("cp1252", errors="replace"))
            return len(objects)

        font_regular = add(
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            "/Encoding /WinAnsiEncoding >>"
        )
        font_bold = add(
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            "/Encoding /WinAnsiEncoding >>"
        )
        info = add(
            f"<< /Title ({_escape(_encode(self.title))}) "
            "/Producer (Agentium demo kit generator) "
            "/Creator (demo-assets/pump-incident-demo/tools/generate_assets.py) "
            "/CreationDate (D:20260105000000Z) /ModDate (D:20260105000000Z) >>"
        )

        pages_obj_id = len(objects) + 2 * total + 1
        page_ids: list[int] = []
        for index, draws in enumerate(pages, start=1):
            content = self._page_content(draws, index, total)
            stream_id = add(
                f"<< /Length {len(content.encode('cp1252', errors='replace'))} >>\n"
                f"stream\n{content}\nendstream"
            )
            page_ids.append(
                add(
                    f"<< /Type /Page /Parent {pages_obj_id} 0 R "
                    f"/MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                    f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
                    f"/Contents {stream_id} 0 R >>"
                )
            )
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        pages_id = add(f"<< /Type /Pages /Kids [{kids}] /Count {total} >>")
        assert pages_id == pages_obj_id, (
            "page tree id must match the /Parent references"
        )
        catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
        xref_offset = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode("ascii")
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R "
            f"/Info {info} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
        return bytes(out)
