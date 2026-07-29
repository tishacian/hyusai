"""Focused tests for the attested, marker-only Lot 7 projector rollout."""
from __future__ import annotations

import base64
import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.api.v1.endpoints.runs import _invocation, _row
from app.models.audit import AuditLog
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.projection_gate import (
    PROJECTION_FINALIZATION_AUDIT_EVENT,
    authoritative_projection_enabled,
    projection_activation_sha256,
    projection_enabled,
)
from scripts import rollout_lot7_projections as rollout

TRUSTED_RUNNER = {
    "issuer": "https://gitlab.example.test",
    "project_id": "42",
    "pipeline_id": "314",
    "job_id": "159",
    "commit_sha": "a" * 40,
    "ref": "demo/agentic",
    "ref_protected": True,
}


@pytest.fixture(autouse=True)
def _deployed_revision(monkeypatch):
    monkeypatch.setattr(rollout.settings, "agentium_image_revision", "a" * 40)
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_oidc_issuer",
        TRUSTED_RUNNER["issuer"],
    )
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_project_id",
        TRUSTED_RUNNER["project_id"],
    )
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_ref",
        TRUSTED_RUNNER["ref"],
    )


def _seed_target(db):
    workspace = Workspace(
        id=str(uuid4()),
        name="Opaque showcase",
        slug=f"opaque-{uuid4()}",
        settings={
            "family": "generic",
            "features": {
                "cockpit_router_axes_v4": True,
                "system_360_projection_v1": True,
                **{
                    feature: False
                    for feature in rollout.FEATURE_BY_PROJECTION.values()
                },
            },
        },
    )
    capability = Capability(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"opaque-{uuid4()}",
        name="Opaque capability",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Opaque System",
        objective="Test marker-only rollout",
        status="active",
        settings={"experience": {"system_360_canary": "v1"}},
    )
    db.add_all([workspace, capability, system])
    db.commit()
    return workspace, capability, system


