"""SAP Installed_base_SPL → Client360DataSource adapter.

Reads spreadsheet originals from the knowledge object store or Secure Deposit
when available, falls back to KnowledgeTableFact rows for smaller files, maps
SAP columns into Client360 canonical fields, applies Phase-1 Greece/Turkey +
pilot technology scope, and upserts Client360DataSource rows linked to the
unified collection slug.
"""

from __future__ import annotations

import logging
import re
import statistics
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.client360 import Client360DataSource
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.secure_deposit import DepositFile
from app.models.workspace import Workspace
from app.services.client360_contract import (
    CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
    CLIENT360_PILOT_DATASET_MARKER,
    CLIENT360_SPL_ADAPTER_VERSION,
)
from app.services.client360_pdr import (
    PILOT_COUNTRIES,
    PILOT_CUSTOMERS,
    PILOT_TECHNOLOGIES,
    _as_dict,
    _as_list,
    _normalize_token,
    _safe_float,
    _safe_non_negative_float,
    _safe_text,
    classify_data_source,
    client360_scope,
    customer_key_variants,
    normalize_customer_key,
    registry_customer_key,
)
from app.services.knowledge_collections import resolve_original_key
from app.services.object_store import get_object_store
from app.services.secure_deposit import staged_file_path

_logger = logging.getLogger(__name__)

MONTHS_TO_WEEKS = 4.345
TABLE_FACT_FALLBACK_LIMIT = 8000
PHASE1_COUNTRY_KEYS = {"greece", "turkey", "gr", "tr", "el"}
PURCHASE_HISTORY_MAX_MATERIALS = 20_000
PURCHASE_HISTORY_SHEET = "View_ASAP_PO_Delivered_By_Proje"
PURCHASE_HISTORY_ROLE_TOKENS = (
    "histo_achat",
    "purchase_history",
    "po_delivered",
    "achat_pieces",
)
SALES_ORDERS_DEFAULT_MIN_YEAR = 2019
SALES_ORDERS_PREFERRED_OFFERING = "sspa"
SALES_ORDERS_EXCLUDE_CUSTOMER_PREFIXES = ("andritz", "dummy customer")

SPL_ROLES = (
    "project_registry",
    "sales_orders",
    "purchase_history",
    "machine",
    "spc",
    "family_opportunity",
    "sales_by_country",
    "materials_consumptions",
    "pilot",
    "generic",
)


def months_to_weeks(months: Any) -> Optional[float]:
    value = _safe_float(months)
    if value is None:
        return None
    return round(value * MONTHS_TO_WEEKS, 4)


def detect_spl_role(filename: str) -> str:
    folded = _fold(filename)
    underscored = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    if "family" in underscored and "opportunity" in underscored:
        return "family_opportunity"
    if "sales_by_country" in underscored or "salesbycountry" in underscored:
        return "sales_by_country"
    if "sales_order" in underscored or "salesorders" in underscored or re.search(
        r"(^|_)va05($|_)", underscored
    ):
        return "sales_orders"
    if "materials_consumption" in underscored:
        return "materials_consumptions"
    # Before ``machine``: Histo_Achat_…_Machines_… must not become machine.
    if any(token in underscored for token in PURCHASE_HISTORY_ROLE_TOKENS):
        return "purchase_history"
    # Before ``machine``: Liste Projets _ Clients must not become machine.
    if ("projets" in underscored and "clients" in underscored) or (
        "project" in underscored and "customer" in underscored
    ):
        return "project_registry"
    if re.search(r"(^|_)spc($|_)", underscored) or "installed_base_spc" in underscored:
        return "spc"
    if "machine" in underscored:
        return "machine"
    if "client360_pilot" in underscored or "septona" in underscored or "turquie" in underscored:
        return "pilot"
    if "client_360" in underscored or "client360" in underscored:
        return "pilot"
    return "generic"


