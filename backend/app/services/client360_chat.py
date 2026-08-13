"""Natural-language Client360 PDR queries for the Andritz workspace chat.

This module translates a chat question into a **bounded** call to the existing
Client360 read functions (:func:`list_opportunities`, :func:`customer_payload`,
:func:`campaign_stats`, :func:`list_campaigns` from :mod:`app.services.client360_pdr`).

Extended dedicated intents (Phase 3): ``customer_audit``, ``forecast``,
``navigation``, ``opportunity_detail``, ``installed_base`` — still
filter-bounded, never free SQL. ``installed_base`` answers deterministic
park aggregations ("quelle référence est la plus installée en Turquie ?")
from the persisted SPC records (« Installed base - SPC.xlsx »).

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
- Registry customer names (when available) enrich the customer facet allow-list.
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
    _raw_source_records_by_roles,
    campaign_stats,
    customer_payload,
    list_campaigns,
    list_data_sources,
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
    "base installee",
    "plus installe",
    "most installed",
    "a relancer",
    "relance",
    "haute confiance",
    "high confidence",
    "fiche client",
    "audit",
    "audite",
    "prevoir",
    "a prevoir",
    "forecast",
    "echeance",
    "navig",
    "onglet",
    "pourquoi cette opportun",
    "formule",
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

# Installed-base (SPC park) intent vocabulary. Matched on the ``_norm``-alised
# question, so « la plus installée » / « les plus installées » both hit
# "plus installe".
_INSTALLED_BASE_TOKENS: tuple[str, ...] = (
    "plus installe",
    "parc installe",
    "base installee",
    "installed base",
    "most installed",
)

# The workspace data mixes ISO-ish country codes (SPC/registry: "TR", "GR")
# with full names (pilot opportunities: "Turkey", "Greece") and users ask in
# French (« en Turquie »). Each group lists the normalised spellings that
# designate the same country, so facet lookups and record filters can match
# across conventions without any free-text widening.
_COUNTRY_EQUIVALENTS: tuple[frozenset[str], ...] = (
    frozenset({"tr", "turkey", "turquie", "turkiye"}),
    frozenset({"gr", "greece", "grece"}),
)

# Free-text part filter (e.g. « la référence MPC la plus installée »):
# either the token right after « référence(s) », or an uppercase code token.
_PART_KEYWORD_RE = re.compile(
    r"\br[ée]f(?:[ée]rences?)?\.?\s+([A-Za-z0-9][A-Za-z0-9\-_./]{1,39})",
    re.IGNORECASE,
)
_PART_CODE_RE = re.compile(r"\b([A-Z][A-Z0-9][A-Z0-9\-_./]{1,38})\b")

# Question words / domain acronyms that must never become a part text filter.
_PART_FILTER_STOP_TOKENS = frozenset(
    {
        "quel", "quels", "quelle", "quelles", "combien", "donne", "montre",
        "liste", "top", "les", "la", "le", "un", "une", "des", "de", "du",
        "en", "et", "ou", "chez", "nos", "vos", "est", "plus", "pour",
        "installe", "installes", "installee", "installees", "installed",
        "most", "base", "parc", "reference", "references", "ref",
        "client", "clients", "pdr", "spc", "spl", "ib", "ibs", "sspa",
        "client360", "what", "which",
    }
)

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


def _registry_customer_names(db: DBSession, workspace: Workspace) -> list[str]:
    """Collect registry / directory customer names as an allow-list for facets.

    Prefers Phase-2 ``list_customers`` when present; otherwise falls back to the
    project-registry index / data-source records. Failures degrade to ``[]``.
    """
    names: list[str] = []

    try:
        from app.services import client360_pdr as pdr_mod

        list_customers = getattr(pdr_mod, "list_customers", None)
    except Exception:  # noqa: BLE001
        list_customers = None

    if callable(list_customers):
        try:
            payload = list_customers(db, workspace)
        except Exception:  # noqa: BLE001 - Phase 2 helper may still be mid-flight.
            _logger.debug("list_customers unavailable for chat facets", exc_info=True)
            payload = None
        rows: list[Any]
        if isinstance(payload, dict):
            rows = list(payload.get("customers") or payload.get("items") or [])
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        for row in rows:
            if isinstance(row, dict):
                name = row.get("customer_name") or row.get("name") or row.get("customer_key")
            else:
                name = row
            if name:
                names.append(str(name))
        if names:
            return list(dict.fromkeys(names))

    try:
        from app.services.client360_spl_adapter import load_project_registry_index

        index = load_project_registry_index(db, workspace)
    except Exception:  # noqa: BLE001
        _logger.debug("project registry index unavailable for chat facets", exc_info=True)
        return []

    for entry in (index or {}).values():
        if not isinstance(entry, dict):
            continue
        name = entry.get("customer_name") or entry.get("customer_key")
        if name:
            names.append(str(name))
    return list(dict.fromkeys(names))


def _merge_facet_allowlist(
    facets: dict[str, dict[str, str]],
    field: str,
    values: list[str],
) -> dict[str, dict[str, str]]:
    """Enrich one facet map with extra allow-listed values (bounded, no free text)."""
    facet = dict(facets.get(field) or {})
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            continue
        facet.setdefault(_norm(text), text[:120])
    merged = dict(facets)
    merged[field] = facet
    return merged


def _merge_customer_allowlist(
    facets: dict[str, dict[str, str]],
    customer_names: list[str],
) -> dict[str, dict[str, str]]:
    """Enrich the customer facet map with registry/directory names (allow-list)."""
    return _merge_facet_allowlist(facets, "customer", customer_names)


def _country_aliases(norm_value: str) -> frozenset[str]:
    for group in _COUNTRY_EQUIVALENTS:
        if norm_value in group:
            return group
    return frozenset()


def _expand_country_aliases(country_facet: dict[str, str]) -> dict[str, str]:
    """Register known spellings (« turquie », "TR", "Turkey") of present countries.

    Only countries already in the facet vocabulary gain aliases, so the filter
    surface never widens beyond values that exist in the workspace data.
    """
    expanded = dict(country_facet)
    for norm_value, canonical in list(country_facet.items()):
        for alias in _country_aliases(norm_value):
            expanded.setdefault(alias, canonical)
    return expanded


def _country_matches(expected: Any, actual: Any) -> bool:
    """True when both values designate the same country across conventions."""
    expected_norm = _norm(expected)
    if not expected_norm:
        return True
    actual_norm = _norm(actual)
    if expected_norm == actual_norm:
        return True
    return actual_norm in _country_aliases(expected_norm)


def _build_facets(
    db: DBSession,
    workspace: Workspace,
    items: list[dict[str, Any]],
    *,
    extra_facet_values: Optional[dict[str, list[str]]] = None,
) -> dict[str, dict[str, str]]:
    facets = _merge_customer_allowlist(_facets(items), _registry_customer_names(db, workspace))
    for field, values in (extra_facet_values or {}).items():
        if field in facets:
            facets = _merge_facet_allowlist(facets, field, values)
    facets["country"] = _expand_country_aliases(facets.get("country") or {})
    return facets


def _sanitize_filters(raw: dict[str, Any], facets: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Bound arbitrary key/value pairs to the existing filter vocabulary.

    This is the single guarantee that the NL translation can never widen the
    query surface: unknown keys are dropped, enumerated values are validated
    against their allow-list, exact-match facet values are re-mapped to a
    canonical value that actually exists in the workspace, and free-text
    ``customer`` is only ever passed to the ORM's parametrised ``ilike``.
    When a registry/directory allow-list is present, customer values are
    remapped to a canonical allow-listed name when possible.
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
            if not text:
                continue
            canonical = facets.get("customer", {}).get(_norm(text))
            out["customer"] = (canonical or text)[:120]
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

    # Prefer longer facet matches so "wear belts" wins over "wear" if both exist.
    for field in ("country", "hub", "technology", "part_family", "customer"):
        best: tuple[int, str] | None = None
        for norm_value, canonical in facets.get(field, {}).items():
            if not norm_value:
                continue
            # Short values (country codes like "TR") only count as whole words,
            # otherwise they would fire inside unrelated words ("montre" ⊃ "tr").
            if len(norm_value) <= 3:
                if f" {norm_value} " not in padded:
                    continue
            elif norm_value not in normalized:
                continue
            score = len(norm_value)
            if best is None or score > best[0]:
                best = (score, canonical)
        if best is not None:
            raw[field] = best[1]

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

    # ``set`` because alias facet keys (« turquie » → "TR") share canonicals.
    vocab = {
        "country": sorted(set(facets["country"].values())),
        "hub": sorted(set(facets["hub"].values())),
        "technology": sorted(set(facets["technology"].values())),
        "part_family": sorted(set(facets["part_family"].values())),
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
    *,
    extra_facet_values: Optional[dict[str, list[str]]] = None,
) -> tuple[dict[str, Any], str]:
    """Return ``(filters, method)`` where ``method`` is ``"llm"`` or ``"deterministic"``.

    Both paths run through :func:`_sanitize_filters`, so the result is always
    bounded to the existing filter vocabulary regardless of translation method.
    ``extra_facet_values`` lets an intent enrich the facet allow-list with
    values from its own data (e.g. SPC park countries), still bounded.
    """
    facets = _build_facets(db, workspace, items, extra_facet_values=extra_facet_values)
    deterministic = _deterministic_filters(query, facets)
    try:
        llm_result = await _llm_filters(db, workspace, query, facets)
    except Exception:  # noqa: BLE001 - degrade to deterministic extraction.
        _logger.warning(
            "Client360 NL translation via LLM failed; using deterministic fallback", exc_info=True
        )
        llm_result = None
    if llm_result is not None:
        # The LLM vocabulary does not include customer names, so the model may
        # omit that filter. Deterministic extraction fills any facet the LLM
        # missed; the LLM keeps precedence on facets it did resolve.
        return {**deterministic, **llm_result}, "llm"
    return deterministic, "deterministic"


_GREETING_TOKENS = {
    "hello",
    "hi",
    "hey",
    "yo",
    "bonjour",
    "salut",
    "coucou",
    "bonsoir",
    "hola",
    "test",
    "ping",
    "ca",
    "va",
}

_HELP_TOKENS = (
    "que sais tu",
    "que peux tu",
    "que sait",
    "comment marche",
    "comment fonctionne",
    "capacite",
    "help",
    "aide",
)


def _is_greeting(normalized: str) -> bool:
    words = normalized.split()
    return bool(words) and len(words) <= 3 and all(word in _GREETING_TOKENS for word in words)


def _detect_intent(query: str) -> str:
    normalized = _norm(query)
    # Small talk must never fall through to the opportunities dump.
    if _is_greeting(normalized):
        return "help"
    asks_why = any(
        token in normalized
        for token in ("pourquoi", "explique", "explication", "formule", "comment calcul", "comment est calcul")
    )
    mentions_opportunity = any(
        token in normalized
        for token in ("opportun", "potentiel", "ecart", "gap", "wear", "piece", "part family", "part_family")
    )
    if (
        "detail opportun" in normalized
        or "opportunity detail" in normalized
        or (asks_why and mentions_opportunity)
        or ("formule" in normalized and mentions_opportunity)
    ):
        return "opportunity_detail"
    if any(
        token in normalized
        for token in (
            "prevoir",
            "a prevoir",
            "forecast",
            "echeance",
            "echeances",
            "next due",
            "pieces a prevoir",
            "quoi prevoir",
        )
    ):
        return "forecast"
    if any(
        token in normalized
        for token in (
            "audit",
            "audite",
            "auditer",
            "data gap",
            "data gaps",
            "lacune",
            "lacunes",
        )
    ):
        return "customer_audit"
    if any(
        token in normalized
        for token in (
            "navig",
            "ouvre",
            "ouvrir",
            "onglet",
            "amene",
            "va vers",
            "montre moi la page",
            "go to",
            "open tab",
        )
    ):
        return "navigation"
    if "campagne" in normalized or "campaign" in normalized:
        return "campaign"
    # Park aggregation questions (« la référence la plus installée … ») must
    # win over the customer fiche and the opportunities fallback.
    if any(token in normalized for token in _INSTALLED_BASE_TOKENS):
        return "installed_base"
    if "fiche client" in normalized:
        return "customer"
    # Checked last so e.g. "aide-moi a auditer Septona" still routes to audit.
    if any(token in normalized for token in _HELP_TOKENS):
        return "help"
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


_MAX_CHAT_SOURCES = 10


def _sources_for(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
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
        # Many opportunities share customer+family labels; showing each one
        # floods the chat with duplicate lines. The full audit trail stays in
        # evidence_refs, which aggregates every opportunity.
        if title in seen_titles:
            continue
        seen_titles.add(title)
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
        if len(sources) >= _MAX_CHAT_SOURCES:
            break
    return sources


def _plain_text(content: str) -> str:
    # The dedicated chat surface renders plain text; markdown markers would
    # otherwise show up literally (e.g. "**Client360**").
    return re.sub(r"\*\*(.+?)\*\*", r"\1", content).replace("`", "")


def _help_response() -> dict[str, Any]:
    content = "\n".join(
        [
            "Assistant Client360 — je réponds uniquement sur les données Client360 "
            "(lectures bornées et sourcées, jamais de SQL libre).",
            "Exemples de questions :",
            "- « Opportunités en Turquie en confiance haute »",
            "- « Fiche client Septona » ou « Audite Septona »",
            "- « Quelle est la référence MPC la plus installée chez nos clients en Turquie ? » (parc installé)",
            "- « Quelles pièces à prévoir dans les 6 prochains mois ? »",
            "- « Pourquoi cette opportunité O'ring ? » (détail du calcul)",
            "- « Campagnes en cours » ou « Ouvre l'onglet campagnes »",
        ]
    )
    return {
        "intent": "help",
        "content": content,
        "result": {},
        "sources": [],
        "evidence_refs": [],
        "cta": _cta(),
    }


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


def _fmt_qty(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _opportunity_formula_lines(item: dict[str, Any]) -> list[str]:
    """Explain gap = theoretical annual need − known sales (deterministic engine).

    Engine formula: ``installed × recommended × (52 / periodicity_weeks) − sales``.
    The product plan shorthand is « installed × periodicity − sales »; we surface
    the full explainable inputs used by :func:`calculate_annual_theoretical_qty`.
    """
    installed = item.get("installed_quantity")
    recommended = item.get("recommended_quantity")
    periodicity = item.get("periodicity_weeks")
    sales = item.get("sales_known_qty")
    annual = item.get("annual_theoretical_qty")
    gap_qty = item.get("potential_gap_qty")
    gap_value = item.get("potential_gap_value")

    lines = [
        "Formule d'opportunité (déterministe) :",
        "- besoin_annuel ≈ installé × qté_recommandée × (52 / périodicité_semaines)",
        "- écart ≈ max(besoin_annuel − ventes_connues, 0)",
        (
            f"- entrées : installé={_fmt_qty(installed)}, "
            f"recommandé={_fmt_qty(recommended)}, "
            f"périodicité={_fmt_qty(periodicity)} sem., "
            f"ventes={_fmt_qty(sales)}"
        ),
        (
            f"- résultat : besoin_annuel={_fmt_qty(annual)}, "
            f"écart_qté={_fmt_qty(gap_qty)}, "
            f"écart_valeur={_fmt_eur(gap_value)}"
        ),
    ]
    return lines


def _pick_opportunity(
    db: DBSession,
    workspace: Workspace,
    filters: dict[str, Any],
) -> Optional[dict[str, Any]]:
    list_filters = dict(filters)
    list_filters.setdefault("limit", 5)
    items = list_opportunities(db, workspace, **list_filters)
    return items[0] if items else None


def _customer_audit_response(
    db: DBSession,
    workspace: Workspace,
    filters: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    customer = filters.get("customer")
    if not customer:
        return {
            "intent": "customer_audit",
            "content": (
                "**Client360 — audit client** : précisez un client du registre "
                "(ex. « audite Eruslu ») pour obtenir fiche, lacunes et échéances."
            ),
            "result": {"customer": None, "data_gaps": [], "next_due": []},
            "sources": [],
            "evidence_refs": [],
            "cta": _cta({"view": "customer"}),
        }

    payload = customer_payload(db, workspace, str(customer))
    opportunities = payload.get("opportunities") or []
    customer_name = (payload.get("customer") or {}).get("name") or customer
    data_gaps = list(payload.get("data_gaps") or [])
    next_due = list(payload.get("next_due") or [])
    if not next_due:
        for item in opportunities:
            due = item.get("next_due_at")
            if due:
                next_due.append(
                    {
                        "part_family": item.get("part_family"),
                        "part_reference": item.get("part_reference"),
                        "next_due_at": due,
                        "opportunity_id": item.get("id"),
                    }
                )
        next_due = sorted(next_due, key=lambda row: str(row.get("next_due_at") or ""))[:10]

    projects = payload.get("projects") or []
    machines = payload.get("machines") or []
    purchases = payload.get("purchases") or []
    total_gap_value = sum(float(item.get("potential_gap_value") or 0) for item in opportunities)

    lines = [
        f"**Client360 — audit {customer_name}** : {len(opportunities)} opportunité(s), "
        f"potentiel {_fmt_eur(total_gap_value)}."
    ]
    if projects:
        lines.append(f"Projets registre : {len(projects)}.")
    if machines:
        lines.append(f"Machines / parc : {len(machines)}.")
    if purchases:
        lines.append(f"Achats / ventes connus : {len(purchases)}.")
    if data_gaps:
        lines.append("Lacunes données : " + ", ".join(str(gap) for gap in data_gaps[:12]) + ".")
    else:
        lines.append("Aucune lacune structurante signalée sur les opportunités.")
    if next_due:
        lines.append("Échéances :")
        for row in next_due[:5]:
            lines.append(
                f"- {row.get('part_family') or '—'} ({row.get('part_reference') or '—'}) "
                f"→ {str(row.get('next_due_at') or '')[:10]}"
            )
    else:
        lines.append("Aucune échéance déterministe disponible (historique d'achat ou périodicité manquants).")

    return {
        "intent": "customer_audit",
        "content": "\n".join(lines),
        "result": {
            "customer": payload.get("customer"),
            "data_gaps": data_gaps,
            "next_due": next_due,
            "projects": projects,
            "machines": machines,
            "purchases": purchases,
            "opportunities": opportunities,
        },
        "sources": _sources_for(opportunities),
        "evidence_refs": _evidence_refs_for(opportunities),
        "cta": _cta({"customer": str(customer_name), "view": "customer"}),
    }


def _normalize_forecast_result(result: Any) -> Optional[dict[str, Any]]:
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"items": result, "count": len(result)}
    return {"value": result}


def _call_forecast_helper(
    db: DBSession,
    workspace: Workspace,
    customer: Optional[str],
    filters: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Best-effort call into Phase-4 ``client360_forecast`` when importable."""
    try:
        from app.services import client360_forecast as forecast_mod
    except ImportError:
        return None

    # Canonical Phase-4 entry point: keyword-only customer_key signature.
    next_due_fn = getattr(forecast_mod, "customer_next_due", None)
    if callable(next_due_fn) and customer:
        from app.services.client360_pdr import normalize_customer_key

        try:
            items = next_due_fn(
                db,
                workspace,
                customer_key=normalize_customer_key(customer),
                customer_name=str(customer),
            )
            return _normalize_forecast_result(items)
        except Exception:  # noqa: BLE001
            _logger.warning("client360_forecast customer_next_due failed", exc_info=True)
            return None

    fn = None
    for name in (
        "customer_forecast",
        "forecast_customer",
        "list_customer_due_items",
        "due_items_for_customer",
        "forecast_due_parts",
    ):
        candidate = getattr(forecast_mod, name, None)
        if callable(candidate):
            fn = candidate
            break
    if fn is None:
        return None

    attempts = [
        lambda: fn(db, workspace, customer),
        lambda: fn(db, workspace, customer=customer),
        lambda: fn(db, workspace),
    ]
    for attempt in attempts:
        try:
            return _normalize_forecast_result(attempt())
        except TypeError:
            continue
        except Exception:  # noqa: BLE001
            _logger.warning("client360_forecast helper failed", exc_info=True)
            return None
    return None


