"""Provider-neutral OCR extraction for visual document intelligence.

The production path is service-first (PP-OCR compatible HTTP service), with an
optional local Tesseract fallback for development or small deployments. All
dependencies are intentionally soft: unavailable OCR providers produce warnings
instead of breaking ingestion unless OCR is marked required.
"""
from __future__ import annotations

import base64
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool = True
    provider_priority: tuple[str, ...] = ("ppocr_service", "tesseract_local")
    ppocr_endpoint_url: str | None = None
    languages: tuple[str, ...] = ("eng", "fra")
    min_confidence: float = 0.0
    timeout_seconds: float = 30.0
    retries: int = 2
    retry_backoff_ms: int = 250
    required: bool = False
    openai_vision_enabled: bool = False
    openai_model: str = "gpt-4o-mini"
    openai_detail: str = "low"
    openai_max_image_bytes: int = 5_000_000
    openai_enrich_min_chars: int = 24
    openai_enrich_min_confidence: float = 0.45


def build_ocr_config(overrides: dict[str, Any] | None = None) -> OcrConfig:
    """Resolve OCR config from global env plus optional workspace/request overrides."""
    overrides = overrides or {}
    priority_raw = overrides.get("provider_priority", settings.document_ocr_provider_priority)
    if isinstance(priority_raw, str):
        provider_priority = tuple(item.strip() for item in priority_raw.split(",") if item.strip())
    else:
        provider_priority = tuple(str(item).strip() for item in priority_raw or [] if str(item).strip())
    languages_raw = overrides.get("languages", settings.document_ocr_languages)
    if isinstance(languages_raw, str):
        languages = tuple(item.strip() for item in languages_raw.replace("+", ",").split(",") if item.strip())
    else:
        languages = tuple(str(item).strip() for item in languages_raw or [] if str(item).strip())
    return OcrConfig(
        enabled=bool(overrides.get("enabled", settings.document_ocr_enabled)),
        provider_priority=provider_priority or ("ppocr_service", "tesseract_local"),
        ppocr_endpoint_url=(overrides.get("ppocr_endpoint_url") or settings.document_ocr_ppocr_endpoint_url or None),
        languages=languages or ("eng",),
        min_confidence=float(overrides.get("min_confidence", settings.document_ocr_min_confidence) or 0.0),
        timeout_seconds=float(overrides.get("timeout_seconds", settings.document_ocr_timeout_seconds) or 30.0),
        retries=int(overrides.get("retries", settings.document_ocr_retries) or 0),
        retry_backoff_ms=int(overrides.get("retry_backoff_ms", settings.document_ocr_retry_backoff_ms) or 0),
        required=bool(overrides.get("required", settings.document_ocr_required)),
        openai_vision_enabled=bool(overrides.get("openai_vision_enabled", settings.document_ocr_openai_vision_enabled)),
        openai_model=str(overrides.get("openai_model", settings.document_ocr_openai_model) or "gpt-4o-mini"),
        openai_detail=str(overrides.get("openai_detail", settings.document_ocr_openai_detail) or "low"),
        openai_max_image_bytes=int(overrides.get("openai_max_image_bytes", settings.document_ocr_openai_max_image_bytes) or 0),
        openai_enrich_min_chars=int(
            overrides.get("openai_enrich_min_chars", settings.document_ocr_openai_enrich_min_chars) or 0
        ),
        openai_enrich_min_confidence=float(
            overrides.get("openai_enrich_min_confidence", settings.document_ocr_openai_enrich_min_confidence) or 0.0
        ),
    )


