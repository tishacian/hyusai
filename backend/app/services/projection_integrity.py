"""Shared integrity boundaries for user-facing object projections.

Projection code must distinguish persisted measurements from convenient
defaults, and recorded runtime evidence from arbitrary business payloads.
This module keeps those rules identical across System, Capability and Run
read models.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.models.run import Run, SkillInvocation

REDACTED = "[redacted]"

_CREDENTIAL_KEY_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "authorization_header",
        "bearer",
        "bearer_token",
        "cookie",
        "cookie_header",
        "cookie_jar",
        "cookies",
        "credential",
        "credentials",
        "dsn",
        "dsn_url",
        "id_token",
        "password",
        "passwd",
        "private_key",
        "private_key_pem",
        "refresh_token",
        "secret",
        "set_cookie",
        "token",
    }
)
_CREDENTIAL_KEY_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_apikey",
    "_auth",
    "_auth_token",
    "_authorization",
    "_authorization_header",
    "_bearer",
    "_cookie",
    "_cookie_header",
    "_cookie_jar",
    "_cookies",
    "_credential",
    "_credentials",
    "_dsn",
    "_dsn_url",
    "_id_token",
    "_password",
    "_passwd",
    "_private_key",
    "_private_key_pem",
    "_refresh_token",
    "_secret",
    "_session_token",
    "_set_cookie",
    "_token",
)
_LOWERCASE_SHA256 = re.compile(r"[0-9a-f]{64}")
_INLINE_CREDENTIAL_PATTERNS = (
    re.compile(r"\bauthorization\s*[:=]\s*(?:bearer|basic)\s+\S+", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-(?:proj-|ant-|svcacct-)?[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{24,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)


@dataclass(frozen=True)
class MeasuredRoiCohort:
    """Run cohort whose value and measured invocation cost can be compared."""

    cost: float | None
    value: float | None
    roi_percent: float | None
    run_count: int
    cost_sample_count: int


def invocation_cost_is_measured(invocation: SkillInvocation) -> bool:
    """Return whether an invocation carries an explicit cost measurement."""

    if invocation.cost_measured is not True or invocation.cost is None:
        return False
    try:
        amount = float(invocation.cost)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(amount) and amount >= 0


def measured_cost_summary(
    invocations: Iterable[SkillInvocation],
) -> tuple[float | None, int]:
    """Sum only explicitly measured invocation costs and return sample size."""

    costs = [
        float(invocation.cost)
        for invocation in invocations
        if invocation_cost_is_measured(invocation)
    ]
    return (sum(costs), len(costs)) if costs else (None, 0)


def measured_costs_by_run(
    invocations: Iterable[SkillInvocation],
) -> dict[str, tuple[float, int]]:
    """Return measured cost totals and sample counts keyed by Run id."""

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for invocation in invocations:
        if not invocation_cost_is_measured(invocation):
            continue
        totals[invocation.run_id] = totals.get(invocation.run_id, 0.0) + float(
            invocation.cost
        )
        counts[invocation.run_id] = counts.get(invocation.run_id, 0) + 1
    return {run_id: (total, counts[run_id]) for run_id, total in totals.items()}


def measured_roi_cohort(
    runs: Iterable[Run],
    cost_evidence: Mapping[str, tuple[float, int]],
) -> MeasuredRoiCohort:
    """Compute ROI only from Runs that have both value and measured cost."""

    rows = [
        run
        for run in runs
        if run.value_estimated is not None
        and str(run.value_source or "unset") in {"auto", "operator"}
        and run.id in cost_evidence
    ]
    if not rows:
        return MeasuredRoiCohort(None, None, None, 0, 0)
    total_cost = sum(cost_evidence[run.id][0] for run in rows)
    total_value = sum(float(run.value_estimated) for run in rows)
    cost_sample_count = sum(cost_evidence[run.id][1] for run in rows)
    roi = (
        (total_value - total_cost) / total_cost * 100.0
        if total_cost
        else None
    )
    return MeasuredRoiCohort(
        cost=total_cost,
        value=total_value,
        roi_percent=roi,
        run_count=len(rows),
        cost_sample_count=cost_sample_count,
    )


def canonical_run_provenance(
    run: Run,
    invocations: Iterable[SkillInvocation],
) -> list[dict[str, Any]]:
    """Return a provenance reference only when typed runtime markers agree.

    A URI/checksum-shaped mapping inside normal output is not evidence.  The
    DAG producer records canonical provenance in a SkillInvocation trace and a
    ``membrane_provenance`` checkpoint. Historical Runs may additionally carry
    a reserved terminal-output field; when present it must agree. This verifies
    typed ledger markers without mutating schema-bound business output.
    """

    output = run.output_ref if isinstance(run.output_ref, Mapping) else {}
    output_evidence = output.get("_membrane_provenance")
    output_pair = _canonical_provenance_pair(output_evidence)

    checkpoint_evidence = {
        pair: checkpoint
        for checkpoint in (run.checkpoints or [])
        if isinstance(checkpoint, Mapping)
        and checkpoint.get("kind") == "membrane_provenance"
        and (pair := _canonical_provenance_pair(checkpoint)) is not None
    }
    trace_evidence = {
        pair: invocation.trace.get("membrane_provenance")
        for invocation in invocations
        if invocation.run_id == run.id
        and isinstance(invocation.trace, Mapping)
        and (pair := _canonical_provenance_pair(invocation.trace.get("membrane_provenance")))
        is not None
    }
    matching_pairs = set(checkpoint_evidence) & set(trace_evidence)
    if len(matching_pairs) != 1:
        return []
    canonical_pair = next(iter(matching_pairs))
    # Historical Runs may also carry the reserved output marker.  When it is
    # present it remains an additional integrity vote and must agree; new
    # schema-bound Runs intentionally keep provenance outside business output.
    if output_evidence is not None and output_pair != canonical_pair:
        return []

    trace_payload = trace_evidence[canonical_pair]
    evidence = (
        output_evidence
        if isinstance(output_evidence, Mapping)
        else trace_payload if isinstance(trace_payload, Mapping) else {}
    )
    evidence_sources = [
        "runs.checkpoints[kind=membrane_provenance]",
        "skill_invocations.trace.membrane_provenance",
    ]
    if output_pair == canonical_pair:
        evidence_sources.insert(0, "runs.output_ref._membrane_provenance")
    row: dict[str, Any] = {
        "uri": canonical_pair[0],
        "sha256": canonical_pair[1],
        "verification": "runtime_markers_agree",
        "evidence_sources": evidence_sources,
    }
    size_bytes = evidence.get("size_bytes")
    if isinstance(size_bytes, int) and not isinstance(size_bytes, bool) and size_bytes >= 0:
        row["size_bytes"] = size_bytes
    created_at = evidence.get("created_at")
    if isinstance(created_at, str) and created_at.strip():
        row["created_at"] = created_at
    return [row]


def scrub_projection_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    """Recursively redact credential-shaped keys and inline credentials."""

    return {
        str(key): REDACTED
        if sensitive_projection_key(key) or _contains_inline_credential(item)
        else scrub_projection_value(item)
        for key, item in value.items()
    }


def scrub_projection_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return scrub_projection_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return [
            REDACTED if _contains_inline_credential(item) else scrub_projection_value(item)
            for item in value
        ]
    if _contains_inline_credential(value):
        return REDACTED
    return value


def sensitive_projection_key(value: Any) -> bool:
    """Recognize credential key variants without hiding benign endpoints."""

    text = str(value).strip()
    snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", snake_case).strip("_").lower()
    return normalized in _CREDENTIAL_KEY_NAMES or normalized.endswith(
        _CREDENTIAL_KEY_SUFFIXES
    )


def _canonical_provenance_pair(value: Any) -> tuple[str, str] | None:
    evidence = value if isinstance(value, Mapping) else {}
    uri = evidence.get("uri")
    sha256 = evidence.get("sha256")
    if (
        not isinstance(uri, str)
        or not uri.startswith("object://")
        or len(uri) <= len("object://")
        or not isinstance(sha256, str)
        or _LOWERCASE_SHA256.fullmatch(sha256) is None
    ):
        return None
    return uri, sha256


def _contains_inline_credential(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if any(pattern.search(text) for pattern in _INLINE_CREDENTIAL_PATTERNS):
        return True
    if re.search(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", text, re.IGNORECASE):
        return True
    if re.match(r"^(?:set-)?cookie\s*:", text, re.IGNORECASE):
        return True
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    if parsed.scheme and parsed.netloc and (
        parsed.username is not None or parsed.password is not None
    ):
        return True
    return any(sensitive_projection_key(key) for key, _item in parse_qsl(parsed.query))