def _forecast_response(
    db: DBSession,
    workspace: Workspace,
    filters: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    customer = filters.get("customer")
    forecast = _call_forecast_helper(db, workspace, str(customer) if customer else None, filters)
    cta_params = {key: str(value) for key, value in filters.items() if key != "limit"}
    cta_params.setdefault("view", "customer")

    if forecast is not None:
        items = list(forecast.get("items") or forecast.get("next_due") or forecast.get("due") or [])
        lines = [
            f"**Client360 — prévisions** ({_filter_summary(filters)}) : "
            f"{len(items)} échéance(s) déterministe(s)."
        ]
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('customer_name') or customer or '—'} · "
                f"{item.get('part_family') or '—'} ({item.get('part_reference') or '—'}) → "
                f"{str(item.get('next_due_at') or item.get('due_at') or 'n/a')[:10]}"
            )
        if not items and forecast.get("message"):
            lines.append(str(forecast["message"]))
        sources = _sources_for(
            [
                item
                for item in items
                if isinstance(item, dict) and (item.get("id") or item.get("evidence_refs"))
            ]
        )
        evidence = _evidence_refs_for(items if all(isinstance(i, dict) for i in items) else [])
        return {
            "intent": "forecast",
            "content": "\n".join(lines),
            "result": forecast,
            "sources": sources,
            "evidence_refs": evidence,
            "cta": _cta(cta_params),
        }

    # Deterministic stub while Phase 4 lands: surface opportunity due dates / gaps.
    list_filters = dict(filters)
    list_filters.setdefault("limit", _DEFAULT_LIST_LIMIT)
    opportunities = list_opportunities(db, workspace, **list_filters)
    due_rows = [item for item in opportunities if item.get("next_due_at")]
    gaps = sorted({gap for item in opportunities for gap in (item.get("data_gaps") or [])})
    scope = f" pour {customer}" if customer else ""
    lines = [
        f"**Client360 — prévisions{scope}** : moteur forecast indisponible pour l'instant.",
        "Estimation déterministe dégradée à partir des opportunités déjà calculées "
        "(last purchase + périodicité absents → pas de prévision fiable).",
    ]
    if due_rows:
        lines.append(f"{len(due_rows)} échéance(s) déjà présentes sur les opportunités :")
        for item in due_rows[:5]:
            lines.append(
                f"- {item.get('customer_name') or '—'} · "
                f"{item.get('part_family') or '—'} → {str(item.get('next_due_at'))[:10]}"
            )
    else:
        lines.append(
            "Aucune échéance `next_due_at` en base. "
            "Brancher sales_orders + périodicité (Phase 4) pour calculer les pièces à prévoir."
        )
    if gaps:
        lines.append("Lacunes bloquantes observées : " + ", ".join(gaps[:8]) + ".")

    return {
        "intent": "forecast",
        "content": "\n".join(lines),
        "result": {
            "forecast_available": False,
            "stub": True,
            "opportunities_with_due": due_rows,
            "data_gaps": gaps,
            "message": (
                "client360_forecast not importable; deterministic stub pointing to data gaps"
            ),
        },
        "sources": _sources_for(due_rows or opportunities[:5]),
        "evidence_refs": _evidence_refs_for(due_rows or opportunities[:5]),
        "cta": _cta(cta_params),
    }


