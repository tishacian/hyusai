"""Unit checks for Client360 promote path matching (no DB)."""

from __future__ import annotations

from scripts.promote_client360_installed_base import _matches_client360_deposit


def test_matches_allowlisted_installed_base_spl_xlsx() -> None:
    assert _matches_client360_deposit(
        "Installed_base_SPL/Installed base - Machine.xlsx"
    )
    assert _matches_client360_deposit(
        "Installed_base_SPL/Sales_By_Country.xlsx"
    )
    assert _matches_client360_deposit(
        "Installed_base_SPL\\Family - Opportunity.xlsx"
    )


def test_matches_client360_pilot_prefix_xlsx() -> None:
    assert _matches_client360_deposit("Client360_Pilot/SEPTONA - Client 360.xlsx")
    assert _matches_client360_deposit(
        "Client360_Pilot/Base installée TURQUIE.xlsx"
    )


def test_rejects_broad_septona_and_non_prefix_paths() -> None:
    assert not _matches_client360_deposit("SEPTONA - Client 360.xlsx")
    assert not _matches_client360_deposit("Needlepunch/SEPTONA report.xlsx")
    assert not _matches_client360_deposit("CIC/reports/SEPTONA notes.xlsx")
    assert not _matches_client360_deposit("photos/SEPTONA site.jpg")
    assert not _matches_client360_deposit("notices_SPL/SEPTONA notice.pdf")


def test_rejects_non_xlsx_under_prefixes() -> None:
    assert not _matches_client360_deposit("Installed_base_SPL/readme.txt")
    assert not _matches_client360_deposit("Client360_Pilot/photo.png")
    assert not _matches_client360_deposit("Installed_base_SPL/archive.zip")


def test_rejects_unknown_basename_under_spl_prefix() -> None:
    assert not _matches_client360_deposit(
        "Installed_base_SPL/SEPTONA - random export.xlsx"
    )
    assert not _matches_client360_deposit(
        "Installed_base_SPL/Needlepunch summary.xlsx"
    )