def resolve_ocr_config_for_workspace(workspace_id: str | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a serialisable OCR config dict for parser kwargs.

    Workspace-specific settings are optional and live under
    ``workspace.settings.document_intelligence.ocr``. This keeps OCR provider
    choices configurable without requiring every parser to know about DB models.
    """
    merged: dict[str, Any] = {}
    if workspace_id:
        try:
            from app.db.base import SessionLocal
            from app.models.workspace import Workspace

            db = SessionLocal()
            try:
                workspace = db.query(Workspace).filter(Workspace.id == str(workspace_id)).first()
                settings_dict = dict(workspace.settings or {}) if workspace and isinstance(workspace.settings, dict) else {}
                doc_settings = settings_dict.get("document_intelligence") if isinstance(settings_dict.get("document_intelligence"), dict) else {}
                ocr_settings = doc_settings.get("ocr") if isinstance(doc_settings.get("ocr"), dict) else {}
                merged.update(ocr_settings)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not resolve workspace OCR config", workspace_id=workspace_id, error=str(exc))
    if overrides:
        merged.update(overrides)
    return build_ocr_config(merged).__dict__


def extract_ocr_for_image(
    image_path: str | Path,
    *,
    config: OcrConfig | dict[str, Any] | None = None,
    page_number: int | None = None,
) -> dict[str, Any]:
    """Extract OCR text and blocks from an image-like file.

    Returns a stable dict so parsers can persist the raw OCR artifact regardless
    of the provider used.
    """
    resolved = config if isinstance(config, OcrConfig) else build_ocr_config(config)
    path = str(image_path)
    base = {
        "schema_version": "ocr_artifact_v1",
        "source_path": path,
        "page": page_number,
        "provider": None,
        "model": None,
        "text": "",
        "blocks": [],
        "warnings": [],
    }
    if not resolved.enabled:
        return {**base, "warnings": ["ocr_disabled"]}

    warnings: list[str] = []
    fallback_result: dict[str, Any] | None = None
    providers = list(resolved.provider_priority)
    for provider_index, provider in enumerate(providers):
        try:
            if provider == "ppocr_service":
                result = _extract_ppocr_service(path, resolved)
            elif provider == "tesseract_local":
                result = _extract_tesseract_local(path, resolved)
            elif provider == "openai_vision":
                result = _extract_openai_vision(path, resolved, prior_text=(fallback_result or {}).get("text"))
            else:
                warnings.append(f"ocr_provider_unknown:{provider}")
                continue
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{provider}_failed:{exc}")
            logger.warning("OCR provider failed", provider=provider, path=path, error=str(exc))
            continue
        if result is None:
            warnings.append(f"{provider}_unavailable")
            continue
        blocks = _normalize_blocks(result.get("blocks"), resolved.min_confidence, page_number)
        text = str(result.get("text") or _blocks_to_text(blocks)).strip()
        if not text:
            warnings.append(f"{provider}_empty")
            continue
        candidate = {
            **base,
            "provider": provider,
            "model": result.get("model"),
            "text": text,
            "blocks": blocks,
            "warnings": warnings + list(result.get("warnings") or []),
        }
        if (
            provider != "openai_vision"
            and "openai_vision" in providers[provider_index + 1 :]
            and _should_try_openai_enrichment(candidate, resolved)
        ):
            fallback_result = candidate
            warnings.append(f"{provider}_low_confidence_try_openai_vision")
            continue
        return candidate

    if fallback_result is not None:
        return {
            **fallback_result,
            "warnings": list(fallback_result.get("warnings") or []) + warnings + ["ocr_low_confidence_openai_unavailable"],
        }

    if resolved.required:
        raise RuntimeError("; ".join(warnings) or "OCR required but no provider returned text")
    return {**base, "warnings": warnings or ["ocr_unavailable"]}


def _extract_ppocr_service(path: str, config: OcrConfig) -> dict[str, Any] | None:
    endpoint = (config.ppocr_endpoint_url or "").strip()
    if not endpoint:
        return None
    try:
        import httpx
    except Exception:
        return None
    content = Path(path).read_bytes()
    url = f"{endpoint.rstrip('/')}/v1/ppocr/items"
    files = {"file": (Path(path).name, content, "application/octet-stream")}
    last_exc: Exception | None = None
    for attempt in range(max(0, config.retries) + 1):
        try:
            with httpx.Client(timeout=max(1.0, config.timeout_seconds)) as client:
                response = client.post(url, files=files)
            if int(response.status_code) == 429 or int(response.status_code) >= 500:
                raise RuntimeError(f"PP-OCR service error {response.status_code}")
            if int(response.status_code) >= 400:
                return None
            data = response.json()
            items = data.get("items")
            if not isinstance(items, list):
                return None
            blocks: list[dict[str, Any]] = []
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                blocks.append(
                    {
                        "id": str(item.get("id", idx)),
                        "text": text,
                        "bbox": {
                            "x1": _to_number(item.get("x1")),
                            "y1": _to_number(item.get("y1")),
                            "x2": _to_number(item.get("x2")),
                            "y2": _to_number(item.get("y2")),
                        },
                        "confidence": _to_number(item.get("conf")),
                    }
                )
            return {"text": _blocks_to_text(blocks), "blocks": blocks, "model": data.get("model") or "ppocr_service"}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= config.retries:
                break
            time.sleep((max(0, config.retry_backoff_ms) / 1000.0) * (2**attempt))
    if last_exc:
        raise last_exc
    return None


def _extract_tesseract_local(path: str, config: OcrConfig) -> dict[str, Any] | None:
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return None
    lang = "+".join(config.languages or ("eng",))
    image = Image.open(path)
    blocks: list[dict[str, Any]] = []
    try:
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
        total = len(data.get("text", []))
        for idx in range(total):
            text = str(data["text"][idx] or "").strip()
            if not text:
                continue
            conf = _to_number(data.get("conf", [None])[idx])
            if conf is not None and conf < 0:
                conf = None
            x = _to_number(data.get("left", [0])[idx]) or 0
            y = _to_number(data.get("top", [0])[idx]) or 0
            w = _to_number(data.get("width", [0])[idx]) or 0
            h = _to_number(data.get("height", [0])[idx]) or 0
            blocks.append(
                {
                    "id": str(idx),
                    "text": text,
                    "bbox": {"x1": x, "y1": y, "x2": x + w, "y2": y + h},
                    "confidence": conf,
                }
            )
    except Exception:
        text = pytesseract.image_to_string(image, lang=lang)
        if text.strip():
            blocks.append({"id": "0", "text": text.strip(), "bbox": {}, "confidence": None})
    return {"text": _blocks_to_text(blocks), "blocks": blocks, "model": f"tesseract:{lang}"}


def _extract_openai_vision(path: str, config: OcrConfig, *, prior_text: str | None = None) -> dict[str, Any] | None:
    """Use OpenAI vision as an optional premium OCR/enrichment lane.

    This provider is intentionally opt-in because it sends image content to an
    external model and can create variable costs. It is best used after
    deterministic OCR fails or returns weak evidence.
    """
    if not config.openai_vision_enabled:
        return None
    if not settings.openai_api_key:
        return None
    image_bytes = Path(path).read_bytes()
    if config.openai_max_image_bytes and len(image_bytes) > config.openai_max_image_bytes:
        return {
            "text": "",
            "blocks": [],
            "model": config.openai_model,
            "warnings": [f"openai_vision_image_too_large:{len(image_bytes)}"],
        }
    try:
        from openai import OpenAI
    except Exception:
        return None

    mime_type = mimetypes.guess_type(path)[0] or "image/png"
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    prior_hint = f"\nExisting weak OCR text, use only as a hint:\n{prior_text[:1600]}" if prior_text else ""
    prompt = (
        "Extract all visible text from this industrial/document image. "
        "Preserve table-like line breaks, labels, numbers and units. "
        "Do not infer hidden values and do not translate. "
        "Return only the extracted text, no commentary."
        f"{prior_hint}"
    )
    client = OpenAI(api_key=settings.openai_api_key, timeout=max(1.0, config.timeout_seconds))
    response = client.chat.completions.create(
        model=config.openai_model,
        temperature=0,
        max_tokens=1600,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_b64}",
                            "detail": config.openai_detail,
                        },
                    },
                ],
            }
        ],
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        return {"text": "", "blocks": [], "model": getattr(response, "model", config.openai_model)}
    return {
        "text": text,
        "blocks": [{"id": "openai_vision_text", "text": text, "bbox": {}, "confidence": None}],
        "model": getattr(response, "model", config.openai_model),
        "warnings": ["openai_vision_no_bounding_boxes"],
    }


def _normalize_blocks(blocks: Any, min_confidence: float, page_number: int | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks or []):
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        confidence = _to_number(block.get("confidence"))
        if confidence is not None and confidence < min_confidence:
            continue
        out.append(
            {
                "id": str(block.get("id", idx)),
                "text": text,
                "bbox": dict(block.get("bbox") or {}),
                "confidence": confidence,
                "page": page_number,
            }
        )
    return out


def _blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    sorted_blocks = sorted(
        blocks,
        key=lambda item: (
            (item.get("bbox") or {}).get("y1") if (item.get("bbox") or {}).get("y1") is not None else 10**9,
            (item.get("bbox") or {}).get("x1") if (item.get("bbox") or {}).get("x1") is not None else 10**9,
            str(item.get("id") or ""),
        ),
    )
    return "\n".join(str(item.get("text") or "").strip() for item in sorted_blocks if str(item.get("text") or "").strip())


def _to_number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _should_try_openai_enrichment(candidate: dict[str, Any], config: OcrConfig) -> bool:
    if not config.openai_vision_enabled:
        return False
    text = str(candidate.get("text") or "").strip()
    if len(text) < max(0, config.openai_enrich_min_chars):
        return True
    confidence = _average_normalized_confidence(candidate.get("blocks") or [])
    if confidence is None:
        return False
    return confidence < max(0.0, config.openai_enrich_min_confidence)


def _average_normalized_confidence(blocks: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for block in blocks:
        confidence = _to_number(block.get("confidence") if isinstance(block, dict) else None)
        if confidence is None:
            continue
        values.append(confidence / 100.0 if confidence > 1 else confidence)
    if not values:
        return None
    return sum(values) / len(values)
