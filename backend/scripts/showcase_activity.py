"""Deterministic daily activity backfill for the Agentium Showcase workspace.

``GET /api/v1/hypervisor/series`` reads completed Runs: how many per day, how
many carry an outcome decision (``OUTCOME_DECISIONS``), what they cost
(``cost_internal``), and converts outcomes to hours / EUR only through the
Capability ``value_basis``. The story in ``seed_showcase_workspace.seed_story``
writes a handful of runs pinned to the moment it ran (and it runs once per
workspace), so a page served weeks later shows a single active day.

This module spreads synthetic runs over the last ``window_days`` with a weekly
rhythm (weekdays full, weekends attenuated), a mild week-to-week drift, one
portfolio-wide peak day inside the last 30 days, and one System kept stale
(``DEFAULT_STALE_SYSTEM``: SAP HANA Maintenance Copilot; it has no story run,
so the "no run in the last N days" signal is true on a fresh database as well
as on the VM). Everything is drawn from ``random.Random(seed)`` in a fixed
order, so the same ``seed`` + ``now`` reproduce the same plan.

Honesty contract: runs and ``cost_internal`` are the measured facts; hours and
value are never written on a run, they only exist through a declared
``value_basis`` on the Capability. ``value_estimated`` follows the seed's
existing convention (declared value per outcome x outcome multiplier).

Every generated Run is flagged ``input_ref.showcase_seed = True``,
``input_ref.evidence_kind = "synthetic_demo"`` (the flags the story already
uses, so System 360 filters it out) and ``input_ref.showcase_activity = True``;
its EvaluationScore carries the same keys in ``metadata_``. Replaying deletes
the previous backfill through that last flag, scoped to the Showcase workspace.
The story runs are never touched: they are guarded once-only and referenced by
canonical answers, chat sessions, decisions and audits.
"""
from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_feedback import EvaluationFeedback
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace

ACTIVITY_MARKER = "showcase_activity"
DEFAULT_WINDOW_DAYS = 90
DEFAULT_SEED = 20260908
DEFAULT_VOLUME_SCALE = 1.0
DEFAULT_WEEKEND_FACTOR = 0.2
DEFAULT_STALE_SYSTEM = "SAP HANA Maintenance Copilot"
DEFAULT_STALE_DAYS = 14
PEAK_BOOST = 2.2
WEEK_DRIFT = (0.85, 1.15)
OFFICE_START = dtime(hour=7, minute=0)  # 09:00 Paris in summer, stored as UTC
OFFICE_END = dtime(hour=17, minute=0)
_DELETE_CHUNK = 500

# approved / partial count as outcomes in the Hypervisor; hitl_escalated and
# failed are the honest remainder (see app.services.outcome.derive).
DECISIONS = ("approved", "partial", "hitl_escalated", "failed")
_VALUE_MULTIPLIER = {"approved": 1.0, "partial": 0.5}
_TRANSLATION_VERDICT = {
    "approved": "ACCEPT_4D",
    "partial": "ACCEPT_4D_WITH_VARIANCES",
    "hitl_escalated": "BLOCK_RELEASE",
    "failed": "BLOCK_RELEASE",
}


@dataclass(frozen=True)
class ActivityProfile:
    system_name: str
    weekday_mean: float
    kind: str  # "answer" (create_run_eval) | "translation_batch" (create_translation_run)
    decision_weights: tuple[float, float, float, float]  # order of DECISIONS
    cost_range: tuple[float, float]
    triggers: tuple[str, ...]
    topic: str
    question_type: str
    sources: tuple[str, ...]
    queries: tuple[str, ...]


