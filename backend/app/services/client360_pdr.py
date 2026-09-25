"""Client360 PDR service layer.

This pre-MVP keeps potential calculation deterministic: it reads real workspace
data, calculates explainable potential when enough fields are present, and
records the commercial workflow that will become future ground truth. Mail
drafts are AI-assisted when configured, with a deterministic fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import statistics
import unicodedata
from datetime import datetime, timedelta
from email.utils import parseaddr
from functools import lru_cache
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.settings_manager import get_resolved_settings
from app.models.action_plan import WorkspaceActionItem
from app.models.capability import Capability
from app.models.client360 import (
    CLIENT360_ATTRIBUTIONS,
    CLIENT360_CAMPAIGN_ACTIVE_STATUSES,
    CLIENT360_CAMPAIGN_STATUSES,
    CLIENT360_CAMPAIGN_TYPES,
    CLIENT360_IMPACT_TYPES,
    CLIENT360_MAIL_STATUSES,
    CLIENT360_MAPPING_STATUSES,
    CLIENT360_OPPORTUNITY_STATUSES,
    CLIENT360_OUTCOME_REASONS,
    Client360Campaign,
    Client360DataSource,
    Client360ImpactEvent,
    Client360MailDraft,
    Client360MappingRule,
    Client360Opportunity,
)
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.secure_deposit import DepositFile
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_plans import create_action_item, update_action_item
from app.services.client360_contract import (
    CLIENT360_ADDRESSABLE_WEIGHTS,
    CLIENT360_AGENT_ROUTING_CONTRACT,
    CLIENT360_CAPABILITY_SLUG,
    CLIENT360_MVP_CONTRACT,
    CLIENT360_SYSTEM_VARIANT,
)
from app.services.client360_forecast import (
    apply_next_due_to_record,
    campaign_expected_value,
    last_purchase_date_from_record,
    parse_forecast_date,
)
from app.services.email import SmtpDeliveryConfig, send_email_with_config
from app.services.iam.app_entitlements import (
    lock_workspace_for_app_entitlement_mutation,
)

_logger = logging.getLogger(__name__)

REQUIRED_SOURCE_TYPES = ("installed_base", "periodicity", "sap_sales_history")
PILOT_TECHNOLOGIES = ("JETLACE", "HFR200")
PILOT_COUNTRIES = ("Greece", "Turkey")
PILOT_CUSTOMERS = ("Septona",)
CLIENT360_MAIL_PROMPT_VERSION = "client360_pdr_mail_v2"
CLIENT360_SUMMARY_PROMPT_VERSION = "client360_pdr_customer_summary_v1"
PRICING_MIN_SAMPLE_QTY = 5.0
COUNTRY_CANONICAL_MAP = {
    "gr": "Greece",
    "greece": "Greece",
    "tr": "Turkey",
    "turkey": "Turkey",
}
KNOWN_LLM_PROVIDERS = {
    "anthropic",
    "azure_openai",
    "deepseek",
    "gemini",
    "groq",
    "litellm",
    "lmstudio",
    "ollama",
    "openai",
    "openai_structured",
    "openrouter",
    "together",
    "xai",
}
CLIENT360_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "customer_name": (
        "customer",
        "client",
        "customer name",
        "client name",
        "account",
        "sold to",
        "ship to",
        "equipment sold to party name",
        "sold to party name",
        "sold name",
    ),
    "customer_key": (
        "customer id",
        "client id",
        "customer code",
        "sold to code",
        "sap customer",
        "sold to party",
    ),
    "country": ("country", "pays", "market", "country key", "country code"),
    "hub": ("hub", "region", "sales hub"),
    "technology": (
        "technology",
        "technologie",
        "machine type",
        "line type",
        "equipment type",
        "object description",
        "project name",
    ),
    "line_label": ("line", "ligne", "production line"),
    "machine_label": ("machine", "equipment", "asset", "installed machine", "object description"),
    "part_family": (
        "part family",
        "famille",
        "famille piece",
        "wear family",
        "pdr family",
        "familly",
        "family",
    ),
    "part_reference": (
        "part reference",
        "reference",
        "material",
        "material number",
        "sap material",
        "part number",
        "item",
        "number",
    ),
    "part_description": (
        "description",
        "designation",
        "part description",
        "material description",
        "title",
    ),
    "installed_quantity": (
        "installed quantity",
        "installed qty",
        "qty installed",
        "quantity installed",
        "base installee",
        "installed base",
        "quantity",
        "ib turkey",
    ),
    "recommended_quantity": (
        "recommended quantity",
        "recommended qty",
        "qty recommended",
        "quantite recommandee",
        "quantity per replacement",
    ),
    "periodicity_weeks": (
        "periodicity weeks",
        "periodicite semaines",
        "periodicity",
        "periodicite",
        "weeks",
        "semaines",
    ),
    "delivery_time_weeks": (
        "delivery time weeks",
        "lead time weeks",
        "lead time",
        "delai",
        "delai semaines",
    ),
    "unit_cost": (
        "unit cost",
        "net order value",
        "purchase cost",
        "achat",
        "cout unitaire",
    ),
    "purchase_unit_price": (
        "purchase unit price",
        "purchase price",
        "prix d'achat",
        "prix achat",
        "buying price",
    ),
    "sales_unit_price": (
        "sales unit price",
        "net price",
        "prix unitaire",
        "prix de vente",
        "list price",
    ),
    "sales_known_qty": (
        "sales qty",
        "qty sold",
        "quantity sold",
        "historique qty",
        "sales history qty",
        "sap qty",
    ),
    "sales_known_value": (
        "sales value",
        "net sales",
        "revenue",
        "turnover",
        "historique valeur",
        "sap value",
    ),
    "currency": ("currency", "devise"),
    "next_due_at": ("next due", "echeance", "next replacement", "due date"),
    "contact_name": ("contact", "contact name"),
    "contact_email": ("email", "contact email"),
}


def client360_scope(workspace: Workspace) -> dict[str, Any]:
    configured = _as_dict(_as_dict(getattr(workspace, "settings", None)).get("client360_pdr_scope"))
    scope_mode = _safe_text(configured.get("scope_mode") or "pilot").lower()
    if scope_mode not in {"pilot", "all"}:
        scope_mode = "pilot"
    return {
        "official_name": CLIENT360_MVP_CONTRACT["official_name"],
        "business_scope": "spare_parts",
        "part_scope": "wear_parts",
        "scope_mode": scope_mode,
        "pilot_technologies": _as_list(configured.get("pilot_technologies"))
        or list(PILOT_TECHNOLOGIES),
        "pilot_countries": _as_list(configured.get("pilot_countries")) or list(PILOT_COUNTRIES),
        "pilot_customers": _as_list(configured.get("pilot_customers")) or list(PILOT_CUSTOMERS),
        "addressable_weights": {
            **CLIENT360_ADDRESSABLE_WEIGHTS,
            **_as_dict(configured.get("addressable_weights")),
        },
        "stock_automation": False,
        "internet_sources_policy": "context_only",
        "live_connectors": {"sap": False, "crm": False, "metris": False, "outlook_send": False},
        "mvp_contract": CLIENT360_MVP_CONTRACT,
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_non_negative_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _normalize_token(value: Any) -> str:
    text = _safe_text(value).lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _mapping_key(*values: Any) -> str:
    return "|".join(part for part in (_normalize_token(value) for value in values) if part)


# --- Shared customer-name normalization (registry / sales_orders / SPC join) ---
#
# The Andritz feeds spell the same customer differently: the project registry
# uses short internal names ("Minet", "Kurt Kumas", "Septona (Alpha Leasing)")
# while SAP exports (VA05 Sold-To, SPC Sold name) carry full legal names
# ("MINET S.A.", "Kurt Kumas Sanayi ve Ticaret A.S.", "Septona S.A.").
# ``normalize_customer_key`` folds both to one join key. Rules — deliberately
# conservative (exact equality after folding, no fuzzy/containment matching):
#
# 1. Turkish letters are transliterated explicitly before the ASCII fold:
#    NFKD drops dotless "ı" entirely ("Kadıköy" → "kadky"), silently breaking
#    equality with the "i" spelling.
# 2. Same accent/punctuation folding as ``_normalize_token``.
# 3. Leading corporate-form tokens are stripped ("LLC Cotton Club" →
#    "cotton club", "OOO Avangard" → "avangard").
# 4. Trailing corporate-form tokens/phrases are stripped repeatedly
#    ("Sanitars SPA" → "sanitars", "Kurt Kumas Sanayi ve Ticaret A.S." →
#    "kurt kumas", "Yibin Grace Co., Ltd." → "yibin grace").
# 5. Descriptive words (Tekstil, Nonwovens, Textile, Hygienics, …) are never
#    stripped and at least one token always remains, so distinct entities such
#    as "Fibertex Nonwovens" vs "Fibertex US" never collapse together.

_TURKISH_ASCII_TRANSLATION = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ç": "c",
        "Ç": "c",
        "ö": "o",
        "Ö": "o",
        "ü": "u",
        "Ü": "u",
    }
)

_CUSTOMER_LEADING_LEGAL_TOKENS = {
    "llc",
    "ooo",
    "oao",
    "zao",
    "pao",
    "ao",
    "jsc",
    "pjsc",
    "snc",
    "uab",
}

# Multi-token legal phrases, matched (longest first) against the name tail.
_CUSTOMER_TRAILING_LEGAL_PHRASES: tuple[tuple[str, ...], ...] = (
    ("sanayi", "ve", "ticaret"),
    ("san", "ve", "tic"),
    ("gmbh", "co", "kg"),
    ("s", "a", "s"),
    ("s", "p", "a"),
    ("s", "r", "l"),
    ("s", "a"),
    ("a", "s"),
    ("s", "l"),
)

_CUSTOMER_TRAILING_LEGAL_TOKENS = {
    "sa",
    "as",
    "ag",
    "ab",
    "nv",
    "bv",
    "oy",
    "plc",
    "llc",
    "ltd",
    "ltda",
    "limited",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "kg",
    "gmbh",
    "srl",
    "spa",
    "sarl",
    "sas",
    "sl",
    "cie",
    "company",
    "pvt",
    "kk",
    # Turkish corporate qualifiers (Sanayi/Ticaret and abbreviations); "ve"
    # ("and") is only ever stripped from the tail, after one of the others.
    "sanayi",
    "ticaret",
    "san",
    "tic",
    "ve",
    "ooo",
    "oao",
    "zao",
    "pao",
    "jsc",
    "pjsc",
}


def _strip_customer_legal_tokens(tokens: list[str]) -> list[str]:
    out = list(tokens)
    while len(out) > 1 and out[0] in _CUSTOMER_LEADING_LEGAL_TOKENS:
        out = out[1:]
    changed = True
    while changed and len(out) > 1:
        changed = False
        for phrase in _CUSTOMER_TRAILING_LEGAL_PHRASES:
            size = len(phrase)
            if len(out) > size and tuple(out[-size:]) == phrase:
                out = out[:-size]
                changed = True
                break
        if not changed and len(out) > 1 and out[-1] in _CUSTOMER_TRAILING_LEGAL_TOKENS:
            out = out[:-1]
            changed = True
    return out


def normalize_customer_key(value: Any) -> str:
    """Canonical customer join key shared by registry, sales_orders and SPC."""
    text = _safe_text(value)
    if not text:
        return ""
    normalized = _normalize_token(text.translate(_TURKISH_ASCII_TRANSLATION))
    if not normalized:
        return ""
    stripped = _strip_customer_legal_tokens(normalized.split(" "))
    return " ".join(stripped) if stripped else normalized


_REGISTRY_ALIAS_RE = re.compile(r"\(([^)]*)\)")


def registry_customer_key(value: Any) -> str:
    """Key for registry FINAL CUSTOMER names, which use a "Primary (Alias)"
    convention for lessors / former names ("Septona (Alpha Leasing)",
    "Selcuk Iplik (Karafiber)"). The primary part is the join key so the SAP
    legal name ("Septona S.A.") folds to the same key."""
    text = _safe_text(value)
    primary = _REGISTRY_ALIAS_RE.sub(" ", text)
    return normalize_customer_key(primary) or normalize_customer_key(text)


def customer_key_variants(value: Any) -> list[str]:
    """All normalized lookup variants of a registry customer name: primary
    (outside parentheses), each parenthetical alias, and the full name."""
    text = _safe_text(value)
    candidates = [
        _REGISTRY_ALIAS_RE.sub(" ", text),
        *_REGISTRY_ALIAS_RE.findall(text),
        text,
    ]
    variants: list[str] = []
    for candidate in candidates:
        candidate = re.sub(r"^(?:ex|via)\s+", "", candidate.strip(), flags=re.IGNORECASE)
        key = normalize_customer_key(candidate)
        if key and key not in variants:
            variants.append(key)
    return variants


def _find_client360_system(db: DBSession, workspace: Workspace) -> System | None:
    rows = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status != "retired")
        .order_by(System.created_at.asc())
        .all()
    )
    for row in rows:
        flow = _as_dict(row.flow_definition)
        system_settings = _as_dict(row.settings)
        if (
            flow.get("variant") == CLIENT360_SYSTEM_VARIANT
            or system_settings.get("system_type") == CLIENT360_SYSTEM_VARIANT
        ):
            return row
    return next((row for row in rows if row.name == "Client360 PDR"), None)


def resolve_client360_authority(
    db: DBSession,
    workspace: Workspace,
) -> tuple[System, Capability]:
    """Resolve the unique marker-backed System and Capability for IAM checks.

    Authorization never falls back to a mutable display name.  A missing,
    ambiguous or cross-workspace binding is an installation error and must
    fail closed at the API boundary.
    """

    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .order_by(System.created_at.asc())
        .all()
    )
    matches = []
    for system in systems:
        flow = _as_dict(system.flow_definition)
        system_settings = _as_dict(system.settings)
        if (
            flow.get("variant") == CLIENT360_SYSTEM_VARIANT
            or system_settings.get("system_type") == CLIENT360_SYSTEM_VARIANT
        ):
            matches.append(system)
    if len(matches) != 1:
        raise LookupError(
            f"Client360 authority requires exactly one active marker-backed System; found {len(matches)}"
        )
    system = matches[0]
    if not system.capability_id:
        raise LookupError("Client360 authority System has no Capability")
    capability = db.query(Capability).filter(Capability.id == system.capability_id).one_or_none()
    if capability is None or capability.workspace_id not in {None, workspace.id}:
        raise LookupError("Client360 authority Capability is missing or crosses workspace scope")
    if capability.slug != CLIENT360_CAPABILITY_SLUG:
        raise LookupError("Client360 authority Capability contract does not match")
    return system, capability


def _pick_config_value(*candidates: tuple[str, Any]) -> tuple[Any, str | None]:
    for source, value in candidates:
        if value is None or value == "":
            continue
        return value, source
    return None, None


def _split_provider_model(provider_value: Any, model_value: Any) -> tuple[str, str]:
    provider = _safe_text(provider_value).lower()
    model = _safe_text(model_value)
    if model:
        prefix, separator, rest = model.partition(":")
        if separator and prefix.lower() in KNOWN_LLM_PROVIDERS and rest:
            return prefix.lower(), rest
    return provider, model


def _resolved_setting(config: dict[str, Any], camel: str, snake: str) -> Any:
    return config.get(camel) if config.get(camel) is not None else config.get(snake)


def _field_for_label_uncached(label: Any) -> str | None:
    normalized = _normalize_token(label)
    if not normalized:
        return None
    for field, aliases in CLIENT360_FIELD_ALIASES.items():
        if normalized == field.replace("_", " "):
            return field
        for alias in aliases:
            alias_norm = _normalize_token(alias)
            if normalized == alias_norm or alias_norm in normalized:
                return field
    return None


@lru_cache(maxsize=4096)
def _field_for_label_cached(label: str) -> str | None:
    return _field_for_label_uncached(label)


def _field_for_label(label: Any) -> str | None:
    # The opportunity engine folds every cell key of every source row through
    # the alias table; purchase-history feeds run to 20k rows x 12 keys, and
    # re-walking/re-normalizing all aliases per key made a dry-run take
    # minutes.  Alias folding is pure, so memoize the (dominant) string path.
    if isinstance(label, str):
        return _field_for_label_cached(label)
    return _field_for_label_uncached(label)


def _coerce_record_value(field: str, raw_value: Any, numeric_value: Any = None) -> Any:
    if field in {
        "installed_quantity",
        "recommended_quantity",
        "periodicity_weeks",
        "delivery_time_weeks",
    }:
        return _safe_float(numeric_value if numeric_value is not None else raw_value)
    if field in {
        "sales_known_qty",
        "sales_known_value",
        "unit_cost",
        "purchase_unit_price",
        "sales_unit_price",
    }:
        return _safe_non_negative_float(numeric_value if numeric_value is not None else raw_value)
    if field == "country":
        return _canonical_country(raw_value) or (_safe_text(raw_value) or None)
    if field == "next_due_at":
        try:
            parsed = _parse_datetime(raw_value)
        except Exception:  # noqa: BLE001
            return None
        return parsed.isoformat() if parsed else None
    return _safe_text(raw_value) or None


def _merge_record(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if value is None or value == "":
            continue
        if key not in merged or merged[key] in (None, "", []):
            merged[key] = value
        elif key in {"evidence_refs", "source_ids"}:
            deduped: list[Any] = []
            seen: set[str] = set()
            for item in _as_list(merged.get(key)) + _as_list(value):
                marker = (
                    json.dumps(item, sort_keys=True, default=str)
                    if isinstance(item, dict)
                    else str(item)
                )
                if marker in seen:
                    continue
                seen.add(marker)
                deduped.append(item)
            merged[key] = deduped
    return merged


def _record_customer_key(record: dict[str, Any]) -> str:
    # Prefer the raw name: persisted records may carry keys computed with an
    # older normalization; re-deriving keeps all feeds on the shared key.
    return (
        normalize_customer_key(record.get("customer_name"))
        or normalize_customer_key(record.get("customer_key"))
        or "unknown_customer"
    )


def _record_family(record: dict[str, Any]) -> str:
    return _safe_text(
        record.get("pdr_family")
        or record.get("part_family")
        or record.get("source_part_family")
        or record.get("part_reference")
    )


def _scope_skip_reason(record: dict[str, Any], scope: dict[str, Any]) -> str | None:
    text = _normalize_token(
        " ".join(
            _safe_text(record.get(key))
            for key in (
                "part_family",
                "part_description",
                "source_part_family",
                "source_part_label",
            )
        )
    )
    if any(term in text for term in ("stock", "inventory", "safety stock", "minimum stock")):
        return "stock_automation_out_of_scope"
    if text and not any(
        term in text
        for term in (
            "wear",
            "usure",
            "spare",
            "pdr",
            "consumable",
            "belt",
            "wire",
            "screen",
            "seal",
            "strip",
            "felt",
        )
    ):
        status = _safe_text(record.get("mapping_status"))
        if status != "validated":
            return "not_confirmed_wear_part"

    technologies = {
        _normalize_token(item) for item in _as_list(scope.get("pilot_technologies")) if item
    }
    technology = _normalize_token(record.get("technology"))
    if (
        technology
        and technologies
        and not any(token in technology or technology in token for token in technologies)
    ):
        return "technology_out_of_pilot_scope"

    # scope_mode=all skips the country/customer pilot gate; wear-parts mapping gate above stays.
    if _safe_text(scope.get("scope_mode")).lower() != "all":
        countries = {_normalize_token(item) for item in _as_list(scope.get("pilot_countries")) if item}
        customers = {_normalize_token(item) for item in _as_list(scope.get("pilot_customers")) if item}
        country = _normalize_token(_canonical_country(record.get("country")) or record.get("country"))
        customer = _normalize_token(record.get("customer_name") or record.get("customer_key"))
        if country and countries and country not in countries and customer not in customers:
            return "country_out_of_pilot_scope"
    return None


def _confidence_label(score: Optional[float]) -> str:
    if score is None:
        return "low"
    if score >= 0.78:
        return "high"
    if score >= 0.52:
        return "medium"
    return "low"


def calculate_annual_theoretical_qty(
    *,
    installed_quantity: Any,
    recommended_quantity: Any,
    periodicity_weeks: Any,
) -> Optional[float]:
    installed = _safe_float(installed_quantity)
    recommended = _safe_float(recommended_quantity)
    periodicity = _safe_float(periodicity_weeks)
    if installed is None or recommended is None or periodicity is None:
        return None
    return round(installed * recommended * 52.0 / periodicity, 4)


def opportunity_data_gaps(opportunity: Client360Opportunity) -> list[str]:
    gaps = list(dict.fromkeys(str(item) for item in _as_list(opportunity.data_gaps) if item))
    checks = {
        "installed_quantity_missing": opportunity.installed_quantity,
        "recommended_quantity_missing": opportunity.recommended_quantity,
        "periodicity_missing": opportunity.periodicity_weeks,
        "customer_location_missing": opportunity.country or opportunity.hub,
        "sap_sales_history_missing": opportunity.sales_known_qty or opportunity.sales_known_value,
        "delivery_time_missing": opportunity.delivery_time_weeks,
    }
    for key, value in checks.items():
        if value is None or value == "":
            gaps.append(key)
    return list(dict.fromkeys(gaps))


def score_opportunity_details(
    opportunity: Client360Opportunity,
) -> tuple[float, str, list[dict[str, Any]]]:
    checks = [
        (
            "installed_base",
            0.2,
            _safe_float(opportunity.installed_quantity) is not None,
            "Base installee exploitable",
        ),
        (
            "periodicity",
            0.2,
            _safe_float(opportunity.periodicity_weeks) is not None,
            "Periodicite connue",
        ),
        (
            "recommended_quantity",
            0.15,
            _safe_float(opportunity.recommended_quantity) is not None,
            "Quantite recommandee connue",
        ),
        (
            "customer_scope",
            0.15,
            bool(opportunity.customer_name and (opportunity.country or opportunity.hub)),
            "Client, pays ou hub renseignes",
        ),
        (
            "sap_sales_history",
            0.12,
            _safe_float(opportunity.sales_known_qty) is not None
            or _safe_float(opportunity.sales_known_value) is not None,
            "Historique SAP disponible",
        ),
        ("due_date", 0.1, opportunity.next_due_at is not None, "Echeance estimee disponible"),
        (
            "evidence",
            0.08,
            bool(_as_list(opportunity.evidence_refs) or _as_list(opportunity.source_ids)),
            "Preuves source rattachees",
        ),
    ]
    score = 0.0
    reasons: list[dict[str, Any]] = []
    for code, weight, met, label in checks:
        if met:
            score += weight
        reasons.append({"code": code, "label": label, "weight": weight, "met": met})
    score = min(round(score, 3), 0.95)
    return score, _confidence_label(score), reasons


def score_opportunity(opportunity: Client360Opportunity) -> tuple[float, str]:
    score, label, _reasons = score_opportunity_details(opportunity)
    return score, label


def recommended_action_for(opportunity: Client360Opportunity) -> str:
    gaps = set(opportunity_data_gaps(opportunity))
    annual = opportunity.annual_theoretical_qty or calculate_annual_theoretical_qty(
        installed_quantity=opportunity.installed_quantity,
        recommended_quantity=opportunity.recommended_quantity,
        periodicity_weeks=opportunity.periodicity_weeks,
    )
    gap = opportunity.potential_gap_qty
    if gap is None and annual is not None and opportunity.sales_known_qty is not None:
        gap = max(round(float(annual) - float(opportunity.sales_known_qty or 0), 4), 0)
    if "periodicity_missing" in gaps or "recommended_quantity_missing" in gaps:
        return "validate_pdr_mapping"
    if "installed_quantity_missing" in gaps:
        return "request_installed_base"
    if opportunity.next_due_at:
        return "prepare_inspection_or_spa"
    if gap is not None and gap > 0:
        return "draft_expertise_email"
    if "sap_sales_history_missing" in gaps:
        return "complete_sap_history"
    return "review_with_sales"


def classify_data_source(text: str) -> str:
    haystack = _safe_text(text).lower()
    folded = unicodedata.normalize("NFKD", haystack).encode("ascii", "ignore").decode("ascii")
    underscored = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")

    # Installed_base_SPL / Client360 pilot filenames (underscored or spaced).
    if "family" in underscored and "opportunity" in underscored:
        return "periodicity"
    if ("projets" in underscored and "clients" in underscored) or (
        "project" in underscored and "customer" in underscored
    ):
        return "contact_hub"
    if "sales_by_country" in underscored or "salesbycountry" in underscored:
        return "sap_sales_history"
    if "sales_order" in underscored or "salesorders" in underscored or re.search(
        r"(^|_)va05($|_)", underscored
    ):
        return "sap_sales_history"
    if "materials_consumption" in underscored:
        return "other"
    # Histo_Achat / purchase PO feed — enrichment only (never sap_sales_history / IB).
    if any(
        token in underscored
        for token in ("histo_achat", "purchase_history", "po_delivered", "achat_pieces")
    ):
        return "other"
    if "installed_base_spl" in underscored or re.search(
        r"installed[_\s-]*base[_\s-]*(machine|spc)\b", folded
    ):
        return "installed_base"
    if re.search(r"\b(base\s+installee|turquie|turkey)\b", folded) and re.search(
        r"\b(base|installee|installed)\b", folded
    ):
        return "installed_base"

    if re.search(r"\b(periodicite|periodicity|periodic|wear\s*part|usure)\b", folded):
        return "periodicity"
    if re.search(
        r"\b(base\s+installee|installed\s+base|installations?|machine\s+base|parc)\b", folded
    ):
        return "installed_base"
    if re.search(
        r"\b(sap|sales\s+history|historique\s+(vente|ventes)|orders?|commandes?)\b", folded
    ):
        return "sap_sales_history"
    if re.search(r"\b(contact|hub|commercial|account|crm)\b", folded):
        return "contact_hub"
    if re.search(
        r"\b(nonwovens|sustainable|textile\s+world|met\s+magazine|market\s+signal|veille)\b", folded
    ):
        return "market_signal"
    return "other"


def _source_status(value: str | None) -> str:
    status = _safe_text(value).lower()
    if status in {"ready", "indexed", "promoted"}:
        return "ready"
    if status in {"error", "failed", "rejected"}:
        return "error"
    if status in {"queued", "ingesting", "received", "candidate"}:
        return "candidate"
    return "needs_review"


def _canonical_country(value: Any) -> str | None:
    text = _safe_text(value)
    if not text:
        return None
    return COUNTRY_CANONICAL_MAP.get(_normalize_token(text), text)


def _country_aliases(value: Any) -> set[str]:
    canonical = _canonical_country(value)
    if not canonical:
        return set()
    token = _normalize_token(canonical)
    aliases = {canonical, token.upper(), token.capitalize()}
    for key, mapped in COUNTRY_CANONICAL_MAP.items():
        if mapped == canonical:
            aliases.add(key)
            aliases.add(key.upper())
            aliases.add(key.capitalize())
    return {item for item in aliases if item}


def _serialize_data_source(row: Client360DataSource) -> dict[str, Any]:
    return {
        "id": row.id,
        "origin": "client360",
        "source_type": row.source_type,
        "label": row.label,
        "filename": row.filename,
        "collection_id": row.collection_id,
        "collection_slug": row.collection_slug,
        "knowledge_source_id": row.knowledge_source_id,
        "deposit_file_id": row.deposit_file_id,
        "status": row.status,
        "row_count": row.row_count,
        "error": row.error,
        "metadata": row.meta_data or {},
        "evidence_refs": row.evidence_refs or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_knowledge_source(
    source: KnowledgeCollectionSource, collection: KnowledgeCollection | None
) -> dict[str, Any]:
    filename = source.filename or source.normalized_name
    source_type = classify_data_source(
        " ".join([filename or "", source.source_kind or "", source.extension or ""])
    )
    return {
        "id": f"knowledge_source:{source.id}",
        "origin": "knowledge_collection_source",
        "source_type": source_type,
        "label": filename or source.normalized_name,
        "filename": filename,
        "collection_id": source.collection_id,
        "collection_slug": collection.slug if collection else None,
        "knowledge_source_id": source.id,
        "deposit_file_id": None,
        "status": _source_status(source.status),
        "row_count": None,
        "error": source.last_error,
        "metadata": {
            "source_kind": source.source_kind,
            "extension": source.extension,
            "mime_type": source.mime_type,
            "origin": source.origin,
            "chunk_count": source.chunk_count,
            "document_count": getattr(collection, "document_count", None),
        },
        "evidence_refs": [
            {
                "kind": "knowledge_collection_source",
                "collection_slug": collection.slug if collection else None,
                "source_id": source.id,
                "filename": filename,
            }
        ],
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def _serialize_deposit_file(file: DepositFile) -> dict[str, Any]:
    source_type = classify_data_source(file.filename)
    return {
        "id": f"deposit_file:{file.id}",
        "origin": "deposit_file",
        "source_type": source_type,
        "label": file.filename,
        "filename": file.filename,
        "collection_id": None,
        "collection_slug": file.promoted_collection_slug,
        "knowledge_source_id": None,
        "deposit_file_id": file.id,
        "status": _source_status(file.status),
        "row_count": None,
        "error": file.rejection_reason,
        "metadata": {
            "content_type": file.content_type,
            "size_bytes": file.size_bytes,
            "sha256": file.sha256,
            "worker_job_id": file.worker_job_id,
            "promotion_result": file.promotion_result or {},
        },
        "evidence_refs": [{"kind": "deposit_file", "file_id": file.id, "filename": file.filename}],
        "created_at": file.uploaded_at.isoformat() if file.uploaded_at else None,
        "updated_at": file.promoted_at.isoformat() if file.promoted_at else None,
    }


def list_data_sources(
    db: DBSession,
    workspace: Workspace,
    *,
    include_workspace_candidates: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    rows = (
        db.query(Client360DataSource)
        .filter(
            Client360DataSource.workspace_id == workspace.id,
            Client360DataSource.status != "archived",
        )
        .order_by(Client360DataSource.updated_at.desc())
        .all()
    )
    for row in rows:
        item = _serialize_data_source(row)
        items.append(item)
        if row.knowledge_source_id:
            seen.add(f"knowledge_source:{row.knowledge_source_id}")
        if row.deposit_file_id:
            seen.add(f"deposit_file:{row.deposit_file_id}")

    if not include_workspace_candidates:
        return items

    knowledge_rows = (
        db.query(KnowledgeCollectionSource, KnowledgeCollection)
        .join(
            KnowledgeCollection, KnowledgeCollection.id == KnowledgeCollectionSource.collection_id
        )
        .filter(KnowledgeCollectionSource.workspace_id == workspace.id)
        .order_by(KnowledgeCollectionSource.updated_at.desc())
        .limit(250)
        .all()
    )
    for source, collection in knowledge_rows:
        key = f"knowledge_source:{source.id}"
        if key in seen:
            continue
        item = _serialize_knowledge_source(source, collection)
        if item["source_type"] == "other":
            continue
        items.append(item)
        seen.add(key)

    deposit_rows = (
        db.query(DepositFile)
        .filter(DepositFile.workspace_id == workspace.id)
        .order_by(DepositFile.uploaded_at.desc())
        .limit(250)
        .all()
    )
    for file in deposit_rows:
        key = f"deposit_file:{file.id}"
        if key in seen:
            continue
        item = _serialize_deposit_file(file)
        if item["source_type"] == "other":
            continue
        items.append(item)
        seen.add(key)

    return items


def _source_gaps(data_sources: list[dict[str, Any]]) -> list[str]:
    available = {
        item["source_type"]
        for item in data_sources
        if item.get("source_type") in REQUIRED_SOURCE_TYPES
        and item.get("status") in {"ready", "mapped"}
    }
    return [
        f"{source_type}_missing"
        for source_type in REQUIRED_SOURCE_TYPES
        if source_type not in available
    ]


def serialize_opportunity(opportunity: Client360Opportunity) -> dict[str, Any]:
    annual = opportunity.annual_theoretical_qty
    if annual is None:
        annual = calculate_annual_theoretical_qty(
            installed_quantity=opportunity.installed_quantity,
            recommended_quantity=opportunity.recommended_quantity,
            periodicity_weeks=opportunity.periodicity_weeks,
        )
    potential = (
        opportunity.potential_theoretical
        if opportunity.potential_theoretical is not None
        else annual
    )
    gap_qty = opportunity.potential_gap_qty
    if gap_qty is None and annual is not None and opportunity.sales_known_qty is not None:
        gap_qty = max(round(float(annual) - float(opportunity.sales_known_qty or 0), 4), 0)
    addressable = opportunity.potential_addressable
    if addressable is None:
        addressable = gap_qty
    gap_value = opportunity.potential_gap_value
    if gap_value is None and gap_qty is not None:
        unit_price, _price_source = _opportunity_unit_price(opportunity)
        if unit_price is not None:
            gap_value = round(gap_qty * unit_price, 2)
    score = opportunity.confidence_score
    label = opportunity.confidence_label
    reasons = _as_list(opportunity.score_reasons)
    if score is None or not reasons:
        score, label, reasons = score_opportunity_details(opportunity)
    recommended_action = opportunity.recommended_action or recommended_action_for(opportunity)
    return {
        "id": opportunity.id,
        "customer_key": opportunity.customer_key,
        "customer_name": opportunity.customer_name,
        "site_name": opportunity.site_name,
        "country": opportunity.country,
        "hub": opportunity.hub,
        "technology": opportunity.technology,
        "line_label": opportunity.line_label,
        "machine_label": opportunity.machine_label,
        "part_family": opportunity.part_family,
        "part_reference": opportunity.part_reference,
        "part_description": opportunity.part_description,
        "installed_quantity": opportunity.installed_quantity,
        "recommended_quantity": opportunity.recommended_quantity,
        "periodicity_weeks": opportunity.periodicity_weeks,
        "delivery_time_weeks": opportunity.delivery_time_weeks,
        "annual_theoretical_qty": annual,
        "potential_theoretical": potential,
        "potential_addressable": addressable,
        "potential_gap_qty": gap_qty,
        "potential_gap_value": gap_value,
        "potential_unit": opportunity.potential_unit,
        "currency": opportunity.currency,
        "sales_known_qty": opportunity.sales_known_qty,
        "sales_known_value": opportunity.sales_known_value,
        "next_due_at": opportunity.next_due_at.isoformat() if opportunity.next_due_at else None,
        "confidence_score": score,
        "confidence_label": label,
        "score_reasons": reasons,
        "recommended_action": recommended_action,
        "status": opportunity.status,
        "data_gaps": opportunity_data_gaps(opportunity),
        "evidence_refs": opportunity.evidence_refs or [],
        "source_ids": opportunity.source_ids or [],
        "metadata": opportunity.meta_data or {},
        "created_at": opportunity.created_at.isoformat() if opportunity.created_at else None,
        "updated_at": opportunity.updated_at.isoformat() if opportunity.updated_at else None,
    }


def list_opportunities(
    db: DBSession,
    workspace: Workspace,
    *,
    status: str | None = None,
    customer: str | None = None,
    country: str | None = None,
    hub: str | None = None,
    technology: str | None = None,
    part_family: str | None = None,
    confidence: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = db.query(Client360Opportunity).filter(Client360Opportunity.workspace_id == workspace.id)
    if status:
        query = query.filter(Client360Opportunity.status == status)
    if customer:
        like = f"%{customer}%"
        query = query.filter(
            (Client360Opportunity.customer_name.ilike(like))
            | (Client360Opportunity.customer_key.ilike(like))
        )
    if country:
        aliases = sorted(_country_aliases(country))
        if aliases:
            query = query.filter(Client360Opportunity.country.in_(aliases))
    if hub:
        query = query.filter(Client360Opportunity.hub == hub)
    if technology:
        query = query.filter(Client360Opportunity.technology == technology)
    if part_family:
        query = query.filter(Client360Opportunity.part_family == part_family)
    if confidence:
        query = query.filter(Client360Opportunity.confidence_label == confidence)
    rows = (
        query.order_by(
            Client360Opportunity.confidence_score.desc().nullslast(),
            Client360Opportunity.potential_gap_value.desc().nullslast(),
            Client360Opportunity.potential_theoretical.desc().nullslast(),
            Client360Opportunity.updated_at.desc(),
        )
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [serialize_opportunity(row) for row in rows]


def summary_payload(
    db: DBSession,
    workspace: Workspace,
    *,
    include_mail_ai: bool = True,
    include_workspace_candidates: bool = True,
) -> dict[str, Any]:
    scope = client360_scope(workspace)
    data_sources = list_data_sources(
        db, workspace, include_workspace_candidates=include_workspace_candidates
    )
    opportunities = list_opportunities(db, workspace, limit=500)
    if include_mail_ai:
        mail_ai_config = _client360_mail_ai_config(db, workspace)
        mail_ai_ready, mail_ai_disabled_reason = _mail_ai_configured(mail_ai_config)
        mail_ai_payload = {
            "enabled": bool(mail_ai_config.get("enabled")),
            "configured": mail_ai_ready,
            "disabled_reason": mail_ai_disabled_reason,
            "provider": mail_ai_config.get("provider"),
            "model": mail_ai_config.get("model"),
            "model_source": mail_ai_config.get("model_source"),
            "provider_source": mail_ai_config.get("provider_source"),
            "routing_source": mail_ai_config.get("routing_source"),
            "system_id": mail_ai_config.get("system_id"),
            "capability_id": mail_ai_config.get("capability_id"),
            "route_id": CLIENT360_AGENT_ROUTING_CONTRACT["mail_draft"]["route_id"],
        }
    else:
        mail_ai_payload = {
            "enabled": True,
            "configured": False,
            "disabled_reason": "resolution_deferred",
            "provider": None,
            "model": None,
            "model_source": None,
            "provider_source": None,
            "routing_source": "deferred",
            "system_id": None,
            "capability_id": None,
            "route_id": CLIENT360_AGENT_ROUTING_CONTRACT["mail_draft"]["route_id"],
        }
    by_status: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    for item in opportunities:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
        by_confidence[item["confidence_label"]] = by_confidence.get(item["confidence_label"], 0) + 1
    total_theoretical = sum(float(item["potential_theoretical"] or 0) for item in opportunities)
    total_gap = sum(float(item["potential_gap_qty"] or 0) for item in opportunities)
    source_counts: dict[str, int] = {}
    for item in data_sources:
        source_counts[item["source_type"]] = source_counts.get(item["source_type"], 0) + 1
    from app.services.client360_alerts import alerts_summary_block

    alerts = alerts_summary_block(db, workspace)
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "positioning": {
            "name": "Client360 PDR",
            "mode": "explainable_potential",
            "no_supervised_prediction": True,
            "no_automatic_email_send": True,
            "scope": scope,
            "mvp_contract": CLIENT360_MVP_CONTRACT,
            "agent_routing": CLIENT360_AGENT_ROUTING_CONTRACT,
            "mail_ai": mail_ai_payload,
        },
        "summary": {
            "opportunities": len(opportunities),
            "customers": len({item["customer_key"] for item in opportunities}),
            "data_sources": len(data_sources),
            "mapping_rules": db.query(Client360MappingRule)
            .filter(Client360MappingRule.workspace_id == workspace.id)
            .count(),
            "potential_theoretical": round(total_theoretical, 4),
            "potential_gap_qty": round(total_gap, 4),
            "potential_unit": "quantity_per_year",
            "mail_drafts": db.query(Client360MailDraft)
            .filter(Client360MailDraft.workspace_id == workspace.id)
            .count(),
            "impact_events": db.query(Client360ImpactEvent)
            .filter(Client360ImpactEvent.workspace_id == workspace.id)
            .count(),
        },
        "by_status": by_status,
        "by_confidence": by_confidence,
        "source_counts": source_counts,
        "data_gaps": _source_gaps(data_sources),
        "data_sources": data_sources[:100],
        "alerts": alerts,
    }


_INSTALLED_BASE_UNKNOWN = "Non renseigne"


def _round_or_none(value: Any) -> Optional[float]:
    number = _safe_float(value)
    if number is None:
        return None
    return round(number, 2)


def build_installed_base_tree(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate the customer opportunities into a technology > line > machine tree.

    No dedicated installed-base entity exists in this pre-MVP: the flat
    opportunity rows carry ``technology`` / ``line_label`` / ``machine_label``
    and are grouped here purely for the customer fiche display.
    """
    tech_index: dict[str, dict[str, Any]] = {}
    for opp in opportunities:
        technology = _safe_text(opp.get("technology")) or _INSTALLED_BASE_UNKNOWN
        line = _safe_text(opp.get("line_label")) or _INSTALLED_BASE_UNKNOWN
        machine = _safe_text(opp.get("machine_label")) or _INSTALLED_BASE_UNKNOWN
        tech_node = tech_index.setdefault(
            technology,
            {
                "technology": technology,
                "_lines": {},
                "opportunity_count": 0,
                "potential_gap_value": 0.0,
            },
        )
        line_node = tech_node["_lines"].setdefault(
            line,
            {
                "line_label": line,
                "_machines": {},
                "opportunity_count": 0,
                "potential_gap_value": 0.0,
            },
        )
        machine_node = line_node["_machines"].setdefault(
            machine,
            {
                "machine_label": machine,
                "parts": [],
                "opportunity_count": 0,
                "potential_gap_value": 0.0,
            },
        )
        gap_value = _safe_float(opp.get("potential_gap_value")) or 0.0
        part = {
            "opportunity_id": opp.get("id"),
            "part_family": opp.get("part_family"),
            "part_reference": opp.get("part_reference"),
            "part_description": opp.get("part_description"),
            "installed_quantity": opp.get("installed_quantity"),
            "potential_gap_qty": opp.get("potential_gap_qty"),
            "potential_gap_value": opp.get("potential_gap_value"),
            "currency": opp.get("currency"),
            "next_due_at": opp.get("next_due_at"),
            "confidence_label": opp.get("confidence_label"),
            "status": opp.get("status"),
        }
        machine_node["parts"].append(part)
        for node in (tech_node, line_node, machine_node):
            node["opportunity_count"] += 1
            node["potential_gap_value"] += gap_value

    tree: list[dict[str, Any]] = []
    for tech_node in sorted(
        tech_index.values(), key=lambda n: (-n["potential_gap_value"], n["technology"])
    ):
        lines: list[dict[str, Any]] = []
        for line_node in sorted(
            tech_node.pop("_lines").values(),
            key=lambda n: (-n["potential_gap_value"], n["line_label"]),
        ):
            machines: list[dict[str, Any]] = []
            for machine_node in sorted(
                line_node.pop("_machines").values(),
                key=lambda n: (-n["potential_gap_value"], n["machine_label"]),
            ):
                machine_node["parts"].sort(
                    key=lambda p: (
                        -(_safe_float(p.get("potential_gap_value")) or 0.0),
                        _safe_text(p.get("part_family")),
                    )
                )
                machine_node["potential_gap_value"] = _round_or_none(
                    machine_node["potential_gap_value"]
                )
                machines.append(machine_node)
            line_node["machines"] = machines
            line_node["potential_gap_value"] = _round_or_none(line_node["potential_gap_value"])
            lines.append(line_node)
        tech_node["lines"] = lines
        tech_node["potential_gap_value"] = _round_or_none(tech_node["potential_gap_value"])
        tree.append(tech_node)
    return tree


