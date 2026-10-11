"""Exhaustive cross-project enumeration via a Qdrant ``project_code`` facet.

For ``transversal_inventory`` answer-profile questions of the form "which
projects use/have <equipment>" the LLM otherwise enumerates from the few dozen
retrieved chunks and returns a *partial* list (e.g. ~48 of ~130 projects for a
common pump brand). The complete answer is a deterministic metadata
aggregation: Qdrant exposes a keyword index on the ``project_code`` payload
field, so a ``facet`` over that key — filtered by a full-text match of the
query's discriminating equipment term(s) against the chunk ``content`` — returns
every distinct project that mentions the equipment, with per-project counts.

The module is deliberately defensive: any Qdrant error, an unsupported facet, a
non-Qdrant backend, or an unresolved discriminating term yields ``None`` so the
caller transparently falls back to the existing deep-retrieval behaviour (no
regression).
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any, Mapping

from app.core.logging import get_logger
from app.services.rag.corpus_planner import _query_terms
from app.services.vector_db.factory import VectorDBFactory

logger = get_logger(__name__)


# Generic enumeration scaffolding: project nouns, possession verbs and the broad
# equipment-category nouns that name *what kind* of thing is asked about rather
# than the *discriminating* brand/model. Faceting on these is useless — a
# category noun like "pompe" matches almost every project — so they are dropped,
# leaving the salient equipment token(s) (e.g. "uraca", "kd724"). Stored as
# accent/punctuation-folded compact forms so "équipés"/"donne-moi" also match.
_INVENTORY_GENERIC_TERMS = frozenset(
    {
        # Project / dossier nouns
        "projet", "projets", "project", "projects", "dossier", "dossiers",
        # Imperative / interrogative scaffolding
        "donnemoi", "donnezmoi", "donner", "montremoi", "montrer", "montre",
        "liste", "lister", "listez", "list", "show", "quels", "quelles",
        "tous", "toutes", "toute", "which", "what", "dans", "where",
        "retrouve", "retrouver", "retrouveton", "trouve", "trouver", "trouveton",
        # Possession verbs / qualifiers
        "utilisent", "utilise", "utiliser", "utilisant", "utilisee", "utilisees",
        "equipes", "equipe", "equipees", "equipee", "equipped", "using", "used",
        "munis", "muni", "munies", "munie", "dotes", "dote", "dotees", "dotee",
        "possedant", "possede", "possedent", "comportant", "comporte",
        "comportent", "integrant", "integre", "integrent", "disposent",
        "dispose", "having", "have", "installes", "installe", "installees",
        "installed", "contient", "contiennent", "contenant", "contain",
        "contains", "avec", "with",
        # Broad equipment-category nouns (not discriminating on their own)
        "pompe", "pompes", "pump", "pumps", "moteur", "moteurs", "motor",
        "motors", "machine", "machines", "equipement", "equipements",
        "equipment", "materiel", "materiels", "injecteur", "injecteurs",
        "injector", "injectors", "buse", "buses", "nozzle", "nozzles", "filtre",
        "filtres", "filter", "filters", "rouleau", "rouleaux", "secheur",
        "secheurs", "dryer", "dryers", "convoyeur", "convoyeurs", "conveyor",
        "conveyors", "vanne", "vannes", "valve", "valves",
    }
)

# A facet on ``project_code`` only makes sense for "which PROJECTS …" questions.
# An equipment-only inventory ("liste toutes les pompes Uraca") stays on the
# regular deep path; this gate keeps the facet scoped to project enumeration.
_PROJECT_ENUMERATION_RE = re.compile(r"\b(projets?|projects?|dossiers?)\b", re.IGNORECASE)

# Facet over at most this many planned collections so a workspace with many
# collections cannot fan the request out without bound (each facet is a server
# aggregation over the whole collection).
_MAX_FACET_COLLECTIONS = 4
# Top-N facet buckets to return; comfortably above the largest observed reverse
# lookup (~130 projects for a common pump brand).
_FACET_BUCKET_LIMIT = 200


def _fold_compact(value: Any) -> str:
    """Lowercase, strip accents and drop non-alphanumerics for comparison."""
    raw = str(value or "")
    folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


def extract_inventory_terms(query: str) -> list[str]:
    """Return the query's discriminating equipment term(s).

    Reuses the planner tokenizer (``_query_terms``) then drops the generic
    enumeration scaffolding, leaving the salient brand/model noun(s). Returns at
    most four terms, preserving query order.
    """
    terms: list[str] = []
    for token in _query_terms(query):
        compact = _fold_compact(token)
        if not compact or compact in _INVENTORY_GENERIC_TERMS:
            continue
        if compact not in terms:
            terms.append(compact)
    return terms[:4]


def query_targets_projects(query: str) -> bool:
    """True when the question enumerates projects (not just equipment)."""
    return bool(_PROJECT_ENUMERATION_RE.search(str(query or "")))


def _facet_once(
    client: Any,
    collection: str,
    terms: list[str],
    *,
    limit: int,
    exact: bool,
) -> list[tuple[str, int]]:
    from qdrant_client import models

    # AND across the discriminating terms. The ``content`` full-text index uses
    # ``lowercase=True``, so a single ``MatchText`` per term is case-insensitive
    # and exhaustive — no case-variant OR needed.
    query_filter = models.Filter(
        must=[
            models.FieldCondition(key="content", match=models.MatchText(text=term))
            for term in terms
        ]
    )
    response = client.facet(
        collection_name=collection,
        key="project_code",
        facet_filter=query_filter,
        limit=limit,
        exact=exact,
    )
    buckets: list[tuple[str, int]] = []
    for hit in getattr(response, "hits", None) or []:
        value = str(getattr(hit, "value", "") or "").strip()
        if not value:
            continue
        try:
            count = int(getattr(hit, "count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        buckets.append((value, count))
    return buckets


def facet_project_codes(
    client: Any,
    collection: str,
    terms: list[str],
    *,
    limit: int = _FACET_BUCKET_LIMIT,
    exact: bool = True,
) -> list[tuple[str, int]]:
    """Facet ``project_code`` for chunks whose ``content`` matches ``terms``.

    All terms are AND-ed (the precise interpretation of "projects with an X Y").
    When that yields nothing and several terms were given — typically because a
    model number is not indexed as a single full-text token — it falls back to
    the single term that surfaces the most projects, so the brand still answers.

    ``exact=True`` (the default) makes the facet traverse every segment so the
    enumeration is genuinely complete and the per-project counts are exact; the
    approximate mode under-counts distinct projects, which defeats the purpose of
    an exhaustive inventory. The aggregation runs concurrently with retrieval and
    well within the deep latency budget.
    """
    if not terms:
        return []
    buckets = _facet_once(client, collection, terms, limit=limit, exact=exact)
    if not buckets and len(terms) > 1:
        for term in terms:
            single = _facet_once(client, collection, [term], limit=limit, exact=exact)
            if len(single) > len(buckets):
                buckets = single
    return buckets


def build_project_inventory(
    profile: Mapping[str, Any],
    query: str,
    *,
    limit: int = _FACET_BUCKET_LIMIT,
) -> dict[str, Any] | None:
    """Aggregate the exhaustive project list for a transversal-inventory query.

    Returns ``None`` (caller falls back to deep retrieval) when the backend is
    not Qdrant, no discriminating term is found, or the facet yields nothing.
    """
    if str(profile.get("vector_db") or "").lower() != "qdrant":
        return None
    terms = extract_inventory_terms(query)
    if not terms:
        return None

    workspace_slug = profile.get("workspace_slug")
    collections: list[str] = []
    for ref in profile.get("collections") or [profile.get("collection")]:
        ref = str(ref or "").strip()
        if ref and ref not in collections:
            collections.append(ref)
    collections = collections[:_MAX_FACET_COLLECTIONS]
    if not collections:
        return None

    merged: dict[str, int] = {}
    collections_faceted = 0
    truncated = False
    started = time.time()
    for slug in collections:
        try:
            db = VectorDBFactory.get_db(slug, db_type="qdrant", workspace_slug=workspace_slug)
            client = db.client
            collection_name = db.collection_name
            if client is None or not client.collection_exists(collection_name):
                continue
            buckets = facet_project_codes(client, collection_name, terms, limit=limit)
        except Exception as exc:  # noqa: BLE001 - never break the answer on a facet error.
            logger.warning(
                "project_inventory: facet failed",
                collection=slug,
                terms=terms,
                error=str(exc),
            )
            continue
        collections_faceted += 1
        if len(buckets) >= limit:
            truncated = True
        for code, count in buckets:
            merged[code] = merged.get(code, 0) + count

    if not merged:
        return None

    ranked = sorted(merged.items(), key=lambda item: (-item[1], item[0]))[:limit]
    logger.info(
        "project_inventory: aggregated project_code facet",
        terms=terms,
        total_projects=len(merged),
        collections_faceted=collections_faceted,
        elapsed_ms=int((time.time() - started) * 1000),
    )
    return {
        "terms": terms,
        "total_projects": len(merged),
        "projects": [{"project_code": code, "chunk_count": count} for code, count in ranked],
        "collections_faceted": collections_faceted,
        "truncated": truncated,
    }