PROFILES: tuple[ActivityProfile, ...] = (
    ActivityProfile(
        system_name="Knowledge Capture",
        weekday_mean=16.0,
        kind="answer",
        decision_weights=(0.78, 0.14, 0.03, 0.05),
        cost_range=(0.18, 0.45),
        triggers=("chat", "chat", "chat", "manual"),
        topic="Expert knowledge capture",
        question_type="knowledge_update",
        sources=("northforge-notices-2026.md", "expert-fiche-hydraulics.md"),
        queries=(
            "Capture the torque sequence change for the NF-220 gearbox service notice",
            "Propose a knowledge update from the field report on pump cavitation",
            "Turn the commissioning debrief into an expert fiche for the turbine team",
            "Record the revised lockout procedure as a knowledge update proposal",
            "Capture the root cause of the bearing overheating case as reusable knowledge",
            "Consolidate the three notices on valve seat wear into one expert fiche",
            "Draft a knowledge update for the new coolant specification",
            "Summarise the shutdown checklist changes for the operations wiki",
        ),
    ),
    ActivityProfile(
        system_name="Tender Response Analyst",
        weekday_mean=13.0,
        kind="answer",
        decision_weights=(0.72, 0.18, 0.05, 0.05),
        cost_range=(0.25, 0.70),
        triggers=("chat", "chat", "api"),
        topic="Tender response",
        question_type="comparative",
        sources=("tender-evidence-library.md", "reference-projects-2025.md"),
        queries=(
            "Answer the availability requirement using our 2025 reference projects",
            "Draft the response to the cybersecurity questionnaire section 4.2",
            "Which references support a 99.95% uptime commitment?",
            "Compose the maintenance SLA answer for the regional water utility tender",
            "Reuse the ISO 27001 evidence for the data residency question",
            "Answer the spare-parts lead time clause with our logistics commitments",
            "Draft the training and handover section from the last three bids",
        ),
    ),
    ActivityProfile(
        system_name="Contract Risk Copilot",
        weekday_mean=9.0,
        kind="answer",
        decision_weights=(0.70, 0.17, 0.08, 0.05),
        cost_range=(0.30, 0.90),
        triggers=("chat", "chat", "manual"),
        topic="SLA and contract risk",
        question_type="factual",
        sources=("sla-enterprise-policy.md", "contract-risk-policy.md"),
        queries=(
            "Flag the liability cap clauses in the Acme master services agreement",
            "Does the renewal clause auto-extend beyond the enterprise policy limit?",
            "Which SLA commitments in this draft exceed our standard 99.9%?",
            "Review the indemnification section against the contract risk policy",
            "Is the termination-for-convenience notice period compliant?",
            "List unsupported claims in the vendor's uptime statement",
        ),
    ),
    ActivityProfile(
        system_name="SAP HANA Maintenance Copilot",
        weekday_mean=6.0,
        kind="answer",
        decision_weights=(0.80, 0.12, 0.02, 0.06),
        cost_range=(0.12, 0.40),
        triggers=("chat", "scheduler", "scheduler"),
        topic="Maintenance orders",
        question_type="factual",
        sources=("sap-hana-maintenance-orders.sql", "pih-operator-brief-template.md"),
        queries=(
            "List released maintenance orders for plant 1100 due this week",
            "Which open orders on the penstock valves are overdue?",
            "Prioritise today's open maintenance orders for the PIH operator",
            "Summarise released orders by work centre for the morning brief",
            "Which orders were released in the last 24 hours on the generator set?",
        ),
    ),
    ActivityProfile(
        system_name="Compliance Review Loop",
        weekday_mean=4.0,
        kind="answer",
        decision_weights=(0.55, 0.15, 0.25, 0.05),
        cost_range=(0.40, 1.20),
        triggers=("hitl", "chat"),
        topic="Compliance review",
        question_type="analytical",
        sources=("compliance-handbook.md", "gdpr-processing-register.md"),
        queries=(
            "Can the marketing team reuse customer emails for the product survey?",
            "Review the data retention answer before it goes to the regulator",
            "Is the subcontractor allowed to process HR records outside the EU?",
            "Approve the sanctions screening response for the export desk",
            "Does the new supplier onboarding form need a DPIA?",
        ),
    ),
    ActivityProfile(
        system_name="Translation Suite",
        weekday_mean=2.0,
        kind="translation_batch",
        decision_weights=(0.70, 0.15, 0.10, 0.05),
        # Daily deltas are far smaller than the story's 39-locale qualification
        # batch (144 EUR); keep translation the costliest System without turning
        # the cost view into a single slab.
        cost_range=(6.0, 48.0),
        triggers=("scheduler", "manual"),
        topic="PMI DITA translation delivery",
        question_type="translation_batch",
        sources=(),
        queries=(
            "KANGOO3 maintenance manual delta - 12 locale fan-out",
            "TRAFIC4 operator guide batch - 39 locale fan-out",
            "ZOE5 service bulletin batch - 8 locale fan-out",
            "MASTER3 diagnostic topics - 21 locale fan-out",
            "Weekly DITA delta - reusable topics replay",
        ),
    ),
)


