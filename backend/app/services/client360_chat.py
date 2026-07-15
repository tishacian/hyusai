"""Natural-language Client360 PDR queries for the Andritz workspace chat.

Phase 5 of the Client360 PDR post-MVP backlog. This module translates a chat
question into a **bounded** call to the *existing* Client360 read functions
(:func:`list_opportunities`, :func:`customer_payload`, :func:`campaign_stats`
and :func:`list_campaigns` from :mod:`app.services.client360_pdr`).

Guardrails (deterministic, explainable, workspace-scoped):

- The action is restricted to the canonical ``andritz`` workspace family (same guard as
  :func:`ensure_client360_pdr_system_default`).
- The question -> filters translation is LLM-assisted but STRICTLY bounded to
  the existing filter vocabulary (``status``, ``customer``, ``country``,
  ``hub``, ``technology``, ``part_family``, ``confidence``, ``limit``). Any key
  or value the model returns is sanitised against the allow-list and the actual
  workspace facet vocabulary before it ever reaches the ORM. There is **never**
  any free SQL or arbitrary DB access.
- A deterministic keyword extractor is the fallback whenever the LLM is
  disabled, unavailable, or returns something out-of-vocabulary.
- Opportunity ``evidence_refs`` are preserved in the response, and a
  "Ouvrir dans Client360" CTA (route ``/client360``) is attached.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.client360 import CLIENT360_OPPORTUNITY_STATUSES
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.canonical import WorkspaceFamily
from app.services.audit_logger import emit_audit_event
from app.services.client360_pdr import (
    CAMPAIGN_SELECTION_KEYS,
    _client360_mail_ai_config,
    _mail_ai_configured,
    campaign_stats,
    customer_payload,
    list_campaigns,
    list_opportunities,
)
from app.services.workspace_features import workspace_family

_logger = logging.getLogger(__name__)

# Registry manifest binding (see ``ANDRITZ_ACTIONS`` in actions/registry.py).
CLIENT360_NL_ACTION_ID = "andritz.client360_nl_query"
CLIENT360_NL_AUDIT_EVENT = "action.andritz.client360_nl_query"

# Bounded filter vocabulary — identical to the campaign selection keys, which
# are exactly the parameters ``list_opportunities`` accepts. Kept in one place
# so the two never drift.
_ALLOWED_FILTER_KEYS: tuple[str, ...] = CAMPAIGN_SELECTION_KEYS
_CONFIDENCE_VALUES = ("high", "medium", "low")
_OPPORTUNITY_STATUSES = set(CLIENT360_OPPORTUNITY_STATUSES)
_MAX_LIMIT = 50
_DEFAULT_LIST_LIMIT = 25

CLIENT360_CTA_LABEL = "Ouvrir dans Client360"
CLIENT360_CTA_ROUTE = "/client360"

# Broad-but-scoped trigger vocabulary. The handler only responds when the
# question is clearly about the Client360 PDR domain, so normal Andritz RAG
# chat is never hijacked.
_TRIGGER_TOKENS: tuple[str, ...] = (
    "opportunit",  # opportunité / opportunities / opportunity
    "client360",
    "client 360",
    "pdr",
    "piece de rechange",
    "pieces de rechange",
    "spare part",
    "wear part",
    "wear belt",
    "potentiel",
    "potential",
    "campagne",
    "campaign",
    "parc installe",
    "installed base",
    "a relancer",
    "relance",
    "haute confiance",
    "high confidence",
    "fiche client",
)

_STATUS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "won": ("won", "gagne", "gagnee", "gagnees", "remporte", "remportees"),
    "lost": ("lost", "perdu", "perdue", "perdues"),
    "quote_requested": ("quote requested", "quote", "devis", "quotation"),
    "responded": ("responded", "repondu", "repondue", "reponse", "replied"),
    "sent": ("sent", "envoye", "envoyee", "envoyees", "envoi"),
    "draft_generated": ("draft generated", "draft", "brouillon", "brouillons"),
    "validated": ("validated", "valide", "validee", "validees"),
    "dismissed": ("dismissed", "ecarte", "ecartee", "rejete", "rejetee"),
    "detected": ("detected", "detecte", "detectee", "detectees", "nouvelle", "nouvelles", "new"),
}

_CONFIDENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "high": ("haute confiance", "high confidence", "haute", "forte", "elevee", "eleve", "high"),
    "medium": ("moyenne confiance", "medium confidence", "moyenne", "medium", "moyen"),
    "low": ("faible confiance", "low confidence", "faible", "basse", "low"),
}

_LIMIT_RE = re.compile(r"\b(?:top|meilleures?|meilleurs?|premi[eè]res?|first)\s+(\d{1,3})\b")

_LLM_SYSTEM_PROMPT = (
    "You translate an Andritz Client360 spare-parts question into a STRICT JSON "
    "filter object for an existing, read-only list API. Output ONLY a JSON object.\n"
    "Allowed keys (all optional): status, customer, country, hub, technology, "
    "part_family, confidence, limit.\n"
    "- status: one of {detected, validated, draft_generated, sent, responded, "
    "quote_requested, won, lost, dismissed}.\n"
    "- confidence: one of {high, medium, low}.\n"
    "- country, hub, technology, part_family: choose EXACTLY from the provided "
    "vocabulary; if none matches, omit the key.\n"
    "- customer: a customer name mentioned in the question, otherwise omit.\n"
    "- limit: integer 1..50, only when the user asks for a top-N.\n"
    "Never invent values. Omit any key you are unsure about. No SQL, no extra "
    "keys, no commentary."
)


def _norm(value: Any) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_client360_query(query: str) -> bool:
    normalized = _norm(query)
    if not normalized:
        return False
    return any(token in normalized for token in _TRIGGER_TOKENS)


def _facets(items: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Map normalised facet value -> canonical value for exact-match filters.

    Only values actually present in the workspace data are eligible, so a
    sanitised filter can never carry a bogus exact-match value.
    """
    facets: dict[str, dict[str, str]] = {
        "country": {},
        "hub": {},
        "technology": {},
        "part_family": {},
        "customer": {},
    }
    for item in items:
        for field in ("country", "hub", "technology", "part_family"):
            value = item.get(field)
            if value:
                facets[field].setdefault(_norm(value), str(value))
        for field in ("customer_name", "customer_key"):
            value = item.get(field)
            if value:
                facets["customer"].setdefault(_norm(value), str(item.get("customer_name") or value))
    return facets


