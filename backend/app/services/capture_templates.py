"""Schema-driven CaptureTemplate registry for constrained capture forks.

The provisional ``fse_intervention_v1`` shape mirrors the frontend registry in
``frontend-ng/.../capture-templates.ts``. Meeting feedback should revise the
config here (and the FE mirror), not fork ``knowledge_capture``.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

FSE_INTERVENTION_TEMPLATE_ID = "fse_intervention_v1"
FSE_INTERVENTION_REPORT_TEMPLATE_ID = "fse_intervention_report_v1"
DEFAULT_FSE_INTERVENTION_TYPE = "weekly_site"
HSE_SAFETY_DEFAULT = "None / rien à signaler"

CaptureTemplate = Dict[str, Any]

_CARTOUCHE_FIELDS: List[Dict[str, Any]] = [
    {"key": "customer", "label": "Client", "kind": "text", "required": True},
    {"key": "country", "label": "Pays", "kind": "text", "required": True},
    {"key": "site_or_machine", "label": "Site / machine", "kind": "text", "required": True},
    {"key": "reference", "label": "Référence", "kind": "text", "required": True},
    {"key": "participants", "label": "Participants", "kind": "text", "required": True},
    {"key": "intervention_date", "label": "Date d'intervention", "kind": "date", "required": True},
    {"key": "week", "label": "Semaine (ex. W28)", "kind": "text", "required": False},
    {"key": "issued_by", "label": "Émis par", "kind": "text", "required": False},
]

_DISTRIBUTION_OPTIONS = [
    {"value": "project_manager", "label": "Project manager"},
    {"value": "head_of_site_management", "label": "Head of site management"},
    {"value": "customer_care_manager", "label": "Customer Care Manager"},
    {"value": "global_service_director", "label": "Global Service Director"},
    {"value": "service_coordinator", "label": "Service coordinator"},
    {"value": "quality", "label": "Quality"},
    {"value": "spare_parts", "label": "Spare Parts"},
    {"value": "field_service", "label": "Field Service"},
]

_DISTRIBUTION_DEFAULT = [
    "project_manager",
    "head_of_site_management",
    "customer_care_manager",
]

_SITE_MODIFICATIONS_DEFAULT = {"selected": ["none"], "description": ""}

_SITE_MODIFICATION_OPTIONS = [
    {"value": "none", "label": "None / aucune modification"},
    {"value": "plc_hmi", "label": "HMI/PLC Modification"},
    {"value": "electrical_diagram", "label": "Electrical diagram modification"},
    {"value": "fa", "label": "FA Modification"},
]

_CUSTOMER_FEEDBACK_SUBTOPICS = [
    {"title": "Customer Specific Needs"},
    {"title": "Spare Parts"},
    {"title": "Rebuild & Improvement"},
    {"title": "Information & Assistance"},
    {"title": "Other"},
]

_FIELD_SERVICE_RUBRIC = [
    {"title": "Constat"},
    {"title": "Action"},
    {"title": "Responsable"},
    {"title": "Échéance"},
]

_OPPORTUNITIES_TOPIC = {
    "title": "Opportunités client",
    "subtopics": [
        {"title": "Audit par équipement"},
        {"title": "Risque A/B/C"},
        {"title": "Département concerné"},
    ],
}

_WEEKLY_SITE_PLAN_SEED = {
    "topics": [
        {
            "title": "HSE — Health Safety and Environment",
            "subtopics": [
                {"title": "Incidents (new/total)"},
                {"title": "Accidents (new/total)"},
                {"title": "Safety deviation"},
                {"title": "Environmental measures & deviation"},
            ],
        },
        {
            "title": "Executive Summary / Situation site",
            "subtopics": [
                {"title": "Site Situation"},
                {"title": "Overall progress / Risks for execution"},
            ],
        },
        {
            "title": "Travaux mécaniques",
            "subtopics": [
                {"title": "Avancement par équipement"},
                {"title": "Problem / Risk"},
                {"title": "Measure"},
                {"title": "Responsible"},
            ],
        },
        {
            "title": "Travaux électriques & automation",
            "subtopics": [
                {"title": "Avancement par équipement"},
                {"title": "Problem / Risk"},
                {"title": "Measure"},
                {"title": "Responsible"},
            ],
        },
        {
            "title": "Livraisons matériel",
            "subtopics": [
                {"title": "Retard"},
                {"title": "Manquant"},
                {"title": "Endommagé"},
            ],
        },
        {
            "title": "Qualité",
            "subtopics": [
                {"title": "Major quality deviations"},
                {"title": "Other erection quality topics"},
                {"title": "Erection inspections (senior visit)"},
            ],
        },
        {
            "title": "Autres points & annexes",
            "subtopics": [
                {"title": "Open list"},
                {"title": "NCR"},
                {"title": "Attachments"},
            ],
        },
        {
            "title": "Customer Feedback",
            "subtopics": list(_CUSTOMER_FEEDBACK_SUBTOPICS),
        },
        dict(_OPPORTUNITIES_TOPIC),
    ],
}

_FIELD_SERVICE_PLAN_SEED = {
    "topics": [
        {
            "title": "Situation sur site",
            "subtopics": list(_FIELD_SERVICE_RUBRIC),
        },
        {
            "title": "Travaux exécutés",
            "subtopics": list(_FIELD_SERVICE_RUBRIC),
        },
        {
            "title": "Résultat des travaux",
            "subtopics": list(_FIELD_SERVICE_RUBRIC),
        },
        {
            "title": "Remarques",
            "subtopics": list(_FIELD_SERVICE_RUBRIC),
        },
        {
            "title": "Points ouverts",
            "subtopics": list(_FIELD_SERVICE_RUBRIC),
        },
        {
            "title": "Customer Survey",
            "subtopics": list(_CUSTOMER_FEEDBACK_SUBTOPICS),
        },
        dict(_OPPORTUNITIES_TOPIC),
    ],
}

_PROCESS_PLAN_SEED = {
    "topics": [
        {
            "title": "HSE — Health Safety and Environment",
            "subtopics": [
                {"title": "Incidents (new/total)"},
                {"title": "Accidents (new/total)"},
                {"title": "Safety deviation"},
                {"title": "Environmental measures & deviation"},
            ],
        },
        {
            "title": "Executive Summary / Situation site",
            "subtopics": [
                {"title": "Site Situation"},
                {"title": "Overall progress / Risks for execution"},
            ],
        },
        {
            "title": "Travaux mécaniques",
            "subtopics": [
                {"title": "Avancement par équipement"},
                {"title": "Problem / Risk"},
                {"title": "Measure"},
                {"title": "Responsible"},
            ],
        },
        {
            "title": "Travaux électriques & automation",
            "subtopics": [
                {"title": "Avancement par équipement"},
                {"title": "Problem / Risk"},
                {"title": "Measure"},
                {"title": "Responsible"},
            ],
        },
        {
            "title": "Process Schedule",
            "subtopics": [
                {"title": "Cible (Target)"},
                {"title": "Réel (Real)"},
            ],
        },
        {
            "title": "Tâches semaine suivante",
            "subtopics": [{"title": "Next Week Task"}],
        },
        {
            "title": "Photos",
            "subtopics": [{"title": "Pictures"}],
        },
        {
            "title": "Issues",
            "subtopics": [{"title": "Open issues"}],
        },
        {
            "title": "Customer Feedback",
            "subtopics": list(_CUSTOMER_FEEDBACK_SUBTOPICS),
        },
        dict(_OPPORTUNITIES_TOPIC),
    ],
}

_FSE_REQUIRED_FIELDS: List[Dict[str, Any]] = [
    *_CARTOUCHE_FIELDS,
    {
        "key": "hse_safety",
        "label": "HSE / Safety",
        "kind": "text",
        "required": True,
        "default": HSE_SAFETY_DEFAULT,
    },
    {
        "key": "progress",
        "label": "Avancement par équipement",
        "kind": "equipment_progress",
        "required": True,
        "condition": {"intervention_type": ["weekly_site", "process"]},
    },
    {
        "key": "site_modifications",
        "label": "Modifications sur site",
        "kind": "checkbox_group",
        "required": True,
        "options": list(_SITE_MODIFICATION_OPTIONS),
        "default": deepcopy(_SITE_MODIFICATIONS_DEFAULT),
    },
    {
        "key": "distribution",
        "label": "Diffusion",
        "kind": "select_multi",
        "required": True,
        "options": list(_DISTRIBUTION_OPTIONS),
        "default": list(_DISTRIBUTION_DEFAULT),
    },
]

FSE_INTERVENTION_TYPES: List[Dict[str, Any]] = [
    {
        "id": "weekly_site",
        "label": "Weekly site report",
        "doc_ref": "P APG EX70 004 01",
        "plan_seed": deepcopy(_WEEKLY_SITE_PLAN_SEED),
    },
    {
        "id": "field_service",
        "label": "Field Service Report",
        "doc_ref": "P APG EX70 003 02",
        "plan_seed": deepcopy(_FIELD_SERVICE_PLAN_SEED),
    },
    {
        "id": "process",
        "label": "Weekly Process site report",
        "doc_ref": "P APG EX70 005 01",
        "plan_seed": deepcopy(_PROCESS_PLAN_SEED),
    },
]

FSE_INTERVENTION_V1: CaptureTemplate = {
    "id": FSE_INTERVENTION_TEMPLATE_ID,
    "label": "Rapport d'intervention FSE",
    "intervention_types": deepcopy(FSE_INTERVENTION_TYPES),
    # Root seed kept for backward compat (= weekly_site).
    "plan_seed": deepcopy(_WEEKLY_SITE_PLAN_SEED),
    "required_fields": deepcopy(_FSE_REQUIRED_FIELDS),
    "report_template_id": FSE_INTERVENTION_REPORT_TEMPLATE_ID,
    "publication": {
        "collection": "andritz-fse-reports",
        "source_type": "fse_report",
        "filename_convention": "PROJECT-Supervisor-Week",
    },
    "ui": {
        "lock_plan": True,
        "hide_free_mode": True,
    },
}

_REGISTRY: Dict[str, CaptureTemplate] = {
    FSE_INTERVENTION_TEMPLATE_ID: FSE_INTERVENTION_V1,
}

_SITE_MOD_MENTION_RE = re.compile(
    r"(?:"
    r"(?:modif\w*|chang\w*|mise\s+[aà]\s+jour|updated?|modified?).{0,48}"
    r"(?:plc|hmi|programme|program|sch[eé]ma|diagramme?|diagram)"
    r"|"
    r"(?:plc|hmi|programme|program|sch[eé]ma|diagramme?|diagram).{0,48}"
    r"(?:modif\w*|chang\w*|mise\s+[aà]\s+jour|updated?|modified?)"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_CLOSED_QUESTION_STATUSES = frozenset({"answered", "dismissed", "closed", "resolved", "addressed"})


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


def intervention_type_id_from_header(
    header_fields: Optional[Mapping[str, Any]] = None,
    *,
    default: str = DEFAULT_FSE_INTERVENTION_TYPE,
) -> str:
    values = header_fields if isinstance(header_fields, Mapping) else {}
    raw = values.get("intervention_type")
    clean = str(raw or "").strip()
    known = {item["id"] for item in FSE_INTERVENTION_TYPES}
    return clean if clean in known else default


def resolve_intervention_type(
    template: CaptureTemplate,
    *,
    intervention_type: Optional[str] = None,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    types = template.get("intervention_types") or []
    by_id = {
        str(item.get("id") or "").strip(): item
        for item in types
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    }
    type_id = str(intervention_type or "").strip()
    if type_id not in by_id:
        type_id = intervention_type_id_from_header(header_fields)
    if type_id not in by_id:
        type_id = DEFAULT_FSE_INTERVENTION_TYPE
    selected = by_id.get(type_id) or (types[0] if types else {})
    return deepcopy(selected) if isinstance(selected, Mapping) else {}


def apply_intervention_type_to_template(
    template: CaptureTemplate,
    *,
    intervention_type: Optional[str] = None,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> CaptureTemplate:
    """Return a template copy with plan_seed / type stamp for the chosen type."""
    out = deepcopy(template)
    selected = resolve_intervention_type(
        out,
        intervention_type=intervention_type,
        header_fields=header_fields,
    )
    type_id = str(selected.get("id") or DEFAULT_FSE_INTERVENTION_TYPE)
    if isinstance(selected.get("plan_seed"), Mapping):
        out["plan_seed"] = deepcopy(selected["plan_seed"])
    out["selected_intervention_type"] = type_id
    return out


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


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def normalize_header_fields(header_fields: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Keep JSON-able structured values; strip empty scalars."""
    if not isinstance(header_fields, Mapping):
        return {}
    out: Dict[str, Any] = {}
    for key, value in header_fields.items():
        clean_key = str(key).strip()
        if not clean_key:
            continue
        parsed = _parse_jsonish(value)
        if isinstance(parsed, str):
            text = parsed.strip()
            if text:
                out[clean_key] = text
            continue
        if isinstance(parsed, (int, float, bool)):
            out[clean_key] = parsed
            continue
        if isinstance(parsed, list):
            if parsed:
                out[clean_key] = parsed
            continue
        if isinstance(parsed, dict):
            if parsed:
                out[clean_key] = parsed
            continue
    return out


