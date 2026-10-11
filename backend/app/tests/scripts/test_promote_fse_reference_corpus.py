"""Unit tests for FSE reference corpus promote prioritization / secret filters."""
from __future__ import annotations

from scripts.promote_fse_reference_corpus import classify_deposit_filename, priority_tier


def test_priority_tiers_esn_ex70_before_onedrive():
    assert priority_tier("APG/P APG EX70 004 01 weekly site.docx") == 1
    assert priority_tier("Experience Sharing Note .docx") == 1
    assert priority_tier("P KNW EX70 SERVICE FEEDBACK PROCEDURE REV02.docx") == 1
    assert priority_tier("OneDrive_1_20-07-2026/manuals/dryer.pdf") == 2
    assert priority_tier("CIC reports/visit-2024.pdf") == 2


def test_secret_exclusion_password_and_uic():
    matches, _tier, secret = classify_deposit_filename(
        "OneDrive/Automation/PASSWORD DUNGS.txt"
    )
    assert secret is True
    assert matches is False
    matches_uic, _tier_uic, secret_uic = classify_deposit_filename(
        "OneDrive/Dryer/parameters Eurotherm.uic"
    )
    assert secret_uic is True
    assert matches_uic is False


def test_configurable_extra_secret_pattern():
    import re

    matches, _tier, secret = classify_deposit_filename(
        "CIC reports/credentials-vault.bin",
        extra_secret_patterns=[re.compile(r"credentials-vault", re.IGNORECASE)],
    )
    assert secret is True
    assert matches is False