def _sanitize_filters(raw: dict[str, Any], facets: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Bound arbitrary key/value pairs to the existing filter vocabulary.

    This is the single guarantee that the NL translation can never widen the
    query surface: unknown keys are dropped, enumerated values are validated
    against their allow-list, exact-match facet values are re-mapped to a
    canonical value that actually exists in the workspace, and free-text
    ``customer`` is only ever passed to the ORM's parametrised ``ilike``.
    """
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        if key not in _ALLOWED_FILTER_KEYS or value in (None, ""):
            continue
        if key == "confidence":
            candidate = _norm(value)
            if candidate in _CONFIDENCE_VALUES:
                out["confidence"] = candidate
        elif key == "status":
            candidate = _norm(value).replace(" ", "_")
            if candidate in _OPPORTUNITY_STATUSES:
                out["status"] = candidate
        elif key in ("country", "hub", "technology", "part_family"):
            canonical = facets.get(key, {}).get(_norm(value))
            if canonical:
                out[key] = canonical
        elif key == "customer":
            text = re.sub(r"\s+", " ", str(value)).strip()
            if text:
                out["customer"] = text[:120]
        elif key == "limit":
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            out["limit"] = max(1, min(parsed, _MAX_LIMIT))
    return out


def _deterministic_filters(query: str, facets: dict[str, dict[str, str]]) -> dict[str, Any]:
    normalized = _norm(query)
    padded = f" {normalized} "
    raw: dict[str, Any] = {}

    for status, tokens in _STATUS_KEYWORDS.items():
        if any(f" {token} " in padded for token in tokens):
            raw["status"] = status
            break

    for label, tokens in _CONFIDENCE_KEYWORDS.items():
        if any(token in normalized for token in tokens):
            raw["confidence"] = label
            break

    for field in ("country", "hub", "technology", "part_family", "customer"):
        for norm_value, canonical in facets.get(field, {}).items():
            if norm_value and norm_value in normalized:
                raw[field] = canonical
                break

    match = _LIMIT_RE.search(normalized)
    if match:
        raw["limit"] = int(match.group(1))

    return _sanitize_filters(raw, facets)


async def _llm_filters(
    db: DBSession,
    workspace: Workspace,
    query: str,
    facets: dict[str, dict[str, str]],
) -> Optional[dict[str, Any]]:
    config = _client360_mail_ai_config(db, workspace)
    configured, _reason = _mail_ai_configured(config)
    if not configured:
        return None

    vocab = {
        "country": sorted(facets["country"].values()),
        "hub": sorted(facets["hub"].values()),
        "technology": sorted(facets["technology"].values()),
        "part_family": sorted(facets["part_family"].values()),
    }
    user_prompt = (
        "Vocabulary (choose exact values from these lists, or omit):\n"
        f"{json.dumps(vocab, ensure_ascii=False)}\n\n"
        f"Question: {query}\n\n"
        "Return the JSON filter object only."
    )

    from app.llm.llm import LLM

    provider = str(config["provider"]).lower() or "openai"
    api_key = settings.openai_api_key if provider == "openai" else None
    llm = LLM(provider=provider, api_key=api_key)
    raw_text = await asyncio.wait_for(
        llm.complete(
            prompt=user_prompt,
            system_prompt=_LLM_SYSTEM_PROMPT,
            model=str(config["model"]),
            temperature=0.0,
            max_tokens=200,
            user=f"workspace:{workspace.id}:client360_nl_query",
        ),
        timeout=float(config["timeout_seconds"]),
    )
    parsed = _parse_json_object(raw_text)
    if parsed is None:
        return None
    return _sanitize_filters(parsed, facets)


def _parse_json_object(text: str) -> Optional[dict[str, Any]]:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


async def translate_query_to_filters(
    db: DBSession,
    workspace: Workspace,
    query: str,
    items: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Return ``(filters, method)`` where ``method`` is ``"llm"`` or ``"deterministic"``.

    Both paths run through :func:`_sanitize_filters`, so the result is always
    bounded to the existing filter vocabulary regardless of translation method.
    """
    facets = _facets(items)
    try:
        llm_result = await _llm_filters(db, workspace, query, facets)
    except Exception:  # noqa: BLE001 - degrade to deterministic extraction.
        _logger.warning(
            "Client360 NL translation via LLM failed; using deterministic fallback", exc_info=True
        )
        llm_result = None
    if llm_result is not None:
        return llm_result, "llm"
    return _deterministic_filters(query, facets), "deterministic"


def _detect_intent(query: str) -> str:
    normalized = _norm(query)
    if "campagne" in normalized or "campaign" in normalized:
        return "campaign"
    if (
        "fiche client" in normalized
        or "parc installe" in normalized
        or "installed base" in normalized
    ):
        return "customer"
    return "opportunities"


def _evidence_refs_for(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        for ref in item.get("evidence_refs") or []:
            key = (
                json.dumps(ref, sort_keys=True, default=str) if isinstance(ref, dict) else str(ref)
            )
            if key in seen:
                continue
            seen.add(key)
            aggregated.append(ref)
    return aggregated


def _sources_for(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in items:
        title = (
            " · ".join(
                part
                for part in (
                    item.get("customer_name"),
                    item.get("part_family"),
                    item.get("part_reference"),
                )
                if part
            )
            or "Opportunité Client360"
        )
        sources.append(
            {
                "title": title,
                "source_label": title,
                "kind": "client360_opportunity",
                "source_id": item.get("id"),
                # Preserve the opportunity evidence so the chat keeps the audit trail.
                "evidence_refs": item.get("evidence_refs") or [],
            }
        )
    return sources


def _fmt_eur(value: Any) -> str:
    try:
        return f"{float(value):,.0f} €".replace(",", " ")
    except (TypeError, ValueError):
        return "n/a"


def _cta(query_params: Optional[dict[str, str]] = None) -> dict[str, Any]:
    return {
        "label": CLIENT360_CTA_LABEL,
        "route": CLIENT360_CTA_ROUTE,
        "query_params": query_params or {},
    }


def _filter_summary(filters: dict[str, Any]) -> str:
    if not filters:
        return "tous les segments"
    labels = {
        "status": "statut",
        "customer": "client",
        "country": "pays",
        "hub": "hub",
        "technology": "technologie",
        "part_family": "famille",
        "confidence": "confiance",
        "limit": "limite",
    }
    return ", ".join(f"{labels.get(key, key)}={value}" for key, value in filters.items())


def _opportunities_response(
    db: DBSession,
    workspace: Workspace,
    filters: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    list_filters = dict(filters)
    list_filters.setdefault("limit", _DEFAULT_LIST_LIMIT)
    items = list_opportunities(db, workspace, **list_filters)
    total_gap_value = sum(float(item.get("potential_gap_value") or 0) for item in items)

    lines = [
        f"**Client360 — opportunités** ({_filter_summary(filters)}) : "
        f"{len(items)} opportunité(s), potentiel cumulé {_fmt_eur(total_gap_value)}."
    ]
    for item in items[:5]:
        lines.append(
            f"- {item.get('customer_name') or item.get('customer_key')} · "
            f"{item.get('part_family') or '—'} ({item.get('part_reference') or '—'}) — "
            f"{_fmt_eur(item.get('potential_gap_value'))} · confiance {item.get('confidence_label') or '—'}"
        )
    if not items:
        lines.append("Aucune opportunité ne correspond à ces critères.")

    return {
        "intent": "opportunities",
        "content": "\n".join(lines),
        "result": {
            "opportunities": items,
            "count": len(items),
            "potential_gap_value": round(total_gap_value, 2),
        },
        "sources": _sources_for(items),
        "evidence_refs": _evidence_refs_for(items),
        "cta": _cta({key: str(value) for key, value in filters.items() if key != "limit"}),
    }


def _customer_response(
    db: DBSession,
    workspace: Workspace,
    filters: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    customer = filters.get("customer")
    if not customer:
        # No customer resolved from the question — fall back to the list view.
        return _opportunities_response(db, workspace, filters, method)
    payload = customer_payload(db, workspace, str(customer))
    opportunities = payload.get("opportunities") or []
    customer_name = (payload.get("customer") or {}).get("name") or customer
    total_gap_value = sum(float(item.get("potential_gap_value") or 0) for item in opportunities)
    technologies = (payload.get("customer") or {}).get("technologies") or []
    lines = [
        f"**Client360 — fiche {customer_name}** : {len(opportunities)} opportunité(s), "
        f"potentiel cumulé {_fmt_eur(total_gap_value)}."
    ]
    if technologies:
        lines.append(f"Parc / technologies : {', '.join(str(t) for t in technologies)}.")
    for item in opportunities[:5]:
        lines.append(
            f"- {item.get('part_family') or '—'} ({item.get('part_reference') or '—'}) — "
            f"{_fmt_eur(item.get('potential_gap_value'))} · confiance {item.get('confidence_label') or '—'}"
        )
    return {
        "intent": "customer",
        "content": "\n".join(lines),
        "result": payload,
        "sources": _sources_for(opportunities),
        "evidence_refs": _evidence_refs_for(opportunities),
        "cta": _cta({"customer": str(customer)}),
    }


def _campaign_response(
    db: DBSession,
    workspace: Workspace,
    query: str,
    filters: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    campaigns = list_campaigns(db, workspace, limit=100)
    normalized = _norm(query)
    matched = next(
        (
            row
            for row in campaigns
            if row.get("name") and _norm(row["name"]) and _norm(row["name"]) in normalized
        ),
        None,
    )
    if matched:
        stats_payload = campaign_stats(db, workspace, matched["id"])
        stats = stats_payload.get("stats") or {}
        campaign = stats_payload.get("campaign") or {}
        content = (
            f"**Client360 — campagne {campaign.get('name')}** : "
            f"{stats.get('targeted_opportunities', 0)} opportunité(s) ciblée(s), "
            f"{stats.get('sent', 0)} envoyé(s), {stats.get('responses', 0)} réponse(s), "
            f"{stats.get('orders', 0)} commande(s), CA gagné {_fmt_eur(stats.get('won_value'))} "
            f"(potentiel {_fmt_eur(stats.get('potential_gap_value'))})."
        )
        return {
            "intent": "campaign",
            "content": content,
            "result": stats_payload,
            "sources": [
                {
                    "title": f"Campagne {campaign.get('name')}",
                    "source_label": f"Campagne {campaign.get('name')}",
                    "kind": "client360_campaign",
                    "source_id": campaign.get("id"),
                }
            ],
            "evidence_refs": [],
            "cta": _cta({"campaign": str(campaign.get("id") or "")}),
        }
    # No specific campaign matched — return the campaign overview.
    lines = [f"**Client360 — campagnes** : {len(campaigns)} campagne(s) enregistrée(s)."]
    for row in campaigns[:5]:
        lines.append(
            f"- {row.get('name')} ({row.get('campaign_type')}) · statut {row.get('status')} · "
            f"{row.get('targeted_count') or 0} cible(s), {row.get('drafts_count') or 0} brouillon(s)"
        )
    if not campaigns:
        lines.append("Aucune campagne enregistrée pour le moment.")
    return {
        "intent": "campaign",
        "content": "\n".join(lines),
        "result": {"campaigns": campaigns, "count": len(campaigns)},
        "sources": [
            {
                "title": f"Campagne {row.get('name')}",
                "source_label": f"Campagne {row.get('name')}",
                "kind": "client360_campaign",
                "source_id": row.get("id"),
            }
            for row in campaigns[:10]
        ],
        "evidence_refs": [],
        "cta": _cta(),
    }


async def handle_client360_chat_query(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str] = None,
    session_id: Optional[str] = None,
    require_trigger: bool = True,
) -> Optional[dict[str, Any]]:
    """Resolve a Client360 NL question into a bounded read + chat response.

    This powers the **dedicated** Client360 assistant surface (endpoint
    ``POST /api/v1/client360/chat``); it is intentionally NOT wired into the
    general Andritz research chat so the two are fully decoupled.

    Returns ``None`` when the workspace is not in the canonical ``andritz``
    family. When
    ``require_trigger`` is ``True`` it also returns ``None`` for questions that
    do not clearly belong to the Client360 domain (legacy keyword guard). The
    dedicated assistant passes ``require_trigger=False`` since every question on
    that surface is implicitly about Client360.
    """
    if workspace_family(workspace) != WorkspaceFamily.andritz.value:
        return None
    if not query or not query.strip():
        return None
    if require_trigger and not is_client360_query(query):
        return None

    # Single bounded scan reused for facet vocabulary and (for the list intent)
    # to seed the translation. No arbitrary DB access beyond the read API.
    scope_items = list_opportunities(db, workspace, limit=500)
    filters, method = await translate_query_to_filters(db, workspace, query, scope_items)
    intent = _detect_intent(query)

    if intent == "campaign":
        response = _campaign_response(db, workspace, query, filters, method)
    elif intent == "customer":
        response = _customer_response(db, workspace, filters, method)
    else:
        response = _opportunities_response(db, workspace, filters, method)

    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=CLIENT360_NL_AUDIT_EVENT,
        actor=(user.email or user.username or user.id) if user else "system:client360_chat",
        details={
            "action_id": CLIENT360_NL_ACTION_ID,
            "query": query,
            "intent": response["intent"],
            "filters": filters,
            "translation_method": method,
        },
    )

    return {
        "action": "client360_nl_query",
        "applied": True,
        "action_manifest_id": CLIENT360_NL_ACTION_ID,
        "intent": response["intent"],
        "filters": filters,
        "translation_method": method,
        "content": response["content"],
        "result": response["result"],
        "sources": response["sources"],
        "evidence_refs": response["evidence_refs"],
        "cta": response["cta"],
        # No auto-navigate effect: the CTA is user-driven so the chat never
        # yanks the operator out of the conversation.
        "action_effects": [],
        "requires_confirmation": False,
    }
