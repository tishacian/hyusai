"""Unit tests for branded Andritz capture report export (PDF / DOCX)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.capture_report_export import (
    ANDRITZ_LOGO,
    build_capture_report_export,
    export_urls_for_proposal,
)


def _proposal(**overrides):
    payload = {
        "title": "ACME · Line 1 · 2026-07-20",
        "report_markdown": (
            "# Rapport d'intervention FSE\n\n"
            "## Cartouche\n\n"
            "| Champ | Valeur |\n| --- | --- |\n| Client | ACME |\n\n"
            "## 1. HSE — Health Safety and Environment\n\n"
            "- **Synthèse HSE** : None\n\n"
            "### Points hors plan\n\n"
            "- Observation terrain\n"
        ),
    }
    payload.update(overrides.pop("proposal", {}))
    return SimpleNamespace(id="prop-1", session_id="sess-1", proposal=payload, **overrides)


def _session(**overrides):
    plan = {
        "header_fields": {
            "customer": "ACME",
            "country": "FR",
            "site_or_machine": "Line 1",
            "reference": "APG-42",
            "participants": "J Dupont",
            "issued_by": "J Dupont",
            "intervention_date": "2026-07-20",
            "week": "W30",
            "distribution": ["project_manager", "quality"],
            "intervention_type": "weekly_site",
        },
        "capture_template": {
            "doc_ref": "P APG EX70 004 01",
            "intervention_type_label": "Weekly site report",
        },
        "intervention_type": "weekly_site",
    }
    plan.update(overrides.pop("plan", {}))
    return SimpleNamespace(id="sess-1", title="ACME session", plan=plan, **overrides)


def test_export_urls_for_proposal():
    urls = export_urls_for_proposal("abc-123")
    assert urls["pdf_url"].endswith("/proposals/abc-123/export?format=pdf")
    assert urls["docx_url"].endswith("/proposals/abc-123/export?format=docx")


def test_andritz_logo_shipped_with_backend():
    assert ANDRITZ_LOGO.is_file(), f"missing logo at {ANDRITZ_LOGO}"


def test_build_pdf_export_returns_pdf_bytes():
    content, media, filename = build_capture_report_export(
        proposal=_proposal(),
        session=_session(),
        fmt="pdf",
    )
    assert media == "application/pdf"
    assert filename.endswith(".pdf")
    assert "APG-42" in filename or "ACME" in filename or filename.startswith("capture-")
    assert content[:4] == b"%PDF" or content.startswith(b"%PDF")


def test_build_docx_export_returns_docx_bytes():
    pytest.importorskip("docx")
    content, media, filename = build_capture_report_export(
        proposal=_proposal(),
        session=_session(),
        fmt="docx",
    )
    assert "wordprocessingml" in media
    assert filename.endswith(".docx")
    # DOCX is a zip package
    assert content[:2] == b"PK"


def test_export_requires_report_markdown():
    with pytest.raises(ValueError, match="empty"):
        build_capture_report_export(
            proposal=_proposal(proposal={"report_markdown": "", "recommended_ingestion": {}}),
            session=_session(),
            fmt="pdf",
        )
