"""Schema-driven CaptureTemplate registry for constrained capture forks.

The provisional ``fse_intervention_v1`` shape mirrors the frontend registry in
``frontend-ng/.../capture-templates.ts``. Meeting feedback should revise the
config here (and the FE mirror), not fork ``knowledge_capture``.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional

FSE_INTERVENTION_TEMPLATE_ID = "fse_intervention_v1"
FSE_INTERVENTION_REPORT_TEMPLATE_ID = "fse_intervention_report_v1"

CaptureTemplate = Dict[str, Any]


FSE_INTERVENTION_V1: CaptureTemplate = {
    "id": FSE_INTERVENTION_TEMPLATE_ID,
    "label": "Rapport d'intervention FSE",
    "plan_seed": {
        "topics": [
            {
                "title": "Contexte et objet de l’intervention",
                "subtopics": [
                    {"title": "Constat"},
                    {"title": "Action"},
                    {"title": "Responsable"},
                    {"title": "Échéance"},
                ],
            },
            {
                "title": "Travaux réalisés / observations",
                "subtopics": [
                    {"title": "Constat"},
                    {"title": "Action"},
                    {"title": "Responsable"},
                    {"title": "Échéance"},
                ],
            },
            {
                "title": "Points ouverts et suivi",
                "subtopics": [
                    {"title": "Constat"},
                    {"title": "Action"},
                    {"title": "Responsable"},
                    {"title": "Échéance"},
                ],
            },
            {
                "title": "Photos et annexes",
                "subtopics": [{"title": "Références pointées"}],
            },
        ],
    },
    "required_fields": [
        {"key": "customer", "label": "Client", "kind": "text", "required": True},
        {"key": "country", "label": "Pays", "kind": "text", "required": True},
        {"key": "site_or_machine", "label": "Site / machine", "kind": "text", "required": True},
        {"key": "reference", "label": "Référence", "kind": "text", "required": True},
        {"key": "participants", "label": "Participants", "kind": "text", "required": True},
        {"key": "intervention_date", "label": "Date d'intervention", "kind": "date", "required": True},
        {"key": "distribution", "label": "Diffusion", "kind": "text", "required": True},
    ],
    "report_template_id": FSE_INTERVENTION_REPORT_TEMPLATE_ID,
    "publication": {
        "collection": "andritz-fse-reports",
        "source_type": "fse_report",
    },
    "ui": {
        "lock_plan": True,
        "hide_free_mode": True,
    },
}

_REGISTRY: Dict[str, CaptureTemplate] = {
    FSE_INTERVENTION_TEMPLATE_ID: FSE_INTERVENTION_V1,
}


def get_capture_template(template_id: Optional[str]) -> Optional[CaptureTemplate]:
    if not template_id:
        return None
    template = _REGISTRY.get(str(template_id).strip())
    return deepcopy(template) if template else None


def list_capture_templates() -> List[CaptureTemplate]:
    return [deepcopy(item) for item in _REGISTRY.values()]


def template_id_from_system_settings(settings: Any) -> Optional[str]:
    if not isinstance(settings, Mapping):
        return None
    capture = settings.get("capture")
    if not isinstance(capture, Mapping):
        return None
    raw = capture.get("template_id")
    if not isinstance(raw, str):
        return None
    clean = raw.strip()
    return clean or None


def plan_seed_to_provided_text(template: CaptureTemplate) -> str:
    topics = (template.get("plan_seed") or {}).get("topics") or []
    blocks: List[str] = []
    for topic in topics:
        if not isinstance(topic, Mapping):
            continue
        title = str(topic.get("title") or "").strip()
        if not title:
            continue
        lines = [f"# {title}"]
        for sub in topic.get("subtopics") or []:
            if not isinstance(sub, Mapping):
                continue
            subtitle = str(sub.get("title") or "").strip()
            if subtitle:
                lines.append(f"## {subtitle}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def header_fields_from_plan(plan: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    if not isinstance(plan, Mapping):
        return {}
    raw = plan.get("header_fields")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): str(value).strip()
        for key, value in raw.items()
        if str(key).strip() and str(value or "").strip()
    }


def missing_required_fields(
    template: CaptureTemplate,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    values = header_fields if isinstance(header_fields, Mapping) else {}
    missing: List[Dict[str, Any]] = []
    for field in template.get("required_fields") or []:
        if not isinstance(field, Mapping):
            continue
        if not field.get("required", True):
            continue
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        if str(values.get(key) or "").strip():
            continue
        missing.append(dict(field))
    return missing


def required_field_gaps(
    template: CaptureTemplate,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Priority oracle / proposal gaps for missing required header fields."""
    gaps: List[Dict[str, Any]] = []
    for index, field in enumerate(missing_required_fields(template, header_fields), start=1):
        key = str(field.get("key") or f"field-{index}")
        label = str(field.get("label") or key)
        gaps.append(
            {
                "id": f"gap-req-{key}",
                "slug": f"required_field_{key}",
                "title": f"Champ obligatoire : {label}",
                "description": f"Renseigner « {label} » (en-tête du rapport).",
                "priority": 0.99,
                "status": "open",
                "blocking": True,
                "required_field_key": key,
                "source": "capture_template_required_field",
            }
        )
    return gaps


