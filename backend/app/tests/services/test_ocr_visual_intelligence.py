from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.document_intelligence import ensure_document_artifacts, replace_document_facts
from app.services.document_parser.parsers.image_parser import ImageParser
from app.services.ocr import build_ocr_config, resolve_ocr_config_for_workspace


@pytest.mark.asyncio
async def test_image_parser_turns_ocr_blocks_into_chunks_and_artifacts(tmp_path, monkeypatch):
    image_path = tmp_path / "panel.png"
    image_path.write_bytes(b"not-really-an-image")

    def fake_ocr(path, *, config=None, page_number=None):
        return {
            "schema_version": "ocr_artifact_v1",
            "source_path": str(path),
            "page": page_number,
            "provider": "ppocr_service",
            "model": "ppocr-test",
            "text": "WARNING\nPressure = 12 bar",
            "blocks": [
                {"id": "1", "text": "WARNING", "bbox": {"x1": 1, "y1": 2, "x2": 20, "y2": 12}, "confidence": 0.92},
                {"id": "2", "text": "Pressure = 12 bar", "bbox": {"x1": 1, "y1": 20, "x2": 80, "y2": 35}, "confidence": 0.88},
            ],
            "warnings": [],
        }

    monkeypatch.setattr("app.services.document_parser.parsers.image_parser.extract_ocr_for_image", fake_ocr)

    parsed = await ImageParser().parse(str(image_path))

    assert parsed.document_type.value == "image"
    assert parsed.chunks[0]["semantic_type"] == "document_ocr_text"
    assert "Pressure = 12 bar" in parsed.raw_content
    assert parsed.structured_content["ocr_block_count"] == 2


def test_ocr_artifacts_are_persisted_as_document_facts(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.object_store.settings.object_store_base_path", str(tmp_path))
    workspace = Workspace(id="ws-ocr", name="OCR", slug="ocr", settings={})
    collection = KnowledgeCollection(
        id="collection-ocr",
        workspace_id=workspace.id,
        slug="visual-pilot",
        name="Visual Pilot",
        vector_collection_name="ocr__visual_pilot",
        artifact_prefix="knowledge/ws-ocr/visual-pilot",
    )
    db_session.add_all([workspace, collection])
    db_session.commit()

    parsed = SimpleNamespace(
        id="visual-doc",
        filename="machine-panel.png",
        file_path="/tmp/machine-panel.png",
        document_type=SimpleNamespace(value="image"),
        metadata={},
        structured_content={
            "ocr_artifacts": [
                {
                    "provider": "ppocr_service",
                    "model": "ppocr-test",
                    "text": "Pressure = 12 bar",
                    "blocks": [
                        {
                            "text": "Pressure = 12 bar",
                            "bbox": {"x1": 10, "y1": 10, "x2": 100, "y2": 30},
                            "confidence": 0.9,
                        }
                    ],
                }
            ]
        },
        chunks=[],
        raw_content="",
        tables=[],
    )

    artifact = ensure_document_artifacts(parsed)
    rows = replace_document_facts(db_session, workspace=workspace, collection=collection, parsed_doc=parsed)
    db_session.commit()

    assert artifact["diagnostics"]["fact_count"] == 2
    assert {row.semantic_type for row in rows} == {"document_ocr_text", "visual_text_block"}
    block = next(row for row in rows if row.semantic_type == "visual_text_block")
    assert block.evidence_locator["bbox"]["x1"] == 10
    assert block.confidence == 0.9


def test_workspace_ocr_config_overrides_global_defaults(db_session):
    workspace = Workspace(
        id="ws-ocr-config",
        name="OCR Config",
        slug="ocr-config",
        settings={
            "document_intelligence": {
                "ocr": {
                    "enabled": True,
                    "provider_priority": ["ppocr_service"],
                    "ppocr_endpoint_url": "http://ocr.local",
                    "languages": ["fra"],
                    "required": True,
                }
            }
        },
    )
    db_session.add(workspace)
    db_session.commit()

    resolved = resolve_ocr_config_for_workspace(workspace.id)
    config = build_ocr_config(resolved)

    assert config.provider_priority == ("ppocr_service",)
    assert config.ppocr_endpoint_url == "http://ocr.local"
    assert config.languages == ("fra",)
    assert config.required is True