def _evidence(
    db,
    workspace,
    capability,
    system,
    projection,
    *,
    trusted_runner=None,
):
    probation = rollout._persisted_probation(rollout._state(system), projection)
    assert probation is not None, "evidence can only be produced inside a probation"
    flow = {
        "schema_version": 3,
        "nodes": [{"id": "node-1", "type": "task"}],
        "edges": [],
    }
    execution_at = datetime.now(UTC)
    version_count = db.query(SystemVersion).filter_by(system_id=system.id).count()
    version = SystemVersion(
        id=str(uuid4()),
        system_id=system.id,
        workspace_id=workspace.id,
        version_number=version_count + 1,
        flow_definition=flow,
        created_at=(execution_at - timedelta(seconds=1)).replace(tzinfo=None),
        created_by="test-validator",
    )
    skill = Skill(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug=f"canary-{uuid4()}",
        name="Canary skill",
        input_schema={},
        output_schema={},
        execution={},
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        capability_id=capability.id,
        status="completed",
        started_at=execution_at.replace(tzinfo=None),
        completed_at=(execution_at + timedelta(milliseconds=10)).replace(tzinfo=None),
        input_ref={
            "execution": {
                "snapshot_at": execution_at.isoformat().replace("+00:00", "Z"),
                "runtime_revision": "a" * 40,
            }
        },
        flow_snapshot=flow,
        flow_version_id=version.id,
    )
    execution_snapshot = {
        "schema_version": 1,
        "resolution": "resolved",
        "skill": {"id": skill.id, "slug": skill.slug, "scope": "workspace"},
        "digests": {
            "input_contract_sha256": "1" * 64,
            "output_contract_sha256": "2" * 64,
            "execution_sha256": "3" * 64,
        },
    }
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_id=skill.id,
        skill_slug=skill.slug,
        status="completed",
        started_at=execution_at.replace(tzinfo=None),
        completed_at=(execution_at + timedelta(milliseconds=5)).replace(tzinfo=None),
        execution_snapshot=execution_snapshot,
    )
    gate_off = Workspace(
        id=str(uuid4()),
        name="Gate-off Workspace",
        slug=f"gate-off-{uuid4()}",
        settings={"features": {}},
    )
    db.add_all([version, skill, run, invocation, gate_off])
    db.commit()

    subject = {
        "workspace_id": workspace.id,
        "capability_id": capability.id,
        "system_id": system.id,
        "projection": projection,
    }
    revision = "a" * 40
    projection_sha256 = {
        lens: rollout._canonical_sha256({"projection": projection, "lens": lens})
        for lens in rollout.EVIDENCE_LENSES
    }
    runner_properties = ""
    if trusted_runner is not None:
        runner_properties = (
            f'<property name="runner_project_id" value="{trusted_runner["project_id"]}" />'
            f'<property name="runner_pipeline_id" value="{trusted_runner["pipeline_id"]}" />'
            f'<property name="runner_job_id" value="{trusted_runner["job_id"]}" />'
        )
    junit_xml = (
        f'<testsuite name="{rollout.EVIDENCE_JUNIT_SUITE}" tests="1" '
        'failures="0" errors="0" skipped="0">'
        '<properties>'
        f'<property name="revision" value="{revision}" />'
        f'<property name="workspace_id" value="{workspace.id}" />'
        f'<property name="system_id" value="{system.id}" />'
        f'<property name="capability_id" value="{capability.id}" />'
        f'<property name="projection" value="{projection}" />'
        f'<property name="lease_id" value="{probation["lease_id"]}" />'
        f'{runner_properties}'
        '</properties>'
        '<testcase classname="lot7.object_graph" name="authenticated canary" />'
        '</testsuite>'
    ).encode()
    artifact_ref = f"sha256:{hashlib.sha256(junit_xml).hexdigest()}"
    source_manifest = {
        "schema_version": 1,
        "kind": rollout.EVIDENCE_SOURCE_KIND,
        "subject": subject,
        "gate": {
            "phase": "probation",
            "lease_id": probation["lease_id"],
            "revision": probation["revision"],
            "staged_at": probation["staged_at"],
            "expires_at": probation["expires_at"],
        },
        "runtime": {
            "run_id": run.id,
            "status": "completed",
            "started_at": execution_at.isoformat(),
            "execution_snapshot_at": execution_at.isoformat(),
            "completed_at": (execution_at + timedelta(milliseconds=10)).isoformat(),
            "runtime_revision": revision,
            "flow_version_id": version.id,
            "flow_snapshot_sha256": rollout._canonical_sha256(flow),
            "primary_invocation_id": invocation.id,
            "catalog_skill_id": skill.id,
            "invocations": [
                {
                    "id": invocation.id,
                    "status": "completed",
                    "resolution": "resolved",
                    "execution_snapshot_sha256": rollout._canonical_sha256(
                        execution_snapshot
                    ),
                }
            ],
        },
        "gate_off_workspace_id": gate_off.id,
        "runner_artifact_ref": artifact_ref,
        "build_info": {
            service: {
                "revision": revision,
                "service": service,
                "revision_verified": True,
            }
            for service in ("backend", "frontend")
        },
        "projection_sha256": projection_sha256,
        "rendered_fact_sources": {
            lens: {
                "block_id": f"{lens}-overview",
                "fact_key": f"{lens}-fact",
                "fact_label": f"{lens.title()} fact",
                "fact_state": "available",
                "api_fact_sha256": rollout._canonical_sha256(
                    {"lens": lens, "source": "api"}
                ),
                "rendered_text_sha256": rollout._canonical_sha256(
                    {"lens": lens, "source": "ui"}
                ),
            }
            for lens in rollout.EVIDENCE_LENSES
        },
        "invariant_chrome_sha256": rollout._canonical_sha256(
            {"header": "invariant", "facets": ["overview"]}
        ),
        "suite": rollout.EVIDENCE_SUITE,
    }
    return {
        "schema_version": rollout.EVIDENCE_SCHEMA_VERSION,
        "result": "passed",
        "subject": subject,
        "validated_by": "test-validator",
        "validated_at": (execution_at + timedelta(seconds=1)).isoformat(),
        "revision": revision,
        "environment": "isolated-test",
        "source_manifest": source_manifest,
        "source_ref": f"sha256:{rollout._canonical_sha256(source_manifest)}",
        "runner_artifact": {
            "format": "junit_xml",
            "artifact_ref": artifact_ref,
            "content_base64": base64.b64encode(junit_xml).decode("ascii"),
        },
    }


def _pilot_observation(system, capability, projection, *, profile="operator"):
    probation = rollout._persisted_probation(rollout._state(system), projection)
    assert probation is not None
    return {
        "schema_version": rollout.PILOT_OBSERVATION_SCHEMA_VERSION,
        "kind": rollout.PILOT_OBSERVATION_KIND,
        "subject": {
            "workspace_id": system.workspace_id,
            "system_id": system.id,
            "capability_id": capability.id,
            "projection": projection,
            "revision": probation["revision"],
            "lease_id": probation["lease_id"],
        },
        "observed_at": datetime.now(UTC).isoformat(),
        "participant": {
            "id": "opaque-participant-lot7",
            "profile": profile,
        },
        "uncoached": True,
        "questions": [
            {
                "lens": lens,
                "success": True,
                "duration_seconds": 30 + index,
                "confidence": 4 + (index % 2),
                "critical_confusion": False,
            }
            for index, lens in enumerate(rollout.PILOT_QUESTION_LENSES)
        ],
    }


def _stage_and_activate(
    db,
    workspace,
    capability,
    system,
    projection,
    *,
    trusted_runner=TRUSTED_RUNNER,
):
    rollout.stage(
        db,
        workspace_id=workspace.id,
        projection=projection,
        apply=True,
        actor="operator",
    )
    db.refresh(workspace)
    db.refresh(system)
    result = rollout.activate(
        db,
        workspace_id=workspace.id,
        projection=projection,
        evidence=_evidence(
            db,
            workspace,
            capability,
            system,
            projection,
            trusted_runner=trusted_runner,
        ),
        pilot_observation=_pilot_observation(system, capability, projection),
        apply=True,
        actor="operator",
        trusted_runner=trusted_runner,
    )
    db.refresh(workspace)
    db.refresh(system)
    return result


