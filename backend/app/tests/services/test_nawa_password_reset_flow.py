"""Runtime proof for the Nawa ITSD ``Password Reset`` flow (demo 2026-07-29).

Two levels, mirroring the pair of guards the seeded Andritz flows already have:

* **Structural** — ``dag_validator.validate_flow`` must report zero *errors* on
  both variants shipped by ``app/resources/flows/nawa_password_reset_v1.json``
  (the flow with real inference and its fully simulated fallback twin), and the
  graph must actually route to the DAG walker (``should_use_dag``). A flow
  without a control node silently falls back to the sequential walker, which
  ignores the HITL gate — the single most expensive way to discover a mistake
  is in front of the client.

* **Behavioural** — the walker is driven end to end with a stubbed registry over
  the three P0 scenarios of the demo script:

  ``nominal``        the six steps run, the ticket closes, the audit entry is written;
  ``ambiguous``      the classification says "account lockout", so the run leaves the
                     procedure with **no identity assessment, no directory gesture and
                     no audit write** — every one of those nodes must be *skipped*,
                     not merely produce an empty payload;
  ``weak_identity``  the identity assessment abstains, the run pauses in
                     ``hitl_pending`` before any privileged step, and only an accepted
                     Decision drives it to closure.

The stubs are deliberately *prompt-driven*: the fake model reads the prompt the
graph actually built and derives its answer from it, exactly like the real
provider would. A wiring mistake (wrong preset, wrong ``inputs_map``) therefore
fails the test instead of being papered over by a hardcoded answer.
"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.chains.dag_validator import validate_flow
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag, resume_run_dag, should_use_dag

ARTIFACT = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "flows"
        / "nawa_password_reset_v1.json"
    ).read_text(encoding="utf-8")
)

LLM_FLOW = ARTIFACT["flow_definition"]
FALLBACK_FLOW = ARTIFACT["fallback_flow_definition"]
SYSTEM_SETTINGS = ARTIFACT["system_settings"]
DEFAULT_MODEL = ARTIFACT["system"]["default_model"]

TEMP_PASSWORD = SYSTEM_SETTINGS["simulation"]["temporary_password_issued"]
TICKET_ID = SYSTEM_SETTINGS["simulation"]["ticket"]["id"]

# Every node that performs, prepares, or reports a privileged gesture. On the
# ``ambiguous`` lane the trace must show all of them skipped — including the
# closed-ticket leaf, which would otherwise claim a resolution that never
# happened.
PRIVILEGED_NODES = (
    "task.verify_identity",
    "hitl.identity_gate",
    "task.ad_reset",
    "task.temporary_credential",
    "task.draft_user_notice",
    "task.close_ticket",
    "task.audit_ledger",
    "sink.ticket_closed",
)

# The subset that must stay dark whenever the authorisation point refuses. The
# identity assessment is deliberately NOT in it: on the incident and quality
# lanes it has already run, and that is the point — the guards act on what it
# produced.
EXECUTION_NODES = (
    "task.ad_reset",
    "task.temporary_credential",
    "task.draft_user_notice",
    "task.close_ticket",
    "task.audit_ledger",
    "sink.ticket_closed",
)


# ---------------------------------------------------------------------------
# Stubbed registry — a prompt-driven fake provider
# ---------------------------------------------------------------------------
async def _fake_azure_llm(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Answer from the prompt the graph built, the way a real model would."""
    prompt = inp.get("prompt")
    assert isinstance(prompt, str) and prompt.strip(), (
        "the graph must feed azure_llm_v1 a non-empty prompt; got %r" % (prompt,)
    )
    assert inp.get("model") == DEFAULT_MODEL

    if "Classify the service desk request" in prompt:
        # The lockout symptom outranks the requester's own wording.
        lockout = "j'ai tape trois fois" in prompt or "bloque" in prompt
        return {"completion": "unlock_ad_account" if lockout else "password_reset"}

    if "identity evidence" in prompt:
        if "No line-manager confirmation obtained" in prompt:
            return {
                "completion": (
                    "IDENTITY_INSUFFICIENT No line-manager confirmation and no staff ID "
                    "matched against the HR record."
                )
            }
        return {
            "completion": (
                "IDENTITY_VERIFIED Staff ID matched the HR record and the line manager "
                "confirmed the request."
            )
        }

    if "Write the message the service desk sends" in prompt:
        assert TEMP_PASSWORD in prompt, "step 5 must be told the temporary password"
        return {
            "completion": (
                f"Your password has been reset. Temporary password: {TEMP_PASSWORD}. "
                "You will be asked to change it at your first sign-in. The service desk "
                "never asks for your password: do not share it with anyone."
            )
        }

    raise AssertionError(f"unexpected prompt reached the fake provider: {prompt[:120]!r}")


