"""The Andritz brand on exported capture and FSE intervention reports.

The export is generic and asks the workspace family for a report brand; this
is Andritz's: the wordmark shipped with the backend, the institutional blue
(close to the historical EX70 covers) and the Field Service Excellence line.
A workspace of another family exports under its own name.
"""

from __future__ import annotations

from pathlib import Path

from app.services.capture_report_export import ReportBrand

RESOURCES_DIR = Path(__file__).resolve().parents[2] / "resources" / "andritz"

REPORT_BRAND = ReportBrand(
    label="ANDRITZ",
    primary="#003366",
    accent="#0055A4",
    program="Field Service Excellence",
    logo=RESOURCES_DIR / "andritz.png",
)