@dataclass(frozen=True)
class ActivityPlan:
    """Per-System, per-day run counts plus the parameters that produced them."""

    counts: dict[str, dict[date, int]]
    peak_day: date
    window_start: date
    window_end: date

    def total(self, system_name: str | None = None) -> int:
        if system_name is not None:
            return sum(self.counts.get(system_name, {}).values())
        return sum(sum(days.values()) for days in self.counts.values())


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    threshold = math.exp(-mean)
    count = 0
    product = 1.0
    while True:
        product *= rng.random()
        if product <= threshold:
            return count
        count += 1


def _office_fraction_elapsed(now: datetime) -> float:
    """Share of today's office window already elapsed (0 before, 1 after)."""
    start = datetime.combine(now.date(), OFFICE_START)
    end = datetime.combine(now.date(), OFFICE_END)
    if now <= start:
        return 0.0
    if now >= end:
        return 1.0
    return (now - start).total_seconds() / (end - start).total_seconds()


def plan_activity(
    *,
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
    seed: int = DEFAULT_SEED,
    volume_scale: float = DEFAULT_VOLUME_SCALE,
    weekend_factor: float = DEFAULT_WEEKEND_FACTOR,
    stale_system: str | None = DEFAULT_STALE_SYSTEM,
    stale_days: int = DEFAULT_STALE_DAYS,
    profiles: tuple[ActivityProfile, ...] = PROFILES,
) -> ActivityPlan:
    """Pure planning step: how many runs each System gets on each day.

    Days are counted back from ``now`` (today included, pro-rated on the office
    hours already elapsed). The RNG is consumed in a fixed order so that a given
    ``seed`` and ``now`` always yield the same plan.
    """
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    rng = random.Random(seed)
    today = now.date()
    window_start = today - timedelta(days=window_days - 1)

    # One visible spike inside the 30-day window, on a weekday, far enough from
    # both edges to be readable on the month dial.
    peak_candidates = [
        today - timedelta(days=offset)
        for offset in range(5, min(26, window_days))
        if (today - timedelta(days=offset)).weekday() < 5
    ]
    peak_day = rng.choice(peak_candidates) if peak_candidates else today

    counts: dict[str, dict[date, int]] = {}
    for profile in profiles:
        week_drift: dict[int, float] = {}
        per_day: dict[date, int] = {}
        for offset in range(window_days - 1, -1, -1):
            day = today - timedelta(days=offset)
            week_index = (day - window_start).days // 7
            if week_index not in week_drift:
                week_drift[week_index] = rng.uniform(*WEEK_DRIFT)
            mean = profile.weekday_mean * volume_scale * week_drift[week_index]
            if day.weekday() >= 5:
                mean *= weekend_factor
            if day == peak_day:
                mean *= PEAK_BOOST
            if offset == 0:
                mean *= _office_fraction_elapsed(now)
            drawn = _poisson(rng, mean)
            if stale_system == profile.system_name and offset < stale_days:
                drawn = 0
            per_day[day] = drawn
        counts[profile.system_name] = per_day
    return ActivityPlan(
        counts=counts, peak_day=peak_day, window_start=window_start, window_end=today
    )


def _pick_decision(rng: random.Random, profile: ActivityProfile) -> str:
    return rng.choices(DECISIONS, weights=profile.decision_weights, k=1)[0]


def _started_at(rng: random.Random, day: date, now: datetime) -> datetime:
    start = datetime.combine(day, OFFICE_START)
    end = datetime.combine(day, OFFICE_END)
    started = start + timedelta(seconds=rng.uniform(0, (end - start).total_seconds()))
    if day == now.date():
        # Today's runs must already be over; the plan only draws them once
        # office hours have begun, so this clamp rarely bites.
        started = min(started, now - timedelta(minutes=5))
    return started


