from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.document_intelligence import ensure_document_artifacts, replace_document_facts
from app.services.document_parser.parsers.image_parser import ImageParser
from app.services.document_parser.parsers.pdf_parser_advanced import AdvancedPDFParser
from app.services.ocr import build_ocr_config, extract_ocr_for_image, resolve_ocr_config_for_workspace


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
                    "openai_vision_enabled": True,
                    "openai_model": "gpt-4o-mini",
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
    assert config.openai_vision_enabled is True
    assert config.openai_model == "gpt-4o-mini"
    assert config.required is True


def test_pdf_parser_honors_ocr_disabled_config():
    parser = AdvancedPDFParser()

    assert parser._should_run_ocr([], use_ocr=True, ocr_config={"enabled": False}) is False
    assert parser._should_run_ocr([], use_ocr=False, ocr_config={"enabled": False}) is False
    assert (
        parser._should_run_ocr(
            [],
            use_ocr=False,
            ocr_config={"enabled": True, "scan_detection": True, "min_text_chars_for_native_pdf": 80},
        )
        is True
    )
    assert parser._should_run_ocr([], use_ocr=False, ocr_config={"enabled": True, "scan_detection": False}) is False


@pytest.mark.asyncio
async def test_pdf_parser_uses_pymupdf_fast_path_without_pdfplumber(monkeypatch):
    parser = AdvancedPDFParser()

    async def fake_fast_path(_path):
        return [{"page_number": 1, "text": "native text"}]

    def guarded_import(name, *args, **kwargs):
        if name == "pdfplumber":
            raise AssertionError("pdfplumber should not run when PyMuPDF extracted text")
        return original_import(name, *args, **kwargs)

    original_import = builtins.__import__
    monkeypatch.setattr(parser, "_extract_with_pymupdf_text", fake_fast_path)
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    pages = await parser._extract_with_markdown_converter("/tmp/native.pdf", ocr_config={"enabled": True})

    assert pages == [{"page_number": 1, "text": "native text"}]


@pytest.mark.asyncio
async def test_pdf_parser_skips_heavy_fallback_when_ocr_disabled(monkeypatch):
    parser = AdvancedPDFParser()

    async def fake_fast_path(_path):
        return []

    def guarded_import(name, *args, **kwargs):
        if name == "pdfplumber":
            raise AssertionError("pdfplumber should not run for OCR-off baseline without native text")
        return original_import(name, *args, **kwargs)

    original_import = builtins.__import__
    monkeypatch.setattr(parser, "_extract_with_pymupdf_text", fake_fast_path)
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    pages = await parser._extract_with_markdown_converter("/tmp/scanned.pdf", ocr_config={"enabled": False})

    assert pages == []


def test_openai_vision_enriches_low_confidence_ocr(tmp_path, monkeypatch):
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake image")

    def fake_tesseract(path, config):
        return {
            "text": "??",
            "blocks": [{"id": "1", "text": "??", "bbox": {}, "confidence": 0.1}],
            "model": "tesseract:eng",
        }

    def fake_openai(path, config, *, prior_text=None):
        return {
            "text": "Serial number ABC123\nPressure = 12 bar",
            "blocks": [{"id": "openai", "text": "Serial number ABC123\nPressure = 12 bar", "bbox": {}, "confidence": None}],
            "model": "gpt-4o-mini",
        }

    monkeypatch.setattr("app.services.ocr._extract_ppocr_service", lambda path, config: None)
    monkeypatch.setattr("app.services.ocr._extract_tesseract_local", fake_tesseract)
    monkeypatch.setattr("app.services.ocr._extract_openai_vision", fake_openai)

    result = extract_ocr_for_image(
        image_path,
        config={
            "provider_priority": ["ppocr_service", "tesseract_local", "openai_vision"],
            "openai_vision_enabled": True,
            "openai_enrich_min_chars": 24,
            "openai_enrich_min_confidence": 0.45,
        },
    )

    assert result["provider"] == "openai_vision"
    assert "Pressure = 12 bar" in result["text"]
    assert "tesseract_local_low_confidence_try_openai_vision" in result["warnings"]


def test_openai_vision_is_opt_in_even_when_listed(tmp_path, monkeypatch):
    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"fake image")

    def fake_tesseract(path, config):
        return {
            "text": "weak",
            "blocks": [{"id": "1", "text": "weak", "bbox": {}, "confidence": 0.1}],
            "model": "tesseract:eng",
        }

    def fail_openai(path, config, *, prior_text=None):
        raise AssertionError("openai vision should not run when disabled")

    monkeypatch.setattr("app.services.ocr._extract_ppocr_service", lambda path, config: None)
    monkeypatch.setattr("app.services.ocr._extract_tesseract_local", fake_tesseract)
    monkeypatch.setattr("app.services.ocr._extract_openai_vision", fail_openai)

    result = extract_ocr_for_image(
        image_path,
        config={
            "provider_priority": ["tesseract_local", "openai_vision"],
            "openai_vision_enabled": False,
        },
    )

    assert result["provider"] == "tesseract_local"
    assert result["text"] == "weak"