def test_dry_run_is_inert_and_apply_requires_matching_evidence(db_session):
    workspace, capability, system = _seed_target(db_session)

    preview = rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=False,
        actor="test",
    )
    assert preview["operation"] == "dry_run"
    assert preview["direction"] == "stage"
    assert rollout._feature(workspace, "capability") is False
    assert rollout.ROLLOUT_STATE_KEY not in system.settings

    staged = rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="test",
    )
    assert staged["probation"]["lease_id"]
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert projection_enabled(
        workspace.settings,
        "capability",
        runtime_revision="a" * 40,
    ) is True

    with pytest.raises(rollout.ProjectionRolloutError, match="requires validation evidence"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=None,
            apply=True,
            actor="test",
        )

    mismatched = _evidence(db_session, workspace, capability, system, "capability")
    mismatched["subject"]["system_id"] = str(uuid4())
    with pytest.raises(rollout.ProjectionRolloutError, match="subject.system_id"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=mismatched,
            apply=True,
            actor="test",
        )

    abbreviated = _evidence(db_session, workspace, capability, system, "capability")
    abbreviated["revision"] = "a" * 12
    with pytest.raises(rollout.ProjectionRolloutError, match="exact 40-character"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=abbreviated,
            apply=False,
            actor="test",
        )

    valid = _evidence(db_session, workspace, capability, system, "capability")
    pilot_missing = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        evidence=valid,
        apply=False,
        actor="test",
    )
    assert pilot_missing["pilot_observation_required"] is True
    with pytest.raises(rollout.ProjectionRolloutError, match="pilot observation"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=valid,
            apply=True,
            actor="test",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("wrong_workspace", "active probation"),
        ("wrong_revision", "active probation"),
        ("wrong_lease", "active probation"),
        ("missing_participant_id", "opaque stable identifier"),
        ("unknown_profile", "canonical profile"),
        ("coached", "explicitly uncoached"),
        ("slow", r"within \(0, 60\]"),
        ("low_confidence", r"within \[4, 5\]"),
        ("failed", "did not answer"),
        ("confused", "critical confusion"),
        ("missing_question", "exactly four"),
        ("duplicate_lens", "each canonical lens exactly once"),
    ],
)
def test_pilot_observation_is_strict_lease_bound_and_uncoached(
    db_session,
    mutation,
    message,
):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    pilot = _pilot_observation(system, capability, "capability")
    if mutation == "wrong_workspace":
        pilot["subject"]["workspace_id"] = str(uuid4())
    elif mutation == "wrong_revision":
        pilot["subject"]["revision"] = "b" * 40
    elif mutation == "wrong_lease":
        pilot["subject"]["lease_id"] = str(uuid4())
    elif mutation == "missing_participant_id":
        pilot["participant"]["id"] = ""
    elif mutation == "unknown_profile":
        pilot["participant"]["profile"] = "admin"
    elif mutation == "coached":
        pilot["uncoached"] = False
    elif mutation == "slow":
        pilot["questions"][0]["duration_seconds"] = 60.1
    elif mutation == "low_confidence":
        pilot["questions"][0]["confidence"] = 3.9
    elif mutation == "failed":
        pilot["questions"][0]["success"] = False
    elif mutation == "confused":
        pilot["questions"][0]["critical_confusion"] = True
    elif mutation == "missing_question":
        pilot["questions"].pop()
    elif mutation == "duplicate_lens":
        pilot["questions"][-1]["lens"] = "build"

    with pytest.raises(rollout.ProjectionRolloutError, match=message):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=_evidence(
                db_session,
                workspace,
                capability,
                system,
                "capability",
            ),
            pilot_observation=pilot,
            apply=False,
            actor="operator",
        )


def test_pilot_observation_is_content_addressed_before_persistence(db_session):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    pilot = _pilot_observation(system, capability, "capability")
    probation = rollout._persisted_probation(
        rollout._state(system),
        "capability",
    )
    assert probation is not None

    metadata = rollout.validate_pilot_observation(
        pilot,
        projection="capability",
        workspace=workspace,
        capability=capability,
        system=system,
        probation=probation,
    )
    assert metadata["observation_ref"] == (
        f"sha256:{rollout._canonical_sha256(pilot)}"
    )
    assert metadata["subject"] == pilot["subject"]
    assert metadata["participant_ref"].startswith("sha256:")
    assert "questions" not in metadata
    assert pilot["participant"]["id"] not in str(metadata)


