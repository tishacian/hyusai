from __future__ import annotations

from types import SimpleNamespace

from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.table_intelligence import (
    TableQueryEngine,
    replace_document_table_facts,
    resolve_table_profile,
)


def _seed_collection(db_session) -> tuple[Workspace, KnowledgeCollection]:
    workspace = Workspace(
        id="ws-table",
        name="Tables",
        slug="tables",
        settings={
            "knowledge_scopes": [
                {
                    "key": "pilot",
                    "label": "Pilot",
                    "collection_slugs": ["table-pilot"],
                    "table_profile_key": "industrial",
                    "is_default": True,
                }
            ],
            "table_intelligence": {
                "default_profile": "industrial",
                "profiles": [
                    {
                        "key": "industrial",
                        "label": "Industrial tables",
                        "synonyms": {"weight": ["poids"], "hemp": ["chanvre"]},
                        "aggregation_policy": {"allow_mean": True, "require_compatible_units": True},
                    }
                ],
            },
        },
    )
    collection = KnowledgeCollection(
        id="collection-table",
        workspace_id=workspace.id,
        slug="table-pilot",
        name="Table Pilot",
        vector_collection_name="tables__table_pilot",
        artifact_prefix="knowledge/ws-table/table-pilot",
    )
    db_session.add_all([workspace, collection])
    db_session.commit()
    return workspace, collection


def _parsed_doc() -> SimpleNamespace:
    return SimpleNamespace(
        id="doc-table",
        filename="measurements.xlsx",
        file_path="/tmp/measurements.xlsx",
        document_type=SimpleNamespace(value="spreadsheet"),
        metadata={"source_path": "/tmp/measurements.xlsx"},
        structured_content={
            "table_artifacts": {
                "cell_facts": [
                    {
                        "sheet_name": "Def strips",
                        "table_region_id": "def-strips-1",
                        "row_index": 2,
                        "row_label": "B",
                        "label_cell": "A2",
                        "value_cell": "B2",
                        "cell_ref": "B2",
                        "value": "85",
                    },
                    {
                        "sheet_name": "Def strips",
                        "table_region_id": "def-strips-1",
                        "row_index": 14,
                        "row_label": "N",
                        "label_cell": "A14",
                        "value_cell": "B14",
                        "cell_ref": "B14",
                        "value": "140",
                    },
                ],
                "table_facts": [
                    {
                        "sheet_name": "Tests",
                        "table_region_id": "tests-1",
                        "row_index": 4,
                        "row_label": "Weight (g/m²)",
                        "column_header": "chanvre",
                        "cell_ref": "C4",
                        "value": "120",
                        "unit": "g/m²",
                    },
                    {
                        "sheet_name": "Tests",
                        "table_region_id": "tests-1",
                        "row_index": 5,
                        "row_label": "Weight (g/m²)",
                        "column_header": "chanvre",
                        "cell_ref": "C5",
                        "value": "130",
                        "unit": "g/m²",
                    },
                ],
            }
        },
    )


def test_table_facts_are_persisted_and_lookup_is_cell_sourced(db_session, tmp_path, monkeypatch):
    workspace, collection = _seed_collection(db_session)
    monkeypatch.setattr("app.services.object_store.settings.object_store_base_path", str(tmp_path))

    rows = replace_document_table_facts(
        db_session,
        workspace=workspace,
        collection=collection,
        parsed_doc=_parsed_doc(),
    )
    db_session.commit()

    assert len(rows) == 4
    result = TableQueryEngine(db_session).query(
        workspace=workspace,
        collection_or_scope="pilot",
        question="Quelle est la valeur du label N ?",
    )

    assert result["intent"] == "lookup"
    assert result["answer_payload"]["value"] == "140"
    assert result["evidence_rows"][0]["sheet_name"] == "Def strips"
    assert result["evidence_rows"][0]["cell_ref"] == "B14"
    assert result["effective_profile"]["key"] == "industrial"


def test_table_query_aggregate_is_exhaustive_and_unit_checked(db_session, tmp_path, monkeypatch):
    workspace, collection = _seed_collection(db_session)
    monkeypatch.setattr("app.services.object_store.settings.object_store_base_path", str(tmp_path))
    replace_document_table_facts(
        db_session,
        workspace=workspace,
        collection=collection,
        parsed_doc=_parsed_doc(),
    )
    db_session.commit()

    result = TableQueryEngine(db_session).query(
        workspace=workspace,
        collection_or_scope="pilot",
        question="Quelle est la moyenne du poids sur le chanvre ?",
    )

    assert result["intent"] == "aggregate"
    assert result["answer_payload"]["mean"] == 125
    assert result["answer_payload"]["count"] == 2
    assert {row["cell_ref"] for row in result["evidence_rows"]} == {"C4", "C5"}


def test_table_profile_resolution_falls_back_to_global(db_session):
    workspace = Workspace(id="ws-empty-table", name="Empty", slug="empty", settings={})
    db_session.add(workspace)
    db_session.commit()

    resolved = resolve_table_profile(workspace=workspace)

    assert resolved.profile["key"] == "generic"
    assert resolved.source == "global_default"
