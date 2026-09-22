from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.rag.project_references import (
    ANDRITZ_PROJECT_SCHEME,
    derive_project_reference,
    extract_query_project_codes,
    numeric_project_candidates,
    project_reference_scheme,
    project_reference_terms,
)

ANDRITZ = ANDRITZ_PROJECT_SCHEME


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
    reference = derive_project_reference(path, scheme=ANDRITZ)

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
    assert derive_project_reference(path, scheme=ANDRITZ) == {}


@pytest.mark.parametrize(
    "malformed",
    [
        "incoming/Notices_Techniques_Needlepunch/60000-69999/61038 Customer/BAO100.pdf",
        "Notices_Techniques_Needlepunch\\60000-69999\\61038 Customer\\BAO100.pdf",
        "Notices_Techniques_Needlepunch/60000-69999/../61038 Customer/BAO100.pdf",
    ],
)
def test_malformed_needlepunch_claim_never_falls_back_to_spl(malformed):
    assert derive_project_reference("Manual_BAO100.pdf", malformed, scheme=ANDRITZ) == {}
    assert derive_project_reference(malformed, "Manual_BAO100.pdf", scheme=ANDRITZ) == {}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Manual_BAO100.zip", "BAO100"),
        ("Notices_BCX200.pdf", "BCX200"),
        ("R__ELM001Y__manual.pdf", "ELM001Y"),
    ],
)
def test_derive_project_reference_preserves_legacy_alpha_grammar(source, expected):
    assert derive_project_reference(source, scheme=ANDRITZ)["project_code"] == expected


def test_extract_query_codes_requires_context_or_authoritative_numeric_code():
    assert extract_query_project_codes("61038", scheme=ANDRITZ) == []
    assert extract_query_project_codes("61038", known_codes={"61038"}, scheme=ANDRITZ) == ["61038"]
    assert extract_query_project_codes("résume 61038", scheme=ANDRITZ) == ["61038"]
    assert extract_query_project_codes("résume le projet 61038", scheme=ANDRITZ) == ["61038"]
    assert extract_query_project_codes("comparaison entre 61038 et 61001", scheme=ANDRITZ) == [
        "61038",
        "61001",
    ]
    assert project_reference_terms("inventaire des pièces pour 61038", scheme=ANDRITZ) == ("61038",)


def test_numeric_project_context_is_deliberately_narrow():
    assert extract_query_project_codes("documents 61038", scheme=ANDRITZ) == []
    assert extract_query_project_codes("pièces 61038", scheme=ANDRITZ) == []
    assert extract_query_project_codes("documents 61038", known_codes={"61038"}, scheme=ANDRITZ) == [
        "61038"
    ]


@pytest.mark.parametrize(
    "query",
    [
        "notice TTN17829J",
        "variante V10234",
        "vitesse moteur 10000 rpm",
    ],
)
def test_extract_query_codes_rejects_embedded_references_and_measurements(query):
    assert extract_query_project_codes(query, scheme=ANDRITZ) == []


def test_measurement_wins_over_an_accidental_known_code_collision():
    assert extract_query_project_codes(
        "vitesse moteur 10000 rpm", known_codes={"10000"}, scheme=ANDRITZ
    ) == []
    assert extract_query_project_codes(
        "toutes les 16000 heures", known_codes={"16000"}, scheme=ANDRITZ
    ) == []


def test_french_article_and_grouped_measurement_never_form_a_legacy_reference():
    text = "Le remplacement est recommandé tous les 16 000 heures [1]."

    assert extract_query_project_codes(text, scheme=ANDRITZ) == []
    assert project_reference_terms(text, scheme=ANDRITZ) == ()

    # Preserve real identifiers and their distinct identity rules: TTN17829J
    # is an exact document/equipment identifier, not an Andritz project code.
    assert extract_query_project_codes(
        "Compare BAO100 avec le projet 61035 et la notice TTN17829J",
        scheme=ANDRITZ,
    ) == ["BAO100", "61035"]


def test_numeric_candidates_are_unvalidated_and_measurement_safe():
    assert numeric_project_candidates("61038", scheme=ANDRITZ) == ("61038",)
    assert numeric_project_candidates("compare 61038 et 61001", scheme=ANDRITZ) == (
        "61038",
        "61001",
    )
    assert numeric_project_candidates("TTN17829J V10234 10000 rpm", scheme=ANDRITZ) == ()


def test_extract_query_codes_keeps_legacy_references_and_source_order():
    assert extract_query_project_codes(
        "compare BAO100, ELM001Y et le projet 61038",
        scheme=ANDRITZ,
    ) == [
        "BAO100",
        "ELM001Y",
        "61038",
    ]


def test_andritz_grammar_is_off_when_scheme_is_omitted():
    needlepunch = (
        "Notices_Techniques_Needlepunch/60000-69999/"
        "61001CdFreudenberg USA du 22 05 2003/manual.pdf"
    )

    assert derive_project_reference("Manual_BBA120.zip") == {}
    assert derive_project_reference(needlepunch) == {}
    assert extract_query_project_codes("résume le projet BBA120") == []
    assert extract_query_project_codes("résume le projet 61038") == []
    assert project_reference_terms("BBA120") == ()
    assert numeric_project_candidates("61038") == ()


@pytest.mark.parametrize("scheme", ("", "industrial", "generic", "sentinel_ci"))
def test_non_andritz_schemes_never_invent_bba120(scheme):
    assert derive_project_reference("Manual_BBA120.zip", scheme=scheme) == {}
    assert extract_query_project_codes("résume BBA120", scheme=scheme) == []
    assert extract_query_project_codes("résume le projet 61038", scheme=scheme) == []


def test_project_reference_scheme_follows_stamped_family_only():
    assert project_reference_scheme(SimpleNamespace(settings={"family": "andritz"})) == ANDRITZ
    assert project_reference_scheme(SimpleNamespace(settings={"family": "industrial"})) == ""
    assert project_reference_scheme(SimpleNamespace(settings={"family": "generic"})) == ""
    assert project_reference_scheme(SimpleNamespace(slug="andritz", settings={})) == ""
    assert project_reference_scheme(SimpleNamespace(slug="andritz", name="Andritz")) == ""