def test_activation_is_ordered_attested_and_idempotent(db_session):
    workspace, capability, system = _seed_target(db_session)

    first = _stage_and_activate(
        db_session, workspace, capability, system, "capability"
    )
    assert first["changed"] is True
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert rollout._feature(workspace, "capability") is True
    assert projection_enabled(
        workspace.settings,
        "capability",
        runtime_revision="a" * 40,
    ) is True
    assert rollout._feature(workspace, "run") is False
    assert len(system.settings[rollout.ROLLOUT_STATE_KEY]["activations"]) == 1
    persisted_pilot = system.settings[rollout.ROLLOUT_STATE_KEY]["activations"][0][
        "pilot_observation"
    ]
    assert persisted_pilot["observation_ref"].startswith("sha256:")
    assert persisted_pilot["participant_ref"].startswith("sha256:")
    assert persisted_pilot["audit_id"]
    assert persisted_pilot["profile"] == "operator"
    assert persisted_pilot["question_count"] == 4
    assert "questions" not in persisted_pilot

    repeated = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        evidence=None,
        apply=True,
        actor="retry",
    )
    assert repeated["changed"] is False
    assert repeated["already_active"] is True

    with pytest.raises(rollout.ProjectionRolloutError, match="next projection must be run"):
        rollout.stage(
            db_session,
            workspace_id=workspace.id,
            projection="skill_invocation",
            apply=True,
            actor="operator",
        )

    for projection in ("run", "skill_invocation"):
        _stage_and_activate(
            db_session, workspace, capability, system, projection
        )

    final = rollout.status(db_session, workspace_id=workspace.id)
    assert final["active_complete"] is True
    assert final["complete"] is True
    assert final["behavior_verified"] is True
    assert final["active_prefix"] == list(rollout.PROJECTION_ORDER)
    assert all(item["enabled"] and item["attested"] for item in final["projections"])
    assert all(item["pilot_observed"] for item in final["projections"])
    assert all(
        item["pilot_observation"]["observation_ref"].startswith("sha256:")
        for item in final["projections"]
    )
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.projection.probation_finalized",
        )
        .count()
        == 3
    )
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type=rollout.PILOT_OBSERVATION_AUDIT_EVENT,
        )
        .count()
        == 3
    )
    assert "opaque-participant-lot7" not in str(system.settings)

    settings = dict(system.settings)
    rollout_state = dict(settings[rollout.ROLLOUT_STATE_KEY])
    activations = [dict(item) for item in rollout_state["activations"]]
    activations[0]["pilot_observation"] = dict(
        activations[0]["pilot_observation"]
    )
    activations[0]["pilot_observation"]["subject"] = {
        **activations[0]["pilot_observation"]["subject"],
        "lease_id": str(uuid4()),
    }
    rollout_state["activations"] = activations
    settings[rollout.ROLLOUT_STATE_KEY] = rollout_state
    system.settings = settings
    db_session.commit()
    drifted = rollout.status(db_session, workspace_id=workspace.id)
    assert drifted["projections"][0]["pilot_observed"] is False
    assert drifted["complete"] is False


def test_final_activation_requires_trusted_runner_and_persisted_pilot_audit(
    db_session,
):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    pilot = _pilot_observation(system, capability, "capability")
    untrusted_evidence = _evidence(
        db_session,
        workspace,
        capability,
        system,
        "capability",
    )

    preview = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        evidence=untrusted_evidence,
        pilot_observation=pilot,
        apply=False,
        actor="operator",
    )
    assert preview["changed"] is True
    assert preview["pilot_observation"]["participant_ref"].startswith("sha256:")
    assert "audit_id" not in preview["pilot_observation"]
    with pytest.raises(
        rollout.ProjectionRolloutError,
        match="protected GitLab OIDC runner",
    ):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=untrusted_evidence,
            pilot_observation=pilot,
            apply=True,
            actor="operator",
        )

    db_session.refresh(workspace)
    db_session.refresh(system)
    probation = rollout.status(db_session, workspace_id=workspace.id)
    assert probation["active_prefix"] == []
    assert probation["projections"][0]["phase"] == "probation"
    assert probation["projections"][0]["enabled"] is True
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type=rollout.PILOT_OBSERVATION_AUDIT_EVENT,
        )
        .count()
        == 0
    )

    trusted_evidence = _evidence(
        db_session,
        workspace,
        capability,
        system,
        "capability",
        trusted_runner=TRUSTED_RUNNER,
    )
    applied = rollout.activate(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        evidence=trusted_evidence,
        pilot_observation=pilot,
        apply=True,
        actor="operator",
        trusted_runner=TRUSTED_RUNNER,
    )
    persisted = applied["validation"]["pilot_observation"]
    assert persisted["audit_id"]
    assert persisted["participant_ref"].startswith("sha256:")
    audit = db_session.query(AuditLog).filter_by(id=persisted["audit_id"]).one()
    assert audit.event_type == rollout.PILOT_OBSERVATION_AUDIT_EVENT
    assert audit.details["trusted_runner"]["job_id"] == TRUSTED_RUNNER["job_id"]
    assert audit.details["participant_ref"] == persisted["participant_ref"]
    assert "opaque-participant-lot7" not in str(audit.details)

    audit.details = {
        **dict(audit.details),
        "trusted_runner": {
            **dict(audit.details["trusted_runner"]),
            "job_id": "tampered-job",
        },
    }
    db_session.commit()
    drifted = rollout.status(db_session, workspace_id=workspace.id)
    assert drifted["projections"][0]["pilot_observed"] is False
    assert drifted["projections"][0]["behavior_verified"] is False