def build_customer_timeline(
    opportunities: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    impacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge drafts, impact events and opportunity updates into a single timeline.

    Sorted most-recent first; entries without a usable timestamp are dropped so
    the fiche only shows anchored events.
    """
    events: list[dict[str, Any]] = []
    for opp in opportunities:
        at = opp.get("updated_at") or opp.get("created_at")
        if not at:
            continue
        events.append(
            {
                "at": at,
                "kind": "opportunity_update",
                "label": f"Opportunite {_safe_text(opp.get('part_family')) or 'PDR'} - {labelify_status(opp.get('status'))}",
                "status": opp.get("status"),
                "opportunity_id": opp.get("id"),
            }
        )
    for draft in drafts:
        if draft.get("sent_at"):
            events.append(
                {
                    "at": draft["sent_at"],
                    "kind": "mail_sent",
                    "label": f"Mail envoye : {_safe_text(draft.get('subject')) or 'brouillon'}",
                    "opportunity_id": draft.get("opportunity_id"),
                    "mail_draft_id": draft.get("id"),
                }
            )
        elif draft.get("created_at"):
            events.append(
                {
                    "at": draft["created_at"],
                    "kind": "mail_draft",
                    "label": f"Brouillon mail : {_safe_text(draft.get('subject')) or 'sans objet'}",
                    "opportunity_id": draft.get("opportunity_id"),
                    "mail_draft_id": draft.get("id"),
                }
            )
    for impact in impacts:
        at = impact.get("occurred_at") or impact.get("created_at")
        if not at:
            continue
        events.append(
            {
                "at": at,
                "kind": f"impact_{_safe_text(impact.get('impact_type')) or 'event'}",
                "label": _safe_text(impact.get("summary"))
                or f"Impact : {_safe_text(impact.get('impact_type'))}",
                "impact_type": impact.get("impact_type"),
                "opportunity_id": impact.get("opportunity_id"),
                "mail_draft_id": impact.get("mail_draft_id"),
            }
        )
    events.sort(key=lambda item: _safe_text(item.get("at")), reverse=True)
    return events


def labelify_status(value: Any) -> str:
    labels = {
        "detected": "detectee",
        "validated": "validee",
        "draft_generated": "brouillon",
        "sent": "envoyee",
        "responded": "reponse",
        "quote_requested": "devis",
        "won": "gagnee",
        "lost": "perdue",
        "dismissed": "ecartee",
    }
    return labels.get(_safe_text(value), _safe_text(value) or "-")


_CLIENT360_SUMMARY_SYSTEM_PROMPT = """Tu es l'assistant commercial technique ANDRITZ pour Client360 PDR.
Tu rediges un resume factuel de la fiche client a partir d'agregats structures,
pour aider un commercial humain a preparer un echange sur les pieces d'usure.

Contraintes strictes:
- N'invente aucun client, contact, prix, delai, reference, date, stock ou chiffre.
- Utilise uniquement les agregats fournis (parc installe, opportunites, chronologie).
- Si une donnee est absente, ne l'affirme pas et signale l'incertitude avec tact.
- Ne promets ni remise ni stock automatique, ne fais aucune prediction supervisee.
- Ton expert, sobre, synthetique. Maximum 6 phrases pour le resume.
- Retourne strictement un objet JSON: {"summary": "...", "highlights": ["...", "..."]}.
"""


def _customer_summary_aggregates(
    customer_name: str,
    opportunities: list[dict[str, Any]],
    installed_base: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    data_gaps: list[str],
) -> dict[str, Any]:
    total_gap_value = sum(
        _safe_float(opp.get("potential_gap_value")) or 0.0 for opp in opportunities
    )
    total_gap_qty = sum(_safe_float(opp.get("potential_gap_qty")) or 0.0 for opp in opportunities)
    by_confidence: dict[str, int] = {}
    for opp in opportunities:
        label = _safe_text(opp.get("confidence_label")) or "unknown"
        by_confidence[label] = by_confidence.get(label, 0) + 1
    due_dates = sorted(
        _safe_text(opp.get("next_due_at")) for opp in opportunities if opp.get("next_due_at")
    )
    technologies = [node.get("technology") for node in installed_base]
    return {
        "customer": customer_name,
        "opportunity_count": len(opportunities),
        "technologies": technologies,
        "technology_count": len(technologies),
        "total_potential_gap_qty": round(total_gap_qty, 2),
        "total_potential_gap_value": round(total_gap_value, 2),
        "by_confidence": by_confidence,
        "next_due_at": due_dates[0] if due_dates else None,
        "data_gaps": data_gaps,
        "recent_events": [
            {"at": event.get("at"), "kind": event.get("kind"), "label": event.get("label")}
            for event in timeline[:5]
        ],
    }


def _summary_user_prompt(aggregates: dict[str, Any]) -> str:
    return (
        "Redige le resume de fiche client ANDRITZ Client360 PDR a partir de ces agregats.\n"
        "Ne retourne ni markdown, ni commentaire hors JSON.\n\n"
        f"{json.dumps(aggregates, ensure_ascii=False, sort_keys=True)}"
    )


def _client360_summary_ai_config(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    """Reuse the mail model-resolution helper, retagged for the summary route."""
    config = dict(_client360_mail_ai_config(db, workspace))
    config["agent_route"] = CLIENT360_AGENT_ROUTING_CONTRACT["customer_summary"]["route_id"]
    return config


def _parse_ai_summary_json(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fence(text)
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        summary = _safe_text(payload.get("summary"))
        if summary:
            highlights = [
                _safe_text(item) for item in _as_list(payload.get("highlights")) if _safe_text(item)
            ]
            return {"summary": summary, "highlights": highlights[:6]}
    if len(cleaned) >= 60:
        return {"summary": cleaned, "highlights": []}
    return None


async def _complete_client360_summary_ai(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    workspace: Workspace,
) -> str:
    from app.llm.llm import LLM

    provider_key = _safe_text(provider).lower() or "openai"
    api_key = settings.openai_api_key if provider_key == "openai" else None
    llm = LLM(provider=provider_key, api_key=api_key)
    return await llm.complete(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=0.2,
        max_tokens=700,
        user=f"workspace:{workspace.id}:client360_pdr_customer_summary",
    )


async def _generate_ai_customer_summary(
    workspace: Workspace,
    aggregates: dict[str, Any],
    *,
    config: dict[str, Any],
) -> dict[str, Any]:
    user_prompt = _summary_user_prompt(aggregates)
    prompt_hash = _prompt_hash(_CLIENT360_SUMMARY_SYSTEM_PROMPT, user_prompt)
    raw = await asyncio.wait_for(
        _complete_client360_summary_ai(
            provider=str(config["provider"]),
            model=str(config["model"]),
            system_prompt=_CLIENT360_SUMMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            workspace=workspace,
        ),
        timeout=float(config["timeout_seconds"]),
    )
    parsed = _parse_ai_summary_json(raw)
    if parsed is None:
        raise ValueError("Client360 customer summary AI returned an unparsable payload")
    return {
        "text": parsed["summary"],
        "highlights": parsed.get("highlights", []),
        "generation_mode": "ai_assisted",
        "provider": config["provider"],
        "model": config["model"],
        "model_source": config.get("model_source"),
        "provider_source": config.get("provider_source"),
        "routing_source": config.get("routing_source"),
        "system_id": config.get("system_id"),
        "capability_id": config.get("capability_id"),
        "route_id": config.get("agent_route"),
        "prompt_version": CLIENT360_SUMMARY_PROMPT_VERSION,
        "prompt_hash": prompt_hash,
    }


def _fallback_customer_summary(
    aggregates: dict[str, Any], *, reason: str | None = None
) -> dict[str, Any]:
    customer = _safe_text(aggregates.get("customer")) or "Ce client"
    count = int(aggregates.get("opportunity_count") or 0)
    technologies = [tech for tech in _as_list(aggregates.get("technologies")) if _safe_text(tech)]
    gap_value = _safe_float(aggregates.get("total_potential_gap_value"))
    by_confidence = _as_dict(aggregates.get("by_confidence"))
    high = int(by_confidence.get("high") or 0)
    next_due = _safe_text(aggregates.get("next_due_at"))
    data_gaps = [gap for gap in _as_list(aggregates.get("data_gaps")) if _safe_text(gap)]

    sentences: list[str] = []
    if count:
        techno_txt = (
            f" sur {len(technologies)} technologie(s) ({', '.join(technologies[:4])})"
            if technologies
            else ""
        )
        sentences.append(f"{customer} presente {count} opportunite(s) PDR detectee(s){techno_txt}.")
    else:
        sentences.append(f"{customer} n'a pas encore d'opportunite PDR detectee.")
    if gap_value:
        sentences.append(
            f"Le potentiel d'ecart valorise cumule est estime a {gap_value:g} EUR (indicatif, non contractuel)."
        )
    if high:
        sentences.append(
            f"{high} opportunite(s) sont en confiance haute et peuvent etre activees en priorite."
        )
    if next_due:
        sentences.append(f"Prochaine echeance estimee : {next_due[:10]}.")
    if data_gaps:
        sentences.append(f"Donnees a completer : {', '.join(data_gaps[:4])}.")

    highlights: list[str] = []
    if gap_value:
        highlights.append(f"Potentiel valorise : {gap_value:g} EUR")
    if high:
        highlights.append(f"Confiance haute : {high}")
    if next_due:
        highlights.append(f"Echeance : {next_due[:10]}")

    metadata_reason = {"fallback_reason": reason} if reason else {}
    return {
        "text": " ".join(sentences),
        "highlights": highlights,
        "generation_mode": "deterministic_template",
        "provider": None,
        "model": None,
        "route_id": CLIENT360_AGENT_ROUTING_CONTRACT["customer_summary"]["route_id"],
        "prompt_version": CLIENT360_SUMMARY_PROMPT_VERSION,
        **metadata_reason,
    }


def _generate_customer_summary_content(
    db: DBSession,
    workspace: Workspace,
    aggregates: dict[str, Any],
) -> dict[str, Any]:
    config = _client360_summary_ai_config(db, workspace)
    configured, reason = _mail_ai_configured(config)
    if not configured:
        return _fallback_customer_summary(aggregates, reason=reason)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(_generate_ai_customer_summary(workspace, aggregates, config=config))
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Client360 AI customer summary failed; using deterministic fallback", exc_info=True
            )
            return _fallback_customer_summary(aggregates, reason=type(exc).__name__)

    _logger.warning("Client360 AI customer summary skipped inside running event loop")
    return _fallback_customer_summary(aggregates, reason="running_event_loop")


def _record_role(record: dict[str, Any]) -> str:
    return _normalize_token(record.get("role"))


def _customer_key_for(value: Any) -> str:
    return normalize_customer_key(value)


def _raw_source_records_by_roles(
    db: DBSession,
    workspace: Workspace,
    roles: set[str],
) -> list[dict[str, Any]]:
    """Read persisted source ``metadata.records`` without canonical field stripping.

    Registry / machine / sales_orders rows carry fields (``project_code``,
    ``sap_reference``, ``construction_year``, …) that the opportunity
    canonicalize path does not keep.
    """
    wanted = {_normalize_token(role) for role in roles if _normalize_token(role)}
    if not wanted:
        return []
    records: list[dict[str, Any]] = []
    rows = (
        db.query(Client360DataSource)
        .filter(
            Client360DataSource.workspace_id == workspace.id,
            Client360DataSource.status != "archived",
        )
        .all()
    )
    for source in rows:
        metadata = _as_dict(source.meta_data)
        source_role = _normalize_token(metadata.get("role") or metadata.get("spl_role"))
        raw_rows = _as_list(
            metadata.get("records") or metadata.get("rows") or metadata.get("mapped_rows")
        )
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            role = _normalize_token(raw.get("role")) or source_role
            if role not in wanted:
                continue
            item = dict(raw)
            item["role"] = role
            item.setdefault("source_type", source.source_type)
            # Source attribution so downstream readers (e.g. the chat installed
            # base intent) can cite the originating file without re-querying.
            item.setdefault("source_id", source.id)
            item.setdefault("source_filename", source.filename or source.label)
            item.setdefault("customer_key", _customer_key_for(item.get("customer_key") or item.get("customer_name")))
            records.append(item)
    return records


def _records_matching_customer(
    records: list[dict[str, Any]],
    *,
    customer_key: str,
    customer_name: str | None = None,
) -> list[dict[str, Any]]:
    keys = {key for key in (customer_key, _customer_key_for(customer_name)) if key}
    if not keys:
        return []
    matched: list[dict[str, Any]] = []
    for record in records:
        record_key = _customer_key_for(record.get("customer_key") or record.get("customer_name"))
        if record_key and record_key in keys:
            matched.append(record)
    return matched


def _load_project_registry_records(db: DBSession, workspace: Workspace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in _raw_source_records_by_roles(db, workspace, {"project_registry"}):
        customer_name = _safe_text(record.get("customer_name"))
        # Name first: registry names carry the "Primary (Alias)" convention and
        # persisted keys may predate the shared normalization.
        customer_key = registry_customer_key(customer_name) or normalize_customer_key(
            record.get("customer_key")
        )
        if not customer_key and not record.get("project_code") and not record.get("sap_reference"):
            continue
        records.append(
            {
                "project_code": _safe_text(record.get("project_code")) or None,
                "sap_reference": _safe_text(record.get("sap_reference")) or None,
                "wbs_element": _safe_text(record.get("wbs_element")) or None,
                "customer_name": customer_name or None,
                "customer_key": customer_key or None,
                "country": _safe_text(record.get("country")) or None,
                "role": "project_registry",
            }
        )
    return records


def _customer_projects(
    registry_records: list[dict[str, Any]],
    *,
    customer_key: str,
    customer_name: str | None = None,
) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in _records_matching_customer(
        registry_records, customer_key=customer_key, customer_name=customer_name
    ):
        item = {
            "project_code": record.get("project_code"),
            "sap_reference": record.get("sap_reference"),
            "wbs_element": record.get("wbs_element"),
            "country": record.get("country"),
        }
        dedupe = (
            _safe_text(item.get("project_code")),
            _safe_text(item.get("sap_reference")),
            _safe_text(item.get("wbs_element")),
        )
        if not any(dedupe) or dedupe in seen:
            continue
        seen.add(dedupe)
        projects.append(item)
    projects.sort(
        key=lambda item: (
            _safe_text(item.get("project_code")),
            _safe_text(item.get("sap_reference")),
        )
    )
    return projects


def _customer_machines(
    db: DBSession,
    workspace: Workspace,
    *,
    customer_key: str,
    customer_name: str | None = None,
    registry_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Machine.xlsx equipment for the customer (Sold-to + registry project join)."""
    from app.services.client360_spl_adapter import (
        build_project_registry_index,
        resolve_customer_for_project,
    )

    registry = registry_records if registry_records is not None else _load_project_registry_records(
        db, workspace
    )
    registry_index = build_project_registry_index(registry)
    keys = {key for key in (customer_key, _customer_key_for(customer_name)) if key}
    machines: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in _raw_source_records_by_roles(db, workspace, {"machine"}):
        record_key = _customer_key_for(record.get("customer_key") or record.get("customer_name"))
        if record_key not in keys:
            resolved = resolve_customer_for_project(
                record.get("project_code"),
                wbs=record.get("wbs_element"),
                sap_ref=record.get("sap_reference"),
                index=registry_index,
            )
            resolved_key = _customer_key_for(
                (resolved or {}).get("customer_key") or (resolved or {}).get("customer_name")
            )
            if resolved_key not in keys:
                continue
            if not record_key and resolved:
                record_key = resolved_key
        item = {
            "machine_label": _safe_text(record.get("machine_label")) or None,
            "technology": _safe_text(record.get("technology")) or None,
            "line_label": _safe_text(record.get("line_label")) or None,
            "project_code": _safe_text(record.get("project_code")) or None,
            "sap_reference": _safe_text(record.get("sap_reference")) or None,
            "wbs_element": _safe_text(record.get("wbs_element")) or None,
            "construction_year": _safe_text(record.get("construction_year")) or None,
            "country": _safe_text(record.get("country")) or None,
            "customer_key": record_key or customer_key,
        }
        dedupe = (
            _safe_text(item.get("machine_label")),
            _safe_text(item.get("technology")),
            _safe_text(item.get("line_label")),
            _safe_text(item.get("project_code")),
        )
        if not any(dedupe) or dedupe in seen:
            continue
        seen.add(dedupe)
        machines.append(item)
    machines.sort(
        key=lambda item: (
            _safe_text(item.get("technology")),
            _safe_text(item.get("line_label")),
            _safe_text(item.get("machine_label")),
        )
    )
    return machines


def _customer_purchases(
    db: DBSession,
    workspace: Workspace,
    *,
    customer_key: str,
    customer_name: str | None = None,
) -> list[dict[str, Any]]:
    """Sales-order aggregates for the customer, enriched with PO cost/lead when present."""
    sales = _raw_source_records_by_roles(db, workspace, {"sales_orders"})
    matched = _records_matching_customer(
        sales, customer_key=customer_key, customer_name=customer_name
    )
    if not matched:
        return []
    matched_ref_keys = {
        _normalize_token(record.get("part_reference"))
        for record in matched
        if _safe_text(record.get("part_reference"))
    }
    # The purchase-history sources hold tens of thousands of materials; only
    # the customer's own references are ever looked up, so filtering before
    # indexing keeps the fiche latency bounded.
    purchase_rows = [
        row
        for row in _raw_source_records_by_roles(db, workspace, {"purchase_history"})
        if _normalize_token(row.get("part_reference")) in matched_ref_keys
    ]
    cost_index = _index_purchase_costs(purchase_rows)
    lead_index = _index_purchase_lead_times(purchase_rows)
    by_ref_cost = _as_dict(cost_index.get("by_part_reference"))
    purchases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in matched:
        part_ref = _safe_text(record.get("part_reference"))
        if not part_ref:
            continue
        ref_key = _normalize_token(part_ref)
        if ref_key in seen:
            # Prefer the first (already aggregated) sales_orders row per material.
            continue
        seen.add(ref_key)
        unit_cost = by_ref_cost.get(ref_key)
        po_count = _safe_float(record.get("po_count"))
        if unit_cost is None:
            unit_cost = _safe_non_negative_float(record.get("unit_cost"))
        lead = lead_index.get(ref_key)
        if lead is None:
            lead = _safe_float(record.get("delivery_time_weeks"))
        if po_count is None:
            for po_record in purchase_rows:
                if _normalize_token(po_record.get("part_reference")) != ref_key:
                    continue
                po_count = _safe_float(po_record.get("po_count")) or 1.0
                if unit_cost is None:
                    unit_cost = _safe_non_negative_float(po_record.get("unit_cost"))
                if lead is None:
                    lead = _safe_float(po_record.get("delivery_time_weeks"))
                break
        purchases.append(
            {
                "part_reference": part_ref,
                "part_description": _safe_text(record.get("part_description")) or None,
                "sales_known_qty": _safe_float(record.get("sales_known_qty")),
                "sales_known_value": _safe_non_negative_float(record.get("sales_known_value")),
                "currency": _safe_text(record.get("currency")) or "EUR",
                "last_document_date": _safe_text(
                    record.get("last_document_date") or record.get("document_date")
                )
                or None,
                "order_line_count": _safe_int(record.get("order_line_count"), 1)
                if record.get("order_line_count") is not None
                else None,
                "unit_cost": unit_cost,
                "delivery_time_weeks": lead,
                "po_count": int(po_count) if po_count is not None else None,
                "cost_sum": _safe_non_negative_float(record.get("cost_sum")),
            }
        )
    purchases.sort(
        key=lambda item: (
            -(_safe_non_negative_float(item.get("sales_known_value")) or 0.0),
            _safe_text(item.get("part_reference")),
        )
    )
    return purchases


def _customer_next_due(
    db: DBSession,
    workspace: Workspace,
    *,
    customer_key: str,
    customer_name: str | None = None,
) -> list[dict[str, Any]]:
    """Deterministic due items from Phase-4 forecast when the module is present."""
    try:
        from app.services.client360_forecast import customer_next_due
    except ImportError:
        return []
    try:
        result = customer_next_due(
            db,
            workspace,
            customer_key=customer_key,
            customer_name=customer_name,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Client360 forecast next_due failed: %s", type(exc).__name__)
        return []
    if result is None:
        return []
    return [item for item in _as_list(result) if isinstance(item, dict)]


def list_customers(
    db: DBSession,
    workspace: Workspace,
    *,
    q: str | None = None,
    country: str | None = None,
    technology: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Customer directory: project registry × opportunities, sorted by potential."""
    registry_records = _load_project_registry_records(db, workspace)
    opportunities = list_opportunities(db, workspace, limit=500)

    directory: dict[str, dict[str, Any]] = {}

    def _ensure(customer_key: str, customer_name: str | None = None) -> dict[str, Any]:
        key = customer_key or _customer_key_for(customer_name)
        if not key:
            key = "unknown"
        bucket = directory.get(key)
        if bucket is None:
            bucket = {
                "customer_key": key,
                "customer_name": customer_name or key,
                "countries": set(),
                "hubs": set(),
                "technologies": set(),
                "projects": [],
                "project_count": 0,
                "opportunity_count": 0,
                "statuses": {},
                "potential_gap_value": 0.0,
                "potential_gap_qty": 0.0,
                "currency": "EUR",
            }
            directory[key] = bucket
        elif customer_name and (
            bucket["customer_name"] == key or len(customer_name) > len(str(bucket["customer_name"]))
        ):
            bucket["customer_name"] = customer_name
        return bucket

    for record in registry_records:
        customer_key = _customer_key_for(record.get("customer_key") or record.get("customer_name"))
        if not customer_key:
            continue
        bucket = _ensure(customer_key, record.get("customer_name"))
        if record.get("country"):
            bucket["countries"].add(_canonical_country(record["country"]) or record["country"])
        project = {
            "project_code": record.get("project_code"),
            "sap_reference": record.get("sap_reference"),
            "wbs_element": record.get("wbs_element"),
            "country": _canonical_country(record.get("country")) or record.get("country"),
        }
        if any(project.get(field) for field in ("project_code", "sap_reference", "wbs_element")):
            if project not in bucket["projects"]:
                bucket["projects"].append(project)

    for opp in opportunities:
        customer_key = _customer_key_for(opp.get("customer_key") or opp.get("customer_name"))
        if not customer_key:
            continue
        bucket = _ensure(customer_key, opp.get("customer_name"))
        bucket["opportunity_count"] += 1
        status = _safe_text(opp.get("status")) or "detected"
        statuses = bucket["statuses"]
        statuses[status] = int(statuses.get(status, 0)) + 1
        bucket["potential_gap_value"] += float(_safe_float(opp.get("potential_gap_value")) or 0.0)
        bucket["potential_gap_qty"] += float(_safe_float(opp.get("potential_gap_qty")) or 0.0)
        if opp.get("currency"):
            bucket["currency"] = opp["currency"]
        if opp.get("country"):
            bucket["countries"].add(_canonical_country(opp["country"]) or opp["country"])
        if opp.get("hub"):
            bucket["hubs"].add(opp["hub"])
        if opp.get("technology"):
            bucket["technologies"].add(opp["technology"])

    query = _normalize_token(q)
    country_filter_aliases = _country_aliases(country) if country else set()
    technology_filter = _safe_text(technology)
    items: list[dict[str, Any]] = []
    facet_countries: set[str] = set()
    facet_technologies: set[str] = set()

    for bucket in directory.values():
        countries = sorted(bucket["countries"])
        technologies = sorted(bucket["technologies"])
        hubs = sorted(bucket["hubs"])
        for value in countries:
            facet_countries.add(value)
        for value in technologies:
            facet_technologies.add(value)
        if country_filter_aliases and not any(item in countries for item in country_filter_aliases):
            continue
        if technology_filter and technology_filter not in technologies:
            continue
        if query:
            haystack = " ".join(
                [
                    _normalize_token(bucket["customer_name"]),
                    _normalize_token(bucket["customer_key"]),
                    " ".join(_normalize_token(c) for c in countries),
                    " ".join(
                        _normalize_token(p.get("project_code")) for p in bucket["projects"]
                    ),
                ]
            )
            if query not in haystack:
                continue
        items.append(
            {
                "customer_key": bucket["customer_key"],
                "customer_name": bucket["customer_name"],
                "countries": countries,
                "hubs": hubs,
                "technologies": technologies,
                "projects": sorted(
                    bucket["projects"],
                    key=lambda item: (
                        _safe_text(item.get("project_code")),
                        _safe_text(item.get("sap_reference")),
                    ),
                ),
                "project_count": len(bucket["projects"]),
                "opportunity_count": bucket["opportunity_count"],
                "statuses": dict(sorted(bucket["statuses"].items())),
                "potential_gap_value": _round_or_none(bucket["potential_gap_value"]) or 0.0,
                "potential_gap_qty": _round_or_none(bucket["potential_gap_qty"]) or 0.0,
                "currency": bucket["currency"] or "EUR",
            }
        )

    items.sort(
        key=lambda item: (
            -(float(item.get("potential_gap_value") or 0.0)),
            -(int(item.get("opportunity_count") or 0)),
            _safe_text(item.get("customer_name")).lower(),
        )
    )
    capped = items[: max(1, min(int(limit or 200), 500))]
    return {
        "items": capped,
        "total": len(items),
        "facets": {
            "countries": sorted(facet_countries),
            "technologies": sorted(facet_technologies),
        },
    }


def customer_payload(
    db: DBSession,
    workspace: Workspace,
    customer_id: str,
    *,
    include_ai_summary: bool = True,
) -> dict[str, Any]:
    rows = (
        db.query(Client360Opportunity)
        .filter(
            Client360Opportunity.workspace_id == workspace.id,
            (Client360Opportunity.customer_key == customer_id)
            | (Client360Opportunity.id == customer_id),
        )
        .order_by(Client360Opportunity.updated_at.desc())
        .all()
    )
    if not rows:
        rows = (
            db.query(Client360Opportunity)
            .filter(
                Client360Opportunity.workspace_id == workspace.id,
                Client360Opportunity.customer_name.ilike(f"%{customer_id}%"),
            )
            .order_by(Client360Opportunity.updated_at.desc())
            .all()
        )
    opportunities = [serialize_opportunity(row) for row in rows]
    opportunity_ids = [row.id for row in rows]
    drafts = (
        db.query(Client360MailDraft)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.opportunity_id.in_(opportunity_ids or [""]),
        )
        .order_by(Client360MailDraft.created_at.desc())
        .all()
    )
    impacts = (
        db.query(Client360ImpactEvent)
        .filter(
            Client360ImpactEvent.workspace_id == workspace.id,
            Client360ImpactEvent.opportunity_id.in_(opportunity_ids or [""]),
        )
        .order_by(Client360ImpactEvent.occurred_at.desc())
        .all()
    )
    registry_records = _load_project_registry_records(db, workspace)
    customer_name = opportunities[0]["customer_name"] if opportunities else customer_id
    customer_key = _customer_key_for(
        opportunities[0].get("customer_key") if opportunities else None
    ) or _customer_key_for(customer_id)
    if not opportunities:
        for record in registry_records:
            record_key = _customer_key_for(record.get("customer_key") or record.get("customer_name"))
            if record_key == customer_key or customer_key in _normalize_token(
                record.get("customer_name")
            ):
                customer_name = record.get("customer_name") or customer_name
                customer_key = record_key or customer_key
                break
    customer_norm = _normalize_token(customer_name)
    market_signals = [
        item
        for item in list_data_sources(db, workspace)
        if item.get("source_type") == "market_signal"
        and (
            not customer_norm
            or customer_norm in _normalize_token(item.get("label"))
            or customer_norm in _normalize_token(item.get("filename"))
        )
    ][:10]
    serialized_drafts = [serialize_mail_draft(row) for row in drafts]
    serialized_impacts = [serialize_impact_event(row) for row in impacts]
    data_gaps = sorted({gap for item in opportunities for gap in item.get("data_gaps", [])})
    installed_base = build_installed_base_tree(opportunities)
    timeline = build_customer_timeline(opportunities, serialized_drafts, serialized_impacts)
    projects = _customer_projects(
        registry_records, customer_key=customer_key, customer_name=customer_name
    )
    machines = _customer_machines(
        db,
        workspace,
        customer_key=customer_key,
        customer_name=customer_name,
        registry_records=registry_records,
    )
    purchases = _customer_purchases(
        db, workspace, customer_key=customer_key, customer_name=customer_name
    )
    next_due = _customer_next_due(
        db, workspace, customer_key=customer_key, customer_name=customer_name
    )
    countries = sorted(
        {
            *(
                _canonical_country(item["country"]) or item["country"]
                for item in opportunities
                if item.get("country")
            ),
            *(
                _canonical_country(item["country"]) or item["country"]
                for item in projects
                if item.get("country")
            ),
            *(
                _canonical_country(item["country"]) or item["country"]
                for item in machines
                if item.get("country")
            ),
        }
    )
    hubs = sorted({item["hub"] for item in opportunities if item.get("hub")})
    technologies = sorted(
        {
            *(item["technology"] for item in opportunities if item.get("technology")),
            *(item["technology"] for item in machines if item.get("technology")),
        }
    )
    aggregates = _customer_summary_aggregates(
        customer_name, opportunities, installed_base, timeline, data_gaps
    )
    # The AI summary is the slow part of the payload (LLM completion); callers
    # can skip it and fetch it separately so the fiche renders immediately.
    ai_summary = (
        _generate_customer_summary_content(db, workspace, aggregates)
        if include_ai_summary
        else None
    )
    return {
        "customer": {
            "id": customer_key or customer_id,
            "name": customer_name,
            "countries": countries,
            "hubs": hubs,
            "technologies": technologies,
        },
        "ai_summary": ai_summary,
        "installed_base": installed_base,
        "timeline": timeline,
        "projects": projects,
        "machines": machines,
        "purchases": purchases,
        "next_due": next_due,
        "opportunities": opportunities,
        "mail_drafts": serialized_drafts,
        "impact_events": serialized_impacts,
        "market_signals": market_signals,
        "data_gaps": data_gaps,
    }


def serialize_mapping_rule(row: Client360MappingRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_part_reference": row.source_part_reference,
        "source_part_label": row.source_part_label,
        "source_part_family": row.source_part_family,
        "source_system": row.source_system,
        "technology": row.technology,
        "pdr_family": row.pdr_family,
        "normalized_key": row.normalized_key,
        "recommended_quantity": row.recommended_quantity,
        "periodicity_weeks": row.periodicity_weeks,
        "delivery_time_weeks": row.delivery_time_weeks,
        "status": row.status,
        "confidence": row.confidence,
        "notes": row.notes,
        "evidence_refs": row.evidence_refs or [],
        "metadata": row.meta_data or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_mapping_rules(
    db: DBSession, workspace: Workspace, *, status: str | None = None
) -> list[dict[str, Any]]:
    query = db.query(Client360MappingRule).filter(Client360MappingRule.workspace_id == workspace.id)
    if status:
        query = query.filter(Client360MappingRule.status == status)
    rows = query.order_by(Client360MappingRule.updated_at.desc()).limit(500).all()
    return [serialize_mapping_rule(row) for row in rows]


def _mapping_payload_key(payload: dict[str, Any]) -> str:
    return _mapping_key(
        payload.get("source_part_reference"),
        payload.get("source_part_family")
        or payload.get("source_part_label")
        or payload.get("pdr_family"),
        payload.get("technology"),
    )


def upsert_mapping_rule(
    db: DBSession,
    workspace: Workspace,
    user: User | None,
    payload: dict[str, Any],
) -> Client360MappingRule:
    normalized_key = _mapping_payload_key(payload)
    if not normalized_key:
        raise ValueError("Mapping source reference, family or label is required")
    pdr_family = _safe_text(
        payload.get("pdr_family")
        or payload.get("source_part_family")
        or payload.get("source_part_label")
    )
    if not pdr_family:
        raise ValueError("PDR family is required")
    row = (
        db.query(Client360MappingRule)
        .filter(
            Client360MappingRule.workspace_id == workspace.id,
            Client360MappingRule.normalized_key == normalized_key,
        )
        .first()
    )
    if row is None:
        row = Client360MappingRule(
            id=str(uuid4()),
            workspace_id=workspace.id,
            normalized_key=normalized_key,
            created_by_user_id=user.id if user else None,
        )
        db.add(row)
    row.source_part_reference = _safe_text(payload.get("source_part_reference")) or None
    row.source_part_label = _safe_text(payload.get("source_part_label")) or None
    row.source_part_family = _safe_text(payload.get("source_part_family")) or None
    row.source_system = _safe_text(payload.get("source_system")) or "sap"
    row.technology = _safe_text(payload.get("technology")) or None
    row.pdr_family = pdr_family
    row.recommended_quantity = _safe_float(payload.get("recommended_quantity"))
    row.periodicity_weeks = _safe_float(payload.get("periodicity_weeks"))
    row.delivery_time_weeks = _safe_float(payload.get("delivery_time_weeks"))
    status = _safe_text(payload.get("status")) or "candidate"
    row.status = status if status in CLIENT360_MAPPING_STATUSES else "candidate"
    row.confidence = float(
        _safe_float(payload.get("confidence")) or (0.75 if row.status == "validated" else 0.4)
    )
    row.notes = _safe_text(payload.get("notes"))
    row.evidence_refs = _as_list(payload.get("evidence_refs"))
    row.meta_data = _as_dict(payload.get("metadata"))
    row.updated_by_user_id = user.id if user else None
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def patch_mapping_rule(
    db: DBSession,
    workspace: Workspace,
    user: User | None,
    mapping_id: str,
    patch: dict[str, Any],
) -> Client360MappingRule:
    row = (
        db.query(Client360MappingRule)
        .filter(
            Client360MappingRule.workspace_id == workspace.id, Client360MappingRule.id == mapping_id
        )
        .first()
    )
    if row is None:
        raise LookupError("Client360 mapping rule not found")
    payload = serialize_mapping_rule(row)
    payload.update({key: value for key, value in patch.items() if value is not None})
    return upsert_mapping_rule(db, workspace, user, payload)


def _canonicalize_source_record(
    record: dict[str, Any], *, source_type: str, evidence_refs: list[Any], source_id: str
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source_type": source_type,
        "evidence_refs": evidence_refs,
        "source_ids": [source_id],
    }
    for key, value in record.items():
        canonical = key if key in CLIENT360_FIELD_ALIASES else _field_for_label(key)
        if canonical:
            out[canonical] = _coerce_record_value(canonical, value)
        elif key in {
            "pdr_family",
            "source_part_reference",
            "source_part_family",
            "source_part_label",
            "contact_name",
            "contact_email",
            "role",
            "vendor_name",
            "vendor_country",
            "po_count",
            "cost_sum",
            # Forecast anchors: sales_orders aggregates carry the last purchase
            # date and machine rows a construction year — dropping them here
            # left every ``compute_next_due`` without an anchor.
            "last_purchase_date",
            "last_document_date",
            "document_date",
            "construction_year",
            "purchase_unit_price",
            "sales_unit_price",
            "order_line_value_avg",
            "order_quantity",
        }:
            if key in {
                "po_count",
                "cost_sum",
                "purchase_unit_price",
                "sales_unit_price",
                "order_line_value_avg",
                "order_quantity",
            }:
                out[key] = _safe_float(value)
            else:
                out[key] = _safe_text(value) or None
    if out.get("country"):
        out["country"] = _canonical_country(out.get("country")) or out.get("country")
    if not out.get("customer_key") and out.get("customer_name"):
        out["customer_key"] = normalize_customer_key(out.get("customer_name"))
    if not out.get("source_part_reference") and out.get("part_reference"):
        out["source_part_reference"] = out.get("part_reference")
    if not out.get("source_part_family") and out.get("part_family"):
        out["source_part_family"] = out.get("part_family")
    return out


def _records_from_data_sources(db: DBSession, workspace: Workspace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    all_rows = (
        db.query(Client360DataSource)
        .filter(
            Client360DataSource.workspace_id == workspace.id,
            Client360DataSource.status != "archived",
        )
        .order_by(Client360DataSource.updated_at.desc())
        .all()
    )
    selected_rows: list[Client360DataSource] = []
    seen_source_keys: set[tuple[str, str]] = set()
    for source in all_rows:
        metadata = _as_dict(source.meta_data)
        role = _normalize_token(metadata.get("role") or metadata.get("spl_role"))
        raw_name = _safe_text(source.filename or source.label or metadata.get("origin_file"))
        basename = _normalize_token(raw_name.replace("\\", "/").split("/")[-1] if raw_name else "")
        if role and basename:
            dedupe_key = (role, basename)
            if dedupe_key in seen_source_keys:
                continue
            seen_source_keys.add(dedupe_key)
        selected_rows.append(source)

    for source in selected_rows:
        metadata = _as_dict(source.meta_data)
        source_role = _safe_text(metadata.get("role") or metadata.get("spl_role")) or None
        raw_rows = _as_list(
            metadata.get("records") or metadata.get("rows") or metadata.get("mapped_rows")
        )
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            record = _canonicalize_source_record(
                raw,
                source_type=source.source_type,
                evidence_refs=source.evidence_refs
                or [
                    {
                        "kind": "client360_data_source",
                        "source_id": source.id,
                        "label": source.label,
                    }
                ],
                source_id=source.id,
            )
            if source_role and not record.get("role"):
                record["role"] = source_role
            records.append(record)
    return records


def _records_from_table_facts(db: DBSession, workspace: Workspace) -> list[dict[str, Any]]:
    facts = (
        db.query(KnowledgeTableFact)
        .filter(
            KnowledgeTableFact.workspace_id == workspace.id,
            KnowledgeTableFact.semantic_type == "spreadsheet_table_fact",
        )
        .order_by(KnowledgeTableFact.updated_at.desc())
        .limit(5000)
        .all()
    )
    grouped: dict[tuple[Any, ...], list[KnowledgeTableFact]] = {}
    for fact in facts:
        key = (
            fact.collection_slug,
            fact.document_filename,
            fact.sheet_name,
            fact.table_region_id,
            fact.row_index,
        )
        grouped.setdefault(key, []).append(fact)
    records: list[dict[str, Any]] = []
    for key, group in grouped.items():
        collection_slug, filename, sheet_name, _region, row_index = key
        source_type = classify_data_source(
            " ".join(_safe_text(value) for value in [filename, sheet_name])
        )
        record: dict[str, Any] = {
            "source_type": source_type,
            "source_ids": [f"table_fact:{fact.id}" for fact in group[:8]],
            "evidence_refs": [
                {
                    "kind": "knowledge_table_fact",
                    "collection_slug": collection_slug,
                    "filename": filename,
                    "sheet_name": sheet_name,
                    "row_index": row_index,
                    "fact_ids": [fact.id for fact in group[:8]],
                }
            ],
        }
        for fact in group:
            label = fact.column_header or fact.measure or fact.subject
            field = _field_for_label(label)
            if field:
                record[field] = _coerce_record_value(field, fact.value_raw, fact.value_numeric)
            if fact.row_label and not record.get("source_part_label"):
                record["source_part_label"] = fact.row_label
        if (
            not record.get("part_family")
            and record.get("source_part_label")
            and source_type == "periodicity"
        ):
            record["part_family"] = record["source_part_label"]
        if not record.get("customer_key") and record.get("customer_name"):
            record["customer_key"] = normalize_customer_key(record.get("customer_name"))
        if any(
            record.get(key)
            for key in (
                "customer_name",
                "part_reference",
                "part_family",
                "installed_quantity",
                "periodicity_weeks",
                "sales_known_qty",
            )
        ):
            records.append(record)
    return records


def _candidate_keys_for_record(record: dict[str, Any]) -> list[str]:
    values = [
        (
            record.get("source_part_reference") or record.get("part_reference"),
            record.get("source_part_family") or record.get("part_family"),
            record.get("technology"),
        ),
        (
            record.get("source_part_reference") or record.get("part_reference"),
            record.get("source_part_family") or record.get("part_family"),
            None,
        ),
        (
            None,
            record.get("source_part_family")
            or record.get("part_family")
            or record.get("source_part_label"),
            record.get("technology"),
        ),
        (
            None,
            record.get("source_part_family")
            or record.get("part_family")
            or record.get("source_part_label"),
            None,
        ),
    ]
    return list(dict.fromkeys(_mapping_key(*items) for items in values if _mapping_key(*items)))


def _mapping_for_record(
    record: dict[str, Any], mappings: list[Client360MappingRule]
) -> Client360MappingRule | None:
    keys = set(_candidate_keys_for_record(record))
    for mapping in mappings:
        if mapping.normalized_key in keys and mapping.status != "rejected":
            return mapping
    return None


def _ensure_candidate_mapping(
    db: DBSession,
    workspace: Workspace,
    record: dict[str, Any],
    mappings: list[Client360MappingRule],
    *,
    dry_run: bool,
) -> Client360MappingRule | None:
    existing = _mapping_for_record(record, mappings)
    if existing is not None:
        return existing
    payload = {
        "source_part_reference": record.get("source_part_reference")
        or record.get("part_reference"),
        "source_part_label": record.get("source_part_label") or record.get("part_description"),
        "source_part_family": record.get("source_part_family") or record.get("part_family"),
        "technology": record.get("technology"),
        "pdr_family": record.get("pdr_family")
        or record.get("part_family")
        or record.get("source_part_family")
        or record.get("source_part_label"),
        "recommended_quantity": record.get("recommended_quantity"),
        "periodicity_weeks": record.get("periodicity_weeks"),
        "delivery_time_weeks": record.get("delivery_time_weeks"),
        "status": "candidate",
        "confidence": 0.55 if record.get("periodicity_weeks") else 0.35,
        "evidence_refs": record.get("evidence_refs") or [],
        "metadata": {"created_by_engine": True, "source_type": record.get("source_type")},
    }
    if not _mapping_payload_key(payload) or not payload.get("pdr_family"):
        return None
    if dry_run:
        return None
    row = upsert_mapping_rule(db, workspace, None, payload)
    mappings.append(row)
    return row


def _apply_mapping(record: dict[str, Any], mapping: Client360MappingRule | None) -> dict[str, Any]:
    if mapping is None:
        return record
    updates = {
        "pdr_family": mapping.pdr_family,
        "part_family": mapping.pdr_family,
        "mapping_status": mapping.status,
        "mapping_id": mapping.id,
        "recommended_quantity": mapping.recommended_quantity,
        "periodicity_weeks": mapping.periodicity_weeks,
        "delivery_time_weeks": mapping.delivery_time_weeks,
    }
    return _merge_record(record, updates)


def _index_periodicity(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        if not record.get("periodicity_weeks") and not record.get("recommended_quantity"):
            continue
        family = _record_family(record)
        if not family:
            continue
        for key in {_mapping_key(family, record.get("technology")), _mapping_key(family, None)}:
            if key:
                index[key] = _merge_record(index.get(key, {}), record)
    return index


def _index_sales(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("sales_known_qty") is None and record.get("sales_known_value") is None:
            continue
        customer = _record_customer_key(record)
        family = _record_family(record)
        if not family:
            continue
        key = _mapping_key(customer, family, record.get("part_reference"))
        current = index.get(key, {})
        merged = _merge_record(current, record)
        merged["sales_known_qty"] = (
            float(current.get("sales_known_qty") or 0) + float(record.get("sales_known_qty") or 0)
        ) or None
        merged["sales_known_value"] = (
            float(current.get("sales_known_value") or 0)
            + float(record.get("sales_known_value") or 0)
        ) or None
        # Keep the latest purchase date for deterministic due-date forecasts.
        candidates = [
            last_purchase_date_from_record(current),
            last_purchase_date_from_record(record),
        ]
        latest = max((item for item in candidates if item is not None), default=None)
        if latest is not None:
            merged["last_document_date"] = latest.isoformat()
            merged["last_purchase_date"] = latest.isoformat()
        index[key] = merged
    return index


def _sales_for_record(
    record: dict[str, Any], sales_index: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    customer = _record_customer_key(record)
    family = _record_family(record)
    keys = [
        _mapping_key(customer, family, record.get("part_reference")),
        _mapping_key(customer, family, None),
    ]
    for key in keys:
        if key in sales_index:
            return sales_index[key]
    return {}


_MATERIAL_TOKEN_RE = re.compile(r"\b\d{9}\b")


def _index_material_families(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Material reference → part families (family rows embed SAP material
    numbers in ``source_part_label``, e.g. ``"132076556 BEARING BALL …"``)."""
    index: dict[str, set[str]] = {}
    for record in records:
        family = _safe_text(record.get("part_family") or record.get("source_part_family"))
        if not family:
            continue
        materials = set(_MATERIAL_TOKEN_RE.findall(_safe_text(record.get("source_part_label"))))
        part_ref = _safe_text(
            record.get("part_reference") or record.get("source_part_reference")
        )
        if part_ref:
            materials.add(part_ref)
        for material in materials:
            key = _normalize_token(material)
            if key:
                index.setdefault(key, set()).add(family)
    return index


def _index_sales_anchor_dates(
    records: list[dict[str, Any]],
    material_families: dict[str, set[str]],
) -> dict[str, str]:
    """Latest purchase date per customer × family (ISO strings).

    Material-level sales (VA05 ``customer × Material`` aggregates) roll up to
    the family via ``material_families`` so family-level records with a
    periodicity get a real ``last_purchase`` forecast anchor.
    """
    anchors: dict[str, str] = {}
    for record in records:
        if record.get("sales_known_qty") is None and record.get("sales_known_value") is None:
            continue
        latest = last_purchase_date_from_record(record)
        if latest is None:
            continue
        customer = _record_customer_key(record)
        families: set[str] = set()
        explicit = _safe_text(record.get("part_family") or record.get("source_part_family"))
        if explicit:
            families.add(explicit)
        ref_key = _normalize_token(record.get("part_reference"))
        if ref_key:
            families.update(material_families.get(ref_key, ()))
        for family in families:
            key = _mapping_key(customer, family)
            if not key:
                continue
            current = parse_forecast_date(anchors.get(key))
            if current is None or latest > current:
                anchors[key] = latest.isoformat()
    return anchors


def _unit_price_from_value_qty(value: Any, qty: Any) -> Optional[float]:
    known_value = _safe_non_negative_float(value)
    known_qty = _safe_float(qty)
    if known_value is None or known_qty is None or known_qty <= 0:
        return None
    return round(known_value / known_qty, 4)


def _index_pricing(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    family: dict[str, dict[str, float]] = {}
    family_technology: dict[str, dict[str, float]] = {}
    for record in records:
        value = _safe_non_negative_float(record.get("sales_known_value"))
        qty = _safe_float(record.get("sales_known_qty"))
        if value is None or qty is None or qty <= 0:
            continue
        fam = _record_family(record)
        if not fam:
            continue
        family_key = _mapping_key(fam)
        if family_key:
            bucket = family.setdefault(family_key, {"value": 0.0, "qty": 0.0})
            bucket["value"] += value
            bucket["qty"] += qty
        family_tech_key = _mapping_key(fam, record.get("technology"))
        if family_tech_key:
            bucket = family_technology.setdefault(family_tech_key, {"value": 0.0, "qty": 0.0})
            bucket["value"] += value
            bucket["qty"] += qty
    return {"family": family, "family_technology": family_technology}


def _index_reference_prices(
    records: list[dict[str, Any]],
    material_families: dict[str, set[str]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Explicit listed prices ("Net Price" column) by reference and by family.

    Unlike the value÷qty ratios of :func:`_index_pricing`, these come from an
    explicit unit-price column, so no minimum-sample guard applies.

    - ``by_ref``: qty-weighted average of ``sales_unit_price`` per material.
    - ``by_family``: park-mix price — each family is valued at the average of
      its member references' explicit prices weighted by the *installed*
      quantities (a family gap is a park-replacement need, so the park mix,
      not the sales mix, is the honest weighting). Family membership comes
      from ``material_families`` plus the record's own family when present.
    """
    by_ref: dict[str, dict[str, float]] = {}
    for record in records:
        price = _safe_non_negative_float(record.get("sales_unit_price"))
        ref_key = _normalize_token(record.get("part_reference"))
        if price is None or price <= 0 or not ref_key:
            continue
        weight = _safe_non_negative_float(record.get("sales_known_qty")) or 1.0
        bucket = by_ref.setdefault(ref_key, {"value": 0.0, "qty": 0.0})
        bucket["value"] += price * weight
        bucket["qty"] += weight

    by_family: dict[str, dict[str, float]] = {}
    for record in records:
        installed = _safe_non_negative_float(record.get("installed_quantity"))
        ref_key = _normalize_token(record.get("part_reference"))
        if not installed or installed <= 0 or not ref_key:
            continue
        ref_price = _bucket_unit_price(by_ref.get(ref_key))
        if ref_price is None:
            continue
        families = set(material_families.get(ref_key) or ())
        own_family = _record_family(record)
        if own_family:
            families.add(own_family)
        for family in families:
            family_key = _mapping_key(family)
            if not family_key:
                continue
            bucket = by_family.setdefault(family_key, {"value": 0.0, "qty": 0.0})
            bucket["value"] += ref_price * installed
            bucket["qty"] += installed

    return {"by_ref": by_ref, "by_family": by_family}


def _is_purchase_history_record(record: dict[str, Any]) -> bool:
    role = _normalize_token(record.get("role"))
    if role == "purchase history" or role == "purchase_history":
        return True
    if _safe_non_negative_float(record.get("unit_cost")) is None:
        return False
    # unit_cost alone is enough when the feed stamped purchase fields without sales.
    return (
        record.get("sales_known_qty") is None
        and record.get("sales_known_value") is None
        and bool(_safe_text(record.get("part_reference")))
    )


def _index_purchase_costs(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Average purchase unit_cost by part_reference and part_family (never sales)."""
    by_ref_buckets: dict[str, dict[str, float]] = {}
    by_family_buckets: dict[str, dict[str, float]] = {}
    for record in records:
        if not _is_purchase_history_record(record):
            continue
        cost = _safe_non_negative_float(record.get("unit_cost"))
        if cost is None or cost <= 0:
            continue
        ref_key = _normalize_token(record.get("part_reference"))
        if ref_key:
            bucket = by_ref_buckets.setdefault(ref_key, {"value": 0.0, "qty": 0.0})
            bucket["value"] += cost
            bucket["qty"] += 1.0
        family = _record_family(record)
        family_key = _mapping_key(family)
        if family_key:
            bucket = by_family_buckets.setdefault(family_key, {"value": 0.0, "qty": 0.0})
            bucket["value"] += cost
            bucket["qty"] += 1.0
    return {
        "by_part_reference": {
            key: round(bucket["value"] / bucket["qty"], 4)
            for key, bucket in by_ref_buckets.items()
            if bucket["qty"] > 0
        },
        "by_family": {
            key: round(bucket["value"] / bucket["qty"], 4)
            for key, bucket in by_family_buckets.items()
            if bucket["qty"] > 0
        },
    }


def _index_purchase_lead_times(records: list[dict[str, Any]]) -> dict[str, float]:
    """Median delivery_time_weeks by part_reference from purchase history rows."""
    by_ref: dict[str, list[float]] = {}
    for record in records:
        if not _is_purchase_history_record(record):
            continue
        lead = _safe_float(record.get("delivery_time_weeks"))
        ref_key = _normalize_token(record.get("part_reference"))
        if lead is None or lead <= 0 or not ref_key:
            continue
        by_ref.setdefault(ref_key, []).append(lead)
    return {key: float(statistics.median(values)) for key, values in by_ref.items()}


def _bucket_unit_price(bucket: dict[str, float] | None) -> Optional[float]:
    if not bucket or bucket.get("qty", 0.0) <= 0:
        return None
    return round(float(bucket["value"]) / float(bucket["qty"]), 4)


def _estimate_unit_price(
    record: dict[str, Any], pricing_index: dict[str, Any]
) -> tuple[Optional[float], dict[str, Any]]:
    currency = _safe_text(record.get("currency")) or None
    role = _normalize_token(record.get("role"))
    if role not in {"purchase_history", "purchase history"}:
        installed_base_purchase = _safe_non_negative_float(record.get("purchase_unit_price"))
        if installed_base_purchase is None and record.get("source_type") == "installed_base":
            installed_base_purchase = _safe_non_negative_float(record.get("unit_cost"))
        if installed_base_purchase is not None:
            return installed_base_purchase, {
                "source": "installed_base_purchase_price",
                "unit_price": installed_base_purchase,
                "currency": currency,
            }

    # Explicit listed prices (VA05 "Net Price") — trusted without a sample
    # threshold because they are prices, not derived value÷qty ratios.
    reference_index = _as_dict(pricing_index.get("reference_sales"))
    ref_key = _normalize_token(record.get("part_reference"))
    if ref_key:
        ref_bucket = _as_dict(_as_dict(reference_index.get("by_ref")).get(ref_key))
        ref_price = _bucket_unit_price(ref_bucket)
        if ref_price is not None:
            return ref_price, {
                "source": "reference_sales_price",
                "unit_price": ref_price,
                "currency": currency,
                "bucket_qty": _safe_float(ref_bucket.get("qty")),
            }
    record_family = _record_family(record)
    family_mix_bucket = _as_dict(
        _as_dict(reference_index.get("by_family")).get(_mapping_key(record_family))
    )
    family_mix_price = _bucket_unit_price(family_mix_bucket)
    if family_mix_price is not None:
        return family_mix_price, {
            "source": "family_installed_mix_price",
            "unit_price": family_mix_price,
            "currency": currency,
            "bucket_qty": _safe_float(family_mix_bucket.get("qty")),
        }

    direct = _unit_price_from_value_qty(
        record.get("sales_known_value"), record.get("sales_known_qty")
    )
    direct_qty = _safe_float(record.get("sales_known_qty"))
    if direct is not None and direct_qty is not None and direct_qty >= PRICING_MIN_SAMPLE_QTY:
        return direct, {
            "source": "direct",
            "unit_price": direct,
            "currency": currency,
            "sales_known_value": _safe_non_negative_float(record.get("sales_known_value")),
            "sales_known_qty": direct_qty,
        }
    family = record_family
    family_tech_index = _as_dict(pricing_index.get("family_technology"))
    family_tech_bucket = _as_dict(
        family_tech_index.get(_mapping_key(family, record.get("technology")))
    )
    family_tech_price = _bucket_unit_price(family_tech_bucket)
    if (
        family_tech_price is not None
        and float(family_tech_bucket.get("qty") or 0.0) >= PRICING_MIN_SAMPLE_QTY
    ):
        return family_tech_price, {
            "source": "family_technology_average",
            "unit_price": family_tech_price,
            "currency": currency,
            "bucket_qty": _safe_float(family_tech_bucket.get("qty")),
        }

    family_index = _as_dict(pricing_index.get("family"))
    family_bucket = _as_dict(family_index.get(_mapping_key(family)))
    family_price = _bucket_unit_price(family_bucket)
    if family_price is not None and float(family_bucket.get("qty") or 0.0) >= PRICING_MIN_SAMPLE_QTY:
        return family_price, {
            "source": "family_average",
            "unit_price": family_price,
            "currency": currency,
            "bucket_qty": _safe_float(family_bucket.get("qty")),
        }
    purchase_index = _as_dict(pricing_index.get("purchase_cost"))
    by_ref = _as_dict(purchase_index.get("by_part_reference"))
    ref_key = _normalize_token(record.get("part_reference"))
    purchase_price = _safe_non_negative_float(by_ref.get(ref_key)) if ref_key else None
    if purchase_price is None:
        by_family = _as_dict(purchase_index.get("by_family"))
        purchase_price = _safe_non_negative_float(by_family.get(_mapping_key(family)))
    if purchase_price is not None:
        return purchase_price, {
            "source": "purchase_cost_average",
            "unit_price": purchase_price,
            "currency": currency,
        }
    return None, {"source": None, "unit_price": None, "currency": currency}


def _addressable_factor(
    weights: dict[str, Any],
    *,
    hub_present: bool,
    has_purchase_history: bool,
    conversion_rate: float,
) -> float:
    factor = float(weights.get("base", CLIENT360_ADDRESSABLE_WEIGHTS["base"]))
    if hub_present:
        factor += float(weights.get("hub_present", CLIENT360_ADDRESSABLE_WEIGHTS["hub_present"]))
    if has_purchase_history:
        factor += float(
            weights.get(
                "existing_purchase_history",
                CLIENT360_ADDRESSABLE_WEIGHTS["existing_purchase_history"],
            )
        )
    factor += float(
        weights.get("observed_conversion", CLIENT360_ADDRESSABLE_WEIGHTS["observed_conversion"])
    ) * max(0.0, min(1.0, conversion_rate))
    return round(max(0.0, min(1.0, factor)), 4)


def _observed_conversion_rate(db: DBSession, workspace: Workspace) -> float:
    counts: dict[str, int] = {}
    for (impact_type,) in (
        db.query(Client360ImpactEvent.impact_type)
        .filter(Client360ImpactEvent.workspace_id == workspace.id)
        .all()
    ):
        counts[impact_type] = counts.get(impact_type, 0) + 1
    orders = counts.get("order", 0)
    signals = (
        orders
        + counts.get("lost", 0)
        + counts.get("response", 0)
        + counts.get("quote", 0)
        + counts.get("no_response", 0)
    )
    if signals <= 0:
        return 0.0
    return round(orders / signals, 4)


def _opportunity_unit_price(
    opportunity: Client360Opportunity,
) -> tuple[Optional[float], str | None]:
    pricing = _as_dict(_as_dict(opportunity.meta_data).get("pricing"))
    stored = _safe_non_negative_float(pricing.get("unit_price"))
    if stored is not None:
        return stored, _safe_text(pricing.get("source")) or "meta_data"
    # Same sample guard as the engine cascade: a value÷qty ratio derived from a
    # couple of invoice lines must not resurface at read time after the engine
    # refused to price the record.
    direct_qty = _safe_float(opportunity.sales_known_qty)
    if direct_qty is not None and direct_qty >= PRICING_MIN_SAMPLE_QTY:
        direct = _unit_price_from_value_qty(
            opportunity.sales_known_value, opportunity.sales_known_qty
        )
        if direct is not None:
            return direct, "direct"
    return None, None


def _build_opportunity_payload(
    record: dict[str, Any],
    scope: dict[str, Any],
    *,
    pricing_index: dict[str, Any] | None = None,
    conversion_rate: float = 0.0,
) -> tuple[dict[str, Any] | None, str | None]:
    customer_name = _safe_text(record.get("customer_name") or record.get("customer_key"))
    family = _record_family(record)
    if not customer_name:
        return None, "customer_missing"
    if not family:
        return None, "part_family_missing"
    skip = _scope_skip_reason(record, scope)
    if skip:
        return None, skip
    annual = calculate_annual_theoretical_qty(
        installed_quantity=record.get("installed_quantity"),
        recommended_quantity=record.get("recommended_quantity"),
        periodicity_weeks=record.get("periodicity_weeks"),
    )
    sales_qty = _safe_non_negative_float(record.get("sales_known_qty"))
    gap_qty = (
        max(round(float(annual) - float(sales_qty or 0), 4), 0)
        if annual is not None and sales_qty is not None
        else None
    )
    unit_price, pricing_meta = _estimate_unit_price(record, _as_dict(pricing_index))
    gap_value = (
        round(gap_qty * unit_price, 2) if gap_qty is not None and unit_price is not None else None
    )
    weights = _as_dict(scope.get("addressable_weights")) or dict(CLIENT360_ADDRESSABLE_WEIGHTS)
    hub_present = bool(_safe_text(record.get("hub")))
    has_purchase_history = _safe_float(record.get("sales_known_qty")) is not None
    factor = _addressable_factor(
        weights,
        hub_present=hub_present,
        has_purchase_history=has_purchase_history,
        conversion_rate=conversion_rate,
    )
    addressable = round(gap_qty * factor, 4) if gap_qty is not None else None
    next_due = None
    if record.get("next_due_at"):
        try:
            next_due = _parse_datetime(record.get("next_due_at"))
        except Exception:  # noqa: BLE001
            next_due = None
    opportunity = Client360Opportunity(
        workspace_id="",
        customer_key=_record_customer_key(record),
        customer_name=customer_name,
        site_name=_safe_text(record.get("site_name")) or None,
        country=_canonical_country(record.get("country")) or _safe_text(record.get("country")) or None,
        hub=_safe_text(record.get("hub")) or None,
        technology=_safe_text(record.get("technology")) or None,
        line_label=_safe_text(record.get("line_label")) or None,
        machine_label=_safe_text(record.get("machine_label")) or None,
        part_family=family,
        part_reference=_safe_text(
            record.get("part_reference") or record.get("source_part_reference")
        )
        or None,
        part_description=_safe_text(
            record.get("part_description") or record.get("source_part_label")
        )
        or None,
        installed_quantity=_safe_float(record.get("installed_quantity")),
        recommended_quantity=_safe_float(record.get("recommended_quantity")),
        periodicity_weeks=_safe_float(record.get("periodicity_weeks")),
        delivery_time_weeks=_safe_float(record.get("delivery_time_weeks")),
        annual_theoretical_qty=annual,
        potential_theoretical=annual,
        potential_addressable=addressable,
        potential_gap_qty=gap_qty,
        potential_gap_value=gap_value,
        sales_known_qty=sales_qty,
        sales_known_value=_safe_non_negative_float(record.get("sales_known_value")),
        currency=_safe_text(record.get("currency")) or pricing_meta.get("currency"),
        next_due_at=next_due,
        data_gaps=[],
        evidence_refs=_as_list(record.get("evidence_refs")),
        source_ids=_as_list(record.get("source_ids")),
        meta_data={
            "engine": "client360_pdr_opportunity_engine",
            "engine_key": _mapping_key(
                _record_customer_key(record),
                family,
                record.get("part_reference"),
                record.get("line_label"),
            ),
            "mapping_id": record.get("mapping_id"),
            "mapping_status": record.get("mapping_status"),
            "contact": {
                "name": record.get("contact_name"),
                "email": record.get("contact_email"),
                "hub": record.get("hub"),
            },
            "pricing": pricing_meta,
            "addressable_factors": {
                "weights": weights,
                "hub_present": hub_present,
                "existing_purchase_history": has_purchase_history,
                "observed_conversion_rate": round(max(0.0, min(1.0, conversion_rate)), 4),
                "factor": factor,
                "gap_qty": gap_qty,
            },
            "scope": scope,
        },
    )
    forecast_meta = _as_dict(_as_dict(record.get("meta_data")).get("forecast"))
    if forecast_meta:
        opportunity.meta_data["forecast"] = forecast_meta
    opportunity.data_gaps = opportunity_data_gaps(opportunity)
    score, label, reasons = score_opportunity_details(opportunity)
    opportunity.confidence_score = score
    opportunity.confidence_label = label
    opportunity.score_reasons = reasons
    opportunity.recommended_action = recommended_action_for(opportunity)
    return {
        "customer_key": opportunity.customer_key,
        "customer_name": opportunity.customer_name,
        "site_name": opportunity.site_name,
        "country": opportunity.country,
        "hub": opportunity.hub,
        "technology": opportunity.technology,
        "line_label": opportunity.line_label,
        "machine_label": opportunity.machine_label,
        "part_family": opportunity.part_family,
        "part_reference": opportunity.part_reference,
        "part_description": opportunity.part_description,
        "installed_quantity": opportunity.installed_quantity,
        "recommended_quantity": opportunity.recommended_quantity,
        "periodicity_weeks": opportunity.periodicity_weeks,
        "delivery_time_weeks": opportunity.delivery_time_weeks,
        "annual_theoretical_qty": opportunity.annual_theoretical_qty,
        "potential_theoretical": opportunity.potential_theoretical,
        "potential_addressable": opportunity.potential_addressable,
        "potential_gap_qty": opportunity.potential_gap_qty,
        "potential_gap_value": opportunity.potential_gap_value,
        "sales_known_qty": opportunity.sales_known_qty,
        "sales_known_value": opportunity.sales_known_value,
        "currency": opportunity.currency,
        "next_due_at": opportunity.next_due_at,
        "confidence_score": opportunity.confidence_score,
        "confidence_label": opportunity.confidence_label,
        "score_reasons": opportunity.score_reasons,
        "recommended_action": opportunity.recommended_action,
        "data_gaps": opportunity.data_gaps,
        "evidence_refs": opportunity.evidence_refs,
        "source_ids": opportunity.source_ids,
        "meta_data": opportunity.meta_data,
    }, None


def run_opportunity_engine(
    db: DBSession,
    workspace: Workspace,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    scope = client360_scope(workspace)
    records = _records_from_data_sources(db, workspace) + _records_from_table_facts(db, workspace)
    mappings = (
        db.query(Client360MappingRule)
        .filter(Client360MappingRule.workspace_id == workspace.id)
        .all()
    )
    mapping_count_before = len(mappings)
    mapped_records: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    for record in records:
        mapping = _ensure_candidate_mapping(db, workspace, record, mappings, dry_run=dry_run)
        mapped_records.append(_apply_mapping(record, mapping))

    periodicity_index = _index_periodicity(mapped_records)
    sales_index = _index_sales(mapped_records)
    material_family_index = _index_material_families(mapped_records)
    sales_anchor_index = _index_sales_anchor_dates(mapped_records, material_family_index)
    pricing_index = _index_pricing(mapped_records)
    purchase_cost_index = _index_purchase_costs(mapped_records)
    purchase_lead_index = _index_purchase_lead_times(mapped_records)
    pricing_index["purchase_cost"] = purchase_cost_index
    pricing_index["reference_sales"] = _index_reference_prices(
        mapped_records, material_family_index
    )
    conversion_rate = _observed_conversion_rate(db, workspace)
    opportunity_records: list[dict[str, Any]] = []
    for record in mapped_records:
        family = _record_family(record)
        if family:
            periodicity = (
                periodicity_index.get(_mapping_key(family, record.get("technology")))
                or periodicity_index.get(_mapping_key(family, None))
                or {}
            )
            record = _merge_record(record, periodicity)
            record = _merge_record(record, _sales_for_record(record, sales_index))
            if last_purchase_date_from_record(record) is None:
                anchor = sales_anchor_index.get(
                    _mapping_key(_record_customer_key(record), family)
                )
                if anchor:
                    record["last_purchase_date"] = anchor
        if record.get("delivery_time_weeks") is None:
            ref_key = _normalize_token(record.get("part_reference"))
            lead = purchase_lead_index.get(ref_key) if ref_key else None
            if lead is not None:
                record = _merge_record(record, {"delivery_time_weeks": lead})
        if not any(
            record.get(key) is not None
            for key in (
                "installed_quantity",
                "recommended_quantity",
                "periodicity_weeks",
                "sales_known_qty",
                "sales_known_value",
            )
        ):
            continue
        if record.get("installed_quantity") is None:
            skipped["installed_quantity_missing_for_generation"] = (
                skipped.get("installed_quantity_missing_for_generation", 0) + 1
            )
            continue
        record = apply_next_due_to_record(record)
        payload, reason = _build_opportunity_payload(
            record,
            scope,
            pricing_index=pricing_index,
            conversion_rate=conversion_rate,
        )
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        if payload:
            opportunity_records.append(payload)

    by_key: dict[str, dict[str, Any]] = {}
    for payload in opportunity_records:
        key = _as_dict(payload.get("meta_data")).get("engine_key") or _mapping_key(
            payload.get("customer_key"),
            payload.get("part_family"),
            payload.get("part_reference"),
            payload.get("line_label"),
        )
        by_key[key] = _merge_record(by_key.get(key, {}), payload)

    created = 0
    updated = 0
    purged_obsolete_customer_keys = 0
    preview: list[dict[str, Any]] = []
    if not dry_run:
        existing_rows = (
            db.query(Client360Opportunity)
            .filter(Client360Opportunity.workspace_id == workspace.id)
            .all()
        )
        for existing in existing_rows:
            expected_key = normalize_customer_key(existing.customer_name)
            current_key = _safe_text(existing.customer_key)
            if expected_key and current_key and expected_key != current_key:
                db.delete(existing)
                purged_obsolete_customer_keys += 1
        if purged_obsolete_customer_keys:
            db.flush()
    for payload in by_key.values():
        preview.append(payload)
        if dry_run:
            continue
        existing = (
            db.query(Client360Opportunity)
            .filter(
                Client360Opportunity.workspace_id == workspace.id,
                Client360Opportunity.customer_key == payload["customer_key"],
                Client360Opportunity.part_family == payload["part_family"],
                Client360Opportunity.part_reference == payload.get("part_reference"),
                Client360Opportunity.line_label == payload.get("line_label"),
            )
            .first()
        )
        if existing is None:
            existing = Client360Opportunity(
                id=str(uuid4()), workspace_id=workspace.id, status="detected"
            )
            db.add(existing)
            created += 1
        else:
            updated += 1
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
    if not dry_run:
        db.flush()
    return {
        "engine": "client360_pdr_opportunity_engine",
        "dry_run": dry_run,
        "scope": scope,
        "records_seen": len(records),
        "candidate_mappings_created": max(len(mappings) - mapping_count_before, 0),
        "opportunities_detected": len(by_key),
        "created": created,
        "updated": updated,
        "purged_obsolete_customer_keys": purged_obsolete_customer_keys,
        "skipped": skipped,
        "preview": [
            serialize_opportunity(Client360Opportunity(workspace_id=workspace.id, **payload))
            for payload in preview[:25]
        ],
    }


def _get_opportunity(
    db: DBSession, workspace: Workspace, opportunity_id: str
) -> Client360Opportunity:
    row = (
        db.query(Client360Opportunity)
        .filter(
            Client360Opportunity.id == opportunity_id,
            Client360Opportunity.workspace_id == workspace.id,
        )
        .first()
    )
    if not row:
        raise LookupError("Client360 opportunity not found")
    return row


def patch_opportunity(
    db: DBSession,
    workspace: Workspace,
    opportunity_id: str,
    patch: dict[str, Any],
) -> Client360Opportunity:
    opportunity = _get_opportunity(db, workspace, opportunity_id)
    status = patch.get("status")
    if status is not None:
        if status not in CLIENT360_OPPORTUNITY_STATUSES:
            raise ValueError("Invalid Client360 opportunity status")
        opportunity.status = status
    metadata = _as_dict(opportunity.meta_data)
    loop = _as_dict(metadata.get("learning_loop"))
    for key in ("validation_reason", "rejection_reason", "notes", "owner_label"):
        if patch.get(key) is not None:
            loop[key] = patch[key]
    if loop:
        metadata["learning_loop"] = loop
        opportunity.meta_data = metadata
    opportunity.updated_at = datetime.utcnow()
    db.flush()
    return opportunity


def _mail_subject(opportunity: Client360Opportunity) -> str:
    family = opportunity.part_family or "pieces d'usure"
    return f"Maintenance preventive - {family} - {opportunity.customer_name}"


def _mail_body(opportunity: Client360Opportunity, *, include_prices: bool = False) -> str:
    opp = serialize_opportunity(opportunity)
    lines = [
        "Bonjour,",
        "",
        "Dans le cadre du suivi maintenance de votre installation, nous avons identifie un point de vigilance sur les pieces d'usure suivantes :",
        f"- Famille / piece : {opp['part_family']}",
    ]
    if opp.get("part_reference"):
        lines.append(f"- Reference : {opp['part_reference']}")
    if opp.get("technology") or opp.get("line_label") or opp.get("machine_label"):
        scope = " / ".join(
            str(v)
            for v in [opp.get("technology"), opp.get("line_label"), opp.get("machine_label")]
            if v
        )
        lines.append(f"- Perimetre : {scope}")
    if opp.get("periodicity_weeks"):
        lines.append(
            f"- Periodicite constructeur connue : toutes les {opp['periodicity_weeks']:g} semaines"
        )
    if opp.get("delivery_time_weeks"):
        lines.append(f"- Delai indicatif de livraison : {opp['delivery_time_weeks']:g} semaines")
    if opp.get("next_due_at"):
        lines.append(f"- Echeance estimee : {opp['next_due_at'][:10]}")
    if opp.get("annual_theoretical_qty"):
        lines.append(
            f"- Besoin annuel theorique estime : {opp['annual_theoretical_qty']:g} unite(s) / an"
        )
    if opp.get("potential_gap_qty") is not None:
        lines.append(f"- Ecart potentiel vs achats connus : {opp['potential_gap_qty']:g} unite(s)")
    if include_prices and opp.get("sales_known_value"):
        lines.append(
            f"- Historique d'achat connu chez ANDRITZ : {opp['sales_known_value']:g} {opp.get('currency') or ''}".strip()
        )
    lines.extend(
        [
            "",
            "L'objectif n'est pas de pousser une remise, mais d'anticiper les risques d'arret, de degradation qualite ou de perte de productivite lies a l'usure.",
            "Nous pouvons vous proposer un point court pour verifier le bon calendrier de remplacement, regrouper les besoins de l'annee ou preparer une inspection si necessaire.",
            "",
            "Souhaitez-vous que nous regardions ensemble les pieces a securiser sur cette installation ?",
            "",
            "Cordialement,",
        ]
    )
    return "\n".join(lines)


_CLIENT360_MAIL_SYSTEM_PROMPT = """Tu es l'assistant commercial technique ANDRITZ pour Client360 PDR.
Tu rediges un brouillon d'email B2B en francais, oriente maintenance, disponibilite,
qualite et productivite. Le commercial humain validera et enverra manuellement.

Contraintes strictes:
- N'invente aucun client, contact, prix, delai, reference, date ou stock.
- Utilise uniquement les donnees structurees fournies.
- Si une donnee est absente, n'en fais pas une affirmation.
- Ne promets pas de remise ni de stock automatique.
- Mentionne l'incertitude avec tact quand un gap de donnees bloque la conclusion.
- Le ton doit etre expert, sobre, utile, non promotionnel.
- Retourne strictement un objet JSON: {"subject": "...", "body": "..."}.
"""


def _resolve_client360_mail_system_prompt(workspace: Workspace) -> tuple[str, str]:
    """Return (effective_prompt, source) where source is default|workspace."""
    override = _safe_text(_client360_mail_settings(workspace).get("system_prompt"))
    if override:
        return override, "workspace"
    return _CLIENT360_MAIL_SYSTEM_PROMPT, "default"


def _client360_mail_ai_config(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    workspace_settings = _as_dict(getattr(workspace, "settings", None))
    configured = _as_dict(workspace_settings.get("client360_pdr_mail"))
    system = _find_client360_system(db, workspace)
    system_settings = _as_dict(system.settings if system else None)
    system_mail = _as_dict(system_settings.get("client360_pdr_mail"))
    system_llm = _as_dict(system_settings.get("llm") or system_settings.get("model_routing"))
    resolved = get_resolved_settings(
        workspace_id=workspace.id,
        capability_id=system.capability_id if system else None,
        system_id=system.id if system else None,
    )

    enabled, enabled_source = _pick_config_value(
        ("workspace.settings.client360_pdr_mail.ai_enabled", configured.get("ai_enabled")),
        ("system.settings.client360_pdr_mail.ai_enabled", system_mail.get("ai_enabled")),
        ("global.client360_mail_ai_enabled", settings.client360_mail_ai_enabled),
    )
    provider_value, provider_source = _pick_config_value(
        ("workspace.settings.client360_pdr_mail.provider", configured.get("provider")),
        ("system.settings.client360_pdr_mail.provider", system_mail.get("provider")),
        ("system.settings.llm.provider", system_llm.get("provider")),
        (
            "agentium.resolved.defaultProvider",
            _resolved_setting(resolved, "defaultProvider", "default_provider"),
        ),
        ("global.default_provider", settings.default_provider),
        ("fallback.openai", "openai"),
    )
    model_value, model_source = _pick_config_value(
        ("workspace.settings.client360_pdr_mail.model", configured.get("model")),
        ("system.settings.client360_pdr_mail.model", system_mail.get("model")),
        ("system.default_model", system.default_model if system else None),
        ("system.settings.llm.model", system_llm.get("model")),
        (
            "agentium.resolved.defaultModel",
            _resolved_setting(resolved, "defaultModel", "default_model"),
        ),
        ("global.client360_mail_model", settings.client360_mail_model),
        ("global.default_model", settings.default_model),
        ("fallback.gpt-4o-mini", "gpt-4o-mini"),
    )
    provider, model = _split_provider_model(provider_value, model_value)
    if not provider:
        provider = _safe_text(settings.default_provider).lower() or "openai"
    if not model:
        model = _safe_text(settings.client360_mail_model or settings.default_model) or "gpt-4o-mini"
    timeout_value, timeout_source = _pick_config_value(
        (
            "workspace.settings.client360_pdr_mail.timeout_seconds",
            configured.get("timeout_seconds"),
        ),
        ("system.settings.client360_pdr_mail.timeout_seconds", system_mail.get("timeout_seconds")),
        ("global.client360_mail_timeout_seconds", settings.client360_mail_timeout_seconds),
    )
    return {
        "enabled": bool(enabled),
        "provider": provider,
        "model": model,
        "timeout_seconds": float(timeout_value or 20.0),
        "enabled_source": enabled_source,
        "provider_source": provider_source,
        "model_source": model_source,
        "timeout_source": timeout_source,
        "routing_source": "agentium_system" if system else "workspace_or_global",
        "system_id": system.id if system else None,
        "capability_id": system.capability_id if system else None,
        "agent_route": CLIENT360_AGENT_ROUTING_CONTRACT["mail_draft"]["route_id"],
    }


CLIENT360_SMTP_ENV_MASTER_KEY = "CLIENT360_SMTP_FERNET_KEY"
CLIENT360_SMTP_ENV_MASTER_KEY_FALLBACK = "HANA_CONNECTOR_FERNET_KEY"
_SMTP_ENVELOPE_VERSION = 1


def _smtp_env_master_key() -> str:
    return (
        os.environ.get(CLIENT360_SMTP_ENV_MASTER_KEY)
        or os.environ.get(CLIENT360_SMTP_ENV_MASTER_KEY_FALLBACK)
        or ""
    ).strip()


def _smtp_fernet_from_env():
    raw = _smtp_env_master_key()
    if not raw:
        return None
    import base64

    try:
        key = raw.encode("ascii")
        if len(base64.urlsafe_b64decode(key)) != 32:
            raise ValueError("expected 32 bytes after base64 decode")
    except Exception as exc:
        raise ValueError(
            f"{CLIENT360_SMTP_ENV_MASTER_KEY} is not a valid urlsafe base64 Fernet key: {exc}"
        ) from exc
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    raw_master = base64.urlsafe_b64decode(key)
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"client360_smtp:v1",
        info=b"client360_smtp",
    ).derive(raw_master)
    return Fernet(base64.urlsafe_b64encode(derived))


def _encrypt_smtp_password(plaintext: str) -> str:
    import base64

    payload = plaintext.encode("utf-8")
    fernet = _smtp_fernet_from_env()
    if fernet is None:
        _logger.warning(
            "%s not set; persisting Client360 SMTP password in PLAINTEXT. "
            "Set %s or %s to a urlsafe-base64 Fernet key before going to production.",
            CLIENT360_SMTP_ENV_MASTER_KEY,
            CLIENT360_SMTP_ENV_MASTER_KEY,
            CLIENT360_SMTP_ENV_MASTER_KEY_FALLBACK,
        )
        return json.dumps(
            {
                "v": _SMTP_ENVELOPE_VERSION,
                "plaintext": base64.b64encode(payload).decode("ascii"),
            }
        )
    return json.dumps(
        {
            "v": _SMTP_ENVELOPE_VERSION,
            "ciphertext": fernet.encrypt(payload).decode("ascii"),
        }
    )


def _decrypt_smtp_password(blob: str) -> str:
    import base64

    if not blob:
        return ""
    try:
        envelope = json.loads(blob)
    except Exception:
        return blob
    if not isinstance(envelope, dict) or "v" not in envelope:
        return blob
    if "plaintext" in envelope:
        return base64.b64decode(envelope["plaintext"]).decode("utf-8")
    if "ciphertext" in envelope:
        fernet = _smtp_fernet_from_env()
        if fernet is None:
            raise ValueError(
                f"{CLIENT360_SMTP_ENV_MASTER_KEY} required to decrypt but is not set."
            )
        return fernet.decrypt(envelope["ciphertext"].encode("ascii")).decode("utf-8")
    raise ValueError(f"Unknown SMTP password envelope keys={sorted(envelope)}")


def _smtp_stored_password(smtp: dict[str, Any]) -> str:
    blob = smtp.get("password_encrypted")
    if blob:
        return _decrypt_smtp_password(str(blob))
    return _safe_text(smtp.get("password"))


def reencrypt_workspace_smtp_password(settings: Any) -> tuple[dict[str, Any], bool]:
    """Move a leftover SMTP password into ``password_encrypted`` and seal it."""
    current = dict(settings) if isinstance(settings, dict) else {}
    mail = dict(_as_dict(current.get("client360_pdr_mail")))
    smtp = dict(_as_dict(mail.get("smtp")))
    if not smtp:
        return current, False
    blob = str(smtp.get("password_encrypted") or "")
    leftover = _safe_text(smtp.get("password"))
    changed = False
    if leftover:
        smtp["password_encrypted"] = _encrypt_smtp_password(leftover)
        smtp.pop("password", None)
        changed = True
    elif blob and _smtp_env_master_key():
        try:
            envelope = json.loads(blob)
        except Exception:
            envelope = {}
        if isinstance(envelope, dict) and "plaintext" in envelope:
            token = _decrypt_smtp_password(blob)
            if token:
                smtp["password_encrypted"] = _encrypt_smtp_password(token)
                changed = True
    if not changed:
        return current, False
    mail["smtp"] = smtp
    current["client360_pdr_mail"] = mail
    return current, True


def _client360_mail_settings(workspace: Workspace) -> dict[str, Any]:
    workspace_settings = _as_dict(getattr(workspace, "settings", None))
    return _as_dict(workspace_settings.get("client360_pdr_mail"))


def _client360_smtp_settings(workspace: Workspace) -> dict[str, Any]:
    return _as_dict(_client360_mail_settings(workspace).get("smtp"))


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _safe_text(value).lower() in {"1", "true", "yes", "on", "enabled"}


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _password_from_env(env_var: Any) -> str:
    key = _safe_text(env_var)
    if not key:
        return ""
    return os.environ.get(key, "")


def _resolve_client360_smtp_config(
    workspace: Workspace,
) -> tuple[SmtpDeliveryConfig | None, str | None, dict[str, Any]]:
    smtp = _client360_smtp_settings(workspace)
    if smtp:
        if not _safe_bool(smtp.get("enabled"), True):
            return None, "smtp_disabled", smtp
        password = _smtp_stored_password(smtp) or _password_from_env(
            smtp.get("password_env_var")
        )
        cfg = SmtpDeliveryConfig(
            host=_safe_text(smtp.get("host")),
            port=_safe_int(smtp.get("port"), 465),
            username=_safe_text(smtp.get("username") or smtp.get("user")),
            password=password,
            from_email=_safe_text(smtp.get("from_email"))
            or _safe_text(smtp.get("username") or smtp.get("user")),
            from_name=_safe_text(smtp.get("from_name")) or "ANDRITZ Service",
            use_ssl=_safe_bool(smtp.get("ssl"), True),
            use_starttls=_safe_bool(smtp.get("starttls"), False),
            timeout_seconds=float(smtp.get("timeout_seconds") or 15.0),
        )
        missing = [
            key
            for key, value in (
                ("host", cfg.host),
                ("username", cfg.username),
                ("password", cfg.password),
            )
            if not value
        ]
        return (None, f"smtp_{missing[0]}_missing", smtp) if missing else (cfg, None, smtp)

    cfg = SmtpDeliveryConfig(
        host=settings.smtp_host or "",
        port=settings.smtp_port,
        username=settings.smtp_user or "",
        password=settings.smtp_password or "",
        from_email=settings.smtp_from or settings.smtp_user or "",
        from_name=settings.smtp_from_name,
        use_ssl=settings.smtp_ssl,
        use_starttls=not settings.smtp_ssl,
    )
    missing = [
        key
        for key, value in (
            ("host", cfg.host),
            ("username", cfg.username),
            ("password", cfg.password),
        )
        if not value
    ]
    return (None, f"global_smtp_{missing[0]}_missing", {}) if missing else (cfg, None, {})


def client360_mail_settings_payload(workspace: Workspace) -> dict[str, Any]:
    smtp = _client360_smtp_settings(workspace)
    cfg, disabled_reason, _raw = _resolve_client360_smtp_config(workspace)
    password_configured = bool(
        _smtp_stored_password(smtp) or _password_from_env(smtp.get("password_env_var"))
    )
    if not smtp:
        password_configured = bool(settings.smtp_password)
    system_prompt, system_prompt_source = _resolve_client360_mail_system_prompt(workspace)
    return {
        "enabled": _safe_bool(smtp.get("enabled"), bool(cfg)) if smtp else bool(cfg),
        "configured": cfg is not None and not disabled_reason,
        "disabled_reason": disabled_reason,
        "source": "workspace.settings.client360_pdr_mail.smtp" if smtp else "global.smtp",
        "host": _safe_text(smtp.get("host")) or settings.smtp_host or "",
        "port": _safe_int(smtp.get("port"), settings.smtp_port),
        "username": _safe_text(smtp.get("username") or smtp.get("user"))
        or settings.smtp_user
        or "",
        "from_email": _safe_text(smtp.get("from_email"))
        or settings.smtp_from
        or settings.smtp_user
        or "",
        "from_name": _safe_text(smtp.get("from_name")) or settings.smtp_from_name,
        "ssl": _safe_bool(smtp.get("ssl"), settings.smtp_ssl if smtp else settings.smtp_ssl),
        "starttls": _safe_bool(smtp.get("starttls"), False if smtp else not settings.smtp_ssl),
        "password_configured": password_configured,
        "password_env_var": _safe_text(smtp.get("password_env_var")),
        "system_prompt": system_prompt,
        "system_prompt_source": system_prompt_source,
        "prompt_version": CLIENT360_MAIL_PROMPT_VERSION,
    }


def patch_client360_mail_settings(
    db: DBSession,
    workspace: Workspace,
    patch: dict[str, Any],
) -> dict[str, Any]:
    workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    workspace_settings = dict(getattr(workspace, "settings", None) or {})
    mail_settings = dict(_as_dict(workspace_settings.get("client360_pdr_mail")))
    smtp = dict(_as_dict(mail_settings.get("smtp")))
    allowed = {
        "enabled",
        "host",
        "port",
        "username",
        "from_email",
        "from_name",
        "ssl",
        "starttls",
        "timeout_seconds",
        "password_env_var",
    }
    for key in allowed:
        if key in patch and patch[key] is not None:
            smtp[key] = patch[key]
    if patch.get("password_encrypted") is not None:
        raise ValueError("password_encrypted is write-only; set password")
    password = _safe_text(patch.get("password"))
    if password:
        smtp["password_encrypted"] = _encrypt_smtp_password(password)
        smtp.pop("password", None)
    elif patch.get("clear_password"):
        smtp.pop("password", None)
        smtp.pop("password_encrypted", None)
    if "port" in smtp:
        smtp["port"] = _safe_int(smtp.get("port"), 465)
    if "enabled" in smtp:
        smtp["enabled"] = _safe_bool(smtp.get("enabled"), True)
    if "ssl" in smtp:
        smtp["ssl"] = _safe_bool(smtp.get("ssl"), True)
    if "starttls" in smtp:
        smtp["starttls"] = _safe_bool(smtp.get("starttls"), False)
    mail_settings["smtp"] = smtp
    if _safe_bool(patch.get("reset_system_prompt"), False):
        mail_settings.pop("system_prompt", None)
    elif "system_prompt" in patch and patch.get("system_prompt") is not None:
        prompt = _safe_text(patch.get("system_prompt"))
        if not prompt:
            raise ValueError("system_prompt cannot be empty; use reset_system_prompt to restore default")
        mail_settings["system_prompt"] = prompt
    workspace_settings["client360_pdr_mail"] = mail_settings
    workspace.settings = workspace_settings
    return client360_mail_settings_payload(workspace)


def _mail_ai_configured(config: dict[str, Any]) -> tuple[bool, str | None]:
    if not config.get("enabled"):
        return False, "ai_disabled"
    provider = _safe_text(config.get("provider")).lower()
    if provider == "openai" and not _safe_text(settings.openai_api_key):
        return False, "openai_api_key_missing"
    return True, None


def _mail_prompt_payload(
    opportunity: Client360Opportunity, *, include_prices: bool
) -> dict[str, Any]:
    opp = serialize_opportunity(opportunity)
    selected = {
        key: opp.get(key)
        for key in (
            "customer_name",
            "country",
            "hub",
            "technology",
            "line_label",
            "machine_label",
            "part_family",
            "part_reference",
            "part_description",
            "installed_quantity",
            "recommended_quantity",
            "periodicity_weeks",
            "delivery_time_weeks",
            "annual_theoretical_qty",
            "potential_gap_qty",
            "sales_known_qty",
            "sales_known_value",
            "currency",
            "next_due_at",
            "confidence_label",
            "recommended_action",
            "data_gaps",
            "evidence_refs",
        )
    }
    if not include_prices:
        selected.pop("sales_known_value", None)
        selected.pop("currency", None)
    return {
        "task": "generate_human_validated_spare_parts_email_draft",
        "language": "fr",
        "include_prices": include_prices,
        "opportunity": selected,
        "business_rules": {
            "scope": "Client360 PDR spare parts wear parts only",
            "automatic_send": False,
            "supervised_prediction": False,
            "email_goal": "Proposer un echange technique ou une inspection, pas pousser une remise.",
        },
    }


def _mail_user_prompt(payload: dict[str, Any]) -> str:
    return (
        "Redige un brouillon d'email pour le commercial ANDRITZ a partir de ce JSON.\n"
        "Le body doit etre directement editable/envoyable apres validation humaine.\n"
        "Ne retourne ni markdown, ni commentaire hors JSON.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def _prompt_hash(system_prompt: str, user_prompt: str) -> str:
    return hashlib.sha256(f"{system_prompt}\n\n{user_prompt}".encode("utf-8")).hexdigest()


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _parse_ai_mail_json(text: str) -> dict[str, str] | None:
    cleaned = _strip_code_fence(text)
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        subject = _safe_text(payload.get("subject"))
        body = _safe_text(payload.get("body"))
        if body:
            return {"subject": subject, "body": body}
    if len(cleaned) >= 80:
        return {"subject": "", "body": cleaned}
    return None


def _safe_mail_subject(value: Any, fallback: str) -> str:
    subject = re.sub(r"\s+", " ", _safe_text(value)).strip()
    if not subject:
        subject = fallback
    return subject[:240]


async def _complete_client360_mail_ai(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    workspace: Workspace,
) -> str:
    from app.llm.llm import LLM

    provider_key = _safe_text(provider).lower() or "openai"
    api_key = settings.openai_api_key if provider_key == "openai" else None
    llm = LLM(provider=provider_key, api_key=api_key)
    return await llm.complete(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=0.2,
        max_tokens=900,
        user=f"workspace:{workspace.id}:client360_pdr_mail",
    )


async def _generate_ai_mail_draft(
    workspace: Workspace,
    opportunity: Client360Opportunity,
    *,
    include_prices: bool,
    config: dict[str, Any],
) -> dict[str, Any]:
    payload = _mail_prompt_payload(opportunity, include_prices=include_prices)
    user_prompt = _mail_user_prompt(payload)
    system_prompt, system_prompt_source = _resolve_client360_mail_system_prompt(workspace)
    prompt_hash = _prompt_hash(system_prompt, user_prompt)
    raw = await asyncio.wait_for(
        _complete_client360_mail_ai(
            provider=str(config["provider"]),
            model=str(config["model"]),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            workspace=workspace,
        ),
        timeout=float(config["timeout_seconds"]),
    )
    parsed = _parse_ai_mail_json(raw)
    if parsed is None:
        raise ValueError("Client360 mail AI returned an unparsable draft")
    fallback_subject = _mail_subject(opportunity)
    return {
        "subject": _safe_mail_subject(parsed.get("subject"), fallback_subject),
        "body": _safe_text(parsed.get("body")),
        "metadata": {
            "generation_mode": "ai_assisted",
            "llm_provider": config["provider"],
            "llm_model": config["model"],
            "llm_model_source": config.get("model_source"),
            "llm_provider_source": config.get("provider_source"),
            "llm_routing_source": config.get("routing_source"),
            "llm_system_id": config.get("system_id"),
            "llm_capability_id": config.get("capability_id"),
            "agent_route": config.get("agent_route"),
            "prompt_version": CLIENT360_MAIL_PROMPT_VERSION,
            "prompt_hash": prompt_hash,
            "system_prompt_source": system_prompt_source,
            "human_validation_required": True,
        },
    }


def _fallback_mail_generation(
    opportunity: Client360Opportunity, *, include_prices: bool, reason: str | None = None
) -> dict[str, Any]:
    metadata = {
        "generation_mode": "deterministic_template",
        "human_validation_required": True,
    }
    if reason:
        metadata["fallback_reason"] = reason
    return {
        "subject": _mail_subject(opportunity),
        "body": _mail_body(opportunity, include_prices=include_prices),
        "metadata": metadata,
    }


def _generate_mail_draft_content(
    db: DBSession,
    workspace: Workspace,
    opportunity: Client360Opportunity,
    *,
    include_prices: bool,
) -> dict[str, Any]:
    config = _client360_mail_ai_config(db, workspace)
    configured, reason = _mail_ai_configured(config)
    if not configured:
        return _fallback_mail_generation(opportunity, include_prices=include_prices, reason=reason)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(
                _generate_ai_mail_draft(
                    workspace,
                    opportunity,
                    include_prices=include_prices,
                    config=config,
                )
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Client360 AI mail generation failed; using deterministic fallback", exc_info=True
            )
            return _fallback_mail_generation(
                opportunity, include_prices=include_prices, reason=type(exc).__name__
            )

    _logger.warning("Client360 AI mail generation skipped inside running event loop")
    return _fallback_mail_generation(
        opportunity, include_prices=include_prices, reason="running_event_loop"
    )


def serialize_mail_draft(row: Client360MailDraft) -> dict[str, Any]:
    return {
        "id": row.id,
        "opportunity_id": row.opportunity_id,
        "action_item_id": row.action_item_id,
        "campaign_id": row.campaign_id,
        "subject": row.subject,
        "generated_body": row.generated_body,
        "sent_body": row.sent_body,
        "language": row.language,
        "status": row.status,
        "metadata": row.meta_data or {},
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    }


def create_mail_draft(
    db: DBSession,
    workspace: Workspace,
    user: User,
    *,
    opportunity_id: str,
    language: str = "fr",
    include_prices: bool = False,
) -> tuple[Client360MailDraft, WorkspaceActionItem]:
    opportunity = _get_opportunity(db, workspace, opportunity_id)
    generation = _generate_mail_draft_content(
        db, workspace, opportunity, include_prices=include_prices
    )
    generation_metadata = dict(generation.get("metadata") or {})
    opportunity_metadata = _as_dict(opportunity.meta_data)
    if opportunity_metadata.get("pilot_dataset"):
        generation_metadata["pilot_dataset"] = opportunity_metadata["pilot_dataset"]
    draft = Client360MailDraft(
        id=str(uuid4()),
        workspace_id=workspace.id,
        opportunity_id=opportunity.id,
        subject=_safe_mail_subject(generation.get("subject"), _mail_subject(opportunity)),
        generated_body=_safe_text(generation.get("body"))
        or _mail_body(opportunity, include_prices=include_prices),
        language=language or "fr",
        status="draft_generated",
        meta_data={
            "include_prices": include_prices,
            "human_validation_required": True,
            **generation_metadata,
        },
        created_by_user_id=user.id,
    )
    db.add(draft)
    db.flush()
    action = create_action_item(
        db,
        workspace,
        user,
        title=f"Valider mail Client360 PDR - {opportunity.customer_name}",
        description=f"Brouillon genere pour {opportunity.part_family}. Envoi manuel uniquement apres validation commerciale.",
        target_kind="client360_pdr_opportunity",
        target_id=opportunity.id,
        target_label=opportunity.customer_name,
        priority="high" if (opportunity.confidence_label == "high") else "medium",
        owner_label="Spare Parts Sales",
        source_kind="client360_pdr",
        source_id=draft.id,
        confidence=opportunity.confidence_label or "medium",
        metadata={
            "client360": {
                "opportunity_id": opportunity.id,
                "mail_draft_id": draft.id,
                "part_family": opportunity.part_family,
                "generation_mode": draft.meta_data.get("generation_mode"),
                "llm_provider": draft.meta_data.get("llm_provider"),
                "llm_model": draft.meta_data.get("llm_model"),
                "agent_route": draft.meta_data.get("agent_route"),
                "manual_send_only": True,
            }
        },
    )
    draft.action_item_id = action.id
    opportunity.status = "draft_generated"
    db.flush()
    return draft, action


def _valid_email(value: Any) -> str:
    raw = _safe_text(value)
    name, address = parseaddr(raw)
    if not address or "@" not in address or address.count("@") != 1:
        raise ValueError("Invalid recipient email")
    local, domain = address.rsplit("@", 1)
    if not local or "." not in domain:
        raise ValueError("Invalid recipient email")
    return address


def _plain_text_to_html(text: str) -> str:
    escaped = html.escape(text or "")
    return "<br/>".join(escaped.splitlines())


def send_mail_draft(
    db: DBSession,
    workspace: Workspace,
    user: User,
    *,
    draft_id: str,
    to_email: str,
    subject: str | None = None,
    body: str | None = None,
) -> tuple[Client360MailDraft, WorkspaceActionItem | None]:
    draft = (
        db.query(Client360MailDraft)
        .filter(Client360MailDraft.id == draft_id, Client360MailDraft.workspace_id == workspace.id)
        .first()
    )
    if not draft:
        raise LookupError("Client360 mail draft not found")
    recipient = _valid_email(to_email)
    cfg, disabled_reason, _raw = _resolve_client360_smtp_config(workspace)
    if cfg is None:
        raise ValueError(disabled_reason or "smtp_not_configured")
    send_subject = _safe_mail_subject(subject, draft.subject)
    send_body = _safe_text(body) or _safe_text(draft.sent_body) or draft.generated_body
    sent = send_email_with_config(
        config=cfg,
        to=recipient,
        subject=send_subject,
        html=_plain_text_to_html(send_body),
        text=send_body,
    )
    if not sent:
        raise RuntimeError("smtp_send_failed")

    now = datetime.utcnow()
    draft.subject = send_subject
    draft.sent_body = send_body
    draft.status = "sent"
    draft.sent_at = now
    draft.updated_at = now
    metadata = dict(draft.meta_data or {})
    metadata["smtp_delivery"] = {
        "to_email": recipient,
        "sent_at": now.isoformat(),
        "source": "workspace.settings.client360_pdr_mail.smtp",
        "host": cfg.host,
        "username": cfg.username,
    }
    draft.meta_data = metadata

    action: WorkspaceActionItem | None = None
    if draft.action_item_id:
        action = patch_action(
            db,
            workspace,
            user,
            draft.action_item_id,
            {
                "mail_draft_id": draft.id,
                "mail_status": "sent",
                "status": "in_progress",
                "sent_body": send_body,
                "sent_at": now,
                "notes": f"Email envoye via SMTP a {recipient}",
            },
        )
    else:
        opportunity = _get_opportunity(db, workspace, draft.opportunity_id)
        opportunity.status = "sent"
    db.flush()
    return draft, action


def patch_action(
    db: DBSession,
    workspace: Workspace,
    user: User,
    action_id: str,
    patch: dict[str, Any],
) -> WorkspaceActionItem:
    action = (
        db.query(WorkspaceActionItem)
        .filter(
            WorkspaceActionItem.id == action_id, WorkspaceActionItem.workspace_id == workspace.id
        )
        .first()
    )
    if not action:
        raise LookupError("Client360 action not found")
    metadata = dict(action.meta_data or {})
    client360 = dict(metadata.get("client360") or {})
    for key in ("mail_status", "notes", "outcome_status", "sent_at"):
        if key in patch and patch[key] is not None:
            value = patch[key]
            client360[key] = value.isoformat() if isinstance(value, datetime) else value
    metadata["client360"] = client360
    updates: dict[str, Any] = {"metadata": metadata}
    if patch.get("status"):
        updates["status"] = patch["status"]
    if patch.get("priority"):
        updates["priority"] = patch["priority"]
    if patch.get("owner_label"):
        updates["owner_label"] = patch["owner_label"]
    action = update_action_item(db, workspace, user, action_id, updates)

    draft_id = patch.get("mail_draft_id") or client360.get("mail_draft_id")
    if draft_id:
        draft = (
            db.query(Client360MailDraft)
            .filter(
                Client360MailDraft.id == draft_id, Client360MailDraft.workspace_id == workspace.id
            )
            .first()
        )
        if draft:
            if patch.get("sent_body") is not None:
                draft.sent_body = str(patch["sent_body"])
            if patch.get("mail_status") in CLIENT360_MAIL_STATUSES:
                draft.status = patch["mail_status"]
            if patch.get("sent_at"):
                draft.sent_at = _parse_datetime(patch.get("sent_at"))
            elif draft.status == "sent" and draft.sent_at is None:
                draft.sent_at = datetime.utcnow()
            draft.updated_at = datetime.utcnow()
            opportunity = _get_opportunity(db, workspace, draft.opportunity_id)
            if draft.status == "sent":
                opportunity.status = "sent"
    db.flush()
    return action


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def serialize_impact_event(row: Client360ImpactEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "opportunity_id": row.opportunity_id,
        "action_item_id": row.action_item_id,
        "mail_draft_id": row.mail_draft_id,
        "campaign_id": row.campaign_id,
        "impact_type": row.impact_type,
        "attribution": row.attribution,
        "reason": row.reason,
        "summary": row.summary,
        "quote_value": row.quote_value,
        "order_value": row.order_value,
        "currency": row.currency,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "metadata": row.meta_data or {},
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def record_impact(
    db: DBSession,
    workspace: Workspace,
    user: User,
    action_id: str,
    *,
    impact_type: str,
    attribution: str = "unknown",
    reason: str = "unknown",
    summary: str = "",
    opportunity_id: str | None = None,
    mail_draft_id: str | None = None,
    quote_value: float | None = None,
    order_value: float | None = None,
    currency: str | None = None,
    occurred_at: Any = None,
    metadata: dict[str, Any] | None = None,
) -> Client360ImpactEvent:
    if impact_type not in CLIENT360_IMPACT_TYPES:
        raise ValueError("Invalid Client360 impact type")
    if attribution not in CLIENT360_ATTRIBUTIONS:
        raise ValueError("Invalid Client360 attribution")
    if reason not in CLIENT360_OUTCOME_REASONS:
        raise ValueError("Invalid Client360 outcome reason")
    action = (
        db.query(WorkspaceActionItem)
        .filter(
            WorkspaceActionItem.id == action_id, WorkspaceActionItem.workspace_id == workspace.id
        )
        .first()
    )
    if not action:
        raise LookupError("Client360 action not found")
    client360_meta = _as_dict(_as_dict(action.meta_data).get("client360"))
    resolved_opportunity_id = opportunity_id or client360_meta.get("opportunity_id")
    resolved_draft_id = mail_draft_id or client360_meta.get("mail_draft_id")
    resolved_campaign_id = None
    if resolved_draft_id:
        draft_row = (
            db.query(Client360MailDraft)
            .filter(
                Client360MailDraft.id == resolved_draft_id,
                Client360MailDraft.workspace_id == workspace.id,
            )
            .first()
        )
        if draft_row is not None:
            resolved_campaign_id = draft_row.campaign_id
    event = Client360ImpactEvent(
        id=str(uuid4()),
        workspace_id=workspace.id,
        opportunity_id=resolved_opportunity_id,
        action_item_id=action.id,
        mail_draft_id=resolved_draft_id,
        campaign_id=resolved_campaign_id,
        impact_type=impact_type,
        attribution=attribution,
        reason=reason,
        summary=summary or "",
        quote_value=quote_value,
        order_value=order_value,
        currency=currency,
        occurred_at=_parse_datetime(occurred_at) or datetime.utcnow(),
        meta_data=metadata or {},
        created_by_user_id=user.id,
    )
    db.add(event)
    if resolved_opportunity_id:
        opportunity = _get_opportunity(db, workspace, resolved_opportunity_id)
        next_status = {
            "response": "responded",
            "quote": "quote_requested",
            "order": "won",
            "lost": "lost",
        }.get(impact_type)
        if next_status in CLIENT360_OPPORTUNITY_STATUSES:
            opportunity.status = next_status
    if impact_type in {"order", "lost"}:
        update_action_item(db, workspace, user, action.id, {"status": "completed"})
    db.flush()
    return event


def opportunity_facets(db: DBSession, workspace: Workspace) -> dict[str, list[str]]:
    rows = (
        db.query(
            Client360Opportunity.country,
            Client360Opportunity.hub,
            Client360Opportunity.technology,
            Client360Opportunity.part_family,
            Client360Opportunity.status,
            Client360Opportunity.confidence_label,
        )
        .filter(Client360Opportunity.workspace_id == workspace.id)
        .all()
    )
    result: dict[str, set[str]] = {
        "countries": set(),
        "hubs": set(),
        "technologies": set(),
        "part_families": set(),
        "statuses": set(),
        "confidence_labels": set(),
    }
    for country, hub, technology, part_family, status, confidence in rows:
        if country:
            result["countries"].add(_canonical_country(country) or country)
        if hub:
            result["hubs"].add(hub)
        if technology:
            result["technologies"].add(technology)
        if part_family:
            result["part_families"].add(part_family)
        if status:
            result["statuses"].add(status)
        if confidence:
            result["confidence_labels"].add(confidence)
    return {key: sorted(value) for key, value in result.items()}


# ---------------------------------------------------------------------------
# Campaign entity and transformation tracking (spec §5).
#
# A campaign selects opportunities from the same filters as ``list_opportunities``,
# de-duplicates customers already engaged in another active campaign or without a
# contact email, then generates human-validated mail drafts in batch. Impact
# events attached to those drafts feed the transformation stats. No email is ever
# sent automatically: the contract ``no_automatic_email_send`` still holds.
# ---------------------------------------------------------------------------

CAMPAIGN_SELECTION_KEYS = (
    "status",
    "customer",
    "country",
    "hub",
    "technology",
    "part_family",
    "confidence",
    "limit",
)
# Explicit targeting keys (annuaire multi-selection / next-due window). Kept
# separate from CAMPAIGN_SELECTION_KEYS so the chat filter allow-list — which
# mirrors the ``list_opportunities`` parameters — stays unchanged.
CAMPAIGN_TARGETING_MAX_CUSTOMERS = 200
_CAMPAIGN_RESPONDED_STATUSES = {"responded", "quote_requested", "won", "lost", "dismissed"}


def _campaign_customer_keys(criteria: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for value in _as_list(criteria.get("customer_keys")):
        text = _safe_text(value)
        normalized = _customer_key_for(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        keys.append(text)
    return keys[:CAMPAIGN_TARGETING_MAX_CUSTOMERS]


def _campaign_selection_filters(criteria: Any) -> dict[str, Any]:
    data = _as_dict(criteria)
    out: dict[str, Any] = {}
    for key in CAMPAIGN_SELECTION_KEYS:
        value = data.get(key)
        if value is None or value == "":
            continue
        out[key] = _safe_int(value, 100) if key == "limit" else _safe_text(value)
    customer_keys = _campaign_customer_keys(data)
    if customer_keys:
        out["customer_keys"] = customer_keys
    due_within_weeks = _safe_int(data.get("due_within_weeks"), 0)
    if due_within_weeks > 0:
        out["due_within_weeks"] = due_within_weeks
    return out


def _campaign_target_opportunities(
    db: DBSession,
    workspace: Workspace,
    criteria: Any,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Resolve campaign targets.

    An explicit ``customer_keys`` selection (annuaire / fiche next-due) resolves
    to those customers' opportunities; otherwise the historical opportunity
    filters apply. ``due_within_weeks`` further restricts targets to
    opportunities whose deterministic ``next_due_at`` falls before the window.
    """
    selection = _campaign_selection_filters(criteria)
    customer_keys = selection.pop("customer_keys", [])
    due_within_weeks = selection.pop("due_within_weeks", None)
    if customer_keys:
        limit = _safe_int(selection.pop("limit", 0), 0) or None
        pool = list_opportunities(db, workspace, **{**selection, "limit": 500})
        wanted = {_customer_key_for(key) for key in customer_keys}
        items = [
            item
            for item in pool
            if _customer_key_for(item.get("customer_key") or item.get("customer_name")) in wanted
        ]
        if limit:
            items = items[:limit]
    else:
        items = list_opportunities(db, workspace, **selection)
    if due_within_weeks:
        horizon = (now or datetime.utcnow()) + timedelta(weeks=int(due_within_weeks))
        filtered: list[dict[str, Any]] = []
        for item in items:
            due = parse_forecast_date(item.get("next_due_at"))
            if due is not None and due <= horizon:
                filtered.append(item)
        items = filtered
    return items


def serialize_campaign(row: Client360Campaign) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "campaign_type": row.campaign_type,
        "status": row.status,
        "description": row.description,
        "selection_criteria": row.selection_criteria or {},
        "targeted_count": row.targeted_count,
        "drafts_count": row.drafts_count,
        "metadata": row.meta_data or {},
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_campaigns(
    db: DBSession,
    workspace: Workspace,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = db.query(Client360Campaign).filter(Client360Campaign.workspace_id == workspace.id)
    if status:
        query = query.filter(Client360Campaign.status == status)
    rows = query.order_by(Client360Campaign.created_at.desc()).limit(max(1, min(limit, 500))).all()
    return [serialize_campaign(row) for row in rows]


def _get_campaign(db: DBSession, workspace: Workspace, campaign_id: str) -> Client360Campaign:
    row = (
        db.query(Client360Campaign)
        .filter(Client360Campaign.id == campaign_id, Client360Campaign.workspace_id == workspace.id)
        .first()
    )
    if not row:
        raise LookupError("Client360 campaign not found")
    return row


def create_campaign(
    db: DBSession,
    workspace: Workspace,
    user: User | None,
    *,
    name: str,
    campaign_type: str,
    selection_criteria: dict[str, Any] | None = None,
    description: str = "",
    status: str = "draft",
    metadata: dict[str, Any] | None = None,
) -> Client360Campaign:
    clean_name = _safe_text(name)
    if not clean_name:
        raise ValueError("Campaign name is required")
    if campaign_type not in CLIENT360_CAMPAIGN_TYPES:
        raise ValueError("Invalid Client360 campaign type")
    if status not in CLIENT360_CAMPAIGN_STATUSES:
        raise ValueError("Invalid Client360 campaign status")
    row = Client360Campaign(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=clean_name,
        campaign_type=campaign_type,
        status=status,
        description=_safe_text(description),
        selection_criteria=_campaign_selection_filters(selection_criteria),
        targeted_count=0,
        drafts_count=0,
        meta_data=_as_dict(metadata),
        created_by_user_id=user.id if user else None,
    )
    db.add(row)
    db.flush()
    return row


def patch_campaign(
    db: DBSession,
    workspace: Workspace,
    campaign_id: str,
    patch: dict[str, Any],
) -> Client360Campaign:
    campaign = _get_campaign(db, workspace, campaign_id)
    if patch.get("name") is not None:
        clean_name = _safe_text(patch["name"])
        if not clean_name:
            raise ValueError("Campaign name is required")
        campaign.name = clean_name
    if patch.get("campaign_type") is not None:
        if patch["campaign_type"] not in CLIENT360_CAMPAIGN_TYPES:
            raise ValueError("Invalid Client360 campaign type")
        campaign.campaign_type = patch["campaign_type"]
    if patch.get("status") is not None:
        if patch["status"] not in CLIENT360_CAMPAIGN_STATUSES:
            raise ValueError("Invalid Client360 campaign status")
        campaign.status = patch["status"]
    if patch.get("description") is not None:
        campaign.description = _safe_text(patch["description"])
    if patch.get("selection_criteria") is not None:
        campaign.selection_criteria = _campaign_selection_filters(patch["selection_criteria"])
    campaign.updated_at = datetime.utcnow()
    db.flush()
    return campaign


def _serialized_contact_email(item: dict[str, Any]) -> str:
    contact = _as_dict(_as_dict(item.get("metadata")).get("contact"))
    return _safe_text(contact.get("email"))


def _customers_in_active_campaigns(
    db: DBSession,
    workspace: Workspace,
    *,
    exclude_campaign_id: str | None = None,
) -> set[str]:
    active_ids = [
        cid
        for (cid,) in db.query(Client360Campaign.id)
        .filter(
            Client360Campaign.workspace_id == workspace.id,
            Client360Campaign.status.in_(CLIENT360_CAMPAIGN_ACTIVE_STATUSES),
        )
        .all()
        if cid and cid != exclude_campaign_id
    ]
    if not active_ids:
        return set()
    rows = (
        db.query(Client360Opportunity.customer_key)
        .join(Client360MailDraft, Client360MailDraft.opportunity_id == Client360Opportunity.id)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.campaign_id.in_(active_ids),
        )
        .all()
    )
    return {customer_key for (customer_key,) in rows if customer_key}


def _customers_with_campaign_drafts(
    db: DBSession, workspace: Workspace, campaign_id: str
) -> set[str]:
    rows = (
        db.query(Client360Opportunity.customer_key)
        .join(Client360MailDraft, Client360MailDraft.opportunity_id == Client360Opportunity.id)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.campaign_id == campaign_id,
        )
        .all()
    )
    return {customer_key for (customer_key,) in rows if customer_key}


def _attach_campaign_to_draft(
    draft: Client360MailDraft, campaign_id: str, *, extra: dict[str, Any] | None = None
) -> None:
    draft.campaign_id = campaign_id
    metadata = dict(draft.meta_data or {})
    metadata["campaign_id"] = campaign_id
    if extra:
        metadata.update(extra)
    draft.meta_data = metadata


def generate_campaign_drafts(
    db: DBSession,
    workspace: Workspace,
    user: User,
    campaign_id: str,
    *,
    language: str = "fr",
    include_prices: bool = False,
    limit: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    campaign = _get_campaign(db, workspace, campaign_id)
    items = _campaign_target_opportunities(db, workspace, campaign.selection_criteria, now=now)

    engaged = _customers_in_active_campaigns(db, workspace, exclude_campaign_id=campaign.id)
    already_drafted = _customers_with_campaign_drafts(db, workspace, campaign.id)
    max_new = _safe_int(limit, 0) if limit is not None else None

    created: list[Client360MailDraft] = []
    skipped: dict[str, int] = {}
    seen_customers: set[str] = set()

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for item in items:
        customer_key = _safe_text(item.get("customer_key"))
        if customer_key and (customer_key in already_drafted or customer_key in seen_customers):
            _skip("already_in_campaign")
            continue
        if customer_key and customer_key in engaged:
            _skip("active_campaign_conflict")
            continue
        if not _serialized_contact_email(item):
            _skip("missing_contact_email")
            continue
        if max_new is not None and len(created) >= max_new:
            break
        draft, _action = create_mail_draft(
            db,
            workspace,
            user,
            opportunity_id=item["id"],
            language=language,
            include_prices=include_prices,
        )
        _attach_campaign_to_draft(draft, campaign.id)
        if customer_key:
            seen_customers.add(customer_key)
        created.append(draft)

    db.flush()
    campaign.targeted_count = len(
        {_safe_text(item.get("customer_key")) for item in items if item.get("customer_key")}
    )
    campaign.drafts_count = (
        db.query(Client360MailDraft)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.campaign_id == campaign.id,
        )
        .count()
    )
    if created and campaign.status in ("draft", "in_review"):
        campaign.status = "active"
    campaign.updated_at = datetime.utcnow()
    db.flush()
    return {
        "campaign": serialize_campaign(campaign),
        "created": len(created),
        "skipped": skipped,
        "drafts": [serialize_mail_draft(draft) for draft in created],
    }


def prepare_campaign_follow_ups(
    db: DBSession,
    workspace: Workspace,
    user: User,
    campaign_id: str,
    *,
    language: str = "fr",
    include_prices: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    from app.services.client360_alerts import alert_thresholds

    campaign = _get_campaign(db, workspace, campaign_id)
    current_time = now or datetime.utcnow()
    no_response_days = int(alert_thresholds(workspace)["no_response_days"])

    sent_drafts = (
        db.query(Client360MailDraft)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.campaign_id == campaign.id,
            Client360MailDraft.status == "sent",
        )
        .all()
    )

    prepared: list[Client360MailDraft] = []
    skipped: dict[str, int] = {}

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    already_followed_up = {
        _safe_text(_as_dict(draft.meta_data).get("follow_up_of"))
        for draft in db.query(Client360MailDraft)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.campaign_id == campaign.id,
        )
        .all()
        if _as_dict(draft.meta_data).get("follow_up_of")
    }

    for draft in sent_drafts:
        if draft.sent_at is None:
            _skip("missing_sent_at")
            continue
        if draft.id in already_followed_up:
            _skip("follow_up_already_prepared")
            continue
        days_since = (current_time - draft.sent_at).days
        if days_since < no_response_days:
            _skip("not_due_yet")
            continue
        opportunity = _get_opportunity(db, workspace, draft.opportunity_id)
        if opportunity.status in _CAMPAIGN_RESPONDED_STATUSES:
            _skip("already_responded")
            continue
        follow_up, _action = create_mail_draft(
            db,
            workspace,
            user,
            opportunity_id=draft.opportunity_id,
            language=language,
            include_prices=include_prices,
        )
        _attach_campaign_to_draft(
            follow_up,
            campaign.id,
            extra={
                "follow_up": True,
                "follow_up_of": draft.id,
                "days_since_sent": days_since,
                "human_validation_required": True,
                "automatic_send": False,
            },
        )
        prepared.append(follow_up)

    db.flush()
    campaign.drafts_count = (
        db.query(Client360MailDraft)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.campaign_id == campaign.id,
        )
        .count()
    )
    campaign.updated_at = datetime.utcnow()
    db.flush()
    return {
        "campaign": serialize_campaign(campaign),
        "prepared": len(prepared),
        "no_response_days": no_response_days,
        "skipped": skipped,
        "drafts": [serialize_mail_draft(draft) for draft in prepared],
    }


def campaign_stats(db: DBSession, workspace: Workspace, campaign_id: str) -> dict[str, Any]:
    campaign = _get_campaign(db, workspace, campaign_id)
    drafts = (
        db.query(Client360MailDraft)
        .filter(
            Client360MailDraft.workspace_id == workspace.id,
            Client360MailDraft.campaign_id == campaign.id,
        )
        .all()
    )
    sent = sum(1 for draft in drafts if draft.status == "sent")

    events = (
        db.query(Client360ImpactEvent)
        .filter(
            Client360ImpactEvent.workspace_id == workspace.id,
            Client360ImpactEvent.campaign_id == campaign.id,
        )
        .all()
    )
    responses = sum(1 for event in events if event.impact_type == "response")
    quotes = sum(1 for event in events if event.impact_type == "quote")
    orders = sum(1 for event in events if event.impact_type == "order")
    won_value = round(
        sum(float(event.order_value or 0) for event in events if event.impact_type == "order"), 2
    )

    items = _campaign_target_opportunities(db, workspace, campaign.selection_criteria)
    potential_gap_value = round(
        sum(float(item.get("potential_gap_value") or 0) for item in items), 2
    )
    targeted_customers = len(
        {_safe_text(item.get("customer_key")) for item in items if item.get("customer_key")}
    )
    impact_counts = {
        "response": responses,
        "quote": quotes,
        "order": orders,
        "lost": sum(1 for event in events if event.impact_type == "lost"),
        "no_response": sum(1 for event in events if event.impact_type == "no_response"),
    }
    expected = campaign_expected_value(items, impact_counts=impact_counts)

    return {
        "campaign": serialize_campaign(campaign),
        "stats": {
            "targeted_opportunities": len(items),
            "targeted_customers": targeted_customers,
            "potential_gap_value": potential_gap_value,
            "expected_value": expected["expected_value"],
            "expected_value_disclaimer": expected["disclaimer"],
            "conversion_proxy": expected["conversion_proxy"],
            "conversion_proxy_source": expected["conversion_proxy_source"],
            "drafts": len(drafts),
            "sent": sent,
            "responses": responses,
            "quotes": quotes,
            "orders": orders,
            "won_value": won_value,
            "currency": "EUR",
        },
    }
