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
import tempfile
import unicodedata
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
)
from app.services.knowledge_collections import resolve_original_key
from app.services.object_store import get_object_store
from app.services.secure_deposit import staged_file_path

_logger = logging.getLogger(__name__)

MONTHS_TO_WEEKS = 4.345
TABLE_FACT_FALLBACK_LIMIT = 8000
PHASE1_COUNTRY_KEYS = {"greece", "turkey", "gr", "tr", "el"}

SPL_ROLES = (
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
    if "materials_consumption" in underscored:
        return "materials_consumptions"
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
            "customer_key": _normalize_token(customer) or None,
            "country": country or None,
            "technology": technology or None,
            "machine_label": machine or None,
            "line_label": _safe_text(_pick(row, "Project Name", "line_label")) or None,
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
            "customer_key": _normalize_token(customer) or None,
            "country": country or None,
            "part_reference": part_ref or None,
            "part_description": part_desc or None,
            "installed_quantity": qty,
            "machine_label": _safe_text(_pick(row, "Machine", "Equipment", "machine_label"))
            or None,
            "technology": _safe_text(_pick(row, "technology", "Object Description")) or None,
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

    # pilot / generic: rely on already-canonical or aliasable keys
    out = {key: value for key, value in row.items() if value not in (None, "")}
    return out or None


def _source_type_for_role(role: str, filename: str) -> str:
    if role == "family_opportunity":
        return "periodicity"
    if role == "sales_by_country":
        return "sap_sales_history"
    if role in {"machine", "spc", "pilot"}:
        return "installed_base" if role != "pilot" else classify_data_source(filename)
    if role == "materials_consumptions":
        return "other"
    return classify_data_source(filename)


def _minimal_columns_ok(source_type: str, records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    if source_type == "periodicity":
        return any(r.get("part_family") and r.get("periodicity_weeks") is not None for r in records)
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


def _read_xlsx_rows(path: Path) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
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
) -> dict[str, Any]:
    ready = _minimal_columns_ok(source_type, records)
    status = "ready" if ready else ("needs_review" if records else "error")
    label = Path(origin_file).name
    metadata = {
        "records": records,
        "origin_file": origin_file,
        "adapter_version": CLIENT360_SPL_ADAPTER_VERSION,
        "spl_role": role,
        "read_via": read_via,
        "record_count": len(records),
    }
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
) -> dict[str, Any]:
    """Map collection spreadsheets into Client360DataSource rows.

    ``scope``: ``phase1`` (Greece/Turkey + pilot) or ``all``.
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

    workspace_scope = client360_scope(workspace)
    filenames = _list_collection_filenames(db, workspace, collection)
    # Also consider deposit files already promoted / pending with expected prefixes.
    deposit_candidates = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.filename.ilike("%Installed_base_SPL%"),
        )
        .all()
    )
    deposit_candidates += (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.filename.ilike("%Client360_Pilot%"),
        )
        .all()
    )
    for deposit in deposit_candidates:
        name = deposit.filename
        if name and name not in filenames:
            filenames.append(name)

    sources_out: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    temp_paths: list[Path] = []

    try:
        for filename in filenames:
            role = detect_spl_role(filename)
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
                    raw_rows = _read_xlsx_rows(path)
                    read_via = "xlsx"
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("failed reading xlsx %s: %s", filename, exc)
                    skipped["xlsx_read_error"] = skipped.get("xlsx_read_error", 0) + 1

            if not raw_rows:
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
                if scope == "phase1" and not passes_phase1_scope(record, scope=workspace_scope):
                    skipped["phase1_filtered"] = skipped.get("phase1_filtered", 0) + 1
                    continue
                if role == "sales_by_country" and scope == "phase1":
                    country = _normalize_token(record.get("country"))
                    if country and country not in PHASE1_COUNTRY_KEYS:
                        skipped["sales_country_filtered"] = skipped.get("sales_country_filtered", 0) + 1
                        continue
                mapped.append(record)

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
        "files_seen": len(filenames),
        "sources": sources_out,
        "skipped": skipped,
        "sources_upserted": sum(
            1 for item in sources_out if item.get("action") in {"created", "updated", "preview"}
        ),
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