def test_runtime_gate_revalidates_exact_finalization_audit_and_current_runner_anchors(
    db_session,
    monkeypatch,
):
    workspace, capability, system = _seed_target(db_session)
    applied = _stage_and_activate(
        db_session,
        workspace,
        capability,
        system,
        "capability",
    )
    activation = applied["validation"]
    assert activation["audit_id"]
    assert activation["activation_sha256"] == projection_activation_sha256(activation)
    finalization_audit = (
        db_session.query(AuditLog)
        .filter_by(id=activation["audit_id"])
        .one()
    )
    assert finalization_audit.event_type == PROJECTION_FINALIZATION_AUDIT_EVENT

    def enabled() -> bool:
        db_session.refresh(workspace)
        db_session.refresh(system)
        return authoritative_projection_enabled(
            db_session,
            workspace,
            "capability",
            runtime_revision=TRUSTED_RUNNER["commit_sha"],
        )

    assert enabled() is True
    original_settings = copy.deepcopy(system.settings)
    original_audit_details = copy.deepcopy(finalization_audit.details)

    # A settings writer cannot forge a different CI job even if it recomputes
    # the content digest: the immutable server receipt still differs.
    tampered_settings = copy.deepcopy(original_settings)
    tampered_activation = tampered_settings[rollout.ROLLOUT_STATE_KEY]["activations"][0]
    tampered_activation["trusted_runner"]["job_id"] = "forged-job"
    tampered_activation["activation_sha256"] = projection_activation_sha256(
        tampered_activation
    )
    system.settings = tampered_settings
    db_session.commit()
    assert enabled() is False

    system.settings = original_settings
    db_session.commit()
    assert enabled() is True

    # Persisted identity is re-evaluated against today's anchors, not merely
    # trusted because it was accepted by an older rollout invocation.
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_project_id",
        "different-project",
    )
    assert enabled() is False
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_project_id",
        TRUSTED_RUNNER["project_id"],
    )
    assert enabled() is True

    # The exact AuditLog content is authoritative; matching only its id and
    # event type is insufficient.
    finalization_audit.details = {
        **original_audit_details,
        "evidence_sha256": "f" * 64,
    }
    db_session.commit()
    assert enabled() is False

    finalization_audit.details = original_audit_details
    db_session.commit()
    assert enabled() is True

    missing_audit_settings = copy.deepcopy(original_settings)
    missing_audit_settings[rollout.ROLLOUT_STATE_KEY]["activations"][0][
        "audit_id"
    ] = str(uuid4())
    system.settings = missing_audit_settings
    db_session.commit()
    assert enabled() is False


def test_finalization_audit_failure_rolls_back_pilot_and_activation_state(
    db_session,
    monkeypatch,
):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(workspace)
    db_session.refresh(system)
    original_emit = rollout.emit_audit_event

    def fail_finalization_audit(**kwargs):
        if kwargs.get("event_type") == PROJECTION_FINALIZATION_AUDIT_EVENT:
            return None
        return original_emit(**kwargs)

    monkeypatch.setattr(rollout, "emit_audit_event", fail_finalization_audit)
    with pytest.raises(
        rollout.ProjectionRolloutError,
        match="activation audit event could not be persisted",
    ):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=_evidence(
                db_session,
                workspace,
                capability,
                system,
                "capability",
                trusted_runner=TRUSTED_RUNNER,
            ),
            pilot_observation=_pilot_observation(
                system,
                capability,
                "capability",
            ),
            apply=True,
            actor="operator",
            trusted_runner=TRUSTED_RUNNER,
        )

    db_session.refresh(workspace)
    db_session.refresh(system)
    state = rollout._state(system)
    assert state["activations"] == []
    assert [row["projection"] for row in state["probations"]] == ["capability"]
    assert (
        db_session.query(AuditLog)
        .filter_by(event_type=rollout.PILOT_OBSERVATION_AUDIT_EVENT)
        .count()
        == 0
    )


def test_formal_completion_requires_trusted_runner_and_deployed_revision(
    db_session,
    monkeypatch,
):
    workspace, capability, system = _seed_target(db_session)
    revision = "a" * 40
    monkeypatch.setattr(rollout.settings, "agentium_image_revision", revision)
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_oidc_issuer",
        "https://gitlab.example.test",
    )
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_project_id",
        "42",
    )
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_ref",
        "demo/agentic",
    )
    runner = {
        "issuer": "https://gitlab.example.test",
        "project_id": "42",
        "pipeline_id": "314",
        "job_id": "159",
        "commit_sha": revision,
        "ref": "demo/agentic",
        "ref_protected": True,
    }
    for projection in rollout.PROJECTION_ORDER:
        _stage_and_activate(
            db_session,
            workspace,
            capability,
            system,
            projection,
            trusted_runner=runner,
        )

    verified = rollout.status(db_session, workspace_id=workspace.id)
    assert verified["active_complete"] is True
    assert verified["complete"] is True
    assert verified["behavior_verified"] is True

    monkeypatch.setattr(rollout.settings, "agentium_image_revision", "b" * 40)
    stale = rollout.status(db_session, workspace_id=workspace.id)
    assert stale["active_complete"] is True
    assert stale["complete"] is False
    assert all(not row["revision_matches_runtime"] for row in stale["projections"])