def required_field_open_questions(
    template: CaptureTemplate,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Blocking open questions for finalize / review checklist."""
    questions: List[Dict[str, Any]] = []
    for field in missing_required_fields(template, header_fields):
        key = str(field.get("key") or "")
        label = str(field.get("label") or key)
        questions.append(
            {
                "gap_id": f"gap-req-{key}",
                "id": f"req-{key}",
                "reason": "required_field_missing",
                "follow_up": f"Champ obligatoire manquant : {label}",
                "text": f"Champ obligatoire manquant : {label}",
                "priority": 0.99,
                "status": "open",
                "blocking": True,
                "required_field_key": key,
                "source": "capture_template_required_field",
            }
        )
    return questions


def publication_defaults_from_template(template: Optional[CaptureTemplate]) -> Dict[str, Any]:
    if not template:
        return {}
    publication = template.get("publication") if isinstance(template.get("publication"), Mapping) else {}
    collection = str(publication.get("collection") or "").strip()
    source_type = str(publication.get("source_type") or "").strip()
    out: Dict[str, Any] = {}
    if collection:
        out["destination"] = collection
        out["destination_scope"] = collection
    if source_type:
        out["source_type"] = source_type
    return out


def tracking_metadata_from_header(header_fields: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    values = header_fields if isinstance(header_fields, Mapping) else {}
    mapping = {
        "customer": "fse_customer",
        "site_or_machine": "fse_machine",
        "reference": "fse_reference",
        "country": "fse_country",
        "intervention_date": "fse_intervention_date",
    }
    out: Dict[str, str] = {}
    for source_key, meta_key in mapping.items():
        value = str(values.get(source_key) or "").strip()
        if value:
            out[meta_key] = value
    return out


def attach_template_to_plan(plan: Dict[str, Any], template: CaptureTemplate) -> Dict[str, Any]:
    """Stamp template snapshot + empty header on the session plan (idempotent)."""
    plan["capture_template"] = {
        "id": template.get("id"),
        "label": template.get("label"),
        "report_template_id": template.get("report_template_id"),
        "required_fields": deepcopy(template.get("required_fields") or []),
        "publication": deepcopy(template.get("publication") or {}),
        "ui": deepcopy(template.get("ui") or {}),
        "plan_seed": deepcopy(template.get("plan_seed") or {}),
    }
    if not isinstance(plan.get("header_fields"), dict):
        plan["header_fields"] = {}
    return plan


def resolve_session_capture_template(
    *,
    plan: Optional[Mapping[str, Any]] = None,
    metrics: Optional[Mapping[str, Any]] = None,
    system_settings: Any = None,
) -> Optional[CaptureTemplate]:
    """Resolve template id from plan snapshot, metrics, or system settings."""
    candidates: List[Optional[str]] = []
    if isinstance(plan, Mapping):
        snapshot = plan.get("capture_template")
        if isinstance(snapshot, Mapping):
            candidates.append(snapshot.get("id") if isinstance(snapshot.get("id"), str) else None)
        candidates.append(plan.get("template_id") if isinstance(plan.get("template_id"), str) else None)
    if isinstance(metrics, Mapping):
        candidates.append(
            metrics.get("capture_template_id")
            if isinstance(metrics.get("capture_template_id"), str)
            else None
        )
    candidates.append(template_id_from_system_settings(system_settings))
    for candidate in candidates:
        template = get_capture_template(candidate)
        if template:
            return template
    return None
