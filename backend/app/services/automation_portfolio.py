"""A published automation is a Work job. A draft is not a portfolio proof.

The package names the objective, the value convention, the gap and the run.
An absent convention stays absent. Source text is not copied into the file.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class AutomationPortfolioRefusal(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def work_job(
    system: Mapping[str, Any],
    *,
    variant: str | None,
    published_version_id: str | None,
    flow_sha256: str | None,
) -> dict[str, Any]:
    """Return the Work job for one published automation."""

    if variant != "automation_v1":
        raise AutomationPortfolioRefusal(
            "not_automation",
            "Only a published automation becomes a Work job",
        )
    objective = system.get("objective") if isinstance(system.get("objective"), str) else ""
    if system.get("status") != "active" or not published_version_id or not flow_sha256:
        raise AutomationPortfolioRefusal(
            "unpublished",
            "An automation becomes a Work job when it is published",
        )
    stated = objective.strip()
    return {
        "kind": "automation_work_job",
        "system_id": system.get("id"),
        "name": system.get("name"),
        "objective": stated or None,
        "objective_status": "stated" if stated else "absent",
        "published_version_id": published_version_id,
        "flow_sha256": flow_sha256,
    }


def _convention(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("status") not in {"declared", "measured"}:
        return {"status": "absent"}
    return {
        "status": raw.get("status"),
        "unit": raw.get("unit"),
        "currency": raw.get("currency"),
        "value_per_unit": raw.get("value_per_unit"),
        "declared_by": raw.get("declared_by"),
        "declared_at": raw.get("declared_at"),
    }


def _citations(run_id: str, proof: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = proof.get("citations") if isinstance(proof.get("citations"), list) else []
    citations = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        if isinstance(source, str) and source:
            citations.append({"run_id": run_id, "source": source})
    return citations


def job_explanation(
    job: Mapping[str, Any],
    convention: Mapping[str, Any] | None = None,
    *,
    run: Mapping[str, Any] | None = None,
    proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The four lines Hypervisor and Work may show. No run means no proof."""

    if run is None:
        return {
            "job": dict(job),
            "objective": {"status": job.get("objective_status"), "text": job.get("objective")},
            "convention": _convention(convention),
            "gap": {"status": "absent"},
            "proof": None,
        }
    return run_package(job, run, convention=convention, proof=proof)


def run_package(
    job: Mapping[str, Any],
    run: Mapping[str, Any],
    *,
    convention: Mapping[str, Any] | None = None,
    proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain one published run. A draft test is not a COMEX proof."""

    if run.get("system_id") != job.get("system_id"):
        raise AutomationPortfolioRefusal(
            "run_mismatch",
            "The run does not belong to this Work job",
        )
    if run.get("execution_surface") == "draft_test":
        raise AutomationPortfolioRefusal(
            "draft_not_proof",
            "A draft test is not the proof of a published automation",
        )
    if run.get("flow_sha256") != job.get("flow_sha256"):
        raise AutomationPortfolioRefusal(
            "stale_proof",
            "The run is not the published automation",
        )
    evidence = proof if isinstance(proof, Mapping) else {}
    gap = evidence.get("gap") if isinstance(evidence.get("gap"), Mapping) else None
    sap = evidence.get("sap") if isinstance(evidence.get("sap"), Mapping) else None
    return {
        "job": dict(job),
        "objective": {
            "status": job.get("objective_status"),
            "text": job.get("objective"),
        },
        "convention": _convention(convention),
        "gap": dict(gap) if gap else {"status": "absent"},
        "proof": {
            "run_id": run.get("id"),
            "status": run.get("status"),
            "flow_sha256": run.get("flow_sha256"),
            "execution_surface": run.get("execution_surface"),
            "decision_status": evidence.get("decision_status"),
            "sap": {
                "sealed": sap.get("sealed") is True,
                "called": sap.get("called") is True,
            } if sap else None,
            "citations": _citations(str(run.get("id")), evidence),
        },
    }
