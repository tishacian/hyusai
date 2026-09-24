"""A published automation is a Work job. A draft is not a portfolio proof.

The package names the objective, the value convention, the gap and the run.
The convention and the gap come from the automation's approved value contract
(ADR 0003 lot 3); without one they stay absent. Source text is not copied into
the file.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.system_version import SystemVersion


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
    if not isinstance(raw, Mapping) or raw.get("status") not in {"approved", "declared", "measured"}:
        return {"status": "absent"}
    shown = {
        "status": raw.get("status"),
        "unit": raw.get("unit"),
        "currency": raw.get("currency"),
        "value_per_unit": raw.get("value_per_unit"),
        "declared_by": raw.get("declared_by"),
        "declared_at": raw.get("declared_at"),
    }
    if isinstance(raw.get("contract"), Mapping):
        shown["contract"] = dict(raw["contract"])
    return shown


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
    gap: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The four lines Hypervisor and Work may show. No run means no proof.

    The gap is the contract's, measured over its period: it does not wait for
    a run of the published version.
    """

    if run is None:
        return {
            "job": dict(job),
            "objective": {"status": job.get("objective_status"), "text": job.get("objective")},
            "convention": _convention(convention),
            "gap": dict(gap) if isinstance(gap, Mapping) else {"status": "absent"},
            "proof": None,
        }
    evidence = {**dict(proof or {}), **({"gap": dict(gap)} if isinstance(gap, Mapping) else {})}
    return run_package(job, run, convention=convention, proof=evidence)


def invocation_proof(db: DBSession, run: Run) -> dict[str, Any]:
    sap = None
    citations = []
    for item in db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all():
        output = item.output_ref if isinstance(item.output_ref, dict) else {}
        if item.skill_slug == "sap_create_po_v1":
            sap = {"sealed": output.get("sealed") is True, "called": output.get("called") is True}
        source = output.get("source") if item.skill_slug == "semantic_search_v1" else None
        if isinstance(source, str) and source:
            citations.append({"source": source})
    return {"sap": sap, "citations": citations}


def list_job_explanations(db: DBSession, workspace: Any, user: Any = None) -> list[dict[str, Any]]:
    """Published automations in one workspace, with proof only from a published run.

    ``user`` is whose evidence measures the gap: runs they cannot read make the
    measure incomplete, never silently smaller. Without one the gap is absent.
    """
    from app.services import value_contracts

    systems = (
        db.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.status == "active",
            System.published_flow_version_id.isnot(None),
        )
        .order_by(System.name.asc(), System.id.asc())
        .all()
    )
    cards = []
    for system in systems:
        version = (
            db.query(SystemVersion)
            .filter(
                SystemVersion.id == system.published_flow_version_id,
                SystemVersion.system_id == system.id,
            )
            .one_or_none()
        )
        flow = version.flow_definition if version is not None and isinstance(version.flow_definition, dict) else {}
        if not isinstance(flow, dict) or flow.get("variant") != "automation_v1" or version is None:
            continue
        try:
            job = work_job(
                {
                    "id": system.id,
                    "name": system.name,
                    "status": system.status,
                    "objective": system.objective,
                },
                variant="automation_v1",
                published_version_id=version.id,
                flow_sha256=version.flow_sha256,
            )
        except AutomationPortfolioRefusal:
            continue
        convention, gap = value_contracts.card_value(
            db, user=user, workspace=workspace, system=system
        )
        run = (
            db.query(Run)
            .filter(
                Run.workspace_id == workspace.id,
                Run.system_id == system.id,
                Run.flow_sha256 == version.flow_sha256,
                or_(Run.execution_surface.is_(None), Run.execution_surface != "draft_test"),
            )
            .order_by(Run.started_at.desc())
            .first()
        )
        if run is None:
            cards.append(job_explanation(job, convention, gap=gap))
            continue
        try:
            cards.append(
                job_explanation(
                    job,
                    convention,
                    run={
                        "id": run.id,
                        "system_id": run.system_id,
                        "status": run.status,
                        "flow_sha256": run.flow_sha256,
                        "execution_surface": run.execution_surface,
                    },
                    proof=invocation_proof(db, run),
                    gap=gap,
                )
            )
        except AutomationPortfolioRefusal:
            cards.append(job_explanation(job, convention, gap=gap))
    return cards


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