def _value_per_outcome(capability: Capability | None) -> float:
    if capability is None:
        return 0.0
    basis = capability.value_basis if isinstance(capability.value_basis, dict) else {}
    if basis.get("status") != "none" and basis.get("value_per_unit") is not None:
        try:
            return float(basis["value_per_unit"])
        except (TypeError, ValueError):
            pass
    return float(capability.value_per_outcome or 0.0)


def _flag(payload: dict[str, Any] | None) -> dict[str, Any]:
    flagged = dict(payload or {})
    flagged["showcase_seed"] = True
    flagged["evidence_kind"] = "synthetic_demo"
    flagged[ACTIVITY_MARKER] = True
    return flagged


def _quality(rng: random.Random, decision: str) -> tuple[float, float, list[str]]:
    """(composite, hallucination_rate, failed_components) coherent with the decision."""
    if decision == "failed":
        return (
            round(rng.uniform(52.0, 68.0), 1),
            round(rng.uniform(0.31, 0.48), 3),
            ["hallucination"],
        )
    if decision == "hitl_escalated":
        return round(rng.uniform(70.0, 82.0), 1), round(rng.uniform(0.08, 0.22), 3), []
    if decision == "partial":
        return round(rng.uniform(74.0, 88.0), 1), round(rng.uniform(0.04, 0.15), 3), []
    return round(rng.uniform(84.0, 98.0), 1), round(rng.uniform(0.0, 0.06), 3), []


def wipe_showcase_activity(db: DBSession, workspace: Workspace) -> int:
    """Delete the previous backfill for this workspace only; returns the run count.

    Only runs flagged ``input_ref.showcase_activity`` go, together with their
    EvaluationScores and anything a reviewer may have attached to them
    (feedback, run-scoped Decisions, invocations). Story runs are untouched.
    """
    rows = (
        db.query(Run.id, Run.input_ref)
        .filter(Run.workspace_id == workspace.id)
        .all()
    )
    run_ids = [
        run_id
        for run_id, input_ref in rows
        if isinstance(input_ref, dict) and input_ref.get(ACTIVITY_MARKER) is True
    ]
    for start in range(0, len(run_ids), _DELETE_CHUNK):
        chunk = run_ids[start : start + _DELETE_CHUNK]
        db.query(EvaluationFeedback).filter(
            EvaluationFeedback.workspace_id == workspace.id,
            EvaluationFeedback.run_id.in_(chunk),
        ).delete(synchronize_session=False)
        db.query(EvaluationScore).filter(
            EvaluationScore.workspace_id == workspace.id,
            EvaluationScore.run_id.in_(chunk),
        ).delete(synchronize_session=False)
        db.query(Decision).filter(
            Decision.workspace_id == workspace.id,
            Decision.scope == "run",
            Decision.target_id.in_(chunk),
        ).delete(synchronize_session=False)
        db.query(SkillInvocation).filter(SkillInvocation.run_id.in_(chunk)).delete(
            synchronize_session=False
        )
        db.query(Run).filter(
            Run.workspace_id == workspace.id, Run.id.in_(chunk)
        ).delete(synchronize_session=False)
    db.flush()
    return len(run_ids)