def _fold(value: Any) -> str:
    text = _safe_text(value).lower()
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _split_multi_codes(value: Any) -> list[str]:
    """Split multi-value SAP cells (e.g. ``SEP100\\nXEP100``)."""
    text = _safe_text(value)
    if not text:
        return []
    parts = re.split(r"[\n\r;/|]+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _index_key(value: Any) -> str:
    token = _normalize_token(value)
    return token.replace(" ", "") if token else ""


def _parse_year(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if hasattr(value, "year"):
        try:
            return int(value.year)
        except (TypeError, ValueError):
            return None
    text = _safe_text(value)
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _pick(row: dict[str, Any], *aliases: str) -> Any:
    """Return the first alias hit, preferring earlier aliases over later ones."""
    normalized_row = {_normalize_token(key): value for key, value in row.items()}
    for alias in aliases:
        alias_norm = _normalize_token(alias)
        if alias_norm in normalized_row:
            return normalized_row[alias_norm]
    # substring match for verbose SAP headers (still alias-order preferred)
    for alias in aliases:
        alias_norm = _normalize_token(alias)
        if len(alias_norm) < 4:
            continue
        for key_norm, value in normalized_row.items():
            if alias_norm in key_norm:
                return value
    return None


def passes_phase1_scope(record: dict[str, Any], *, scope: dict[str, Any] | None = None) -> bool:
    """Keep Greece/Turkey (+ codes) or pilot customers; tech filter when clear."""
    scope = scope or {}
    countries = {
        _normalize_token(item)
        for item in (_as_list(scope.get("pilot_countries")) or list(PILOT_COUNTRIES))
        if item
    } | set(PHASE1_COUNTRY_KEYS)
    customers = {
        _normalize_token(item)
        for item in (_as_list(scope.get("pilot_customers")) or list(PILOT_CUSTOMERS))
        if item
    }
    technologies = {
        _normalize_token(item)
        for item in (_as_list(scope.get("pilot_technologies")) or list(PILOT_TECHNOLOGIES))
        if item
    }

    country = _normalize_token(record.get("country"))
    customer = _normalize_token(record.get("customer_name") or record.get("customer_key"))
    tech = _normalize_token(
        " ".join(
            _safe_text(record.get(key))
            for key in ("technology", "machine_label", "line_label", "part_description")
        )
    )

    # Family / catalog rows without geography stay in scope (periodicity reference).
    if not country and not customer and record.get("part_family"):
        return True

    country_ok = bool(country) and any(
        token == country or token in country or country in token for token in countries
    )
    customer_ok = bool(customer) and any(
        token == customer or token in customer or customer in token for token in customers
    )
    if not (country_ok or customer_ok):
        return False

    if tech and technologies:
        tech_hit = any(token in tech or tech in token for token in technologies)
        if not tech_hit:
            # Soft reject only when another known nonwoven tech is explicit.
            other = ("needlepunch", "spunbond", "wetlaid", "airlay", "carding")
            if any(token in tech for token in other):
                return False
    return True


def map_row_for_role(role: str, row: dict[str, Any]) -> dict[str, Any] | None:
    if role == "project_registry":
        # Multi-code CONTRACT NAME expands to one record per project_code.
        project_codes = _split_multi_codes(
            _pick(row, "CONTRACT NAME", "Contract Name", "project_code", "Project")
        )
        customer = _safe_text(
            _pick(row, "FINAL CUSTOMER", "Final Customer", "customer_name", "Customer")
        )
        sap_ref = _safe_text(
            _pick(row, "SAP REFERENCE", "SAP Reference", "sap_reference", "SAP Ref")
        )
        country = _safe_text(_pick(row, "Site Country", "Country", "Country Key", "country"))
        if not project_codes and not customer and not sap_ref:
            return None
        codes = project_codes or [None]
        # Caller expands list via map_project_registry_row; return first + extras marker.
        base = {
            "project_code": codes[0],
            "project_codes": [code for code in codes if code],
            "customer_name": customer or None,
            "customer_key": registry_customer_key(customer) or None,
            "sap_reference": sap_ref or None,
            "country": country or None,
            "role": "project_registry",
        }
        return base

    if role == "sales_orders":
        customer = _safe_text(
            _pick(
                row,
                "Sold-To Party Name",
                "Sold-to party name",
                "Sold To Party Name",
                "Sold-To Party",
                "customer_name",
            )
        )
        part_ref = _safe_text(_pick(row, "Material", "part_reference", "Material Number"))
        part_desc = _safe_text(
            _pick(row, "Description", "Material Description", "part_description")
        )
        qty = _safe_non_negative_float(
            _pick(row, "Order Quantity", "Order Qty", "sales_known_qty", "Quantity")
        )
        net_price = _safe_non_negative_float(
            _pick(row, "Net Price", "Net price", "Unit Price")
        )
        net_value = _safe_non_negative_float(
            _pick(row, "Net Value", "Net value", "sales_known_value")
        )
        if net_value is None and net_price is not None and qty is not None:
            net_value = round(net_price * qty, 4)
        offering = _safe_text(_pick(row, "Offering", "offering", "Product hierarchy"))
        doc_date = _pick(row, "Document Date", "Doc. Date", "Billing Date", "date")
        if not customer and not part_ref:
            return None
        return {
            "customer_name": customer or None,
            "customer_key": normalize_customer_key(customer) or None,
            "part_reference": part_ref or None,
            "part_description": part_desc or None,
            "sales_known_qty": qty,
            "sales_known_value": net_value,
            "currency": _safe_text(_pick(row, "Currency", "Document Currency")) or "EUR",
            "offering": offering or None,
            "document_date": _safe_text(doc_date) or None,
            "document_year": _parse_year(doc_date),
            "role": "sales_orders",
        }

    if role == "machine":
        customer = _safe_text(
            _pick(
                row,
                "Equipment Sold to party name",
                "Sold to party name",
                "Sold-to party name",
                "customer_name",
                "customer",
            )
        )
        machine = _safe_text(_pick(row, "Machine", "machine_label", "Equipment"))
        technology = _safe_text(
            _pick(row, "Object Description", "technology", "Project Name", "Machine")
        )
        country = _safe_text(_pick(row, "Country", "Country Key", "country"))
        if not customer and not machine:
            return None
        return {
            "customer_name": customer or None,
            "customer_key": normalize_customer_key(customer) or None,
            "country": country or None,
            "technology": technology or None,
            "machine_label": machine or None,
            "line_label": _safe_text(_pick(row, "Project Name", "line_label")) or None,
            "project_code": _safe_text(
                _pick(row, "Project definition", "CONTRACT NAME", "project_code")
            )
            or None,
            "sap_reference": _safe_text(_pick(row, "SAP REFERENCE", "SAP Reference")) or None,
            "wbs_element": _safe_text(_pick(row, "Andritz WBS Element", "WBS Element")) or None,
            "construction_year": _safe_text(_pick(row, "Construction year", "Construction Year"))
            or None,
        }

    if role == "spc":
        customer = _safe_text(
            _pick(
                row,
                "Sold name",
                "Sold to party name",
                "Equipment Sold to party name",
                "customer_name",
            )
        )
        part_ref = _safe_text(_pick(row, "Number", "Material", "part_reference"))
        part_desc = _safe_text(_pick(row, "Title", "Description", "part_description"))
        qty = _safe_float(_pick(row, "Quantity", "installed_quantity", "Qty"))
        country = _safe_text(_pick(row, "Country", "Country Key", "country"))
        if not customer and not part_ref:
            return None
        return {
            "customer_name": customer or None,
            "customer_key": normalize_customer_key(customer) or None,
            "country": country or None,
            "part_reference": part_ref or None,
            "part_description": part_desc or None,
            "installed_quantity": qty,
            "machine_label": _safe_text(_pick(row, "Machine", "Equipment", "machine_label"))
            or None,
            "technology": _safe_text(_pick(row, "technology", "Object Description")) or None,
            "project_code": _safe_text(
                _pick(row, "Project definition", "CONTRACT NAME", "project_code")
            )
            or None,
            "sap_reference": _safe_text(_pick(row, "SAP REFERENCE", "SAP Reference")) or None,
            "wbs_element": _safe_text(_pick(row, "Andritz WBS Element", "WBS Element")) or None,
        }

    if role == "family_opportunity":
        family = _safe_text(_pick(row, "Familly", "Family", "part_family", "Famille"))
        periodicity_months = _pick(row, "Periodicity", "Periodicite", "periodicity_weeks")
        weeks = months_to_weeks(periodicity_months)
        # If value already looks like weeks (> 24 months would be unusual for wear parts
        # but keep months→weeks as the explicit contract for this SAP export).
        if weeks is None:
            weeks = _safe_float(periodicity_months)
        ib = _safe_float(_pick(row, "IB Turkey", "IB Turquie", "installed_quantity", "IB"))
        unit_price = _safe_non_negative_float(
            _pick(row, "Price", "Unit Price", "Prix", "Market Price", "sales_known_value")
        )
        if not family:
            return None
        out: dict[str, Any] = {
            "part_family": family,
            "source_part_family": family,
            "periodicity_weeks": weeks,
            "periodicity_months_raw": _safe_float(periodicity_months),
            "installed_quantity": ib,
            "country": "Turkey" if ib is not None else None,
            "customer_name": "Turkey IBS portfolio" if ib is not None else None,
            "customer_key": "turkey_ibs_portfolio" if ib is not None else None,
        }
        if unit_price is not None:
            out["sales_known_value"] = unit_price
            out["sales_known_qty"] = 1.0
            out["currency"] = _safe_text(_pick(row, "Currency", "Devise")) or "EUR"
        return out

    if role == "sales_by_country":
        country = _safe_text(_pick(row, "Country Key", "Country", "country"))
        material = _safe_text(_pick(row, "Material", "part_reference", "Item"))
        net_value = _safe_non_negative_float(
            _pick(row, "Net value", "Net Value", "sales_known_value")
        )
        qty = _safe_non_negative_float(_pick(row, "Quantity", "sales_known_qty", "Billing Quantity"))
        if not material and net_value is None and qty is None:
            return None
        return {
            "country": country or None,
            "part_reference": material or None,
            "part_family": _safe_text(_pick(row, "part_family", "Family", "Familly")) or None,
            "sales_known_value": net_value,
            "sales_known_qty": qty,
            "currency": _safe_text(_pick(row, "Currency", "Document Currency")) or None,
            "customer_name": _safe_text(_pick(row, "Sold-to party name", "customer_name")) or None,
        }

    if role == "materials_consumptions":
        material = _safe_text(_pick(row, "Material", "part_reference"))
        if not material:
            return None
        return {
            "part_reference": material,
            "part_description": _safe_text(_pick(row, "Description", "Title", "part_description"))
            or None,
            "delivery_time_weeks": _safe_float(
                _pick(row, "Lead time", "Lead Time", "delivery_time_weeks")
            ),
            "sales_known_value": _safe_non_negative_float(
                _pick(row, "Price", "Unit Price", "Moving Price")
            ),
            "installed_quantity": _safe_float(_pick(row, "Stock", "Unrestricted")),
            "enrichment": True,
        }

    if role == "purchase_history":
        material = _safe_text(_pick(row, "Material", "part_reference"))
        if not material:
            return None
        unit_cost = _safe_non_negative_float(
            _pick(
                row,
                "(EUR) Net order value",
                "Net order value",
                "Net Order Value",
                "unit_cost",
            )
        )
        delivery_raw = _safe_float(
            _pick(
                row,
                "Planned Deliv# Time",
                "Planned Deliv Time",
                "Planned Delivery Time",
                "delivery_time_weeks",
            )
        )
        out: dict[str, Any] = {
            "part_reference": material,
            "part_description": _safe_text(
                _pick(row, "Material Description", "Description", "part_description")
            )
            or None,
            "unit_cost": unit_cost,
            "currency": _safe_text(_pick(row, "Currency", "Document Currency")) or "EUR",
            "delivery_time_weeks": delivery_raw,
            "project_code": _safe_text(_pick(row, "Project definition", "Project Definition"))
            or None,
            "project_name": _safe_text(_pick(row, "Name", "Project Name", "project_name")) or None,
            "wbs_element": _safe_text(_pick(row, "Andritz WBS Element", "WBS Element")) or None,
            "vendor_name": _safe_text(_pick(row, "Vendor Name", "Vendor")) or None,
            # Vendor geography — never map to client ``country``.
            "vendor_country": _safe_text(_pick(row, "Country", "Country Key", "vendor_country"))
            or None,
            "role": "purchase_history",
        }
        if delivery_raw is not None and delivery_raw > 104:
            out["delivery_time_unit_note"] = "raw_value_may_not_be_weeks"
        return out

    # pilot / generic: rely on already-canonical or aliasable keys
    out = {key: value for key, value in row.items() if value not in (None, "")}
    return out or None


def aggregate_purchase_history_records(
    records: list[dict[str, Any]],
    *,
    max_materials: int = PURCHASE_HISTORY_MAX_MATERIALS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse PO lines to one structured record per Material."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        part_ref = _safe_text(record.get("part_reference"))
        if not part_ref:
            continue
        groups[part_ref].append(record)

    truncated = len(groups) > max_materials
    if truncated:
        _logger.warning(
            "purchase_history aggregation truncated from %s to %s materials",
            len(groups),
            max_materials,
        )

    aggregated: list[dict[str, Any]] = []
    for part_ref in list(groups.keys())[:max_materials]:
        rows = groups[part_ref]
        costs = [
            cost
            for cost in (_safe_non_negative_float(row.get("unit_cost")) for row in rows)
            if cost is not None and cost > 0
        ]
        leads = [
            lead
            for lead in (_safe_float(row.get("delivery_time_weeks")) for row in rows)
            if lead is not None and lead > 0
        ]
        descriptions = [
            text
            for text in (_safe_text(row.get("part_description")) for row in rows)
            if text
        ]
        description = Counter(descriptions).most_common(1)[0][0] if descriptions else None
        last = rows[-1]
        aggregated.append(
            {
                "part_reference": part_ref,
                "part_description": description or last.get("part_description"),
                "unit_cost": round(sum(costs) / len(costs), 4) if costs else None,
                "currency": _safe_text(last.get("currency")) or "EUR",
                "delivery_time_weeks": float(statistics.median(leads)) if leads else None,
                "po_count": len(rows),
                "cost_sum": round(sum(costs), 4) if costs else None,
                "last_project_name": last.get("project_name"),
                "last_wbs_element": last.get("wbs_element"),
                "vendor_name": last.get("vendor_name"),
                "vendor_country": last.get("vendor_country"),
                "role": "purchase_history",
            }
        )

    meta = {
        "aggregation": "by_material",
        "material_count": len(aggregated),
        "po_lines_seen": len(records),
        "truncated": truncated,
    }
    return aggregated, meta


def expand_project_registry_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One registry row per project_code (CONTRACT NAME may hold multiple codes)."""
    expanded: list[dict[str, Any]] = []
    for record in records:
        codes = [
            code
            for code in (_as_list(record.get("project_codes")) or [_safe_text(record.get("project_code"))])
            if _safe_text(code)
        ]
        if not codes:
            codes = [None]
        for code in codes:
            item = {
                "project_code": code,
                "customer_name": record.get("customer_name"),
                "customer_key": registry_customer_key(record.get("customer_name"))
                or record.get("customer_key")
                or None,
                "sap_reference": record.get("sap_reference"),
                "country": record.get("country"),
                "wbs_element": record.get("wbs_element"),
                "role": "project_registry",
            }
            if item.get("customer_name") or item.get("project_code") or item.get("sap_reference"):
                expanded.append(item)
    return expanded


def build_project_registry_index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index registry rows by normalized project_code / wbs / sap_reference."""
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        payload = {
            "customer_name": record.get("customer_name"),
            "customer_key": registry_customer_key(record.get("customer_name"))
            or record.get("customer_key")
            or None,
            "country": record.get("country"),
            "sap_reference": record.get("sap_reference"),
            "project_code": record.get("project_code"),
            "wbs_element": record.get("wbs_element"),
        }
        for field in ("project_code", "wbs_element", "sap_reference"):
            key = _index_key(record.get(field))
            if key:
                index[key] = payload
        # Secondary lookups used by the SPC Sold-name → country join. Register
        # every name variant (primary, parenthetical alias, full) so SAP legal
        # names resolve against registry short names.
        customer_keys = {
            _index_key(variant)
            for variant in customer_key_variants(record.get("customer_name"))
        }
        customer_keys.add(_index_key(record.get("customer_key")))
        if payload.get("country"):
            for customer_key in customer_keys:
                if customer_key:
                    index.setdefault(f"customer:{customer_key}", payload)
    return index


def resolve_customer_for_project(
    project_code: str | None = None,
    *,
    wbs: str | None = None,
    sap_ref: str | None = None,
    index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Resolve FINAL CUSTOMER / country from the project registry index."""
    if not index:
        return None
    for candidate in (project_code, wbs, sap_ref):
        key = _index_key(candidate)
        if key and key in index:
            return dict(index[key])
    return None


def load_project_registry_index(
    db: DBSession,
    workspace: Workspace,
    *,
    extra_records: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a resolve index from persisted project_registry sources (+ optional rows)."""
    records: list[dict[str, Any]] = list(extra_records or [])
    rows = (
        db.query(Client360DataSource)
        .filter(
            Client360DataSource.workspace_id == workspace.id,
            Client360DataSource.status != "archived",
        )
        .all()
    )
    for row in rows:
        meta = _as_dict(row.meta_data)
        if meta.get("role") != "project_registry":
            continue
        for record in _as_list(meta.get("records")):
            if isinstance(record, dict):
                records.append(record)
    return build_project_registry_index(expand_project_registry_records(records))


def sales_orders_row_accepted(
    record: dict[str, Any],
    *,
    min_year: int = SALES_ORDERS_DEFAULT_MIN_YEAR,
) -> bool:
    """Quality gate: drop internal sold-tos, non-SSPA offerings, pre-window years."""
    customer = _fold(record.get("customer_name") or record.get("customer_key"))
    if any(customer.startswith(prefix) for prefix in SALES_ORDERS_EXCLUDE_CUSTOMER_PREFIXES):
        return False
    year = record.get("document_year")
    if isinstance(year, int) and year < min_year:
        return False
    offering = _fold(record.get("offering"))
    if offering:
        if SALES_ORDERS_PREFERRED_OFFERING in offering or "spare" in offering:
            return True
        # Prefer SSPA: drop other explicit offerings (machines, services, …).
        return False
    return True


def aggregate_sales_orders_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse sales order lines to customer × Material."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        customer_key = normalize_customer_key(
            record.get("customer_key") or record.get("customer_name")
        )
        part_ref = _safe_text(record.get("part_reference"))
        if not customer_key or not part_ref:
            continue
        groups[(customer_key, part_ref)].append(record)

    aggregated: list[dict[str, Any]] = []
    for (customer_key, part_ref), rows in groups.items():
        qtys = [
            qty
            for qty in (_safe_non_negative_float(row.get("sales_known_qty")) for row in rows)
            if qty is not None
        ]
        values = [
            value
            for value in (_safe_non_negative_float(row.get("sales_known_value")) for row in rows)
            if value is not None
        ]
        descriptions = [
            text for text in (_safe_text(row.get("part_description")) for row in rows) if text
        ]
        last = rows[-1]
        dated = []
        for row in rows:
            year = row.get("document_year")
            doc = _safe_text(row.get("document_date"))
            dated.append((year or 0, doc or "", row))
        dated.sort(key=lambda item: (item[0], item[1]))
        latest_row = dated[-1][2] if dated else last
        aggregated.append(
            {
                "customer_name": last.get("customer_name"),
                "customer_key": customer_key,
                "part_reference": part_ref,
                "part_description": (
                    Counter(descriptions).most_common(1)[0][0] if descriptions else None
                ),
                "sales_known_qty": round(sum(qtys), 4) if qtys else None,
                "sales_known_value": round(sum(values), 4) if values else None,
                "currency": _safe_text(last.get("currency")) or "EUR",
                "offering": last.get("offering"),
                "last_document_date": latest_row.get("document_date"),
                "last_purchase_date": latest_row.get("document_date"),
                "order_line_count": len(rows),
                "role": "sales_orders",
            }
        )

    meta = {
        "aggregation": "by_customer_material",
        "material_count": len(aggregated),
        "order_lines_seen": len(records),
    }
    return aggregated, meta


def aggregate_spc_records(
    records: list[dict[str, Any]],
    *,
    registry_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate SPC lines by Sold name × Material (qty > 0); join registry for country."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        qty = _safe_float(record.get("installed_quantity"))
        if qty is None or qty <= 0:
            continue
        customer_key = normalize_customer_key(
            record.get("customer_key") or record.get("customer_name")
        )
        part_ref = _safe_text(record.get("part_reference"))
        if not customer_key or not part_ref:
            continue
        groups[(customer_key, part_ref)].append(record)

    index = registry_index or {}
    aggregated: list[dict[str, Any]] = []
    joined_country = 0
    for (customer_key, part_ref), rows in groups.items():
        qtys = [
            qty
            for qty in (_safe_float(row.get("installed_quantity")) for row in rows)
            if qty is not None and qty > 0
        ]
        descriptions = [
            text for text in (_safe_text(row.get("part_description")) for row in rows) if text
        ]
        last = rows[-1]
        country = _safe_text(last.get("country")) or None
        if not country:
            resolved = index.get(f"customer:{_index_key(customer_key)}")
            if not resolved:
                resolved = resolve_customer_for_project(
                    last.get("project_code"),
                    wbs=last.get("wbs_element"),
                    sap_ref=last.get("sap_reference"),
                    index=index,
                )
            if resolved and resolved.get("country"):
                country = resolved.get("country")
                joined_country += 1
        aggregated.append(
            {
                "customer_name": last.get("customer_name"),
                "customer_key": customer_key,
                "country": country,
                "part_reference": part_ref,
                "part_description": (
                    Counter(descriptions).most_common(1)[0][0] if descriptions else None
                ),
                "installed_quantity": round(sum(qtys), 4) if qtys else None,
                "machine_label": last.get("machine_label"),
                "technology": last.get("technology"),
                "role": "spc",
            }
        )

    meta = {
        "aggregation": "by_customer_material",
        "material_count": len(aggregated),
        "spc_lines_seen": len(records),
        "registry_country_joins": joined_country,
    }
    return aggregated, meta


def _enrich_record_from_registry(
    record: dict[str, Any],
    registry_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Fill customer/country from project registry when project/wbs/sap keys exist."""
    if not registry_index:
        return record
    resolved = resolve_customer_for_project(
        record.get("project_code"),
        wbs=record.get("wbs_element"),
        sap_ref=record.get("sap_reference"),
        index=registry_index,
    )
    if not resolved:
        return record
    out = dict(record)
    if not out.get("customer_name") and resolved.get("customer_name"):
        out["customer_name"] = resolved["customer_name"]
        out["customer_key"] = resolved.get("customer_key") or registry_customer_key(
            resolved["customer_name"]
        )
    if not out.get("country") and resolved.get("country"):
        out["country"] = resolved["country"]
    return out


def _source_type_for_role(role: str, filename: str) -> str:
    if role == "project_registry":
        return "contact_hub"
    if role == "family_opportunity":
        return "periodicity"
    if role in {"sales_by_country", "sales_orders"}:
        return "sap_sales_history"
    if role in {"machine", "spc", "pilot"}:
        return "installed_base" if role != "pilot" else classify_data_source(filename)
    if role in {"materials_consumptions", "purchase_history"}:
        return "other"
    return classify_data_source(filename)


def _minimal_columns_ok(source_type: str, records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    if source_type == "periodicity":
        return any(r.get("part_family") and r.get("periodicity_weeks") is not None for r in records)
    if source_type == "contact_hub":
        return any(
            (r.get("customer_name") or r.get("customer_key"))
            and (r.get("project_code") or r.get("sap_reference"))
            for r in records
        )
    if source_type == "installed_base":
        return any(
            (r.get("customer_name") or r.get("customer_key"))
            and (r.get("installed_quantity") is not None or r.get("machine_label"))
            for r in records
        )
    if source_type == "sap_sales_history":
        return any(
            (r.get("part_reference") or r.get("part_family"))
            and (r.get("sales_known_qty") is not None or r.get("sales_known_value") is not None)
            for r in records
        )
    return True


def _read_xlsx_rows(
    path: Path, *, preferred_sheet: str | None = None
) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = None
        if preferred_sheet:
            preferred_fold = _fold(preferred_sheet)
            for name in workbook.sheetnames:
                if preferred_fold in _fold(name) or _fold(name) in preferred_fold:
                    sheet = workbook[name]
                    break
        if sheet is None:
            sheet = workbook.active
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            headers = next(rows_iter)
        except StopIteration:
            return []
        labels = [str(h).strip() if h is not None else f"col_{idx}" for idx, h in enumerate(headers)]
        records: list[dict[str, Any]] = []
        for values in rows_iter:
            if values is None:
                continue
            row = {
                labels[idx]: values[idx]
                for idx in range(min(len(labels), len(values)))
                if labels[idx]
            }
            if any(value not in (None, "") for value in row.values()):
                records.append(row)
        return records
    finally:
        workbook.close()


def _materialize_collection_file(
    db: DBSession,
    workspace: Workspace,
    collection: KnowledgeCollection,
    filename: str,
) -> tuple[Path | None, str | None, str | None]:
    """Return (local_path, knowledge_source_id, deposit_file_id)."""
    source = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.workspace_id == workspace.id,
            KnowledgeCollectionSource.filename == filename,
        )
        .first()
    )
    if source is None:
        basename = Path(filename).name
        source = (
            db.query(KnowledgeCollectionSource)
            .filter(
                KnowledgeCollectionSource.collection_id == collection.id,
                KnowledgeCollectionSource.workspace_id == workspace.id,
                KnowledgeCollectionSource.normalized_name == basename,
            )
            .first()
        )

    knowledge_source_id = source.id if source else None
    store = get_object_store()
    if source is not None:
        try:
            key = resolve_original_key(collection, source.filename)
            if store.exists(key):
                tmp = tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".xlsx", delete=False)
                tmp_path = Path(tmp.name)
                tmp.close()
                store.copy_to_local(key, tmp_path)
                return tmp_path, knowledge_source_id, None
        except Exception:  # noqa: BLE001
            _logger.debug("object store miss for %s", filename, exc_info=True)

    deposit = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.filename == filename,
        )
        .order_by(DepositFile.uploaded_at.desc())
        .first()
    )
    if deposit is None:
        # prefix / path-style deposit names
        deposit = (
            db.query(DepositFile)
            .filter(
                DepositFile.workspace_id == workspace.id,
                DepositFile.filename.ilike(f"%{Path(filename).name}"),
            )
            .order_by(DepositFile.uploaded_at.desc())
            .first()
        )
    if deposit is not None:
        try:
            return staged_file_path(deposit), knowledge_source_id, deposit.id
        except Exception:  # noqa: BLE001
            _logger.debug("deposit staged path miss for %s", filename, exc_info=True)

    return None, knowledge_source_id, deposit.id if deposit else None


def _records_from_table_facts_for_file(
    db: DBSession,
    workspace: Workspace,
    *,
    collection_slug: str,
    filename: str,
) -> list[dict[str, Any]]:
    basename = Path(filename).name
    facts = (
        db.query(KnowledgeTableFact)
        .filter(
            KnowledgeTableFact.workspace_id == workspace.id,
            KnowledgeTableFact.semantic_type == "spreadsheet_table_fact",
            KnowledgeTableFact.collection_slug == collection_slug,
        )
        .order_by(KnowledgeTableFact.updated_at.desc())
        .limit(TABLE_FACT_FALLBACK_LIMIT)
        .all()
    )
    grouped: dict[tuple[Any, ...], list[KnowledgeTableFact]] = {}
    for fact in facts:
        doc = _safe_text(fact.document_filename)
        if basename not in doc and filename not in doc:
            continue
        key = (fact.sheet_name, fact.table_region_id, fact.row_index)
        grouped.setdefault(key, []).append(fact)

    rows: list[dict[str, Any]] = []
    for _key, group in grouped.items():
        row: dict[str, Any] = {}
        for fact in group:
            label = fact.column_header or fact.measure or fact.subject
            if label:
                row[str(label)] = (
                    fact.value_numeric if fact.value_numeric is not None else fact.value_raw
                )
        if row:
            rows.append(row)
    return rows


def _list_collection_filenames(
    db: DBSession, workspace: Workspace, collection: KnowledgeCollection
) -> list[str]:
    names: list[str] = []
    sources = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.workspace_id == workspace.id,
            KnowledgeCollectionSource.status != "deleted",
        )
        .all()
    )
    for source in sources:
        name = source.filename or source.normalized_name
        if name and name not in names:
            names.append(name)
    for name in _as_list(collection.document_names):
        text = _safe_text(name)
        if text and text not in names:
            names.append(text)
    return names


def _find_existing_source(
    db: DBSession,
    workspace: Workspace,
    *,
    collection_slug: str,
    origin_file: str,
) -> Client360DataSource | None:
    rows = (
        db.query(Client360DataSource)
        .filter(
            Client360DataSource.workspace_id == workspace.id,
            Client360DataSource.collection_slug == collection_slug,
            Client360DataSource.status != "archived",
        )
        .all()
    )
    basename = Path(origin_file).name
    for row in rows:
        meta = _as_dict(row.meta_data)
        if meta.get("origin_file") in {origin_file, basename}:
            return row
        if _safe_text(row.filename) in {origin_file, basename}:
            return row
    return None


def _upsert_data_source(
    db: DBSession,
    workspace: Workspace,
    *,
    collection: KnowledgeCollection,
    origin_file: str,
    source_type: str,
    records: list[dict[str, Any]],
    knowledge_source_id: str | None,
    deposit_file_id: str | None,
    role: str,
    read_via: str,
    dry_run: bool,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ready = _minimal_columns_ok(source_type, records)
    if role in {"purchase_history", "project_registry"} and records:
        ready = True
    status = "ready" if ready else ("needs_review" if records else "error")
    label = Path(origin_file).name
    metadata = {
        "records": records,
        "origin_file": origin_file,
        "adapter_version": CLIENT360_SPL_ADAPTER_VERSION,
        "role": role,
        "spl_role": role,
        "read_via": read_via,
        "record_count": len(records),
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    evidence = [
        {
            "kind": "client360_spl_adapter",
            "collection_slug": collection.slug,
            "origin_file": origin_file,
            "adapter_version": CLIENT360_SPL_ADAPTER_VERSION,
        }
    ]
    payload = {
        "label": label,
        "filename": label,
        "source_type": source_type,
        "status": status,
        "row_count": float(len(records)),
        "error": None if records else "no_rows_mapped",
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "knowledge_source_id": knowledge_source_id,
        "deposit_file_id": deposit_file_id,
        "metadata": metadata,
        "evidence_refs": evidence,
    }
    if dry_run:
        return {"action": "preview", **payload, "id": None}

    existing = _find_existing_source(
        db, workspace, collection_slug=collection.slug, origin_file=origin_file
    )
    if existing is None:
        existing = Client360DataSource(
            id=str(uuid4()),
            workspace_id=workspace.id,
            source_type=source_type,
            label=label,
        )
        db.add(existing)
        action = "created"
    else:
        action = "updated"

    existing.source_type = source_type
    existing.label = label
    existing.filename = label
    existing.collection_id = collection.id
    existing.collection_slug = collection.slug
    existing.knowledge_source_id = knowledge_source_id
    existing.deposit_file_id = deposit_file_id
    existing.status = status
    existing.row_count = float(len(records))
    existing.error = None if records else "no_rows_mapped"
    existing.meta_data = metadata
    existing.evidence_refs = evidence
    flag_modified(existing, "meta_data")
    flag_modified(existing, "evidence_refs")
    db.flush()
    return {"action": action, "id": existing.id, **payload}


def sync_sources_from_collection(
    db: DBSession,
    workspace: Workspace,
    *,
    collection_slug: str = CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
    dry_run: bool = False,
    scope: str = "phase1",
    rehydrate_mvp: bool = True,
    include_purchase_history: bool = False,
    include_spc: bool = False,
) -> dict[str, Any]:
    """Map collection spreadsheets into Client360DataSource rows.

    ``scope``: ``phase1`` (Greece/Turkey + pilot) or ``all``.

    ``include_purchase_history``: Phase-2 opt-in to sync Histo_Achat (also
    included when ``scope == "all"``). Phase-1 interactive sync skips it.

    ``include_spc``: opt-in to sync Installed base SPC (~56MB / 50k+ lines);
    also included when ``scope == "all"``. Default Phase-1 HTTP sync skips it.

    ``project_registry`` always syncs (small file, no country filter).
    ``sales_orders`` always syncs with quality filters + customer×Material agg.

    Always rehydrates MVP pilot sources into the unified collection first (unless
    ``rehydrate_mvp=False``), so the UI is not stuck at 0 linked sources when
    deposit SPL files are still ``received`` / unpromoted.

    Only **promoted** (or already-in-collection) spreadsheets are parsed. Reading
    raw ``received`` deposit xlsx (Sales 32k / Machine 11k) from the sync HTTP
    path previously hung the Données tab.
    """
    collection = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == collection_slug,
        )
        .first()
    )
    if collection is None:
        raise LookupError(f"Knowledge collection not found: {collection_slug}")

    rehydrate_result: dict[str, Any] | None = None
    if rehydrate_mvp:
        rehydrate_result = rehydrate_pilot_mvp_into_collection(
            db,
            workspace,
            collection_slug=collection.slug,
            dry_run=dry_run,
        )

    workspace_scope = client360_scope(workspace)
    filenames = _list_collection_filenames(db, workspace, collection)
    # Only promoted deposit files — never parse staging ``received`` blobs here.
    deposit_candidates = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.status == "promoted",
            DepositFile.filename.ilike("Installed_base_SPL/%"),
        )
        .all()
    )
    deposit_candidates += (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.status == "promoted",
            DepositFile.filename.ilike("Client360_Pilot/%"),
        )
        .all()
    )
    for deposit in deposit_candidates:
        name = deposit.filename
        if name and name not in filenames:
            filenames.append(name)

    # Registry first so Machine / SPC / PO can resolve customer + country.
    filenames = sorted(
        filenames,
        key=lambda name: 0 if detect_spl_role(name) == "project_registry" else 1,
    )

    sources_out: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    temp_paths: list[Path] = []
    allow_purchase_history = include_purchase_history or scope == "all"
    allow_spc = include_spc or scope == "all"
    registry_index = load_project_registry_index(db, workspace)

    try:
        for filename in filenames:
            role = detect_spl_role(filename)
            # Materials master is Phase-2 enrichment — skip on the interactive sync path.
            if role == "materials_consumptions" and scope == "phase1":
                skipped["materials_deferred"] = skipped.get("materials_deferred", 0) + 1
                sources_out.append(
                    {
                        "action": "skipped",
                        "filename": filename,
                        "role": role,
                        "reason": "materials_deferred_phase2",
                    }
                )
                continue
            if role == "purchase_history" and not allow_purchase_history:
                skipped["purchase_history_deferred"] = (
                    skipped.get("purchase_history_deferred", 0) + 1
                )
                sources_out.append(
                    {
                        "action": "skipped",
                        "filename": filename,
                        "role": role,
                        "reason": "purchase_history_deferred_phase2",
                    }
                )
                continue
            if role == "spc" and not allow_spc:
                skipped["spc_deferred"] = skipped.get("spc_deferred", 0) + 1
                sources_out.append(
                    {
                        "action": "skipped",
                        "filename": filename,
                        "role": role,
                        "reason": "spc_deferred_until_include_spc_or_scope_all",
                    }
                )
                continue
            if role == "generic" and "installed_base" not in _fold(filename):
                # Ignore notices / unrelated collection noise if any slipped in.
                if classify_data_source(filename) == "other" and "consumption" not in _fold(
                    filename
                ):
                    skipped["unrelated_filename"] = skipped.get("unrelated_filename", 0) + 1
                    continue

            path, knowledge_source_id, deposit_file_id = _materialize_collection_file(
                db, workspace, collection, filename
            )
            raw_rows: list[dict[str, Any]] = []
            read_via = "none"
            if path is not None:
                temp_paths.append(path)
                try:
                    preferred = (
                        PURCHASE_HISTORY_SHEET if role == "purchase_history" else None
                    )
                    raw_rows = _read_xlsx_rows(path, preferred_sheet=preferred)
                    read_via = "xlsx"
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("failed reading xlsx %s: %s", filename, exc)
                    skipped["xlsx_read_error"] = skipped.get("xlsx_read_error", 0) + 1

            # Heavy / PO feeds must come from the workbook (not table-facts 5k cap).
            if not raw_rows and role not in {
                "purchase_history",
                "spc",
                "sales_orders",
                "project_registry",
            }:
                raw_rows = _records_from_table_facts_for_file(
                    db,
                    workspace,
                    collection_slug=collection.slug,
                    filename=filename,
                )
                if raw_rows:
                    read_via = "table_facts"

            if not raw_rows:
                skipped["empty_source"] = skipped.get("empty_source", 0) + 1
                sources_out.append(
                    {
                        "action": "skipped",
                        "filename": filename,
                        "role": role,
                        "reason": "no_rows",
                        "read_via": read_via,
                    }
                )
                continue

            mapped: list[dict[str, Any]] = []
            for raw in raw_rows:
                record = map_row_for_role(role, raw)
                if not record:
                    skipped["unmapped_row"] = skipped.get("unmapped_row", 0) + 1
                    continue
                if role == "sales_orders" and not sales_orders_row_accepted(record):
                    skipped["sales_orders_filtered"] = skipped.get("sales_orders_filtered", 0) + 1
                    continue
                if role in {"machine", "spc", "purchase_history"}:
                    record = _enrich_record_from_registry(record, registry_index)
                # Registry + sales_orders are global feeds; PO has no client country.
                if (
                    role not in {"purchase_history", "project_registry", "sales_orders"}
                    and scope == "phase1"
                    and not passes_phase1_scope(record, scope=workspace_scope)
                ):
                    skipped["phase1_filtered"] = skipped.get("phase1_filtered", 0) + 1
                    continue
                if role == "sales_by_country" and scope == "phase1":
                    country = _normalize_token(record.get("country"))
                    if country and country not in PHASE1_COUNTRY_KEYS:
                        skipped["sales_country_filtered"] = skipped.get("sales_country_filtered", 0) + 1
                        continue
                mapped.append(record)

            extra_metadata: dict[str, Any] | None = None
            if role == "project_registry":
                mapped = expand_project_registry_records(mapped)
                registry_index = load_project_registry_index(
                    db, workspace, extra_records=mapped
                )
                extra_metadata = {"record_count": len(mapped)}
            elif role == "purchase_history":
                mapped, agg_meta = aggregate_purchase_history_records(mapped)
                extra_metadata = agg_meta
            elif role == "sales_orders":
                mapped, agg_meta = aggregate_sales_orders_records(mapped)
                extra_metadata = agg_meta
            elif role == "spc":
                mapped, agg_meta = aggregate_spc_records(
                    mapped, registry_index=registry_index
                )
                extra_metadata = agg_meta

            source_type = _source_type_for_role(role, filename)
            # Family-Opportunity also carries market pricing — emit a companion
            # market_signal source when price fields are present.
            result = _upsert_data_source(
                db,
                workspace,
                collection=collection,
                origin_file=filename,
                source_type=source_type,
                records=mapped,
                knowledge_source_id=knowledge_source_id,
                deposit_file_id=deposit_file_id,
                role=role,
                read_via=read_via,
                dry_run=dry_run,
                extra_metadata=extra_metadata,
            )
            sources_out.append(result)

            if role == "family_opportunity":
                price_rows = [
                    {
                        "part_family": row.get("part_family"),
                        "sales_known_value": row.get("sales_known_value"),
                        "sales_known_qty": row.get("sales_known_qty"),
                        "currency": row.get("currency"),
                        "country": row.get("country"),
                    }
                    for row in mapped
                    if row.get("sales_known_value") is not None
                ]
                if price_rows:
                    market_file = f"{filename}#market_signal"
                    sources_out.append(
                        _upsert_data_source(
                            db,
                            workspace,
                            collection=collection,
                            origin_file=market_file,
                            source_type="market_signal",
                            records=price_rows,
                            knowledge_source_id=knowledge_source_id,
                            deposit_file_id=deposit_file_id,
                            role="family_opportunity_market",
                            read_via=read_via,
                            dry_run=dry_run,
                        )
                    )
    finally:
        for path in temp_paths:
            try:
                # Only delete NamedTemporaryFile copies, not deposit staged paths.
                if path.exists() and str(path).startswith(tempfile.gettempdir()):
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    if not dry_run:
        db.flush()

    return {
        "adapter": "client360_spl_adapter",
        "adapter_version": CLIENT360_SPL_ADAPTER_VERSION,
        "collection_slug": collection.slug,
        "dry_run": dry_run,
        "scope": scope,
        "include_purchase_history": allow_purchase_history,
        "include_spc": allow_spc,
        "files_seen": len(filenames),
        "sources": sources_out,
        "skipped": skipped,
        "rehydrate_mvp": rehydrate_result,
        "sources_upserted": sum(
            1 for item in sources_out if item.get("action") in {"created", "updated", "preview"}
        ),
        "mvp_sources_linked": (rehydrate_result or {}).get("count") or 0,
    }


def preview_archive_mvp_orphan_sources(
    db: DBSession,
    workspace: Workspace,
    *,
    collection_slug: str = CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
) -> dict[str, Any]:
    """Dry-run listing of MVP pilot sources not linked to the unified collection."""
    rows = (
        db.query(Client360DataSource)
        .filter(
            Client360DataSource.workspace_id == workspace.id,
            Client360DataSource.status != "archived",
        )
        .all()
    )
    candidates: list[dict[str, Any]] = []
    for row in rows:
        meta = _as_dict(row.meta_data)
        marker = _safe_text(meta.get("pilot_dataset"))
        linked = _safe_text(row.collection_slug) == collection_slug
        if marker == CLIENT360_PILOT_DATASET_MARKER and not linked:
            candidates.append(
                {
                    "id": row.id,
                    "label": row.label,
                    "filename": row.filename,
                    "source_type": row.source_type,
                    "collection_slug": row.collection_slug,
                    "pilot_dataset": marker,
                    "row_count": row.row_count,
                }
            )
    return {
        "dry_run": True,
        "collection_slug": collection_slug,
        "archive_candidates": candidates,
        "count": len(candidates),
        "note": "No archive performed. Call with an explicit ops action after parity validation.",
    }


def rehydrate_pilot_mvp_into_collection(
    db: DBSession,
    workspace: Workspace,
    *,
    collection_slug: str = CLIENT360_INSTALLED_BASE_COLLECTION_SLUG,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Link existing MVP Client360DataSource rows to the unified collection.

    Used when pilot xlsx files are absent from Secure Deposit: keep the
    structured records, attach collection_slug, and stamp adapter metadata.
    """
    collection = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == collection_slug,
        )
        .first()
    )
    if collection is None:
        raise LookupError(f"Knowledge collection not found: {collection_slug}")

    rows = (
        db.query(Client360DataSource)
        .filter(
            Client360DataSource.workspace_id == workspace.id,
            Client360DataSource.status != "archived",
        )
        .all()
    )
    updated: list[dict[str, Any]] = []
    for row in rows:
        meta = _as_dict(row.meta_data)
        marker = _safe_text(meta.get("pilot_dataset"))
        has_records = bool(_as_list(meta.get("records") or meta.get("rows")))
        if marker != CLIENT360_PILOT_DATASET_MARKER and not (
            has_records and not row.collection_slug
        ):
            continue
        if row.collection_slug == collection_slug and meta.get("adapter_version"):
            continue
        payload = {
            "id": row.id,
            "label": row.label,
            "filename": row.filename,
            "source_type": row.source_type,
            "previous_collection_slug": row.collection_slug,
        }
        if dry_run:
            updated.append({"action": "preview", **payload})
            continue
        row.collection_id = collection.id
        row.collection_slug = collection.slug
        meta = dict(meta)
        meta.setdefault("origin_file", row.filename or row.label)
        meta["adapter_version"] = meta.get("adapter_version") or CLIENT360_SPL_ADAPTER_VERSION
        meta["rehydrated_from_mvp"] = True
        if marker:
            meta["pilot_dataset"] = marker
        row.meta_data = meta
        flag_modified(row, "meta_data")
        updated.append({"action": "linked", **payload, "collection_slug": collection.slug})
    if not dry_run:
        db.flush()
    return {
        "collection_slug": collection.slug,
        "dry_run": dry_run,
        "updated": updated,
        "count": len(updated),
    }