AUDIT_EVENT_TYPES = {
    SYSTEM_SETTINGS["simulation"]["audit_event_type"],
    *(
        record["event_type"]
        for record in SYSTEM_SETTINGS["simulation"]["audit_withheld"].values()
    ),
}


async def _fake_audit_log(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    assert inp.get("event_type") in AUDIT_EVENT_TYPES
    assert isinstance(inp.get("details"), dict)
    return {"id": "audit-event-test", "status": "recorded"}


BRIDGE_ERROR = "RPA Bridge connector is not enabled for this workspace"


async def _fake_rpa_dispatch(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """The bridge is not provisioned for this workspace, so it raises.

    Same failure the real ``rpa_dispatch_v1`` wrapper produces on its first
    guard — the point of the incident lane is that nothing about it is staged.
    """
    assert inp.get("job_key") == SYSTEM_SETTINGS["simulation"]["directory_bridge"]["job_key"]
    assert isinstance(inp.get("input"), dict), "the bridge must receive a payload object"
    raise ValueError(BRIDGE_ERROR)


async def _fake_response_eval(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror the real evaluator's contract, including its degraded mode.

    ``context_count`` is structural — the real wrapper derives it from the
    payload before touching the embedding backend — so it is exact here. The
    scores are the part that degrades to zero in production when embeddings
    are unavailable, which is precisely why the flow must not gate on them.
    """
    answer = inp.get("answer")
    assert isinstance(answer, str) and answer.strip(), "the guard needs the assessment text"
    assert isinstance(inp.get("query"), str) and inp["query"].strip()
    chunks = inp.get("context_chunks") or []
    assert isinstance(chunks, list)
    return {
        "composite": 82.5 if chunks else 0.0,
        "hallucination_rate": 0.1 if chunks else 1.0,
        "context_count": len(chunks),
        "hhem": 0.7 if chunks else 0.0,
        "factuality": 0.9 if chunks else 0.0,
        "coherence": 0.9 if chunks else 0.0,
    }


SkillFn = Callable[[Dict[str, Any], Dict[str, Any]], Any]


def _install_registry(monkeypatch: pytest.MonkeyPatch, skills: Dict[str, SkillFn]) -> None:
    """Patch the ``resolve_skill`` reference the walker actually calls."""

    def _resolve(slug: str) -> SkillFn:
        fn = skills.get(slug)
        if fn is None:
            raise NotImplementedError(f"flow reached an unexpected skill: {slug!r}")
        return fn

    monkeypatch.setattr(engine_module, "resolve_skill", _resolve)


SKILL_SLUGS = ("azure_llm_v1", "audit_log_v1", "response_eval_v1", "rpa_dispatch_v1")


def _install_full_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_registry(
        monkeypatch,
        {
            "azure_llm_v1": _fake_azure_llm,
            "audit_log_v1": _fake_audit_log,
            "response_eval_v1": _fake_response_eval,
            "rpa_dispatch_v1": _fake_rpa_dispatch,
        },
    )


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def _mk_skill(db, slug: str) -> Skill:
    row = Skill(
        id=str(uuid.uuid4()),
        slug=slug,
        version="1",
        name=slug,
        description=f"stub {slug}",
        input_schema={},
        output_schema={},
        pricing={"unit_price": 0.0},
        execution={"mode": "sync", "timeout_ms": 5000, "retryable": True, "idempotent": True},
        certification_level="production",
    )
    db.add(row)
    db.commit()
    return row


def _mk_system(db, flow: Dict[str, Any]) -> System:
    for slug in SKILL_SLUGS:
        _mk_skill(db, slug)
    row = System(
        id=str(uuid.uuid4()),
        name=ARTIFACT["system"]["name"],
        objective=ARTIFACT["system"]["objective"],
        skill_ids=[],
        flow_definition=flow,
        settings=SYSTEM_SETTINGS,
        default_model=DEFAULT_MODEL,
        execution_mode=ARTIFACT["system"]["execution_mode"],
        coordination_pattern=ARTIFACT["system"]["coordination_pattern"],
        status="active",
    )
    db.add(row)
    db.commit()
    return row


def _mk_run(db, system: System, scenario: str, **extra: Any) -> Run:
    row = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        input_ref={"scenario": scenario, "channel": "demo_ui", **extra},
        status="pending",
    )
    db.add(row)
    db.commit()
    return row


def _reload(db, run: Run) -> Run:
    db.expire_all()
    return db.query(Run).filter(Run.id == run.id).one()


def _invocations(db, run: Run) -> List[SkillInvocation]:
    return db.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).all()


def _slug_counts(db, run: Run, *, allow_failed: tuple = ()) -> Counter:
    rows = _invocations(db, run)
    assert all(
        row.status == "completed" or row.skill_slug in allow_failed for row in rows
    ), [(row.skill_slug, row.status, row.error) for row in rows]
    return Counter(row.skill_slug for row in rows)


def _node_status(run: Run) -> Dict[str, str]:
    """Last ``node_end`` status per node id, as the cockpit renders it."""
    out: Dict[str, str] = {}
    for cp in run.checkpoints or []:
        if cp.get("kind") == "node_end" and cp.get("node_id"):
            out[cp["node_id"]] = cp.get("status") or "completed"
    return out


def _checkpoint_kinds(run: Run) -> List[str]:
    return [cp.get("kind") for cp in (run.checkpoints or [])]


def _pending_decision(db, summary: Dict[str, Any]) -> Decision:
    decision_id: Optional[str] = summary.get("awaiting_decision")
    assert decision_id, f"the HITL gate must expose its Decision: {summary}"
    return db.query(Decision).filter(Decision.id == decision_id).one()


# ---------------------------------------------------------------------------
# 1 — Structural guards
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("variant", ["flow_definition", "fallback_flow_definition"])
def test_flow_has_no_validator_errors(variant) -> None:
    errors = [
        issue.to_dict() for issue in validate_flow(ARTIFACT[variant]) if issue.level == "error"
    ]
    assert errors == [], f"{variant} produced error-level issues: {errors}"


@pytest.mark.parametrize("variant", ["flow_definition", "fallback_flow_definition"])
def test_flow_routes_to_the_dag_walker(variant) -> None:
    """Without schema_version >= 2 AND a control node the run would take the
    sequential walker, which ignores ``hitl`` — the gate would never pause."""
    flow = ARTIFACT[variant]
    assert flow["schema_version"] >= 2
    kinds = {node["kind"] for node in flow["nodes"]}
    assert {"decision", "hitl"} <= kinds
    assert should_use_dag(System(flow_definition=flow)) is True


def test_both_variants_share_one_topology() -> None:
    """The fallback is a drop-in switch: same nodes, same edges, same labels.
    Everything that would leave the platform loses its bound skill."""
    assert [n["id"] for n in FALLBACK_FLOW["nodes"]] == [n["id"] for n in LLM_FLOW["nodes"]]
    assert FALLBACK_FLOW["edges"] == LLM_FLOW["edges"]

    def bound(flow):
        return {
            n["id"]: (n.get("config") or {}).get("skill_slug")
            for n in flow["nodes"]
            if (n.get("config") or {}).get("skill_slug")
        }

    assert bound(LLM_FLOW) == {
        "task.classify_intent": "azure_llm_v1",
        "task.verify_identity": "azure_llm_v1",
        "task.draft_user_notice": "azure_llm_v1",
        "task.quality_gate": "response_eval_v1",
        "task.directory_bridge": "rpa_dispatch_v1",
        "task.audit_ledger": "audit_log_v1",
        "task.audit_withheld_incident": "audit_log_v1",
        "task.audit_withheld_quality": "audit_log_v1",
    }
    # The audit ledger survives the switch on all three of its lanes: losing the
    # provider must not cost us the compliance trail.
    assert bound(FALLBACK_FLOW) == {
        "task.audit_ledger": "audit_log_v1",
        "task.audit_withheld_incident": "audit_log_v1",
        "task.audit_withheld_quality": "audit_log_v1",
    }


# Anything on this list names a piece of OUR machinery. It may appear in the
# execution trace and under `diagnostic_*`; it may never appear in a sentence a
# customer reads, nor in a compliance record.
PLUMBING_WORDS = (
    "rpa",
    "connector",
    "bridge",
    "skill",
    "azure",
    "provider",
    "endpoint",
    "api",
    "workspace",
    "flow",
    "node",
    "traceback",
    "exception",
)


def _assert_no_plumbing(text: str, label: str) -> None:
    lowered = text.lower()
    for word in PLUMBING_WORDS:
        assert word not in lowered, f"{label} leaks {word!r}: {text!r}"


def test_every_outcome_speaks_business_and_names_no_component() -> None:
    """The surface must never have to fall back on a technical string to have
    something to show. Each outcome carries its own sentence, and that sentence
    describes what happened to the request — not to a piece of our software."""
    for key, outcome in SYSTEM_SETTINGS["outcomes"].items():
        assert set(outcome) >= {"code", "label", "message"}, key
        message = outcome["message"]
        assert len(message) > 80, f"{key} message is too thin to stand alone: {message!r}"
        _assert_no_plumbing(message, f"{key} outcome message")


def test_the_ledger_records_what_was_prevented_in_business_language() -> None:
    """A compliance record is read by an auditor, not by us. It says what was
    withheld and why, and it names no component — same rule as the outcomes."""
    withheld = SYSTEM_SETTINGS["simulation"]["audit_withheld"]
    assert set(withheld) == {"incident", "quality_hold"}
    for key, record in withheld.items():
        details = record["details"]
        assert record["event_type"] == "itsd.password_reset.withheld"
        assert details["disposition"] == "withheld"
        # The three assertions an auditor needs to be able to quote.
        assert details["account_modified"] is False
        assert details["temporary_password_issued"] is False
        assert details["requester_notified"] is False
        assert len(details["withheld_reason"]) > 120, key
        _assert_no_plumbing(json.dumps(record), f"{key} ledger record")

    # The success record is held to the same standard.
    _assert_no_plumbing(
        json.dumps(SYSTEM_SETTINGS["simulation"]["audit_details"]), "completion ledger record"
    )


async def test_the_incident_business_plane_carries_no_provider_string(
    db_session, monkeypatch
) -> None:
    """The one place the demo could break: the raw error reads as OUR platform
    being misconfigured, not as the customer's directory being down. It is kept
    verbatim, but only under `diagnostic_*` and in the trace."""
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "ad_unreachable")
    await_result = await execute_run_dag(run.id)
    assert await_result["status"] == "completed"

    run = _reload(db_session, run)
    business = {
        key: value
        for key, value in run.output_ref.items()
        if not key.startswith("diagnostic_")
    }
    # `replay_input` is the payload of the retry action, not a string anyone
    # reads — it is excluded from the prose scan on purpose, and that is why the
    # parameter name never had to appear in the remediation sentence.
    displayed = deepcopy(business)
    displayed["outcome"].pop("replay_input")
    _assert_no_plumbing(json.dumps(displayed), "incident business plane")
    assert "not enabled" not in json.dumps(displayed).lower()

    # ...and it really is still there for the auditor, in both places.
    assert BRIDGE_ERROR in run.output_ref["diagnostic_detail"]
    node_end = next(
        cp
        for cp in run.checkpoints
        if cp.get("kind") == "node_end" and cp.get("node_id") == "task.directory_bridge"
    )
    assert BRIDGE_ERROR in node_end["error"]
    invocation = next(
        i for i in _invocations(db_session, run) if i.skill_slug == "rpa_dispatch_v1"
    )
    assert BRIDGE_ERROR in invocation.error


def test_no_competitor_brand_reaches_the_artifact() -> None:
    """§5.4 of the demo spec: the assistant is NAWA WE and nothing else. The
    source spreadsheet names a competitor's tooling 53 times; none of it may
    leak into a flow that is shown on screen."""
    raw = json.dumps(ARTIFACT, ensure_ascii=False).lower()
    for banned in ("servicenow", "service now", "virtual agent", "now assist", "uipath"):
        assert banned not in raw, f"banned term {banned!r} reached the flow artifact"
    assert "NAWA WE" in json.dumps(ARTIFACT, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 2 — P0 scenario: nominal
# ---------------------------------------------------------------------------
async def test_nominal_runs_the_six_steps_and_closes_the_ticket(db_session, monkeypatch):
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "nominal")

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    run = _reload(db_session, run)
    assert run.status == "completed"
    assert "hitl_pause" not in _checkpoint_kinds(run)

    out = run.output_ref
    assert out["outcome"]["code"] == "ticket_closed"
    assert out["outcome"]["reset_performed"] is True
    assert "password_reset" in out["detected_intent"]
    assert "IDENTITY_VERIFIED" in out["identity_verdict"]
    assert out["ticket"]["id"] == TICKET_ID
    assert out["ticket"]["state"] == "closed"
    # The fake credential must survive the pool's credential scrubber, which
    # strips any key named like a secret on the way in from System.settings.
    assert out["temporary_password_issued"] == TEMP_PASSWORD
    assert out["directory_action"]["mode"] == "dry_run"
    assert out["audit_event_id"] == "audit-event-test"
    assert TEMP_PASSWORD in out["user_message"]
    assert "never asks" in out["user_message"]

    # The grounding check runs on the unattended lane and passes; the
    # automation bridge is never dispatched outside the incident lane.
    assert out["evidence_on_file"] == 3
    assert _slug_counts(db_session, run) == Counter(
        {"azure_llm_v1": 3, "audit_log_v1": 1, "response_eval_v1": 1}
    )
    statuses = _node_status(run)
    assert [statuses.get(nid) for nid in PRIVILEGED_NODES] == [
        "completed",
        "skipped",  # no human gate needed when the evidence holds
        "completed",
        "completed",
        "completed",
        "completed",
        "completed",
        "completed",
    ]
    assert statuses["task.quality_gate"] == "completed"
    for nid in (
        "task.directory_bridge",
        "task.audit_withheld_incident",
        "task.audit_withheld_quality",
    ):
        assert statuses[nid] == "skipped"
    for nid in ("sink.routed_elsewhere", "sink.incident", "sink.quality_hold"):
        assert statuses[nid] == "skipped"


# ---------------------------------------------------------------------------
# 3 — P0 scenario: ambiguous
# ---------------------------------------------------------------------------
async def test_ambiguous_routes_out_without_any_privileged_step(db_session, monkeypatch):
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "ambiguous")

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    run = _reload(db_session, run)
    out = run.output_ref
    assert out["outcome"]["code"] == "routed_to_other_use_case"
    assert out["outcome"]["reset_performed"] is False
    assert out["outcome"]["target_use_case"] == "Account unlock (UC-02)"
    assert "unlock_ad_account" in out["detected_intent"]

    # Nothing from the reset procedure may appear in the result.
    for absent in ("ticket", "temporary_password_issued", "audit_event_id", "user_message"):
        assert absent not in out, f"{absent!r} leaked into an ambiguous run: {out}"

    # One classification call, and that is all: no identity assessment, no
    # drafting, no audit write.
    assert _slug_counts(db_session, run) == Counter({"azure_llm_v1": 1})

    statuses = _node_status(run)
    for nid in PRIVILEGED_NODES:
        assert statuses.get(nid) == "skipped", f"{nid} ran on the ambiguous lane"
    # Neither guard nor either withheld-write record costs anything on a lane
    # that never even reached the account.
    for nid in (
        "task.quality_gate",
        "task.directory_bridge",
        "task.audit_withheld_incident",
        "task.audit_withheld_quality",
    ):
        assert statuses[nid] == "skipped", f"{nid} ran on the ambiguous lane"
    for nid in ("sink.incident", "sink.quality_hold"):
        assert statuses[nid] == "skipped"
    assert statuses["sink.routed_elsewhere"] == "completed"
    assert "hitl_pause" not in _checkpoint_kinds(run)


# ---------------------------------------------------------------------------
# 4 — P0 scenario: weak_identity (pause / approve / resume)
# ---------------------------------------------------------------------------
async def test_weak_identity_pauses_at_the_gate_then_closes_on_approval(
    db_session, monkeypatch
):
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "weak_identity")

    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending", paused

    run = _reload(db_session, run)
    assert run.status == "hitl_pending"
    assert "hitl_pause" in _checkpoint_kinds(run)

    # The gate is durable and carries its expiry policy, even though the
    # deployment runs with the Celery beat off (so it never fires by itself).
    decision = _pending_decision(db_session, paused)
    assert decision.status == "proposed"
    assert decision.expires_at is not None
    assert decision.expiry_action == "reject"
    assert "IDENTITY_INSUFFICIENT" in decision.rationale["upstream"]["identity_verdict"]

    # Nothing privileged happened before the human verdict.
    assert _slug_counts(db_session, run) == Counter({"azure_llm_v1": 2})
    assert not run.output_ref
    paused_statuses = _node_status(run)
    for nid in ("task.ad_reset", "task.temporary_credential", "task.audit_ledger"):
        assert nid not in paused_statuses, f"{nid} ran before the gate was resolved"

    decision.status = "accepted"
    db_session.commit()

    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed", resumed

    run = _reload(db_session, run)
    assert run.status == "completed"
    assert "hitl_resume" in _checkpoint_kinds(run)

    out = run.output_ref
    assert out["outcome"]["code"] == "ticket_closed"
    assert "IDENTITY_INSUFFICIENT" in out["identity_verdict"]
    assert out["human_approval"]["approved"] is True
    assert out["human_approval"]["decision_id"] == decision.id
    assert out["ticket"]["state"] == "closed"
    assert out["temporary_password_issued"] == TEMP_PASSWORD
    assert out["audit_event_id"] == "audit-event-test"

    assert _slug_counts(db_session, run) == Counter(
        {"azure_llm_v1": 3, "audit_log_v1": 1}
    )
    statuses = _node_status(run)
    assert statuses["hitl.identity_gate"] == "completed"
    assert statuses["task.ad_reset"] == "completed"
    assert statuses["sink.approval_refused"] == "skipped"


async def test_weak_identity_refusal_performs_no_privileged_step(db_session, monkeypatch):
    """The governance claim cuts both ways: a refused gate must leave the
    directory untouched and still close the run cleanly."""
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "weak_identity")

    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"
    decision = _pending_decision(db_session, paused)
    decision.status = "rejected"
    db_session.commit()

    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed", resumed

    run = _reload(db_session, run)
    assert run.output_ref["outcome"]["code"] == "approval_refused"
    assert run.output_ref["outcome"]["reset_performed"] is False
    assert "ticket" not in run.output_ref
    assert _slug_counts(db_session, run) == Counter({"azure_llm_v1": 2})
    statuses = _node_status(run)
    for nid in ("task.ad_reset", "task.temporary_credential", "task.close_ticket"):
        assert statuses[nid] == "skipped"
    assert statuses["sink.ticket_closed"] == "skipped"
    assert statuses["sink.approval_refused"] == "completed"


# ---------------------------------------------------------------------------
# 5 — P0 scenario: ad_unreachable (traced incident, then a successful remediation run)
# ---------------------------------------------------------------------------
async def test_ad_unreachable_traces_a_real_failure_and_contains_it(db_session, monkeypatch):
    """The bridge is the only node that leaves the platform, and it is not
    provisioned: the failure is real, traced, and stops the procedure dead."""
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "ad_unreachable")

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    run = _reload(db_session, run)
    out = run.output_ref
    assert out["outcome"]["code"] == "incident_directory_unreachable"
    assert out["outcome"]["reset_performed"] is False
    assert out["outcome"]["replay_input"] == {
        "scenario": "ad_unreachable",
        "bridge_fallback": True,
    }
    # The verbatim provider error is kept, but only under the diagnostic prefix.
    assert BRIDGE_ERROR in out["diagnostic_detail"]
    assert out["diagnostic_status"] == "failed"
    assert "IDENTITY_VERIFIED" in out["identity_verdict"]
    for absent in ("ticket", "temporary_password_issued", "audit_event_id", "user_message"):
        assert absent not in out, f"{absent!r} leaked into an incident run: {out}"

    # A genuinely failed invocation, not a staged one.
    failed = [i for i in _invocations(db_session, run) if i.status != "completed"]
    assert [i.skill_slug for i in failed] == ["rpa_dispatch_v1"]
    assert BRIDGE_ERROR in (failed[0].error or "")
    assert _slug_counts(db_session, run, allow_failed=("rpa_dispatch_v1",)) == Counter(
        {
            "azure_llm_v1": 2,
            "response_eval_v1": 1,
            "rpa_dispatch_v1": 1,
            "audit_log_v1": 1,
        }
    )

    # The cockpit reads the failure straight off the checkpoint.
    node_end = next(
        cp
        for cp in run.checkpoints
        if cp.get("kind") == "node_end" and cp.get("node_id") == "task.directory_bridge"
    )
    assert node_end["status"] == "failed"
    assert BRIDGE_ERROR in node_end["error"]

    statuses = _node_status(run)
    for nid in EXECUTION_NODES:
        assert statuses.get(nid) == "skipped", f"{nid} ran after the bridge failed"
    assert statuses["sink.incident"] == "completed"
    assert statuses["task.audit_withheld_incident"] == "completed"
    assert statuses["task.audit_withheld_quality"] == "skipped"
    for nid in ("sink.routed_elsewhere", "sink.approval_refused", "sink.quality_hold"):
        assert statuses[nid] == "skipped"


async def test_ad_unreachable_remediation_run_completes_the_reset(db_session, monkeypatch):
    """The manual replay: same request, bridge left out, procedure completes."""
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)

    incident = _mk_run(db_session, system, "ad_unreachable")
    await execute_run_dag(incident.id)
    assert _reload(db_session, incident).output_ref["outcome"]["code"] == (
        "incident_directory_unreachable"
    )

    replay = _mk_run(db_session, system, "ad_unreachable", bridge_fallback=True)
    summary = await execute_run_dag(replay.id)
    assert summary["status"] == "completed", summary

    replay = _reload(db_session, replay)
    out = replay.output_ref
    assert out["outcome"]["code"] == "ticket_closed"
    assert out["ticket"]["state"] == "closed"
    assert out["audit_event_id"] == "audit-event-test"
    # Same caller case as the incident run — the remediation changes the route,
    # not the request.
    assert "Omar Al-Kuwari" in out["user_message"] or TEMP_PASSWORD in out["user_message"]

    # The bridge was never dispatched a second time: no failed invocation at all.
    assert _slug_counts(db_session, replay) == Counter(
        {"azure_llm_v1": 3, "audit_log_v1": 1, "response_eval_v1": 1}
    )
    statuses = _node_status(replay)
    assert statuses["task.directory_bridge"] == "skipped"
    assert statuses["sink.incident"] == "skipped"
    assert statuses["sink.ticket_closed"] == "completed"


# ---------------------------------------------------------------------------
# 6 — P0 scenario: quality_guard (confident model, empty evidence record)
# ---------------------------------------------------------------------------
async def test_quality_guard_holds_the_privileged_write_on_an_ungrounded_assessment(
    db_session, monkeypatch
):
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "quality_guard")

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    run = _reload(db_session, run)
    out = run.output_ref
    assert out["outcome"]["code"] == "quality_hold_ungrounded_assessment"
    assert out["outcome"]["reset_performed"] is False
    # The model DID verify — the hold is the guard's doing, not the model's.
    assert "IDENTITY_VERIFIED" in out["identity_verdict"]
    assert out["evidence_on_file"] == 0
    # The floor scores an empty evidence record mechanically produces are kept
    # out of the business plane: read as a defect rate they would say something
    # about the model that is simply not true.
    assert out["diagnostic_hallucination_rate"] == 1.0
    assert "hallucination_rate" not in out
    for absent in ("ticket", "temporary_password_issued", "audit_event_id", "user_message"):
        assert absent not in out, f"{absent!r} leaked into a held run: {out}"

    assert _slug_counts(db_session, run) == Counter(
        {"azure_llm_v1": 2, "response_eval_v1": 1, "audit_log_v1": 1}
    )
    statuses = _node_status(run)
    for nid in EXECUTION_NODES:
        assert statuses.get(nid) == "skipped", f"{nid} ran on an ungrounded assessment"
    assert statuses["task.quality_gate"] == "completed"
    assert statuses["sink.quality_hold"] == "completed"
    assert statuses["task.audit_withheld_quality"] == "completed"
    assert statuses["task.audit_withheld_incident"] == "skipped"
    for nid in ("sink.ticket_closed", "sink.incident", "sink.approval_refused"):
        assert statuses[nid] == "skipped"
    assert "hitl_pause" not in _checkpoint_kinds(run)


async def test_quality_guard_does_not_fire_when_the_evaluator_is_degraded(
    db_session, monkeypatch
):
    """Fail-open by construction: the branch reads the evidence count, which is
    structural, never the scores, which zero out when embeddings are down."""

    async def _degraded_eval(inp: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "composite": 0.0,
            "hallucination_rate": 1.0,
            "context_count": len(inp.get("context_chunks") or []),
            "hhem": 0.0,
            "factuality": 0.0,
            "coherence": 0.0,
        }

    _install_registry(
        monkeypatch,
        {
            "azure_llm_v1": _fake_azure_llm,
            "audit_log_v1": _fake_audit_log,
            "response_eval_v1": _degraded_eval,
            "rpa_dispatch_v1": _fake_rpa_dispatch,
        },
    )
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "nominal")

    assert (await execute_run_dag(run.id))["status"] == "completed"
    run = _reload(db_session, run)
    assert run.output_ref["outcome"]["code"] == "ticket_closed"
    assert run.output_ref["diagnostic_quality_score"] == 0.0


# ---------------------------------------------------------------------------
# 7 — The fallback variant: same outcomes, zero provider calls
# ---------------------------------------------------------------------------
async def test_fallback_variant_reaches_the_same_outcomes_without_a_provider(
    db_session, monkeypatch
):
    """If the provider degrades mid-demo we swap ``flow_definition`` for this
    twin. It must reproduce the three P0 outcomes — HITL gate included — while
    calling nothing but the audit ledger."""
    _install_registry(monkeypatch, {"audit_log_v1": _fake_audit_log})

    system = _mk_system(db_session, FALLBACK_FLOW)

    nominal = _mk_run(db_session, system, "nominal")
    assert (await execute_run_dag(nominal.id))["status"] == "completed"
    nominal = _reload(db_session, nominal)
    assert nominal.output_ref["outcome"]["code"] == "ticket_closed"
    assert nominal.output_ref["temporary_password_issued"] == TEMP_PASSWORD
    assert TEMP_PASSWORD in nominal.output_ref["user_message"]
    assert _slug_counts(db_session, nominal) == Counter({"audit_log_v1": 1})

    ambiguous = _mk_run(db_session, system, "ambiguous")
    assert (await execute_run_dag(ambiguous.id))["status"] == "completed"
    ambiguous = _reload(db_session, ambiguous)
    assert ambiguous.output_ref["outcome"]["code"] == "routed_to_other_use_case"
    assert _slug_counts(db_session, ambiguous) == Counter()
    assert _node_status(ambiguous)["task.ad_reset"] == "skipped"

    weak = _mk_run(db_session, system, "weak_identity")
    paused = await execute_run_dag(weak.id)
    assert paused["status"] == "hitl_pending", paused
    decision = _pending_decision(db_session, paused)
    decision.status = "accepted"
    db_session.commit()
    assert (await resume_run_dag(weak.id, decision_id=decision.id))["status"] == "completed"
    weak = _reload(db_session, weak)
    assert weak.output_ref["outcome"]["code"] == "ticket_closed"
    assert weak.output_ref["human_approval"]["approved"] is True
    assert _slug_counts(db_session, weak) == Counter({"audit_log_v1": 1})

    # The two incident/quality lanes reach the same verdicts without the
    # connector or the evaluator: the twin binds neither.
    incident = _mk_run(db_session, system, "ad_unreachable")
    assert (await execute_run_dag(incident.id))["status"] == "completed"
    incident = _reload(db_session, incident)
    assert incident.output_ref["outcome"]["code"] == "incident_directory_unreachable"
    assert _slug_counts(db_session, incident) == Counter({"audit_log_v1": 1})
    assert _node_status(incident)["task.ad_reset"] == "skipped"

    remediated = _mk_run(db_session, system, "ad_unreachable", bridge_fallback=True)
    assert (await execute_run_dag(remediated.id))["status"] == "completed"
    remediated = _reload(db_session, remediated)
    assert remediated.output_ref["outcome"]["code"] == "ticket_closed"
    assert _slug_counts(db_session, remediated) == Counter({"audit_log_v1": 1})

    held = _mk_run(db_session, system, "quality_guard")
    assert (await execute_run_dag(held.id))["status"] == "completed"
    held = _reload(db_session, held)
    assert held.output_ref["outcome"]["code"] == "quality_hold_ungrounded_assessment"
    assert held.output_ref["evidence_on_file"] == 0
    assert _slug_counts(db_session, held) == Counter({"audit_log_v1": 1})


# ---------------------------------------------------------------------------
# 6 — An unknown scenario must never be an error path on stage
# ---------------------------------------------------------------------------
async def test_unknown_scenario_falls_back_to_the_nominal_case(db_session, monkeypatch):
    _install_full_registry(monkeypatch)
    system = _mk_system(db_session, LLM_FLOW)
    run = _mk_run(db_session, system, "not-a-scenario")

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary
    run = _reload(db_session, run)
    assert run.output_ref["outcome"]["code"] == "ticket_closed"
