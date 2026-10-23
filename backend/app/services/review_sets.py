"""Review sets: per-record human review (Experience Lot 10).

A producer opens a set of items; reviewers claim an item, then approve,
correct or reject it with annotations from the set's taxonomy. The queue
policy orders items by tier, packs them into work packages under a weight
budget and keeps a tier locked until earlier tiers reach a threshold. Every
rule a client shows is enforced here as well.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.review_set import ReviewDecision, ReviewItem, ReviewSet
from app.services.audit_logger import emit_audit_event

DECISIONS = ("approve", "correct", "reject")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
_MAX_SUBJECT_BYTES = 64 * 1024
_MAX_VALUE_CHARS = 100_000
_PAGE_MAX = 200


class ReviewError(ValueError):
    def __init__(self, code: str, status_code: int = 400, detail: str | None = None):
        self.code, self.status_code = code, status_code
        super().__init__(detail or code)


def utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Taxonomy and policy
# ---------------------------------------------------------------------------


def clean_taxonomy(raw: Any) -> dict:
    """``{"categories": [{"key", "label", "severities": [..]}], "comment_required_for": [..],
    "severity_weights": {severity: number}}``"""

    if raw in (None, {}):
        return {"categories": [], "comment_required_for": [], "severity_weights": {}}
    if not isinstance(raw, dict) or set(raw) - {
        "categories",
        "comment_required_for",
        "severity_weights",
        "severity_order",
    }:
        raise ReviewError("REVIEW_TAXONOMY_INVALID")
    categories = raw.get("categories") or []
    if not isinstance(categories, list) or len(categories) > 50:
        raise ReviewError("REVIEW_TAXONOMY_INVALID", detail="categories")
    seen, out = set(), []
    for item in categories:
        if not isinstance(item, dict) or not _KEY_RE.match(str(item.get("key", ""))):
            raise ReviewError("REVIEW_TAXONOMY_INVALID", detail="category key")
        severities = item.get("severities") or []
        if (
            not isinstance(severities, list)
            or not severities
            or not all(isinstance(s, str) and _KEY_RE.match(s) for s in severities)
        ):
            raise ReviewError("REVIEW_TAXONOMY_INVALID", detail=f"{item['key']} severities")
        if item["key"] in seen:
            raise ReviewError("REVIEW_TAXONOMY_INVALID", detail=f"{item['key']} duplicated")
        seen.add(item["key"])
        out.append(
            {
                "key": item["key"],
                "label": str(item.get("label") or item["key"])[:120],
                "description": str(item.get("description") or "")[:500],
                "severities": list(dict.fromkeys(severities)),
            }
        )
    all_severities = {s for c in out for s in c["severities"]}
    required = raw.get("comment_required_for") or []
    if not isinstance(required, list) or not set(required) <= all_severities:
        raise ReviewError("REVIEW_TAXONOMY_INVALID", detail="comment_required_for")
    weights = raw.get("severity_weights") or {}
    if not isinstance(weights, dict) or not all(
        k in all_severities and isinstance(v, (int, float)) and not isinstance(v, bool)
        for k, v in weights.items()
    ):
        raise ReviewError("REVIEW_TAXONOMY_INVALID", detail="severity_weights")
    order = raw.get("severity_order") or sorted(all_severities)
    if not isinstance(order, list) or set(order) != all_severities:
        raise ReviewError("REVIEW_TAXONOMY_INVALID", detail="severity_order")
    return {
        "categories": out,
        "comment_required_for": list(required),
        "severity_weights": {k: float(v) for k, v in weights.items()},
        "severity_order": list(order),
    }


def clean_policy(raw: Any) -> dict:
    """``{"tiers": [{"key", "label", "unlock_after": {"tiers": [..], "threshold": 0..1}}],
    "package_weight": number}``"""

    if raw in (None, {}):
        return {"tiers": [], "package_weight": 0}
    if not isinstance(raw, dict) or set(raw) - {"tiers", "package_weight"}:
        raise ReviewError("REVIEW_POLICY_INVALID")
    tiers = raw.get("tiers") or []
    if not isinstance(tiers, list) or len(tiers) > 20:
        raise ReviewError("REVIEW_POLICY_INVALID", detail="tiers")
    keys, out = [], []
    for tier in tiers:
        if not isinstance(tier, dict) or not _KEY_RE.match(str(tier.get("key", ""))):
            raise ReviewError("REVIEW_POLICY_INVALID", detail="tier key")
        unlock = tier.get("unlock_after")
        if unlock is not None:
            if (
                not isinstance(unlock, dict)
                or not isinstance(unlock.get("tiers"), list)
                or not set(unlock["tiers"]) <= set(keys)
                or not isinstance(unlock.get("threshold"), (int, float))
                or not 0 < float(unlock["threshold"]) <= 1
            ):
                raise ReviewError("REVIEW_POLICY_INVALID", detail=f"{tier['key']} unlock_after")
            unlock = {"tiers": list(unlock["tiers"]), "threshold": float(unlock["threshold"])}
        keys.append(tier["key"])
        out.append(
            {
                "key": tier["key"],
                "label": str(tier.get("label") or tier["key"])[:120],
                "unlock_after": unlock,
            }
        )
    weight = raw.get("package_weight") or 0
    if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
        raise ReviewError("REVIEW_POLICY_INVALID", detail="package_weight")
    return {"tiers": out, "package_weight": float(weight)}


# ---------------------------------------------------------------------------
# Open, read, close
# ---------------------------------------------------------------------------


def _search_text(subject: dict) -> str:
    parts = []
    for key in ("source", "candidate"):
        if isinstance(subject.get(key), str):
            parts.append(subject[key])
    return " ".join(parts)[:4000].lower()


def open_set(
    db: Session,
    *,
    workspace_id: str,
    namespace: str,
    group_key: str,
    title: str,
    items: Iterable[dict],
    group_labels: dict | None = None,
    taxonomy: dict | None = None,
    policy: dict | None = None,
    reviewers: list[str] | None = None,
    deadline_at: datetime | None = None,
    source: dict | None = None,
    user_id: str | None = None,
) -> ReviewSet:
    if not isinstance(namespace, str) or not _SLUG_RE.match(namespace):
        raise ReviewError("REVIEW_NAMESPACE_INVALID")
    if not isinstance(group_key, str) or not 0 < len(group_key) <= 200:
        raise ReviewError("REVIEW_GROUP_INVALID")
    if not isinstance(title, str) or not title.strip():
        raise ReviewError("REVIEW_TITLE_INVALID")
    if reviewers is not None and (
        not isinstance(reviewers, list) or not all(isinstance(r, str) for r in reviewers)
    ):
        raise ReviewError("REVIEW_REVIEWERS_INVALID")
    clean_tax = clean_taxonomy(taxonomy)
    clean_pol = clean_policy(policy)
    tier_keys = [t["key"] for t in clean_pol["tiers"]]
    labels = group_labels or {}
    if not isinstance(labels, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in labels.items()
    ):
        raise ReviewError("REVIEW_GROUP_INVALID", detail="group_labels")
    now = utcnow()
    row = ReviewSet(
        workspace_id=workspace_id,
        namespace=namespace,
        group_key=group_key,
        group_labels=labels,
        title=title.strip()[:300],
        source=source or {},
        taxonomy=clean_tax,
        policy=clean_pol,
        reviewers=reviewers,
        status="open",
        deadline_at=deadline_at,
        created_by=user_id,
        created_at=now,
    )
    db.add(row)
    db.flush()
    refs, count = set(), 0
    import json as _json

    for position, item in enumerate(items):
        if count >= settings.review_set_max_items:
            raise ReviewError("REVIEW_SET_TOO_LARGE")
        if not isinstance(item, dict):
            raise ReviewError("REVIEW_ITEM_INVALID", detail=str(position))
        ref = item.get("item_ref")
        if not isinstance(ref, str) or not 0 < len(ref) <= 200 or ref in refs:
            raise ReviewError("REVIEW_ITEM_REF_INVALID", detail=str(ref))
        refs.add(ref)
        tier = str(item.get("tier") or (tier_keys[-1] if tier_keys else "default"))
        if tier_keys and tier not in tier_keys:
            raise ReviewError("REVIEW_ITEM_TIER_UNKNOWN", detail=f"{ref}: {tier}")
        weight = item.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
            raise ReviewError("REVIEW_ITEM_INVALID", detail=f"{ref}: weight")
        subject = item.get("subject") or {}
        if not isinstance(subject, dict) or len(_json.dumps(subject)) > _MAX_SUBJECT_BYTES:
            raise ReviewError("REVIEW_ITEM_INVALID", detail=f"{ref}: subject")
        db.add(
            ReviewItem(
                set_id=row.id,
                item_ref=ref,
                position=position,
                tier=tier,
                weight=float(weight),
                subject=subject,
                search_text=_search_text(subject),
                revision=0,
                status="pending",
                categories=[],
                duration_ms=0,
            )
        )
        count += 1
    if count == 0:
        raise ReviewError("REVIEW_SET_EMPTY")
    row.item_count, row.decided_count = count, 0
    db.flush()
    _audit(
        db,
        workspace_id,
        "review_set.opened",
        user_id,
        {"set_id": row.id, "namespace": namespace, "group_key": group_key, "items": count},
    )
    return row


def get_set(db: Session, workspace_id: str, set_id: str) -> ReviewSet:
    row = db.query(ReviewSet).filter_by(id=set_id, workspace_id=workspace_id).first()
    if row is None:
        raise ReviewError("REVIEW_SET_NOT_FOUND", 404)
    return row


def get_item(db: Session, workspace_id: str, item_id: str) -> tuple[ReviewSet, ReviewItem]:
    item = db.get(ReviewItem, item_id)
    if item is None:
        raise ReviewError("REVIEW_ITEM_NOT_FOUND", 404)
    review_set = db.get(ReviewSet, item.set_id)
    if review_set is None or review_set.workspace_id != workspace_id:
        raise ReviewError("REVIEW_ITEM_NOT_FOUND", 404)
    return review_set, item


def check_reviewer(review_set: ReviewSet, user_id: str, *, admin: bool) -> None:
    if admin or review_set.reviewers is None:
        return
    if user_id not in review_set.reviewers:
        raise ReviewError("REVIEW_NOT_A_REVIEWER", 403)


def close_set(db: Session, review_set: ReviewSet, *, user_id: str | None) -> ReviewSet:
    if review_set.status == "closed":
        return review_set
    now = utcnow()
    review_set.status, review_set.closed_at = "closed", now
    review_set.completed_at = review_set.completed_at or now
    db.flush()
    _audit(db, review_set.workspace_id, "review_set.closed", user_id, {"set_id": review_set.id})
    return review_set


def set_view(row: ReviewSet) -> dict:
    iso = lambda value: value.isoformat() if value else None  # noqa: E731
    return {
        "id": row.id,
        "namespace": row.namespace,
        "group_key": row.group_key,
        "group_labels": row.group_labels,
        "title": row.title,
        "source": row.source,
        "taxonomy": row.taxonomy,
        "policy": row.policy,
        "status": row.status,
        "item_count": row.item_count,
        "decided_count": row.decided_count,
        "progress": (row.decided_count / row.item_count) if row.item_count else 0.0,
        "deadline_at": iso(row.deadline_at),
        "created_at": iso(row.created_at),
        "completed_at": iso(row.completed_at),
        "closed_at": iso(row.closed_at),
    }


def item_view(row: ReviewItem, *, now: datetime | None = None, with_subject: bool = True) -> dict:
    now = now or utcnow()
    claimed = row.claimed_by if row.claim_expires_at and row.claim_expires_at > now else None
    view = {
        "id": row.id,
        "item_ref": row.item_ref,
        "tier": row.tier,
        "weight": row.weight,
        "revision": row.revision,
        "status": row.status,
        "worst_severity": row.worst_severity,
        "categories": list(row.categories or []),
        "claimed_by": claimed,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "duration_ms": row.duration_ms,
    }
    if with_subject:
        view["subject"] = row.subject
    return view


# ---------------------------------------------------------------------------
# Queue: packages and unlock rules
# ---------------------------------------------------------------------------


def _tier_progress(db: Session, review_set: ReviewSet) -> dict[str, tuple[int, int]]:
    rows = (
        db.query(ReviewItem.tier, ReviewItem.status, func.count(ReviewItem.id))
        .filter(ReviewItem.set_id == review_set.id)
        .group_by(ReviewItem.tier, ReviewItem.status)
        .all()
    )
    out: dict[str, list[int]] = {}
    for tier, status, count in rows:
        total_decided = out.setdefault(tier, [0, 0])
        total_decided[0] += count
        if status != "pending":
            total_decided[1] += count
    return {tier: (values[0], values[1]) for tier, values in out.items()}


def locked_tiers(db: Session, review_set: ReviewSet) -> set[str]:
    progress = _tier_progress(db, review_set)
    locked = set()
    for tier in review_set.policy.get("tiers") or []:
        rule = tier.get("unlock_after")
        if not rule:
            continue
        total = sum(progress.get(t, (0, 0))[0] for t in rule["tiers"])
        decided = sum(progress.get(t, (0, 0))[1] for t in rule["tiers"])
        if total and decided / total < rule["threshold"]:
            locked.add(tier["key"])
    return locked


def packages(db: Session, review_set: ReviewSet) -> list[dict]:
    """Deterministic work packages: per tier, consecutive items under the weight budget."""

    budget = float(review_set.policy.get("package_weight") or 0)
    order = [t["key"] for t in review_set.policy.get("tiers") or []]
    locked = locked_tiers(db, review_set)
    rows = (
        db.query(
            ReviewItem.id,
            ReviewItem.tier,
            ReviewItem.weight,
            ReviewItem.status,
            ReviewItem.duration_ms,
        )
        .filter(ReviewItem.set_id == review_set.id)
        .order_by(ReviewItem.position)
        .all()
    )
    by_tier: dict[str, list] = {}
    for row in rows:
        by_tier.setdefault(row.tier, []).append(row)
    tiers = order + sorted(t for t in by_tier if t not in order)
    out = []
    for tier in tiers:
        current: dict | None = None
        for row in by_tier.get(tier, []):
            if current is None or (
                budget and current["weight"] + row.weight > budget and current["items"]
            ):
                current = {
                    "key": f"{tier}-{sum(1 for p in out if p['tier'] == tier) + 1}",
                    "tier": tier,
                    "locked": tier in locked,
                    "items": 0,
                    "decided": 0,
                    "weight": 0.0,
                    "duration_ms": 0,
                    "item_ids": [],
                }
                out.append(current)
            current["items"] += 1
            current["decided"] += row.status != "pending"
            current["weight"] += row.weight
            current["duration_ms"] += row.duration_ms or 0
            current["item_ids"].append(row.id)
    return out


def list_items(
    db: Session,
    review_set: ReviewSet,
    *,
    status: str | None = None,
    tier: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    query: str | None = None,
    package: str | None = None,
    sort: str = "position",
    offset: int = 0,
    limit: int = 50,
) -> dict:
    q = db.query(ReviewItem).filter(ReviewItem.set_id == review_set.id)
    if status:
        if status not in ("pending", "decided", *DECISIONS):
            raise ReviewError("REVIEW_FILTER_INVALID", detail="status")
        q = (
            q.filter(ReviewItem.status != "pending")
            if status == "decided"
            else q.filter(ReviewItem.status == status)
        )
    if tier:
        q = q.filter(ReviewItem.tier == tier)
    if severity:
        q = q.filter(ReviewItem.worst_severity == severity)
    if query:
        q = q.filter(ReviewItem.search_text.contains(query.lower()[:200]))
    if package:
        match = next((p for p in packages(db, review_set) if p["key"] == package), None)
        if match is None:
            raise ReviewError("REVIEW_PACKAGE_NOT_FOUND", 404)
        q = q.filter(ReviewItem.id.in_(match["item_ids"]))
    columns = {
        "position": ReviewItem.position,
        "-position": ReviewItem.position.desc(),
        "weight": ReviewItem.weight,
        "-weight": ReviewItem.weight.desc(),
        "decided_at": ReviewItem.decided_at,
        "-decided_at": ReviewItem.decided_at.desc(),
    }
    if sort not in columns:
        raise ReviewError("REVIEW_SORT_INVALID")
    rows = q.order_by(columns[sort], ReviewItem.position).all()
    if category:
        rows = [r for r in rows if category in (r.categories or [])]
    limit = max(1, min(int(limit), _PAGE_MAX))
    offset = max(0, int(offset))
    now = utcnow()
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "items": [item_view(r, now=now) for r in rows[offset : offset + limit]],
    }


# ---------------------------------------------------------------------------
# Claim and decide
# ---------------------------------------------------------------------------


def claim(db: Session, review_set: ReviewSet, item: ReviewItem, *, user_id: str) -> dict:
    if review_set.status != "open":
        raise ReviewError("REVIEW_SET_CLOSED", 409)
    if item.tier in locked_tiers(db, review_set):
        raise ReviewError("REVIEW_TIER_LOCKED", 409, detail=item.tier)
    now = utcnow()
    expires = now + timedelta(seconds=settings.review_claim_ttl_s)
    changed = (
        db.query(ReviewItem)
        .filter(
            ReviewItem.id == item.id,
            or_(
                ReviewItem.claimed_by.is_(None),
                ReviewItem.claimed_by == user_id,
                ReviewItem.claim_expires_at <= now,
            ),
        )
        .update({"claimed_by": user_id, "claim_expires_at": expires}, synchronize_session=False)
    )
    db.flush()
    db.refresh(item)
    if changed != 1:
        raise ReviewError("REVIEW_ITEM_CLAIMED", 409)
    return {"item_id": item.id, "revision": item.revision, "claim_expires_at": expires.isoformat()}


def release(db: Session, item: ReviewItem, *, user_id: str) -> None:
    db.query(ReviewItem).filter_by(id=item.id, claimed_by=user_id).update(
        {"claimed_by": None, "claim_expires_at": None}, synchronize_session=False
    )
    db.flush()


def _check_annotations(taxonomy: dict, annotations: Any) -> list[dict]:
    if annotations in (None, []):
        return []
    if not isinstance(annotations, list) or len(annotations) > 20:
        raise ReviewError("REVIEW_ANNOTATIONS_INVALID")
    allowed = {c["key"]: set(c["severities"]) for c in taxonomy.get("categories") or []}
    out, seen = [], set()
    for item in annotations:
        if not isinstance(item, dict) or set(item) - {"category", "severity"}:
            raise ReviewError("REVIEW_ANNOTATIONS_INVALID")
        category, severity = item.get("category"), item.get("severity")
        if category not in allowed or severity not in allowed[category] or category in seen:
            raise ReviewError("REVIEW_ANNOTATION_UNKNOWN", detail=f"{category}/{severity}")
        seen.add(category)
        out.append({"category": category, "severity": severity})
    return out


def _check_protected(subject: dict, value: str) -> None:
    spans = subject.get("protected_spans") or []
    cursor = 0
    for span in spans:
        if not isinstance(span, str) or not span:
            continue
        found = value.find(span, cursor)
        if found < 0:
            raise ReviewError("REVIEW_PROTECTED_SPAN_LOST", detail=span)
        cursor = found + len(span)


def decide(
    db: Session,
    review_set: ReviewSet,
    item: ReviewItem,
    *,
    user_id: str,
    revision: int,
    decision: str,
    value: str | None = None,
    annotations: Any = None,
    comment: str | None = None,
    duration_ms: int = 0,
) -> ReviewItem:
    if review_set.status != "open":
        raise ReviewError("REVIEW_SET_CLOSED", 409)
    if item.tier in locked_tiers(db, review_set):
        raise ReviewError("REVIEW_TIER_LOCKED", 409, detail=item.tier)
    now = utcnow()
    if (
        item.claimed_by
        and item.claimed_by != user_id
        and item.claim_expires_at
        and item.claim_expires_at > now
    ):
        raise ReviewError("REVIEW_ITEM_CLAIMED", 409)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision != item.revision:
        raise ReviewError("REVIEW_REVISION_STALE", 409)
    candidate = item.subject.get("candidate") if isinstance(item.subject, dict) else None
    if decision == "auto":
        decision = "approve" if value is None or value == candidate else "correct"
    if decision not in DECISIONS:
        raise ReviewError("REVIEW_DECISION_INVALID")
    if decision == "correct":
        if not isinstance(value, str) or not value.strip() or len(value) > _MAX_VALUE_CHARS:
            raise ReviewError("REVIEW_VALUE_REQUIRED")
        if value == candidate:
            raise ReviewError("REVIEW_VALUE_UNCHANGED")
        _check_protected(item.subject or {}, value)
    else:
        value = None
    clean = _check_annotations(review_set.taxonomy or {}, annotations)
    if decision == "approve" and clean:
        raise ReviewError("REVIEW_ANNOTATIONS_ON_APPROVE")
    required = set((review_set.taxonomy or {}).get("comment_required_for") or [])
    if comment is not None and (not isinstance(comment, str) or len(comment) > 5000):
        raise ReviewError("REVIEW_COMMENT_INVALID")
    comment = comment.strip() if comment else None
    if not comment and (decision == "reject" or any(a["severity"] in required for a in clean)):
        raise ReviewError("REVIEW_COMMENT_REQUIRED")
    if (
        isinstance(duration_ms, bool)
        or not isinstance(duration_ms, int)
        or not 0 <= duration_ms <= 86_400_000
    ):
        raise ReviewError("REVIEW_DURATION_INVALID")
    changed = (
        db.query(ReviewItem)
        .filter(ReviewItem.id == item.id, ReviewItem.revision == revision)
        .update(
            {
                "revision": revision + 1,
                "status": decision,
                "categories": [a["category"] for a in clean],
                "worst_severity": _worst(review_set.taxonomy or {}, clean),
                "decided_by": user_id,
                "decided_at": now,
                "duration_ms": (item.duration_ms or 0) + duration_ms,
                "claimed_by": None,
                "claim_expires_at": None,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise ReviewError("REVIEW_REVISION_STALE", 409)
    was_pending = item.status == "pending"
    db.add(
        ReviewDecision(
            item_id=item.id,
            set_id=review_set.id,
            revision=revision + 1,
            decision=decision,
            value=value,
            annotations=clean,
            comment=comment,
            duration_ms=duration_ms,
            decided_by=user_id,
            decided_at=now,
        )
    )
    if was_pending:
        review_set.decided_count = (review_set.decided_count or 0) + 1
        if review_set.decided_count >= review_set.item_count and not review_set.completed_at:
            review_set.completed_at = now
    db.flush()
    db.refresh(item)
    return item


def _worst(taxonomy: dict, annotations: list[dict]) -> str | None:
    order = taxonomy.get("severity_order") or []
    ranked = [order.index(a["severity"]) for a in annotations if a["severity"] in order]
    return order[max(ranked)] if ranked else None


def bulk_approve(db: Session, review_set: ReviewSet, item_ids: list[str], *, user_id: str) -> dict:
    if not isinstance(item_ids, list) or len(item_ids) > 500:
        raise ReviewError("REVIEW_BULK_INVALID")
    approved, skipped = [], []
    for item_id in item_ids:
        item = db.get(ReviewItem, item_id)
        if item is None or item.set_id != review_set.id:
            skipped.append({"item_id": item_id, "code": "REVIEW_ITEM_NOT_FOUND"})
            continue
        if item.status != "pending":
            skipped.append({"item_id": item_id, "code": "REVIEW_ITEM_DECIDED"})
            continue
        try:
            decide(
                db, review_set, item, user_id=user_id, revision=item.revision, decision="approve"
            )
            approved.append(item_id)
        except ReviewError as exc:
            skipped.append({"item_id": item_id, "code": exc.code})
    return {"approved": approved, "skipped": skipped}


def history(db: Session, item: ReviewItem) -> list[dict]:
    rows = (
        db.query(ReviewDecision)
        .filter_by(item_id=item.id)
        .order_by(ReviewDecision.revision.desc())
        .all()
    )
    return [
        {
            "revision": r.revision,
            "decision": r.decision,
            "value": r.value,
            "annotations": r.annotations,
            "comment": r.comment,
            "duration_ms": r.duration_ms,
            "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Export, stats and the completion event
# ---------------------------------------------------------------------------


def latest_decisions(db: Session, review_set: ReviewSet) -> dict[str, ReviewDecision]:
    latest: dict[str, ReviewDecision] = {}
    for row in (
        db.query(ReviewDecision)
        .filter_by(set_id=review_set.id)
        .order_by(ReviewDecision.revision)
        .all()
    ):
        latest[row.item_id] = row
    return latest


def export_csv(
    db: Session,
    review_set: ReviewSet,
    *,
    subject_fields: list[str] | None = None,
    user_id: str | None = None,
) -> str:
    fields = [f for f in (subject_fields or ["source", "candidate"]) if isinstance(f, str)][:20]
    latest = latest_decisions(db, review_set)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "item_ref",
            "tier",
            *fields,
            "decision",
            "value",
            "annotations",
            "comment",
            "decided_by",
            "duration_ms",
            "decided_at",
        ]
    )
    for item in (
        db.query(ReviewItem).filter_by(set_id=review_set.id).order_by(ReviewItem.position).all()
    ):
        decision = latest.get(item.id)
        subject = item.subject if isinstance(item.subject, dict) else {}
        writer.writerow(
            [
                item.item_ref,
                item.tier,
                *[_cell(subject.get(f)) for f in fields],
                decision.decision if decision else "",
                decision.value if decision and decision.value is not None else "",
                ";".join(
                    f"{a['category']}:{a['severity']}"
                    for a in (decision.annotations if decision else [])
                ),
                decision.comment if decision and decision.comment else "",
                decision.decided_by if decision else "",
                item.duration_ms,
                decision.decided_at.isoformat() if decision else "",
            ]
        )
    _audit(db, review_set.workspace_id, "review_set.exported", user_id, {"set_id": review_set.id})
    return buffer.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    # Spreadsheet formula injection: a leading operator is neutralised.
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def stats(db: Session, review_set: ReviewSet) -> dict:
    taxonomy = review_set.taxonomy or {}
    weights = taxonomy.get("severity_weights") or {}
    latest = latest_decisions(db, review_set)
    by_decision = {d: 0 for d in DECISIONS}
    by_category: dict[str, dict[str, int]] = {}
    penalty = 0.0
    for decision in latest.values():
        by_decision[decision.decision] += 1
        for annotation in decision.annotations or []:
            bucket = by_category.setdefault(annotation["category"], {})
            bucket[annotation["severity"]] = bucket.get(annotation["severity"], 0) + 1
            penalty += float(weights.get(annotation["severity"], 0))
    total_weight = (
        db.query(func.coalesce(func.sum(ReviewItem.weight), 0))
        .filter_by(set_id=review_set.id)
        .scalar()
    )
    duration = (
        db.query(func.coalesce(func.sum(ReviewItem.duration_ms), 0))
        .filter_by(set_id=review_set.id)
        .scalar()
    )
    return {
        "items": review_set.item_count,
        "decided": review_set.decided_count,
        "by_decision": by_decision,
        "by_category": by_category,
        "penalty": penalty,
        "total_weight": float(total_weight or 0),
        "penalty_per_1000_weight": (penalty * 1000 / float(total_weight)) if total_weight else None,
        "duration_ms": int(duration or 0),
    }


def completed_event_payload(review_set: ReviewSet) -> dict:
    return {
        "set_id": review_set.id,
        "namespace": review_set.namespace,
        "group_key": review_set.group_key,
        "group_labels": review_set.group_labels,
        "status": review_set.status,
        "items": review_set.item_count,
        "decided": review_set.decided_count,
        "source": review_set.source,
        "correlation_key": (review_set.source or {}).get("correlation_key") or review_set.id,
    }


def announce_completed(db: Session, *, limit: int = 100) -> int:
    """Hand each completed set once to the trigger registry (``review_set.completed``)."""

    from app.services.run_engine.triggers import EVENT_REVIEW_SET_COMPLETED, emit_event

    rows = (
        db.query(ReviewSet)
        .filter(ReviewSet.completed_at.isnot(None), ReviewSet.event_emitted_at.is_(None))
        .order_by(ReviewSet.completed_at)
        .limit(limit)
        .all()
    )
    for row in rows:
        target = (row.source or {}).get("notify_system_id")
        emit_event(
            EVENT_REVIEW_SET_COMPLETED,
            row.workspace_id,
            completed_event_payload(row),
            system_id=target if isinstance(target, str) else None,
        )
        row.event_emitted_at = utcnow()
        db.commit()
    return len(rows)


def _audit(db: Session, workspace_id: str, event: str, actor: str | None, details: dict) -> None:
    emit_audit_event(
        workspace_id=workspace_id, event_type=event, actor=actor or "system", details=details, db=db
    )
