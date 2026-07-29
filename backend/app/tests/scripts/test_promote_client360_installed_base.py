"""Unit checks for Client360 promote path matching (no DB)."""

from __future__ import annotations

from scripts.promote_client360_installed_base import (
    LARGE_SPL_MAX_PROMOTE_BYTES,
    _effective_max_promote_bytes,
    _matches_client360_deposit,
)


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
    assert _matches_client360_deposit(
        "Installed_base_SPL/Liste Projets _ Clients.xlsx"
    )
    assert _matches_client360_deposit(
        "Installed_base_SPL/Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx"
    )
    assert _matches_client360_deposit(
        "Installed_base_SPL/Installed base - SPC.xlsx"
    )


def test_large_spl_promote_byte_exceptions() -> None:
    default_cap = 20_000_000
    assert (
        _effective_max_promote_bytes(
            "Installed_base_SPL/Installed base - SPC.xlsx", default_cap
        )
        == LARGE_SPL_MAX_PROMOTE_BYTES
    )
    assert (
        _effective_max_promote_bytes(
            "Installed_base_SPL/Liste Projets _ Clients.xlsx", default_cap
        )
        == LARGE_SPL_MAX_PROMOTE_BYTES
    )
    assert (
        _effective_max_promote_bytes(
            "Installed_base_SPL/Liste Sales Orders D800 MNT SPL 2011_2026 VA05.xlsx",
            default_cap,
        )
        == LARGE_SPL_MAX_PROMOTE_BYTES
    )
    assert (
        _effective_max_promote_bytes(
            "Installed_base_SPL/Installed base - Machine.xlsx", default_cap
        )
        == default_cap
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