def _navigation_response(
    filters: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    normalized = _norm(query)
    view = "opportunities"
    if any(token in normalized for token in ("campagne", "campaign", "mail", "suivi")):
        view = "campaigns"
    elif any(token in normalized for token in ("mapping", "regle", "règle")):
        view = "mapping"
    elif any(token in normalized for token in ("donnee", "source", "data")):
        view = "data"
    elif any(
        token in normalized
        for token in ("fiche", "client", "parc", "audit", "customer", "echeance", "prevoir")
    ):
        view = "customer"

    query_params = {key: str(value) for key, value in filters.items() if key != "limit"}
    query_params["view"] = view
    if filters.get("customer"):
        query_params["customer"] = str(filters["customer"])

    lines = [
        f"**Client360 — navigation** : ouvrir l'onglet `{view}`",
    ]
    if query_params.get("customer"):
        lines.append(f"avec le client `{query_params['customer']}`.")
    else:
        lines.append("avec les filtres résolus de la question.")
    if filters:
        lines.append(f"Filtres : {_filter_summary(filters)}.")

    return {
        "intent": "navigation",
        "content": "\n".join(lines),
        "result": {"view": view, "query_params": query_params},
        "sources": [],
        "evidence_refs": [],
        "cta": _cta(query_params),
    }


def _opportunity_detail_response(
    db: DBSession,
    workspace: Workspace,
    filters: dict[str, Any],
    method: str,
) -> dict[str, Any]:
    item = _pick_opportunity(db, workspace, filters)
    if not item:
        return {
            "intent": "opportunity_detail",
            "content": (
                "**Client360 — détail opportunité** : aucune opportunité ne correspond "
                f"à {_filter_summary(filters)}. Affinez client / famille / référence."
            ),
            "result": {"opportunity": None, "formula": None},
            "sources": [],
            "evidence_refs": [],
            "cta": _cta({key: str(value) for key, value in filters.items() if key != "limit"}),
        }

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
        or "Opportunité"
    )
    lines = [
        f"**Client360 — pourquoi {title} ?**",
        *_opportunity_formula_lines(item),
    ]
    evidence = item.get("evidence_refs") or []
    if evidence:
        lines.append("Preuves d'entrée :")
        for ref in evidence[:5]:
            if isinstance(ref, dict):
                label = ref.get("filename") or ref.get("label") or ref.get("kind") or "source"
                extra = ref.get("row") or ref.get("rows") or ref.get("line")
                lines.append(f"- {label}" + (f" (ligne {extra})" if extra is not None else ""))
            else:
                lines.append(f"- {ref}")

    cta_params = {key: str(value) for key, value in filters.items() if key != "limit"}
    if item.get("customer_name"):
        cta_params["customer"] = str(item["customer_name"])
    if item.get("id"):
        cta_params["opportunity"] = str(item["id"])

    return {
        "intent": "opportunity_detail",
        "content": "\n".join(lines),
        "result": {
            "opportunity": item,
            "formula": {
                "annual_theoretical_qty": (
                    "installed_quantity × recommended_quantity × (52 / periodicity_weeks)"
                ),
                "potential_gap_qty": "max(annual_theoretical_qty − sales_known_qty, 0)",
                "plan_shorthand": "installed × recommended × 52/periodicity − sales",
                "inputs": {
                    "installed_quantity": item.get("installed_quantity"),
                    "recommended_quantity": item.get("recommended_quantity"),
                    "periodicity_weeks": item.get("periodicity_weeks"),
                    "sales_known_qty": item.get("sales_known_qty"),
                },
                "outputs": {
                    "annual_theoretical_qty": item.get("annual_theoretical_qty"),
                    "potential_gap_qty": item.get("potential_gap_qty"),
                    "potential_gap_value": item.get("potential_gap_value"),
                },
            },
        },
        "sources": _sources_for([item]),
        "evidence_refs": _evidence_refs_for([item]),
        "cta": _cta(cta_params),
    }


