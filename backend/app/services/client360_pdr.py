"""Client360 PDR service layer.

This pre-MVP is intentionally deterministic: it reads real workspace data,
calculates explainable potential when enough fields are present, and records the
commercial workflow that will become future ground truth.
"""
from __future__ import annotations

import re
import unicodedata
import json
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.action_plan import WorkspaceActionItem
from app.models.client360 import (
    CLIENT360_ATTRIBUTIONS,
    CLIENT360_IMPACT_TYPES,
    CLIENT360_MAIL_STATUSES,
    CLIENT360_MAPPING_STATUSES,
    CLIENT360_OPPORTUNITY_STATUSES,
    CLIENT360_OUTCOME_REASONS,
    Client360DataSource,
    Client360ImpactEvent,
    Client360MappingRule,
    Client360MailDraft,
    Client360Opportunity,
)
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.secure_deposit import DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_plans import create_action_item, serialize_action_item, update_action_item


REQUIRED_SOURCE_TYPES = ("installed_base", "periodicity", "sap_sales_history")
PILOT_TECHNOLOGIES = ("JETLACE", "HFR200")
PILOT_COUNTRIES = ("Greece", "Turkey")
PILOT_CUSTOMERS = ("Septona",)
CLIENT360_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "customer_name": ("customer", "client", "customer name", "client name", "account", "sold to", "ship to"),
    "customer_key": ("customer id", "client id", "customer code", "sold to code", "sap customer"),
    "country": ("country", "pays", "market"),
    "hub": ("hub", "region", "sales hub"),
    "technology": ("technology", "technologie", "machine type", "line type", "equipment type"),
    "line_label": ("line", "ligne", "production line"),
    "machine_label": ("machine", "equipment", "asset", "installed machine"),
    "part_family": ("part family", "famille", "famille piece", "wear family", "pdr family"),
    "part_reference": ("part reference", "reference", "material", "material number", "sap material", "part number", "item"),
    "part_description": ("description", "designation", "part description", "material description"),
    "installed_quantity": ("installed quantity", "installed qty", "qty installed", "quantity installed", "base installee", "installed base"),
    "recommended_quantity": ("recommended quantity", "recommended qty", "qty recommended", "quantite recommandee", "quantity per replacement"),
    "periodicity_weeks": ("periodicity weeks", "periodicite semaines", "periodicity", "periodicite", "weeks", "semaines"),
    "delivery_time_weeks": ("delivery time weeks", "lead time weeks", "lead time", "delai", "delai semaines"),
    "sales_known_qty": ("sales qty", "qty sold", "quantity sold", "historique qty", "sales history qty", "sap qty"),
    "sales_known_value": ("sales value", "net sales", "revenue", "turnover", "historique valeur", "sap value"),
    "currency": ("currency", "devise"),
    "next_due_at": ("next due", "echeance", "next replacement", "due date"),
    "contact_name": ("contact", "contact name"),
    "contact_email": ("email", "contact email"),
}