def test_discovery_is_marker_based_and_explicitly_workspace_scoped(db_session):
    workspace, capability, system = _seed_target(db_session)
    discovered = rollout.discover_target(db_session, workspace_id=workspace.id)
    assert discovered == (workspace, capability, system)

    other_workspace = Workspace(
        id=str(uuid4()),
        name="Not named Showcase",
        slug=f"random-{uuid4()}",
        settings={"family": "sentinel_ci"},
    )
    other_capability = Capability(
        id=str(uuid4()),
        workspace_id=other_workspace.id,
        slug=f"random-{uuid4()}",
        name="Other capability",
    )
    duplicate = System(
        id=str(uuid4()),
        workspace_id=other_workspace.id,
        capability_id=other_capability.id,
        name="Other system",
        objective="Duplicate marker",
        status="active",
        settings={"experience": {"system_360_canary": "v1"}},
    )
    db_session.add_all([other_workspace, other_capability, duplicate])
    db_session.commit()

    assert rollout.discover_target(
        db_session,
        workspace_id=other_workspace.id,
    ) == (other_workspace, other_capability, duplicate)
    assert rollout.discover_target(
        db_session,
        workspace_id=workspace.id,
    ) == (workspace, capability, system)

    same_workspace_duplicate = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        capability_id=capability.id,
        name="Second system in target Workspace",
        objective="Ambiguous scoped marker",
        status="active",
        settings={"experience": {"system_360_canary": "v1"}},
    )
    db_session.add(same_workspace_duplicate)
    db_session.commit()
    with pytest.raises(rollout.ProjectionRolloutError, match="exactly one active"):
        rollout.discover_target(db_session, workspace_id=workspace.id)
    assert rollout.discover_target(
        db_session,
        workspace_id=other_workspace.id,
    ) == (other_workspace, other_capability, duplicate)


def test_discovery_requires_an_active_explicit_workspace(db_session):
    workspace, _, _ = _seed_target(db_session)
    with pytest.raises(rollout.ProjectionRolloutError, match="workspace_id is required"):
        rollout.discover_target(db_session, workspace_id="")
    with pytest.raises(rollout.ProjectionRolloutError, match="missing or inactive"):
        rollout.discover_target(db_session, workspace_id=str(uuid4()))

    workspace.is_active = False
    db_session.commit()
    with pytest.raises(rollout.ProjectionRolloutError, match="missing or inactive"):
        rollout.discover_target(db_session, workspace_id=workspace.id)


def test_cli_requires_the_immutable_workspace_id():
    with pytest.raises(SystemExit):
        rollout._parser().parse_args(["status"])
    args = rollout._parser().parse_args(
        ["stage", "capability", "--workspace-id", "workspace-123"]
    )
    assert args.workspace_id == "workspace-123"
    finalize = rollout._parser().parse_args(
        [
            "finalize",
            "capability",
            "--workspace-id",
            "workspace-123",
            "--pilot-observation",
            "pilot.json",
        ]
    )
    assert finalize.pilot_observation == "pilot.json"


def test_manual_flag_drift_without_attestation_fails_closed(db_session):
    workspace, _, _ = _seed_target(db_session)
    settings = dict(workspace.settings)
    settings["features"] = dict(settings["features"])
    settings["features"][rollout.FEATURE_BY_PROJECTION["capability"]] = True
    workspace.settings = settings
    db_session.commit()

    assert projection_enabled(workspace.settings, "capability") is False
    with pytest.raises(
        rollout.ProjectionRolloutError,
        match="feature/evidence/Workspace-gate state diverged",
    ):
        rollout.status(db_session, workspace_id=workspace.id)


def test_content_drifted_workspace_gate_is_detected_by_authoritative_status(db_session):
    workspace, capability, system = _seed_target(db_session)
    _stage_and_activate(
        db_session, workspace, capability, system, "capability"
    )
    db_session.refresh(workspace)
    settings = dict(workspace.settings)
    gate = dict(settings["_lot7_projection_gate_v1"])
    activations = [dict(item) for item in gate["activations"]]
    activations[0]["evidence_sha256"] = "f" * 64
    gate["activations"] = activations
    settings["_lot7_projection_gate_v1"] = gate
    workspace.settings = settings
    db_session.commit()

    assert projection_enabled(
        workspace.settings,
        "capability",
        runtime_revision="a" * 40,
    ) is True
    # Runtime can validate the server-owned gate structurally without querying
    # the canary System on every request. The authoritative status additionally
    # binds it to persisted evidence; generic API writes are blocked separately.
    with pytest.raises(rollout.ProjectionRolloutError, match="differs from persisted"):
        rollout.status(db_session, workspace_id=workspace.id)