def _installed_base_records(db: DBSession, workspace: Workspace) -> list[dict[str, Any]]:
    """SPC park records (aggregated customer × material at ingestion).

    The same SFTP file can be registered under several ``Client360DataSource``
    rows (with/without folder prefix in the label), so rows are deduplicated on
    (customer, part_reference) first-seen — same convention as the purchases
    reader in :mod:`app.services.client360_pdr`.
    """
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in _raw_source_records_by_roles(db, workspace, {"spc"}):
        ref_key = _norm(record.get("part_reference"))
        if not ref_key:
            continue
        key = (str(record.get("customer_key") or ""), ref_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _installed_base_part_filter(query: str, records: list[dict[str, Any]]) -> Optional[str]:
    """Extract a bounded free-text part filter (« MPC ») from the question.

    Candidates are the token following « référence(s) » and uppercase code
    tokens. Anything that resolves to a country, a customer or a technology of
    the park is rejected so facet values never leak into the text filter. The
    filter is only ever applied as a case-insensitive substring match in
    Python — never SQL.
    """
    candidates: list[str] = []
    keyword_match = _PART_KEYWORD_RE.search(query)
    if keyword_match:
        candidates.append(keyword_match.group(1))
    candidates.extend(_PART_CODE_RE.findall(query))

    excluded: set[str] = set(_PART_FILTER_STOP_TOKENS)
    for group in _COUNTRY_EQUIVALENTS:
        excluded.update(group)
    for record in records:
        for field in ("country", "technology"):
            value_norm = _norm(record.get(field))
            if value_norm:
                excluded.add(value_norm)
    customer_norms = {
        _norm(record.get("customer_name")) for record in records if record.get("customer_name")
    }

    for candidate in candidates:
        text = str(candidate).strip().strip(".,;:!?")[:40]
        norm = _norm(text)
        if len(norm) < 2 or norm in excluded:
            continue
        if any(norm in name or name in norm for name in customer_norms if name):
            continue
        return text
    return None


def _short_text(value: Any, max_len: int = 60) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" |")
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _installed_base_scope_summary(
    country: Any, customer: Any, part_filter: Optional[str]
) -> str:
    parts: list[str] = []
    if country:
        parts.append(f"pays={country}")
    if customer:
        parts.append(f"client={customer}")
    if part_filter:
        parts.append(f"filtre={part_filter}")
    return ", ".join(parts) if parts else "tout le parc"