def apply_required_field_defaults(
    template: CaptureTemplate,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    values = normalize_header_fields(header_fields)
    for field in template.get("required_fields") or []:
        if not isinstance(field, Mapping):
            continue
        key = str(field.get("key") or "").strip()
        if not key or key in values:
            continue
        if "default" in field and field.get("default") is not None:
            values[key] = deepcopy(field["default"])
    return values


def header_fields_from_plan(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(plan, Mapping):
        return {}
    raw = plan.get("header_fields")
    if not isinstance(raw, Mapping):
        return {}
    return normalize_header_fields(raw)


def _intervention_type_for_fields(
    template: CaptureTemplate,
    header_fields: Optional[Mapping[str, Any]],
) -> str:
    values = header_fields if isinstance(header_fields, Mapping) else {}
    snapshot_type = None
    # Prefer explicit header, then template stamp when present on a plan snapshot.
    return intervention_type_id_from_header(values)


def _field_applies(
    field: Mapping[str, Any],
    *,
    intervention_type: str,
) -> bool:
    if not field.get("required", True):
        return False
    condition = field.get("condition")
    if not isinstance(condition, Mapping):
        return True
    allowed = condition.get("intervention_type")
    if isinstance(allowed, Sequence) and not isinstance(allowed, (str, bytes)):
        return intervention_type in {str(item).strip() for item in allowed}
    return True


def _as_string_list(value: Any) -> List[str]:
    parsed = _parse_jsonish(value)
    if isinstance(parsed, str):
        text = parsed.strip()
        if not text:
            return []
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, dict):
        selected = parsed.get("selected") or parsed.get("values") or parsed.get("options")
        if isinstance(selected, list):
            return [str(item).strip() for item in selected if str(item).strip()]
    return []


def checkbox_group_payload(value: Any) -> Tuple[List[str], str]:
    parsed = _parse_jsonish(value)
    if isinstance(parsed, dict):
        selected = _as_string_list(parsed.get("selected") or parsed.get("values") or [])
        description = str(parsed.get("description") or parsed.get("details") or "").strip()
        return selected, description
    if isinstance(parsed, list):
        return _as_string_list(parsed), ""
    if isinstance(parsed, str) and parsed.strip():
        return _as_string_list(parsed), ""
    return [], ""


def equipment_progress_rows(value: Any) -> List[Dict[str, Any]]:
    parsed = _parse_jsonish(value)
    if isinstance(parsed, dict):
        rows = parsed.get("rows") or parsed.get("items") or parsed.get("equipment")
        parsed = rows
    if not isinstance(parsed, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, Mapping):
            continue
        rows.append(dict(item))
    return rows


def _has_progress_percent(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        percent = row.get("percent")
        if percent is None or str(percent).strip() == "":
            continue
        try:
            float(percent)
            return True
        except (TypeError, ValueError):
            if str(percent).strip():
                return True
    return False


def field_value_is_complete(field: Mapping[str, Any], value: Any) -> bool:
    kind = str(field.get("kind") or "text").strip() or "text"
    if kind in {"text", "date"}:
        return bool(str(value or "").strip())
    if kind == "select_multi":
        return bool(_as_string_list(value))
    if kind == "checkbox_group":
        selected, description = checkbox_group_payload(value)
        if not selected:
            return False
        non_none = [item for item in selected if item != "none"]
        if non_none and not description:
            return False
        return True
    if kind == "equipment_progress":
        return _has_progress_percent(equipment_progress_rows(value))
    return bool(str(value or "").strip())


def missing_required_fields(
    template: CaptureTemplate,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    values = normalize_header_fields(header_fields)
    intervention_type = _intervention_type_for_fields(template, values)
    missing: List[Dict[str, Any]] = []
    for field in template.get("required_fields") or []:
        if not isinstance(field, Mapping):
            continue
        if not _field_applies(field, intervention_type=intervention_type):
            continue
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        if field_value_is_complete(field, values.get(key)):
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
        kind = str(field.get("kind") or "text")
        description = f"Renseigner « {label} » (en-tête du rapport)."
        if kind == "equipment_progress":
            description = f"Ajouter au moins une ligne d'avancement avec pourcentage pour « {label} »."
        elif kind == "checkbox_group" and key == "site_modifications":
            description = (
                f"Déclarer « {label} » (none ou type de modification) ; "
                "description obligatoire si modification."
            )
        elif kind == "select_multi":
            description = f"Sélectionner au moins un destinataire pour « {label} »."
        gaps.append(
            {
                "id": f"gap-req-{key}",
                "slug": f"required_field_{key}",
                "title": f"Champ obligatoire : {label}",
                "description": description,
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


def site_modifications_are_undeclared_or_none(header_fields: Optional[Mapping[str, Any]]) -> bool:
    values = header_fields if isinstance(header_fields, Mapping) else {}
    raw = values.get("site_modifications")
    if raw is None or raw == "" or raw == {}:
        return True
    selected, _description = checkbox_group_payload(raw)
    if not selected:
        return True
    return selected == ["none"] or set(selected) == {"none"}


def transcript_mentions_site_modifications(transcript_text: str) -> bool:
    return bool(_SITE_MOD_MENTION_RE.search(transcript_text or ""))


def site_modification_consistency_question(
    header_fields: Optional[Mapping[str, Any]],
    transcript_text: str,
) -> Optional[Dict[str, Any]]:
    """High-priority OQ when transcript mentions PLC/HMI mods but declaration is none."""
    if not transcript_mentions_site_modifications(transcript_text):
        return None
    if not site_modifications_are_undeclared_or_none(header_fields):
        return None
    text = (
        "Le transcript évoque une modification PLC/HMI/programme/schéma, "
        "mais « Modifications sur site » est None ou non déclaré. "
        "Confirmer et décrire la modification (procédure EX70)."
    )
    return {
        "gap_id": "gap-site-mod-consistency",
        "id": "site-mod-consistency",
        "reason": "site_modification_undeclared",
        "follow_up": text,
        "text": text,
        "priority": 0.95,
        "status": "open",
        "blocking": False,
        "source": "capture_template_consistency",
        "required_field_key": "site_modifications",
    }


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


def _scalar_header(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def tracking_metadata_from_header(
    header_fields: Optional[Mapping[str, Any]] = None,
    *,
    intervention_type: Optional[str] = None,
) -> Dict[str, str]:
    values = normalize_header_fields(header_fields)
    mapping = {
        "customer": "fse_customer",
        "site_or_machine": "fse_machine",
        "reference": "fse_reference",
        "country": "fse_country",
        "intervention_date": "fse_intervention_date",
        "week": "fse_week",
    }
    out: Dict[str, str] = {}
    for source_key, meta_key in mapping.items():
        value = _scalar_header(values.get(source_key))
        if value:
            out[meta_key] = value
    type_id = str(intervention_type or values.get("intervention_type") or "").strip()
    if type_id:
        out["fse_intervention_type"] = type_id
    elif values:
        out.setdefault("fse_intervention_type", DEFAULT_FSE_INTERVENTION_TYPE)
    # Week fallback from intervention_date when week not explicit.
    if "fse_week" not in out and out.get("fse_intervention_date"):
        out["fse_week"] = out["fse_intervention_date"]
    return out


def _sanitize_filename_part(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "-", (value or "").strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip(".-")
    return cleaned or fallback


def publication_filename_from_header(
    header_fields: Optional[Mapping[str, Any]] = None,
    *,
    fallback_session_id: Optional[str] = None,
) -> str:
    """Trame convention: PROJECT-Supervisor-Week.md."""
    values = normalize_header_fields(header_fields)
    project = _scalar_header(values.get("reference")) or _scalar_header(values.get("customer"))
    supervisor = (
        _scalar_header(values.get("issued_by"))
        or _scalar_header(values.get("participants"))
    )
    week = _scalar_header(values.get("week")) or _scalar_header(values.get("intervention_date"))
    if project or supervisor or week:
        parts = [
            _sanitize_filename_part(project, fallback="PROJECT"),
            _sanitize_filename_part(supervisor, fallback="Supervisor"),
            _sanitize_filename_part(week, fallback="Week"),
        ]
        return f"{'-'.join(parts)}.md"
    suffix = (fallback_session_id or "session")[:8]
    return f"capture-{suffix}.md"


def publication_title_from_header(
    header_fields: Optional[Mapping[str, Any]] = None,
    *,
    fallback: str = "Rapport d'intervention FSE",
) -> str:
    values = normalize_header_fields(header_fields)
    project = _scalar_header(values.get("reference")) or _scalar_header(values.get("customer"))
    supervisor = (
        _scalar_header(values.get("issued_by"))
        or _scalar_header(values.get("participants"))
    )
    week = _scalar_header(values.get("week")) or _scalar_header(values.get("intervention_date"))
    parts = [part for part in (project, supervisor, week) if part]
    return "-".join(parts) if parts else fallback


def attach_template_to_plan(
    plan: Dict[str, Any],
    template: CaptureTemplate,
    *,
    intervention_type: Optional[str] = None,
    header_fields: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Stamp template snapshot + empty header on the session plan (idempotent)."""
    values = normalize_header_fields(header_fields if header_fields is not None else plan.get("header_fields"))
    selected = resolve_intervention_type(
        template,
        intervention_type=intervention_type,
        header_fields=values,
    )
    type_id = str(selected.get("id") or DEFAULT_FSE_INTERVENTION_TYPE)
    plan_seed = (
        deepcopy(selected.get("plan_seed"))
        if isinstance(selected.get("plan_seed"), Mapping)
        else deepcopy(template.get("plan_seed") or {})
    )
    values["intervention_type"] = type_id
    plan["capture_template"] = {
        "id": template.get("id"),
        "label": template.get("label"),
        "report_template_id": template.get("report_template_id"),
        "required_fields": deepcopy(template.get("required_fields") or []),
        "publication": deepcopy(template.get("publication") or {}),
        "ui": deepcopy(template.get("ui") or {}),
        "plan_seed": plan_seed,
        "intervention_type": type_id,
        "intervention_types": deepcopy(template.get("intervention_types") or []),
        "doc_ref": selected.get("doc_ref"),
        "intervention_type_label": selected.get("label"),
    }
    plan["header_fields"] = apply_required_field_defaults(template, values)
    return plan


def unresolved_open_questions(items: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
    unresolved: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "open").strip().lower()
        if status in _CLOSED_QUESTION_STATUSES:
            continue
        text = str(
            item.get("follow_up")
            or item.get("text")
            or item.get("reason")
            or item.get("gap_id")
            or ""
        ).strip()
        if not text:
            continue
        unresolved.append(dict(item))
    return unresolved


def previous_report_open_question_payload(
    question: Mapping[str, Any],
    *,
    index: int,
    source_proposal_id: Optional[str] = None,
    source_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    text = str(
        question.get("follow_up")
        or question.get("text")
        or question.get("reason")
        or question.get("gap_id")
        or ""
    ).strip()
    return {
        "id": f"previous-report-{index:02d}",
        "gap_id": str(question.get("gap_id") or f"previous-report-{index:02d}"),
        "text": text,
        "follow_up": text,
        "reason": str(question.get("reason") or "previous_report_open_item"),
        "priority": float(question.get("priority") or 0.85),
        "status": "open",
        "blocking": False,
        "source": "previous_report",
        "source_proposal_id": source_proposal_id,
        "source_session_id": source_session_id,
    }


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