def test_activation_requires_lot6_prerequisites_and_fresh_evidence(db_session):
    workspace, capability, system = _seed_target(db_session)
    settings = dict(workspace.settings)
    settings["features"] = dict(settings["features"])
    settings["features"]["system_360_projection_v1"] = False
    workspace.settings = settings
    db_session.commit()

    with pytest.raises(rollout.ProjectionRolloutError, match="Lot 6 prerequisites"):
        rollout.stage(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            apply=False,
            actor="operator",
        )

    settings["features"]["system_360_projection_v1"] = True
    workspace.settings = settings
    db_session.commit()
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(workspace)
    db_session.refresh(system)
    stale = _evidence(db_session, workspace, capability, system, "capability")
    stale["validated_at"] = "2020-01-01T00:00:00+00:00"
    with pytest.raises(rollout.ProjectionRolloutError, match="older than 24 hours"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=stale,
            apply=False,
            actor="operator",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("failed_run", "Run must be successful"),
        ("stale_execution", "predates the probation"),
        ("wrong_runtime_sha", "runtime SHA"),
        ("wrong_flow_version", "flow_version_id differs"),
        ("mutated_flow", "flow_snapshot digest differs"),
        ("unresolved_invocation", "no resolved execution_snapshot"),
        ("tampered_source", "source_ref does not match"),
        ("tampered_artifact", "artifact_ref differs"),
    ],
)
def test_evidence_revalidates_runtime_and_content_addresses(
    db_session,
    mutation,
    message,
):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    evidence = _evidence(db_session, workspace, capability, system, "capability")
    runtime = evidence["source_manifest"]["runtime"]
    run = db_session.query(Run).filter_by(id=runtime["run_id"]).one()
    invocation = db_session.query(SkillInvocation).filter_by(
        id=runtime["primary_invocation_id"]
    ).one()

    if mutation == "failed_run":
        run.status = "failed"
    elif mutation == "stale_execution":
        probation = rollout._persisted_probation(
            rollout._state(system),
            "capability",
        )
        assert probation is not None
        before = rollout._parse_utc(
            probation["staged_at"],
            field="probation.staged_at",
        ) - timedelta(seconds=1)
        run.input_ref = {
            "execution": {
                "snapshot_at": before.isoformat(),
                "runtime_revision": "a" * 40,
            }
        }
        runtime["execution_snapshot_at"] = before.isoformat()
        evidence["source_ref"] = (
            f"sha256:{rollout._canonical_sha256(evidence['source_manifest'])}"
        )
    elif mutation == "wrong_runtime_sha":
        run.input_ref = {
            "execution": {
                **run.input_ref["execution"],
                "runtime_revision": "b" * 40,
            }
        }
    elif mutation == "wrong_flow_version":
        run.flow_version_id = str(uuid4())
    elif mutation == "mutated_flow":
        run.flow_snapshot = {**run.flow_snapshot, "edges": [{"source": "x"}]}
    elif mutation == "unresolved_invocation":
        invocation.execution_snapshot = {
            **invocation.execution_snapshot,
            "resolution": "unresolved",
        }
    elif mutation == "tampered_source":
        evidence["source_manifest"]["projection_sha256"]["build"] = "f" * 64
    elif mutation == "tampered_artifact":
        evidence["runner_artifact"]["content_base64"] = base64.b64encode(
            b"<testsuite />"
        ).decode("ascii")
    db_session.commit()

    with pytest.raises(rollout.ProjectionRolloutError, match=message):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=evidence,
            apply=False,
            actor="operator",
        )


def test_evidence_rejects_declarative_boolean_contract_and_non_passing_junit(
    db_session,
):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    evidence = _evidence(db_session, workspace, capability, system, "capability")
    legacy = {
        **evidence,
        "schema_version": 1,
        "checks": {"four_lenses_distinct": True},
    }
    with pytest.raises(rollout.ProjectionRolloutError, match="schema_version must be 2"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=legacy,
            apply=False,
            actor="operator",
        )

    failing_xml = base64.b64decode(evidence["runner_artifact"]["content_base64"])
    failing_xml = failing_xml.replace(
        b'tests="1" failures="0"',
        b'tests="1" failures="1"',
    ).replace(
        b'<testcase classname="lot7.object_graph" name="authenticated canary" />',
        b'<testcase classname="lot7.object_graph" name="authenticated canary">'
        b'<failure /></testcase>',
    )
    artifact_ref = f"sha256:{hashlib.sha256(failing_xml).hexdigest()}"
    evidence["runner_artifact"] = {
        "format": "junit_xml",
        "artifact_ref": artifact_ref,
        "content_base64": base64.b64encode(failing_xml).decode("ascii"),
    }
    evidence["source_manifest"]["runner_artifact_ref"] = artifact_ref
    evidence["source_ref"] = (
        f"sha256:{rollout._canonical_sha256(evidence['source_manifest'])}"
    )
    with pytest.raises(rollout.ProjectionRolloutError, match="zero failures"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=evidence,
            apply=False,
            actor="operator",
        )


def test_run_detail_exposes_only_content_addressed_projection_evidence(db_session):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    evidence = _evidence(db_session, workspace, capability, system, "capability")
    runtime = evidence["source_manifest"]["runtime"]
    run = db_session.query(Run).filter_by(id=runtime["run_id"]).one()
    invocation = db_session.query(SkillInvocation).filter_by(
        id=runtime["primary_invocation_id"]
    ).one()

    run_payload = _row(run, db=db_session)
    invocation_payload = _invocation(invocation)
    assert run_payload["flow_evidence"] == {
        "flow_version_id": runtime["flow_version_id"],
        "flow_snapshot_sha256": runtime["flow_snapshot_sha256"],
        "execution_snapshot_at": runtime["execution_snapshot_at"].replace(
            "+00:00",
            "Z",
        ),
        "runtime_revision": "a" * 40,
    }
    assert "flow_snapshot" not in run_payload
    assert invocation_payload["execution_evidence"] == {
        "resolution": "resolved",
        "execution_snapshot_sha256": runtime["invocations"][0][
            "execution_snapshot_sha256"
        ],
    }
    assert "execution_snapshot" not in invocation_payload


