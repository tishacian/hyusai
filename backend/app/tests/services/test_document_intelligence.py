from __future__ import annotations

import zipfile
from types import SimpleNamespace

import pytest

from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.document_intelligence import (
    DocumentQueryEngine,
    ensure_document_artifacts,
    replace_document_facts,
    resolve_document_profile,
)
from app.services.document_parser.parsers.docx_parser import DocxParser


def _seed_collection(db_session) -> tuple[Workspace, KnowledgeCollection]:
    workspace = Workspace(
        id="ws-document",
        name="Documents",
        slug="documents",
        settings={
            "knowledge_scopes": [
                {
                    "key": "manuals",
                    "label": "Manuals",
                    "collection_slugs": ["manuals-pilot"],
                    "document_profile_key": "industrial_docs",
                    "is_default": True,
                }
            ],
            "document_intelligence": {
                "default_profile": "industrial_docs",
                "profiles": [
                    {
                        "key": "industrial_docs",
                        "label": "Industrial manuals",
                        "synonyms": {
                            "torque": ["couple"],
                            "warning": ["avertissement"],
                        },
                    }
                ],
            },
        },
    )
    collection = KnowledgeCollection(
        id="collection-document",
        workspace_id=workspace.id,
        slug="manuals-pilot",
        name="Manuals Pilot",
        vector_collection_name="documents__manuals_pilot",
        artifact_prefix="knowledge/ws-document/manuals-pilot",
    )
    db_session.add_all([workspace, collection])
    db_session.commit()
    return workspace, collection


def _parsed_manual() -> SimpleNamespace:
    return SimpleNamespace(
        id="doc-manual",
        filename="maintenance-manual.pdf",
        file_path="/tmp/maintenance-manual.pdf",
        document_type=SimpleNamespace(value="pdf"),
        metadata={"source_path": "/tmp/maintenance-manual.pdf"},
        structured_content={
            "headings": [
                {"level": 1, "text": "Maintenance procedure", "paragraph_index": 1},
            ],
        },
        chunks=[
            {
                "page": 4,
                "chunk_index": 0,
                "content": "\n".join(
                    [
                        "Maintenance procedure",
                        "WARNING: disconnect power before maintenance.",
                        "Torque: 12 Nm",
                        "1. Check belt tension before restart.",
                    ]
                ),
            }
        ],
        raw_content="",
        tables=[],
    )


def test_document_facts_are_extracted_persisted_and_queryable(db_session, tmp_path, monkeypatch):
    workspace, collection = _seed_collection(db_session)
    monkeypatch.setattr("app.services.object_store.settings.object_store_base_path", str(tmp_path))
    parsed = _parsed_manual()

    artifact = ensure_document_artifacts(parsed)
    rows = replace_document_facts(
        db_session,
        workspace=workspace,
        collection=collection,
        parsed_doc=parsed,
    )
    db_session.commit()

    assert artifact["schema_version"] == "document_artifact_v1"
    assert {row.semantic_type for row in rows} >= {
        "document_warning",
        "document_parameter",
        "document_procedure_step",
    }

    result = DocumentQueryEngine(db_session).query(
        workspace=workspace,
        collection_or_scope="manuals",
        question="Quel est le couple indiqué dans la procédure de maintenance ?",
    )

    assert result["intent"] == "parameter"
    assert result["effective_profile"]["key"] == "industrial_docs"
    assert result["evidence_rows"][0]["value_raw"] == "12 Nm"
    assert result["evidence_rows"][0]["page"] == 4


def test_document_query_warning_returns_sourced_warning(db_session, tmp_path, monkeypatch):
    workspace, collection = _seed_collection(db_session)
    monkeypatch.setattr("app.services.object_store.settings.object_store_base_path", str(tmp_path))
    replace_document_facts(
        db_session,
        workspace=workspace,
        collection=collection,
        parsed_doc=_parsed_manual(),
    )
    db_session.commit()

    result = DocumentQueryEngine(db_session).query(
        workspace=workspace,
        collection_or_scope="manuals",
        question="Quels avertissements sont associés à la maintenance ?",
    )

    assert result["intent"] == "warning"
    assert "disconnect power" in result["evidence_rows"][0]["content"]
    assert result["evidence_rows"][0]["semantic_type"] == "document_warning"


@pytest.mark.asyncio
async def test_docx_parser_extracts_headings_paragraphs_and_tables(tmp_path):
    path = tmp_path / "manual.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Maintenance</w:t></w:r></w:p>
    <w:p><w:r><w:t>WARNING: verify guards before start.</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Parameter</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>Speed</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>42 m/min</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    parsed = await DocxParser().parse(str(path))

    assert parsed.document_type.value == "docx"
    assert parsed.structured_content["heading_count"] == 1
    assert parsed.structured_content["table_count"] == 1
    assert parsed.structured_content["paragraphs"][1]["text"] == "WARNING: verify guards before start."
    assert parsed.tables[0]["rows"][1] == ["Speed", "42 m/min"]


def test_document_profile_resolution_falls_back_to_global(db_session):
    workspace = Workspace(id="ws-empty-document", name="Empty", slug="empty", settings={})
    db_session.add(workspace)
    db_session.commit()

    resolved = resolve_document_profile(workspace=workspace)

    assert resolved.profile["key"] == "generic_document"
    assert resolved.source == "global_default"