def backfill_showcase_activity(
    db: DBSession,
    workspace: Workspace,
    systems_by_name: dict[str, System],
    *,
    now: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    seed: int = DEFAULT_SEED,
    volume_scale: float = DEFAULT_VOLUME_SCALE,
    weekend_factor: float = DEFAULT_WEEKEND_FACTOR,
    stale_system: str | None = DEFAULT_STALE_SYSTEM,
    stale_days: int = DEFAULT_STALE_DAYS,
    profiles: tuple[ActivityProfile, ...] = PROFILES,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Replace the workspace's synthetic activity with a fresh deterministic backfill.

    Reuses the seed's own run factories (``create_run_eval`` for answer-style
    Systems, ``create_translation_run`` for the Translation Suite) so Score rows
    keep their shape; objects are collected and flushed once (bulk insert).
    Systems missing from ``systems_by_name`` are skipped and reported.
    """
    # Imported lazily: the seed module imports this one.
    from scripts.seed_showcase_workspace import create_run_eval, create_translation_run

    started = time.perf_counter()
    now = now or datetime.utcnow()
    wiped = wipe_showcase_activity(db, workspace)
    plan = plan_activity(
        now=now,
        window_days=window_days,
        seed=seed,
        volume_scale=volume_scale,
        weekend_factor=weekend_factor,
        stale_system=stale_system,
        stale_days=stale_days,
        profiles=profiles,
    )
    # Independent stream so the plan (counts) is stable regardless of how the
    # per-run details below evolve.
    rng = random.Random(seed ^ 0x5EED)

    created_runs = 0
    created_scores = 0
    per_system: dict[str, int] = {}
    skipped: list[str] = []
    for profile in profiles:
        system = systems_by_name.get(profile.system_name)
        if system is None:
            skipped.append(profile.system_name)
            continue
        capability = (
            db.get(Capability, system.capability_id) if system.capability_id else None
        )
        value_per_outcome = _value_per_outcome(capability)
        system_total = 0
        for day in sorted(plan.counts[profile.system_name]):
            for _ in range(plan.counts[profile.system_name][day]):
                decision = _pick_decision(rng, profile)
                started_at = _started_at(rng, day, now)
                cost = round(rng.uniform(*profile.cost_range), 2)
                value = round(value_per_outcome * _VALUE_MULTIPLIER.get(decision, 0.0), 2)
                trigger = rng.choice(profile.triggers)
                title = rng.choice(profile.queries)
                if profile.kind == "translation_batch":
                    # A batch started today must also have finished by now.
                    max_minutes = int((now - started_at).total_seconds() // 60) - 1
                    duration_minutes = max(1, min(int(rng.uniform(25, 240)), max_minutes))
                    run, score = create_translation_run(
                        db,
                        workspace,
                        system,
                        title=title,
                        status="completed",
                        verdict=_TRANSLATION_VERDICT[decision],
                        decision=decision,
                        started_at=started_at,
                        duration_minutes=duration_minutes,
                        confidence=round(rng.uniform(0.9, 0.99), 3)
                        if decision in _VALUE_MULTIPLIER
                        else round(rng.uniform(0.6, 0.85), 3),
                        value=value,
                        cost=cost,
                        trigger=trigger,
                        blocked_topic=(
                            None if decision in _VALUE_MULTIPLIER else "KANGOO3-OM-0423.dita"
                        ),
                        flush=False,
                        with_invocations=False,
                    )
                else:
                    composite, hallucination, failed_components = _quality(rng, decision)
                    run, score = create_run_eval(
                        db,
                        workspace,
                        system,
                        query=title,
                        response=(
                            f"Grounded answer for '{title}' with citations "
                            f"({profile.topic})."
                        ),
                        question_type=profile.question_type,
                        composite=composite,
                        hallucination=hallucination,
                        failed_components=failed_components,
                        started_at=started_at,
                        value=value,
                        cost=cost,
                        decision=decision,
                        trigger=trigger,
                        topic=profile.topic,
                        sources=[{"filename": name} for name in profile.sources],
                        claims=[
                            f"{title} is supported by {profile.sources[0]}",
                            f"The answer cites {len(profile.sources)} governed sources",
                        ],
                        flush=False,
                    )
                run.input_ref = _flag(run.input_ref)
                score.metadata_ = _flag(score.metadata_)
                created_runs += 1
                created_scores += 1
                system_total += 1
        per_system[profile.system_name] = system_total
    db.flush()
    elapsed = time.perf_counter() - started
    summary = {
        "wiped_runs": wiped,
        "created_runs": created_runs,
        "created_scores": created_scores,
        "per_system": per_system,
        "skipped_systems": skipped,
        "peak_day": plan.peak_day.isoformat(),
        "window_start": plan.window_start.isoformat(),
        "window_end": plan.window_end.isoformat(),
        "stale_system": stale_system,
        "stale_days": stale_days,
        "seed": seed,
        "elapsed_seconds": round(elapsed, 2),
    }
    log(
        "Showcase activity backfill: "
        f"wiped={wiped} created={created_runs} window={window_days}d "
        f"peak={summary['peak_day']} stale={stale_system!r} "
        f"skipped={skipped or 'none'} in {elapsed:.1f}s"
    )
    return summary