def test_runner_artifact_is_bound_to_the_authenticated_job(db_session):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    runner = {
        "issuer": "https://gitlab.example.test",
        "project_id": "42",
        "pipeline_id": "314",
        "job_id": "159",
        "commit_sha": "a" * 40,
        "ref": "demo/agentic",
        "ref_protected": True,
    }
    evidence = _evidence(
        db_session,
        workspace,
        capability,
        system,
        "capability",
        trusted_runner=runner,
    )
    xml = base64.b64decode(evidence["runner_artifact"]["content_base64"])
    xml = xml.replace(b'runner_job_id" value="159', b'runner_job_id" value="160')
    artifact_ref = f"sha256:{hashlib.sha256(xml).hexdigest()}"
    evidence["runner_artifact"].update(
        {
            "artifact_ref": artifact_ref,
            "content_base64": base64.b64encode(xml).decode("ascii"),
        }
    )
    evidence["source_manifest"]["runner_artifact_ref"] = artifact_ref
    evidence["source_ref"] = (
        f"sha256:{rollout._canonical_sha256(evidence['source_manifest'])}"
    )

    with pytest.raises(rollout.ProjectionRolloutError, match="runner_job_id"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=evidence,
            apply=False,
            actor="operator",
            trusted_runner=runner,
        )


def test_probation_is_sha_bound_expires_and_can_be_aborted(db_session):
    workspace, capability, system = _seed_target(db_session)
    staged_at = datetime(2020, 1, 1, tzinfo=UTC)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
        now=staged_at,
    )
    db_session.refresh(workspace)
    db_session.refresh(system)

    assert projection_enabled(
        workspace.settings,
        "capability",
        runtime_revision="a" * 40,
        at=staged_at,
    ) is True
    assert projection_enabled(
        workspace.settings,
        "capability",
        runtime_revision="b" * 40,
        at=staged_at,
    ) is False
    assert projection_enabled(
        workspace.settings,
        "capability",
        runtime_revision="a" * 40,
        at=staged_at + rollout.PROBATION_MAX_LEASE,
    ) is False
    with pytest.raises(rollout.ProjectionRolloutError, match="expired"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=_evidence(db_session, workspace, capability, system, "capability"),
            apply=True,
            actor="operator",
        )

    aborted = rollout.deactivate(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    assert aborted["deactivation"]["phase"] == "probation"
    db_session.refresh(workspace)
    assert rollout._feature(workspace, "capability") is False


def test_finalization_rejects_a_different_probation_lease(db_session):
    workspace, capability, system = _seed_target(db_session)
    rollout.stage(
        db_session,
        workspace_id=workspace.id,
        projection="capability",
        apply=True,
        actor="operator",
    )
    db_session.refresh(system)
    evidence = _evidence(db_session, workspace, capability, system, "capability")
    evidence["source_manifest"]["gate"]["lease_id"] = str(uuid4())
    evidence["source_ref"] = (
        f"sha256:{rollout._canonical_sha256(evidence['source_manifest'])}"
    )
    with pytest.raises(rollout.ProjectionRolloutError, match="lease_id differs"):
        rollout.activate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            evidence=evidence,
            apply=True,
            actor="operator",
        )


def test_deactivation_is_reverse_order_audited_and_reactivatable(db_session):
    workspace, capability, system = _seed_target(db_session)
    for projection in rollout.PROJECTION_ORDER:
        _stage_and_activate(
            db_session, workspace, capability, system, projection
        )

    with pytest.raises(rollout.ProjectionRolloutError, match="next projection must be skill_invocation"):
        rollout.deactivate(
            db_session,
            workspace_id=workspace.id,
            projection="capability",
            apply=True,
            actor="operator",
        )

    for projection in reversed(rollout.PROJECTION_ORDER):
        preview = rollout.deactivate(
            db_session,
            workspace_id=workspace.id,
            projection=projection,
            apply=False,
            actor="operator",
        )
        assert preview["changed"] is True
        applied = rollout.deactivate(
            db_session,
            workspace_id=workspace.id,
            projection=projection,
            apply=True,
            actor="operator",
        )
        assert applied["changed"] is True
        db_session.refresh(workspace)
        db_session.refresh(system)

    rolled_back = rollout.status(db_session, workspace_id=workspace.id)
    assert rolled_back["active_prefix"] == []
    assert rolled_back["deactivation_count"] == 3
    assert (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.projection.deactivated",
        )
        .count()
        == 3
    )

    _stage_and_activate(
        db_session, workspace, capability, system, "capability"
    )
    db_session.refresh(workspace)
    assert rollout._feature(workspace, "capability") is True