def _installed_base_sources(
    db: DBSession,
    workspace: Workspace,
    source_files: dict[str, str],
) -> list[dict[str, Any]]:
    """Chat sources for the contributing SPC files (Client360DataSource rows)."""
    serialized = {
        item.get("id"): item
        for item in list_data_sources(db, workspace)
        if item.get("id")
    }
    sources: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for source_id, fallback_filename in source_files.items():
        row = serialized.get(source_id) or {}
        filename = row.get("filename") or row.get("label") or fallback_filename
        if not filename or filename in seen_titles:
            continue
        seen_titles.add(filename)
        evidence = row.get("evidence_refs") or [
            {"kind": "client360_data_source", "source_id": source_id, "filename": filename}
        ]
        sources.append(
            {
                "title": filename,
                "source_label": filename,
                "kind": "client360_data_source",
                "source_id": source_id,
                "evidence_refs": evidence,
            }
        )
        if len(sources) >= _MAX_CHAT_SOURCES:
            break
    return sources


def _installed_base_response(
    db: DBSession,
    workspace: Workspace,
    query: str,
    records: list[dict[str, Any]],
    filters: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic park aggregation: top references by installed quantity.

    Bounded read: persisted SPC records filtered in Python on the sanitised
    country/customer facets plus an optional free-text part filter, then
    summed per reference. No SQL is built from the question.
    """
    part_filter = _installed_base_part_filter(query, records)
    country = filters.get("country")
    customer = filters.get("customer")
    top_n = max(1, min(int(filters.get("limit") or 5), 10))
    scope = _installed_base_scope_summary(country, customer, part_filter)
    cta_params: dict[str, str] = {"view": "customer"}
    if country:
        cta_params["country"] = str(country)
    if customer:
        cta_params["customer"] = str(customer)
    applied_filters = {
        key: value
        for key, value in (
            ("country", country),
            ("customer", customer),
            ("part_filter", part_filter),
        )
        if value
    }

    if not records:
        return {
            "intent": "installed_base",
            "content": (
                "**Client360 — parc installé** : aucune donnée de parc (fichier SPC) "
                "n'est chargée dans ce workspace."
            ),
            "result": {"installed_base": [], "count": 0, "filters": applied_filters},
            "sources": [],
            "evidence_refs": [],
            "cta": _cta(cta_params),
        }

    customer_norm = _norm(customer) if customer else ""
    part_norm = _norm(part_filter) if part_filter else ""
    matched: list[dict[str, Any]] = []
    for record in records:
        if country and not _country_matches(country, record.get("country")):
            continue
        if customer_norm:
            haystack = _norm(
                f"{record.get('customer_name') or ''} {record.get('customer_key') or ''}"
            )
            if customer_norm not in haystack:
                continue
        if part_norm:
            haystack = _norm(
                f"{record.get('part_reference') or ''} {record.get('part_description') or ''}"
            )
            if part_norm not in haystack:
                continue
        matched.append(record)

    if not matched:
        return {
            "intent": "installed_base",
            "content": "\n".join(
                [
                    "**Client360 — parc installé** : aucune référence trouvée pour ce filtre.",
                    f"Filtres compris : {scope}.",
                ]
            ),
            "result": {
                "installed_base": [],
                "count": 0,
                "total_installed_quantity": 0,
                "customer_count": 0,
                "filters": applied_filters,
            },
            "sources": [],
            "evidence_refs": [],
            "cta": _cta(cta_params),
        }

    buckets: dict[str, dict[str, Any]] = {}
    customers: set[str] = set()
    total_qty = 0.0
    source_files: dict[str, str] = {}
    for record in matched:
        reference = str(record.get("part_reference"))
        try:
            qty = float(record.get("installed_quantity") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        bucket = buckets.setdefault(
            _norm(reference),
            {
                "part_reference": reference,
                "part_description": None,
                "installed_quantity": 0.0,
                "customer_keys": set(),
            },
        )
        bucket["installed_quantity"] += qty
        total_qty += qty
        if not bucket["part_description"] and record.get("part_description"):
            bucket["part_description"] = str(record["part_description"])
        customer_key = str(record.get("customer_key") or _norm(record.get("customer_name")))
        if customer_key:
            bucket["customer_keys"].add(customer_key)
            customers.add(customer_key)
        source_id = record.get("source_id")
        if source_id:
            source_files.setdefault(str(source_id), str(record.get("source_filename") or ""))

    top = sorted(
        buckets.values(),
        key=lambda bucket: (-bucket["installed_quantity"], bucket["part_reference"]),
    )
    lines = [
        f"**Client360 — parc installé** ({scope}) : {len(buckets)} référence(s), "
        f"{_fmt_qty(total_qty)} unité(s) chez {len(customers)} client(s)."
    ]
    for bucket in top[:top_n]:
        lines.append(
            f"- {bucket['part_reference']} · {_short_text(bucket['part_description']) or '—'} · "
            f"{_fmt_qty(bucket['installed_quantity'])} unité(s) · "
            f"{len(bucket['customer_keys'])} client(s)"
        )

    sources = _installed_base_sources(db, workspace, source_files)
    return {
        "intent": "installed_base",
        "content": "\n".join(lines),
        "result": {
            "installed_base": [
                {
                    "part_reference": bucket["part_reference"],
                    "part_description": bucket["part_description"],
                    "installed_quantity": round(bucket["installed_quantity"], 4),
                    "customer_count": len(bucket["customer_keys"]),
                }
                for bucket in top[:top_n]
            ],
            "count": len(buckets),
            "total_installed_quantity": round(total_qty, 4),
            "customer_count": len(customers),
            "filters": applied_filters,
        },
        "sources": sources,
        "evidence_refs": _evidence_refs_for(sources),
        "cta": _cta(cta_params),
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

    intent = _detect_intent(query)
    if intent == "help":
        # Greetings/help never need the opportunity scan or filter translation.
        filters, method = {}, "none"
        response = _help_response()
        return _finalize_answer(db, workspace, user, query, response, filters, method)

    # Single bounded scan reused for facet vocabulary and (for the list intent)
    # to seed the translation. No arbitrary DB access beyond the read API.
    scope_items = list_opportunities(db, workspace, limit=500)
    spc_records: list[dict[str, Any]] = []
    extra_facet_values: Optional[dict[str, list[str]]] = None
    if intent == "installed_base":
        # The opportunity facets do not necessarily cover the whole SPC park
        # (countries come as "TR"/"GR" codes there); enrich the allow-list with
        # the park's own values so « en Turquie » resolves even without
        # matching opportunities.
        spc_records = _installed_base_records(db, workspace)
        extra_facet_values = {
            "country": [r["country"] for r in spc_records if r.get("country")],
            "customer": [r["customer_name"] for r in spc_records if r.get("customer_name")],
        }
    filters, method = await translate_query_to_filters(
        db, workspace, query, scope_items, extra_facet_values=extra_facet_values
    )

    if intent == "campaign":
        response = _campaign_response(db, workspace, query, filters, method)
    elif intent == "customer":
        response = _customer_response(db, workspace, filters, method)
    elif intent == "customer_audit":
        response = _customer_audit_response(db, workspace, filters, method)
    elif intent == "forecast":
        response = _forecast_response(db, workspace, filters, method)
    elif intent == "navigation":
        response = _navigation_response(filters, query)
    elif intent == "opportunity_detail":
        response = _opportunity_detail_response(db, workspace, filters, method)
    elif intent == "installed_base":
        response = _installed_base_response(db, workspace, query, spc_records, filters)
    else:
        response = _opportunities_response(db, workspace, filters, method)

    return _finalize_answer(db, workspace, user, query, response, filters, method)


def _finalize_answer(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    query: str,
    response: dict[str, Any],
    filters: dict[str, Any],
    method: str,
) -> dict[str, Any]:
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
        "content": _plain_text(response["content"]),
        "result": response["result"],
        "sources": response["sources"],
        "evidence_refs": response["evidence_refs"],
        "cta": response["cta"],
        # No auto-navigate effect: the CTA is user-driven so the chat never
        # yanks the operator out of the conversation.
        "action_effects": [],
        "requires_confirmation": False,
    }
