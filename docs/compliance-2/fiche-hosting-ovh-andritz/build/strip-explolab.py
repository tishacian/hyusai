#!/usr/bin/env python3
"""
Generate a Datategy-only reference.docx by stripping the ExploLab logo
from the shared CarakAI/METROPOLIS reference template.

The shared reference.docx (project-carakai/doc/build/reference.docx) embeds two
header logos:
  - image1.png  → ExploLab (anchored, top right)
  - image2.png  → Datategy (inline, top left)

For client-specific deliverables that do not involve ExploLab (e.g. ANDRITZ
hosting compliance bundle), we only want the Datategy logo. This script:

  1. Reads the shared reference.docx
  2. Removes the entire <w:r>...</w:r> wrapper that hosts the anchored drawing
     referencing rId1 in word/header1.xml
  3. Drops word/media/image1.png from the archive
  4. Rewrites word/_rels/header1.xml.rels to remove the rId1 relationship

Usage:
    python3 strip-explolab.py <input.docx> <output.docx>
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import zipfile


HEADER_PATH = "word/header1.xml"
HEADER_RELS_PATH = "word/_rels/header1.xml.rels"
EXPLOLAB_IMAGE = "word/media/image1.png"


def strip_anchored_run(header_xml: str) -> str:
    """Drop the <w:r>...</w:r> block that contains an anchored drawing
    (i.e. the ExploLab logo, positioned via <wp:anchor>).
    """
    pattern = re.compile(
        r"<w:r>(?:(?!</w:r>).)*?<w:drawing>\s*<wp:anchor\b.*?</wp:anchor>\s*</w:drawing>\s*</w:r>",
        re.DOTALL,
    )
    new_xml, n = pattern.subn("", header_xml, count=1)
    if n == 0:
        raise RuntimeError(
            "No anchored drawing found in header1.xml — template may have changed."
        )
    return new_xml


def strip_rid1_rel(rels_xml: str) -> str:
    """Remove the rId1 Relationship element pointing to image1.png.

    Matches a self-closing <Relationship .../> whose Id attribute is rId1,
    regardless of attribute order. Slashes inside Type URLs prevent naive
    [^/]* patterns, so we use a tolerant lazy match terminated by /> .
    """
    pattern = re.compile(
        r'<Relationship\b[^>]*\bId="rId1"[^>]*?/>',
        re.DOTALL,
    )
    candidates = pattern.findall(rels_xml)
    if not candidates:
        raise RuntimeError("No <Relationship Id=\"rId1\" .../> found in header1.xml.rels.")
    target_present = any("image1.png" in c for c in candidates)
    if not target_present:
        raise RuntimeError(
            "rId1 relationship found but does not target media/image1.png — "
            "template may have changed."
        )
    return pattern.sub("", rels_xml, count=1)


def patch_docx(src_path: str, dst_path: str) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(src_path, "r") as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:

            for item in zin.infolist():
                name = item.filename
                if name == EXPLOLAB_IMAGE:
                    continue

                data = zin.read(name)

                if name == HEADER_PATH:
                    text = data.decode("utf-8")
                    text = strip_anchored_run(text)
                    data = text.encode("utf-8")

                elif name == HEADER_RELS_PATH:
                    text = data.decode("utf-8")
                    text = strip_rid1_rel(text)
                    data = text.encode("utf-8")

                zout.writestr(item, data)

        shutil.move(tmp_path, dst_path)
        print(f"OK  {dst_path} (ExploLab logo removed, Datategy logo kept)")

    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.docx> <output.docx>")
        sys.exit(1)

    patch_docx(sys.argv[1], sys.argv[2])