def client360_scope(workspace: Workspace) -> dict[str, Any]:
    configured = _as_dict(_as_dict(getattr(workspace, "settings", None)).get("client360_pdr_scope"))
    return {
        "business_scope": "spare_parts",
        "part_scope": "wear_parts",
        "pilot_technologies": _as_list(configured.get("pilot_technologies")) or list(PILOT_TECHNOLOGIES),
        "pilot_countries": _as_list(configured.get("pilot_countries")) or list(PILOT_COUNTRIES),
        "pilot_customers": _as_list(configured.get("pilot_customers")) or list(PILOT_CUSTOMERS),
        "stock_automation": False,
        "internet_sources_policy": "context_only",
        "live_connectors": {"sap": False, "crm": False, "metris": False, "outlook_send": False},
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


def _field_for_label(label: Any) -> str | None:
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


def _coerce_record_value(field: str, raw_value: Any, numeric_value: Any = None) -> Any:
    if field in {
        "installed_quantity",
        "recommended_quantity",
        "periodicity_weeks",
        "delivery_time_weeks",
    }:
        return _safe_float(numeric_value if numeric_value is not None else raw_value)
    if field in {"sales_known_qty", "sales_known_value"}:
        return _safe_non_negative_float(numeric_value if numeric_value is not None else raw_value)
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
                marker = json.dumps(item, sort_keys=True, default=str) if isinstance(item, dict) else str(item)
                if marker in seen:
                    continue
                seen.add(marker)
                deduped.append(item)
            merged[key] = deduped
    return merged


def _record_customer_key(record: dict[str, Any]) -> str:
    return _safe_text(record.get("customer_key")) or _normalize_token(record.get("customer_name")) or "unknown_customer"


def _record_family(record: dict[str, Any]) -> str:
    return _safe_text(record.get("pdr_family") or record.get("part_family") or record.get("source_part_family") or record.get("part_reference"))


def _scope_skip_reason(record: dict[str, Any], scope: dict[str, Any]) -> str | None:
    text = _normalize_token(
        " ".join(
            _safe_text(record.get(key))
            for key in ("part_family", "part_description", "source_part_family", "source_part_label")
        )
    )
    if any(term in text for term in ("stock", "inventory", "safety stock", "minimum stock")):
        return "stock_automation_out_of_scope"
    if text and not any(term in text for term in ("wear", "usure", "spare", "pdr", "consumable", "belt", "wire", "screen", "seal", "strip", "felt")):
        status = _safe_text(record.get("mapping_status"))
        if status != "validated":
            return "not_confirmed_wear_part"

    technologies = {_normalize_token(item) for item in _as_list(scope.get("pilot_technologies")) if item}
    technology = _normalize_token(record.get("technology"))
    if technology and technologies and not any(token in technology or technology in token for token in technologies):
        return "technology_out_of_pilot_scope"

    countries = {_normalize_token(item) for item in _as_list(scope.get("pilot_countries")) if item}
    customers = {_normalize_token(item) for item in _as_list(scope.get("pilot_customers")) if item}
    country = _normalize_token(record.get("country"))
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


def score_opportunity_details(opportunity: Client360Opportunity) -> tuple[float, str, list[dict[str, Any]]]:
    checks = [
        ("installed_base", 0.2, _safe_float(opportunity.installed_quantity) is not None, "Base installee exploitable"),
        ("periodicity", 0.2, _safe_float(opportunity.periodicity_weeks) is not None, "Periodicite connue"),
        ("recommended_quantity", 0.15, _safe_float(opportunity.recommended_quantity) is not None, "Quantite recommandee connue"),
        ("customer_scope", 0.15, bool(opportunity.customer_name and (opportunity.country or opportunity.hub)), "Client, pays ou hub renseignes"),
        (
            "sap_sales_history",
            0.12,
            _safe_float(opportunity.sales_known_qty) is not None or _safe_float(opportunity.sales_known_value) is not None,
            "Historique SAP disponible",
        ),
        ("due_date", 0.1, opportunity.next_due_at is not None, "Echeance estimee disponible"),
        ("evidence", 0.08, bool(_as_list(opportunity.evidence_refs) or _as_list(opportunity.source_ids)), "Preuves source rattachees"),
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
    if re.search(r"\b(periodicite|periodicity|periodic|wear\s*part|usure)\b", folded):
        return "periodicity"
    if re.search(r"\b(base\s+installee|installed\s+base|installations?|machine\s+base|parc)\b", folded):
        return "installed_base"
    if re.search(r"\b(sap|sales\s+history|historique\s+(vente|ventes)|orders?|commandes?)\b", folded):
        return "sap_sales_history"
    if re.search(r"\b(contact|hub|commercial|account|crm)\b", folded):
        return "contact_hub"
    if re.search(r"\b(nonwovens|sustainable|textile\s+world|met\s+magazine|market\s+signal|veille)\b", folded):
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


def _serialize_knowledge_source(source: KnowledgeCollectionSource, collection: KnowledgeCollection | None) -> dict[str, Any]:
    filename = source.filename or source.normalized_name
    source_type = classify_data_source(" ".join([filename or "", source.source_kind or "", source.extension or ""]))
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


def list_data_sources(db: DBSession, workspace: Workspace) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    rows = (
        db.query(Client360DataSource)
        .filter(Client360DataSource.workspace_id == workspace.id, Client360DataSource.status != "archived")
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

    knowledge_rows = (
        db.query(KnowledgeCollectionSource, KnowledgeCollection)
        .join(KnowledgeCollection, KnowledgeCollection.id == KnowledgeCollectionSource.collection_id)
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
        if item.get("source_type") in REQUIRED_SOURCE_TYPES and item.get("status") in {"ready", "mapped"}
    }
    return [f"{source_type}_missing" for source_type in REQUIRED_SOURCE_TYPES if source_type not in available]


def serialize_opportunity(opportunity: Client360Opportunity) -> dict[str, Any]:
    annual = opportunity.annual_theoretical_qty
    if annual is None:
        annual = calculate_annual_theoretical_qty(
            installed_quantity=opportunity.installed_quantity,
            recommended_quantity=opportunity.recommended_quantity,
            periodicity_weeks=opportunity.periodicity_weeks,
        )
    potential = opportunity.potential_theoretical if opportunity.potential_theoretical is not None else annual
    gap_qty = opportunity.potential_gap_qty
    if gap_qty is None and annual is not None and opportunity.sales_known_qty is not None:
        gap_qty = max(round(float(annual) - float(opportunity.sales_known_qty or 0), 4), 0)
    addressable = opportunity.potential_addressable
    if addressable is None:
        addressable = gap_qty
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
        "potential_gap_value": opportunity.potential_gap_value,
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
        query = query.filter(Client360Opportunity.country == country)
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
            Client360Opportunity.potential_theoretical.desc().nullslast(),
            Client360Opportunity.updated_at.desc(),
        )
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [serialize_opportunity(row) for row in rows]


def summary_payload(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    scope = client360_scope(workspace)
    data_sources = list_data_sources(db, workspace)
    opportunities = list_opportunities(db, workspace, limit=500)
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
    return {
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "positioning": {
            "name": "Client360 PDR",
            "mode": "explainable_potential",
            "no_supervised_prediction": True,
            "no_automatic_email_send": True,
            "scope": scope,
        },
        "summary": {
            "opportunities": len(opportunities),
            "customers": len({item["customer_key"] for item in opportunities}),
            "data_sources": len(data_sources),
            "mapping_rules": db.query(Client360MappingRule).filter(Client360MappingRule.workspace_id == workspace.id).count(),
            "potential_theoretical": round(total_theoretical, 4),
            "potential_gap_qty": round(total_gap, 4),
            "potential_unit": "quantity_per_year",
            "mail_drafts": db.query(Client360MailDraft).filter(Client360MailDraft.workspace_id == workspace.id).count(),
            "impact_events": db.query(Client360ImpactEvent).filter(Client360ImpactEvent.workspace_id == workspace.id).count(),
        },
        "by_status": by_status,
        "by_confidence": by_confidence,
        "source_counts": source_counts,
        "data_gaps": _source_gaps(data_sources),
        "data_sources": data_sources[:100],
    }


def customer_payload(db: DBSession, workspace: Workspace, customer_id: str) -> dict[str, Any]:
    rows = (
        db.query(Client360Opportunity)
        .filter(
            Client360Opportunity.workspace_id == workspace.id,
            (Client360Opportunity.customer_key == customer_id) | (Client360Opportunity.id == customer_id),
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
        .filter(Client360MailDraft.workspace_id == workspace.id, Client360MailDraft.opportunity_id.in_(opportunity_ids or [""]))
        .order_by(Client360MailDraft.created_at.desc())
        .all()
    )
    impacts = (
        db.query(Client360ImpactEvent)
        .filter(Client360ImpactEvent.workspace_id == workspace.id, Client360ImpactEvent.opportunity_id.in_(opportunity_ids or [""]))
        .order_by(Client360ImpactEvent.occurred_at.desc())
        .all()
    )
    customer_name = opportunities[0]["customer_name"] if opportunities else customer_id
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
    return {
        "customer": {
            "id": customer_id,
            "name": customer_name,
            "countries": sorted({item["country"] for item in opportunities if item.get("country")}),
            "hubs": sorted({item["hub"] for item in opportunities if item.get("hub")}),
            "technologies": sorted({item["technology"] for item in opportunities if item.get("technology")}),
        },
        "opportunities": opportunities,
        "mail_drafts": [serialize_mail_draft(row) for row in drafts],
        "impact_events": [serialize_impact_event(row) for row in impacts],
        "market_signals": market_signals,
        "data_gaps": sorted({gap for item in opportunities for gap in item.get("data_gaps", [])}),
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


def list_mapping_rules(db: DBSession, workspace: Workspace, *, status: str | None = None) -> list[dict[str, Any]]:
    query = db.query(Client360MappingRule).filter(Client360MappingRule.workspace_id == workspace.id)
    if status:
        query = query.filter(Client360MappingRule.status == status)
    rows = query.order_by(Client360MappingRule.updated_at.desc()).limit(500).all()
    return [serialize_mapping_rule(row) for row in rows]


def _mapping_payload_key(payload: dict[str, Any]) -> str:
    return _mapping_key(
        payload.get("source_part_reference"),
        payload.get("source_part_family") or payload.get("source_part_label") or payload.get("pdr_family"),
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
    pdr_family = _safe_text(payload.get("pdr_family") or payload.get("source_part_family") or payload.get("source_part_label"))
    if not pdr_family:
        raise ValueError("PDR family is required")
    row = (
        db.query(Client360MappingRule)
        .filter(Client360MappingRule.workspace_id == workspace.id, Client360MappingRule.normalized_key == normalized_key)
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
    row.confidence = float(_safe_float(payload.get("confidence")) or (0.75 if row.status == "validated" else 0.4))
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
        .filter(Client360MappingRule.workspace_id == workspace.id, Client360MappingRule.id == mapping_id)
        .first()
    )
    if row is None:
        raise LookupError("Client360 mapping rule not found")
    payload = serialize_mapping_rule(row)
    payload.update({key: value for key, value in patch.items() if value is not None})
    return upsert_mapping_rule(db, workspace, user, payload)


def _canonicalize_source_record(record: dict[str, Any], *, source_type: str, evidence_refs: list[Any], source_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source_type": source_type, "evidence_refs": evidence_refs, "source_ids": [source_id]}
    for key, value in record.items():
        canonical = key if key in CLIENT360_FIELD_ALIASES else _field_for_label(key)
        if canonical:
            out[canonical] = _coerce_record_value(canonical, value)
        elif key in {"pdr_family", "source_part_reference", "source_part_family", "source_part_label", "contact_name", "contact_email"}:
            out[key] = _safe_text(value) or None
    if not out.get("customer_key") and out.get("customer_name"):
        out["customer_key"] = _normalize_token(out.get("customer_name"))
    if not out.get("source_part_reference") and out.get("part_reference"):
        out["source_part_reference"] = out.get("part_reference")
    if not out.get("source_part_family") and out.get("part_family"):
        out["source_part_family"] = out.get("part_family")
    return out


def _records_from_data_sources(db: DBSession, workspace: Workspace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    rows = (
        db.query(Client360DataSource)
        .filter(Client360DataSource.workspace_id == workspace.id, Client360DataSource.status != "archived")
        .all()
    )
    for source in rows:
        metadata = _as_dict(source.meta_data)
        raw_rows = _as_list(metadata.get("records") or metadata.get("rows") or metadata.get("mapped_rows"))
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            records.append(
                _canonicalize_source_record(
                    raw,
                    source_type=source.source_type,
                    evidence_refs=source.evidence_refs or [{"kind": "client360_data_source", "source_id": source.id, "label": source.label}],
                    source_id=source.id,
                )
            )
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
        key = (fact.collection_slug, fact.document_filename, fact.sheet_name, fact.table_region_id, fact.row_index)
        grouped.setdefault(key, []).append(fact)
    records: list[dict[str, Any]] = []
    for key, group in grouped.items():
        collection_slug, filename, sheet_name, _region, row_index = key
        source_type = classify_data_source(" ".join(_safe_text(value) for value in [filename, sheet_name]))
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
        if not record.get("part_family") and record.get("source_part_label") and source_type == "periodicity":
            record["part_family"] = record["source_part_label"]
        if not record.get("customer_key") and record.get("customer_name"):
            record["customer_key"] = _normalize_token(record.get("customer_name"))
        if any(record.get(key) for key in ("customer_name", "part_reference", "part_family", "installed_quantity", "periodicity_weeks", "sales_known_qty")):
            records.append(record)
    return records


def _candidate_keys_for_record(record: dict[str, Any]) -> list[str]:
    values = [
        (record.get("source_part_reference") or record.get("part_reference"), record.get("source_part_family") or record.get("part_family"), record.get("technology")),
        (record.get("source_part_reference") or record.get("part_reference"), record.get("source_part_family") or record.get("part_family"), None),
        (None, record.get("source_part_family") or record.get("part_family") or record.get("source_part_label"), record.get("technology")),
        (None, record.get("source_part_family") or record.get("part_family") or record.get("source_part_label"), None),
    ]
    return list(dict.fromkeys(_mapping_key(*items) for items in values if _mapping_key(*items)))


def _mapping_for_record(record: dict[str, Any], mappings: list[Client360MappingRule]) -> Client360MappingRule | None:
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
        "source_part_reference": record.get("source_part_reference") or record.get("part_reference"),
        "source_part_label": record.get("source_part_label") or record.get("part_description"),
        "source_part_family": record.get("source_part_family") or record.get("part_family"),
        "technology": record.get("technology"),
        "pdr_family": record.get("pdr_family") or record.get("part_family") or record.get("source_part_family") or record.get("source_part_label"),
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
        merged["sales_known_qty"] = (float(current.get("sales_known_qty") or 0) + float(record.get("sales_known_qty") or 0)) or None
        merged["sales_known_value"] = (float(current.get("sales_known_value") or 0) + float(record.get("sales_known_value") or 0)) or None
        index[key] = merged
    return index


def _sales_for_record(record: dict[str, Any], sales_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
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


def _build_opportunity_payload(record: dict[str, Any], scope: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
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
    gap_qty = max(round(float(annual) - float(sales_qty or 0), 4), 0) if annual is not None and sales_qty is not None else None
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
        country=_safe_text(record.get("country")) or None,
        hub=_safe_text(record.get("hub")) or None,
        technology=_safe_text(record.get("technology")) or None,
        line_label=_safe_text(record.get("line_label")) or None,
        machine_label=_safe_text(record.get("machine_label")) or None,
        part_family=family,
        part_reference=_safe_text(record.get("part_reference") or record.get("source_part_reference")) or None,
        part_description=_safe_text(record.get("part_description") or record.get("source_part_label")) or None,
        installed_quantity=_safe_float(record.get("installed_quantity")),
        recommended_quantity=_safe_float(record.get("recommended_quantity")),
        periodicity_weeks=_safe_float(record.get("periodicity_weeks")),
        delivery_time_weeks=_safe_float(record.get("delivery_time_weeks")),
        annual_theoretical_qty=annual,
        potential_theoretical=annual,
        potential_addressable=gap_qty,
        potential_gap_qty=gap_qty,
        sales_known_qty=sales_qty,
        sales_known_value=_safe_non_negative_float(record.get("sales_known_value")),
        currency=_safe_text(record.get("currency")) or None,
        next_due_at=next_due,
        data_gaps=[],
        evidence_refs=_as_list(record.get("evidence_refs")),
        source_ids=_as_list(record.get("source_ids")),
        meta_data={
            "engine": "client360_pdr_opportunity_engine",
            "engine_key": _mapping_key(_record_customer_key(record), family, record.get("part_reference"), record.get("line_label")),
            "mapping_id": record.get("mapping_id"),
            "mapping_status": record.get("mapping_status"),
            "contact": {
                "name": record.get("contact_name"),
                "email": record.get("contact_email"),
                "hub": record.get("hub"),
            },
            "scope": scope,
        },
    )
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
    mappings = db.query(Client360MappingRule).filter(Client360MappingRule.workspace_id == workspace.id).all()
    mapping_count_before = len(mappings)
    mapped_records: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    for record in records:
        mapping = _ensure_candidate_mapping(db, workspace, record, mappings, dry_run=dry_run)
        mapped_records.append(_apply_mapping(record, mapping))

    periodicity_index = _index_periodicity(mapped_records)
    sales_index = _index_sales(mapped_records)
    opportunity_records: list[dict[str, Any]] = []
    for record in mapped_records:
        family = _record_family(record)
        if family:
            periodicity = periodicity_index.get(_mapping_key(family, record.get("technology"))) or periodicity_index.get(_mapping_key(family, None)) or {}
            record = _merge_record(record, periodicity)
            record = _merge_record(record, _sales_for_record(record, sales_index))
        if not any(record.get(key) is not None for key in ("installed_quantity", "recommended_quantity", "periodicity_weeks", "sales_known_qty", "sales_known_value")):
            continue
        if record.get("installed_quantity") is None:
            skipped["installed_quantity_missing_for_generation"] = skipped.get("installed_quantity_missing_for_generation", 0) + 1
            continue
        payload, reason = _build_opportunity_payload(record, scope)
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
    preview: list[dict[str, Any]] = []
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
            existing = Client360Opportunity(id=str(uuid4()), workspace_id=workspace.id, status="detected")
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
        "skipped": skipped,
        "preview": [serialize_opportunity(Client360Opportunity(workspace_id=workspace.id, **payload)) for payload in preview[:25]],
    }


def _get_opportunity(db: DBSession, workspace: Workspace, opportunity_id: str) -> Client360Opportunity:
    row = (
        db.query(Client360Opportunity)
        .filter(Client360Opportunity.id == opportunity_id, Client360Opportunity.workspace_id == workspace.id)
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
        scope = " / ".join(str(v) for v in [opp.get("technology"), opp.get("line_label"), opp.get("machine_label")] if v)
        lines.append(f"- Perimetre : {scope}")
    if opp.get("periodicity_weeks"):
        lines.append(f"- Periodicite constructeur connue : toutes les {opp['periodicity_weeks']:g} semaines")
    if opp.get("delivery_time_weeks"):
        lines.append(f"- Delai indicatif de livraison : {opp['delivery_time_weeks']:g} semaines")
    if opp.get("next_due_at"):
        lines.append(f"- Echeance estimee : {opp['next_due_at'][:10]}")
    if opp.get("annual_theoretical_qty"):
        lines.append(f"- Besoin annuel theorique estime : {opp['annual_theoretical_qty']:g} unite(s) / an")
    if opp.get("potential_gap_qty") is not None:
        lines.append(f"- Ecart potentiel vs achats connus : {opp['potential_gap_qty']:g} unite(s)")
    if include_prices and opp.get("sales_known_value"):
        lines.append(f"- Historique d'achat connu chez ANDRITZ : {opp['sales_known_value']:g} {opp.get('currency') or ''}".strip())
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


def serialize_mail_draft(row: Client360MailDraft) -> dict[str, Any]:
    return {
        "id": row.id,
        "opportunity_id": row.opportunity_id,
        "action_item_id": row.action_item_id,
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
    draft = Client360MailDraft(
        id=str(uuid4()),
        workspace_id=workspace.id,
        opportunity_id=opportunity.id,
        subject=_mail_subject(opportunity),
        generated_body=_mail_body(opportunity, include_prices=include_prices),
        language=language or "fr",
        status="draft_generated",
        meta_data={
            "include_prices": include_prices,
            "generation_mode": "deterministic_template",
            "human_validation_required": True,
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
                "manual_send_only": True,
            }
        },
    )
    draft.action_item_id = action.id
    opportunity.status = "draft_generated"
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
        .filter(WorkspaceActionItem.id == action_id, WorkspaceActionItem.workspace_id == workspace.id)
        .first()
    )
    if not action:
        raise LookupError("Client360 action not found")
    metadata = dict(action.meta_data or {})
    client360 = dict(metadata.get("client360") or {})
    for key in ("mail_status", "notes", "outcome_status", "sent_at"):
        if key in patch and patch[key] is not None:
            client360[key] = patch[key]
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
            .filter(Client360MailDraft.id == draft_id, Client360MailDraft.workspace_id == workspace.id)
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
        .filter(WorkspaceActionItem.id == action_id, WorkspaceActionItem.workspace_id == workspace.id)
        .first()
    )
    if not action:
        raise LookupError("Client360 action not found")
    client360_meta = _as_dict(_as_dict(action.meta_data).get("client360"))
    resolved_opportunity_id = opportunity_id or client360_meta.get("opportunity_id")
    resolved_draft_id = mail_draft_id or client360_meta.get("mail_draft_id")
    event = Client360ImpactEvent(
        id=str(uuid4()),
        workspace_id=workspace.id,
        opportunity_id=resolved_opportunity_id,
        action_item_id=action.id,
        mail_draft_id=resolved_draft_id,
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
    rows = db.query(
        Client360Opportunity.country,
        Client360Opportunity.hub,
        Client360Opportunity.technology,
        Client360Opportunity.part_family,
        Client360Opportunity.status,
        Client360Opportunity.confidence_label,
    ).filter(Client360Opportunity.workspace_id == workspace.id).all()
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
            result["countries"].add(country)
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
