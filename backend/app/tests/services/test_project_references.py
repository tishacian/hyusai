from __future__ import annotations

import pytest

from app.services.rag.project_references import (
    derive_project_reference,
    extract_query_project_codes,
    numeric_project_candidates,
    project_reference_terms,
)


@pytest.mark.parametrize(
    ("path", "code", "project_range"),
    [
        (
            (
                "Notices_Techniques_Needlepunch/60000-69999/"
                "61001CdFreudenberg USA du 22 05 2003/manual.pdf"
            ),
            "61001",
            "60000-69999",
        ),
        (
            (
                "Notices_Techniques_Needlepunch/60000-69999/"
                "61038CdMeishengWenzhouMach.Asselin du 20 11 2004/file.doc"
            ),
            "61038",
            "60000-69999",
        ),
        (
            (
                "Notices_Techniques_Needlepunch/70000-79999/"
                "70170 - SHIMALL _SIM200Y_ C-I4-854826-166 DOC Full Scope/archive.zip"
            ),
            "70170",
            "70000-79999",
        ),
    ],
)
def test_derive_needlepunch_reference_from_trusted_structure(path, code, project_range):
    reference = derive_project_reference(path)

    assert reference == {
        "project_code": code,
        "project_reference_kind": "andritz_project",
        "project_code_scheme": "needlepunch_numeric5",
        "business_scope": "needlepunch",
        "project_range": project_range,
        "project_folder": path.replace("\\", "/").split("/")[-2],
    }
    assert "initial_buyer_code" not in reference
    assert "project_position" not in reference


@pytest.mark.parametrize(
    "path",
    [
        # Project is outside the declared range.
        "Notices_Techniques_Needlepunch/60000-69999/70170 Customer/manual.pdf",
        # A sixth contiguous digit is not a separator or a project label.
        "Notices_Techniques_Needlepunch/60000-69999/610011Customer/manual.pdf",
        # The parent range is an exact structural segment, not fuzzy prose.
        "Notices_Techniques_Needlepunch/60000 - 69999/61038 Customer/manual.pdf",
        # The five-digit code is lower than the immediate project folder.
        "Notices_Techniques_Needlepunch/60000-69999/Manuals/61038/manual.pdf",
        # A project folder must include its structural label.
        "Notices_Techniques_Needlepunch/60000-69999/61038/manual.pdf",
        "Notices_Techniques_Needlepunch/60000-69999/61038 ---/manual.pdf",
        # A concatenated label starts with a letter, not arbitrary punctuation.
        "Notices_Techniques_Needlepunch/60000-69999/61038!Customer/manual.pdf",
        # Once the source declares Needlepunch, a legacy-looking filename must
        # not become a fallback project identity.
        "Notices_Techniques_Needlepunch/bad-range/bad-folder/BAO100.pdf",
        # Only canonical relative POSIX deposit paths are accepted.
        "/Notices_Techniques_Needlepunch/60000-69999/61038 Customer/manual.pdf",
        "incoming/Notices_Techniques_Needlepunch/60000-69999/61038 Customer/manual.pdf",
        "./Notices_Techniques_Needlepunch/60000-69999/61038 Customer/manual.pdf",
        "Notices_Techniques_Needlepunch\\60000-69999\\61038 Customer\\manual.pdf",
        "Notices_Techniques_Needlepunch//60000-69999/61038 Customer/manual.pdf",
        "Notices_Techniques_Needlepunch/60000-69999/./61038 Customer/manual.pdf",
        "Notices_Techniques_Needlepunch/60000-69999/61038 Customer/../manual.pdf",
        # A second marker deeper in the path is an ambiguous nested prefix.
        (
            "Notices_Techniques_Needlepunch/60000-69999/61038 Customer/"
            "Notices_Techniques_Needlepunch/70000-79999/70170 Other/manual.pdf"
        ),
    ],
)
def test_derive_needlepunch_reference_fails_closed(path):
    assert derive_project_reference(path) == {}


@pytest.mark.parametrize(
    "malformed",
    [
        "incoming/Notices_Techniques_Needlepunch/60000-69999/61038 Customer/BAO100.pdf",
        "Notices_Techniques_Needlepunch\\60000-69999\\61038 Customer\\BAO100.pdf",
        "Notices_Techniques_Needlepunch/60000-69999/../61038 Customer/BAO100.pdf",
    ],
)
def test_malformed_needlepunch_claim_never_falls_back_to_spl(malformed):
    assert derive_project_reference("Manual_BAO100.pdf", malformed) == {}
    assert derive_project_reference(malformed, "Manual_BAO100.pdf") == {}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Manual_BAO100.zip", "BAO100"),
        ("Notices_BCX200.pdf", "BCX200"),
        ("R__ELM001Y__manual.pdf", "ELM001Y"),
    ],
)
def test_derive_project_reference_preserves_legacy_alpha_grammar(source, expected):
    assert derive_project_reference(source)["project_code"] == expected


def test_extract_query_codes_requires_context_or_authoritative_numeric_code():
    assert extract_query_project_codes("61038") == []
    assert extract_query_project_codes("61038", known_codes={"61038"}) == ["61038"]
    assert extract_query_project_codes("résume 61038") == ["61038"]
    assert extract_query_project_codes("résume le projet 61038") == ["61038"]
    assert extract_query_project_codes("comparaison entre 61038 et 61001") == ["61038", "61001"]
    assert project_reference_terms("inventaire des pièces pour 61038") == ("61038",)


def test_numeric_project_context_is_deliberately_narrow():
    assert extract_query_project_codes("documents 61038") == []
    assert extract_query_project_codes("pièces 61038") == []
    assert extract_query_project_codes("documents 61038", known_codes={"61038"}) == ["61038"]


@pytest.mark.parametrize(
    "query",
    [
        "notice TTN17829J",
        "variante V10234",
        "vitesse moteur 10000 rpm",
    ],
)
def test_extract_query_codes_rejects_embedded_references_and_measurements(query):
    assert extract_query_project_codes(query) == []


def test_measurement_wins_over_an_accidental_known_code_collision():
    assert extract_query_project_codes("vitesse moteur 10000 rpm", known_codes={"10000"}) == []


def test_numeric_candidates_are_unvalidated_and_measurement_safe():
    assert numeric_project_candidates("61038") == ("61038",)
    assert numeric_project_candidates("compare 61038 et 61001") == ("61038", "61001")
    assert numeric_project_candidates("TTN17829J V10234 10000 rpm") == ()


def test_extract_query_codes_keeps_legacy_references_and_source_order():
    assert extract_query_project_codes("compare BAO100, ELM001Y et le projet 61038") == [
        "BAO100",
        "ELM001Y",
        "61038",
    ]
