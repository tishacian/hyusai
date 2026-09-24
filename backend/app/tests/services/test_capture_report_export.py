"""Unit tests for the branded capture report export (PDF / DOCX).

The brand is the workspace's: Andritz's from its family adapter, any other
workspace's own name on neutral colours (ADR 0003 lot 2).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.capture_report_export import (
    DEFAULT_BRAND,
    NEUTRAL_PRIMARY,
    _branded_html,
    build_capture_report_export,
    export_urls_for_proposal,
    report_brand_for,
)
from app.tenants.andritz.capture_report import REPORT_BRAND as ANDRITZ_BRAND


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
    assert ANDRITZ_BRAND.logo.is_file(), f"missing logo at {ANDRITZ_BRAND.logo}"


def _html(brand):
    return _branded_html(
        markdown="# Rapport\n\nTexte",
        title="Rapport",
        header={},
        doc_ref="P APG EX70 004 01",
        type_label="Weekly site report",
        brand=brand,
    )


def test_an_andritz_workspace_exports_under_the_andritz_brand():
    workspace = SimpleNamespace(name="Andritz", settings={"family": "andritz"})
    brand = report_brand_for(workspace)
    assert brand == ANDRITZ_BRAND
    page = _html(brand)
    assert 'alt="ANDRITZ"' in page
    assert "#003366" in page and "Field Service Excellence" in page
    assert 'content: "ANDRITZ · P APG EX70 004 01 · page "' in page


def test_another_workspace_exports_under_its_own_name():
    workspace = SimpleNamespace(
        name="Nawa",
        settings={"family": "generic", "platform_brand": {"label": "NAWA", "emblem": "/x.png"}},
    )
    brand = report_brand_for(workspace)
    assert brand.label == "NAWA" and brand.primary == NEUTRAL_PRIMARY and brand.logo is None
    page = _html(brand)
    assert "ANDRITZ" not in page and "Field Service Excellence" not in page
    assert '<div class="logo-text">NAWA</div>' in page
    unbranded = report_brand_for(SimpleNamespace(name="Showcase", settings={}))
    assert unbranded.label == "Showcase"


def test_a_brand_label_cannot_break_out_of_the_page_footer():
    page = _html(DEFAULT_BRAND.__class__(label='Evil" } body { color: red', primary="#111111", accent="#222222"))
    assert 'content: "Evil\\" } body { color: red · ' in page


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
