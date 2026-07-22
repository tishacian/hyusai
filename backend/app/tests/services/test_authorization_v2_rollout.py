"""Safety contract for the attested authorization-v2 promotion gate."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.audit import AuditLog
from app.models.workspace import Workspace, WorkspaceIAMConfig
from app.services.iam.decision_plane import candidate_config_sha256
from app.services.iam.shadow_review import (
    apply_review_to_summaries,
    build_review_document,
    build_source_manifest_row,
    sha256_ref,
    validate_review_envelope,
    validate_source_manifest,
)
from scripts import rollout_authorization_v2 as rollout

REVISION = "a" * 40
ACTIONS = ("run.read", "system.read")


@pytest.fixture(autouse=True)
def _trusted_promotion_anchor(monkeypatch):
    monkeypatch.setattr(rollout.settings, "agentium_image_revision", REVISION)
    monkeypatch.setattr(
        rollout.settings,
        "authorization_v2_trusted_oidc_issuer",
        "https://gitlab.com",
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


def _seed(db, *, modes: dict[str, str] | None = None):
    workspace = Workspace(
        id=str(uuid4()),
        name="Opaque workspace",
        slug=f"opaque-{uuid4()}",
        settings={"family": "generic"},
    )
    config = WorkspaceIAMConfig(
        workspace_id=workspace.id,
        version=7,
        role_flags={"custom_role_flag": True},
        capability_overrides={
            "custom_top_level": {"preserve": True},
            "authorization_v2": {
                "policy_version": 2,
                "default_mode": "compat",
                "owner_note": "preserve this workspace policy",
                "modes": {
                    "custom_resource.publish": "shadow",
                    **(modes or {action: "shadow" for action in ACTIONS}),
                },
                "custom_metadata": {"ticket": "SEC-42"},
            },
        },
    )
    db.add_all([workspace, config])
    db.commit()
    return workspace, config


def _persist_evidence_source(db, evidence: dict) -> dict:
    manifest = evidence["shadow_observation"]["source_manifest"]
    for row in manifest["rows"]:
        timestamp = datetime.fromisoformat(row["timestamp"])
        db.add(
            AuditLog(
                id=row["id"],
                workspace_id=manifest["workspace_id"],
                timestamp=timestamp.astimezone(UTC).replace(tzinfo=None),
                event_type=manifest["event_type"],
                actor="trusted-shadow-runner",
                details={
                    "origin": "server",
                    "resource": {"kind": row["action"].split(".", maxsplit=1)[0]},
                    "action": row["action"],
                    "evaluation_count": row["evaluation_count"],
                    "legacy_allowed": row["legacy_allowed"],
                    "legacy_denied": row["legacy_denied"],
                    "candidate_allowed": row["candidate_allowed"],
                    "candidate_denied": row["candidate_denied"],
                    "matches": row["matches"],
                    "mismatches": row["mismatches"],
                    "policy_id": "policy-v2",
                    "policy_version": 2,
                    "configured_mode": "shadow",
                    "runtime_revision": row["runtime_revision"],
                    "candidate_config_sha256": row["candidate_config_sha256"],
                    "candidate_config_version": row["candidate_config_version"],
                },
            )
        )
    db.flush()
    return evidence


def _evidence(config: WorkspaceIAMConfig, actions=ACTIONS, *, db=None):
    workspace_id = config.workspace_id
    action_list = sorted(actions)
    validated_at = datetime.now(UTC)
    window_ended_at = validated_at - timedelta(minutes=5)
    window_started_at = window_ended_at - timedelta(hours=1)
    source_manifest = {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "actions": action_list,
        "window_started_at": window_started_at.isoformat(),
        "window_ended_at": window_ended_at.isoformat(),
        "event_type": "iam.shadow.evaluation",
        "runtime_revision": REVISION,
        "candidate_config_sha256": candidate_config_sha256(config),
        "candidate_config_version": config.version,
        "rows": [
            build_source_manifest_row(
                row_id=f"audit-{index}",
                timestamp=window_started_at + timedelta(minutes=index + 1),
                action=action,
                evaluation_count=5,
                runtime_revision=REVISION,
                candidate_config_sha256=candidate_config_sha256(config),
                candidate_config_version=config.version,
                counters={
                    "legacy_allowed": 4,
                    "legacy_denied": 1,
                    "candidate_allowed": 4,
                    "candidate_denied": 1,
                    "matches": 5,
                    "mismatches": 0,
                },
            )
            for index, action in enumerate(action_list)
        ],
    }
    source_ref = sha256_ref(source_manifest)
    evidence = {
        "schema_version": 1,
        "result": "passed",
        "subject": {
            "workspace_id": workspace_id,
            "actions": action_list,
            "revision": REVISION,
        },
        "validated_by": "security-gate",
        "validated_at": validated_at.isoformat(),
        "environment": "isolated-test",
        "contracts": {
            "legacy": {
                "result": "passed",
                "format": "junit",
                "artifact_ref": "sha256:" + "d" * 64,
                "test_count": 11,
                "failure_count": 0,
                "error_count": 0,
                "skipped_count": 0,
                "producer": _trusted_runner(),
            },
            "candidate": {
                "result": "passed",
                "format": "junit",
                "artifact_ref": "sha256:" + "e" * 64,
                "test_count": 13,
                "failure_count": 0,
                "error_count": 0,
                "skipped_count": 0,
                "producer": _trusted_runner(),
            },
        },
        "shadow_observation": {
            "source": "runtime_metrics",
            "source_ref": source_ref,
            "window_started_at": window_started_at.isoformat(),
            "window_ended_at": window_ended_at.isoformat(),
            "runtime_revision": REVISION,
            "candidate_config_sha256": candidate_config_sha256(config),
            "candidate_config_version": config.version,
            "actions": {
                action: {
                    "evaluations": 5,
                    "legacy_allowed": 4,
                    "legacy_denied": 1,
                    "candidate_allowed": 4,
                    "candidate_denied": 1,
                    "matches": 5,
                    "mismatches": 0,
                    "explained_mismatches": 0,
                    "unexplained_mismatches": 0,
                }
                for action in action_list
            },
            "source_manifest": source_manifest,
        },
        "blockers": [],
    }
    return _persist_evidence_source(db, evidence) if db is not None else evidence


def _trusted_runner(revision: str = REVISION):
    return {
        "issuer": "https://gitlab.com",
        "project_id": "42",
        "pipeline_id": "84",
        "job_id": "126",
        "commit_sha": revision,
        "ref": "demo/agentic",
        "ref_protected": True,
    }


def _forged_review_evidence(config: WorkspaceIAMConfig, db) -> dict:
    evidence = _evidence(config, actions=["run.read"])
    observation = evidence["shadow_observation"]
    manifest = observation["source_manifest"]
    observed_at = datetime.fromisoformat(manifest["window_started_at"]) + timedelta(minutes=1)
    manifest["rows"] = [
        build_source_manifest_row(
            row_id="audit-forged-review",
            timestamp=observed_at,
            action="run.read",
            evaluation_count=1,
            runtime_revision=REVISION,
            candidate_config_sha256=candidate_config_sha256(config),
            candidate_config_version=config.version,
            counters={
                "legacy_allowed": 1,
                "legacy_denied": 0,
                "candidate_allowed": 0,
                "candidate_denied": 1,
                "matches": 0,
                "mismatches": 1,
            },
        )
    ]
    observation["source_ref"] = sha256_ref(manifest)
    source = validate_source_manifest(
        manifest,
        source_ref=observation["source_ref"],
        workspace_id=config.workspace_id,
        actions=["run.read"],
        revision=REVISION,
        candidate_config_sha256=candidate_config_sha256(config),
        candidate_config_version=config.version,
        window_started_at=datetime.fromisoformat(manifest["window_started_at"]),
        window_ended_at=datetime.fromisoformat(manifest["window_ended_at"]),
    )
    document = build_review_document(
        source=source,
        reviewer_user_id="forged-reviewer",
        reviewer_identity="forged-reviewer@example.net",
        reviewed_at=datetime.fromisoformat(manifest["window_ended_at"]) + timedelta(seconds=1),
        entries=[
            {
                "action": "run.read",
                "observation_ids": ["audit-forged-review"],
                "reason_code": "reviewer_role_separation",
                "reason": "Reviewer execution rights are intentionally removed in policy v2.",
            }
        ],
    )
    envelope = {
        "audit_id": "review-not-in-ledger",
        "artifact_ref": sha256_ref(document),
        "document": document,
    }
    review = validate_review_envelope(
        envelope,
        source=source,
        validated_at=datetime.fromisoformat(evidence["validated_at"]),
    )
    observation["mismatch_review"] = envelope
    observation["actions"] = apply_review_to_summaries(source, review)
    evidence["result"] = "passed"
    evidence["blockers"] = []
    return _persist_evidence_source(db, evidence)


def test_dry_run_is_inert_and_refuses_compat_jump_or_missing_actor(db_session):
    workspace, config = _seed(
        db_session,
        modes={"system.read": "compat", "run.read": "shadow"},
    )

    with pytest.raises(rollout.AuthorizationPromotionError, match="directly from compat"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=_evidence(config),
            apply=False,
            actor="",
        )

    payload = copy.deepcopy(config.capability_overrides)
    payload["authorization_v2"]["modes"]["system.read"] = "shadow"
    config.capability_overrides = payload
    db_session.commit()
    before_version = config.version

    preview = rollout.promote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision=REVISION,
        evidence=_evidence(config, db=db_session),
        apply=False,
        actor="",
    )
    assert preview["operation"] == "dry_run"
    assert preview["changed"] is True
    assert preview["validation_required"] is False
    db_session.refresh(config)
    assert config.version == before_version
    assert all(
        config.capability_overrides["authorization_v2"]["modes"][action] == "shadow"
        for action in ACTIONS
    )
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "lot7.authorization.enforce_promoted")
        .count()
        == 0
    )

    with pytest.raises(rollout.AuthorizationPromotionError, match="non-empty actor"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=_evidence(config),
            apply=True,
            actor="",
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda evidence: evidence["subject"].update({"workspace_id": str(uuid4())}),
            "subject must exactly match",
        ),
        (
            lambda evidence: evidence["subject"].update({"actions": ["system.read"]}),
            "subject must exactly match",
        ),
        (
            lambda evidence: evidence["contracts"]["candidate"].update({"result": "failed"}),
            "candidate contract",
        ),
        (
            lambda evidence: evidence["shadow_observation"]["actions"]["run.read"].update(
                {"evaluations": 0}
            ),
            "summaries differ",
        ),
        (
            lambda evidence: evidence["shadow_observation"]["actions"]["run.read"].update(
                {
                    "matches": 3,
                    "mismatches": 2,
                    "explained_mismatches": 1,
                    "unexplained_mismatches": 1,
                }
            ),
            "summaries differ",
        ),
    ],
)
def test_proof_must_bind_exact_subject_contracts_and_real_shadow_counts(
    db_session, mutate, message
):
    workspace, config = _seed(db_session)
    evidence = _evidence(config)
    mutate(evidence)

    with pytest.raises(rollout.AuthorizationPromotionError, match=message):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=evidence,
            apply=False,
            actor="operator",
        )


def test_promotion_rejects_structurally_valid_review_missing_from_audit_ledger(
    db_session,
):
    workspace, config = _seed(db_session, modes={"run.read": "shadow"})

    with pytest.raises(
        rollout.AuthorizationPromotionError,
        match="not present in the authoritative audit ledger",
    ):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=["run.read"],
            revision=REVISION,
            evidence=_forged_review_evidence(config, db_session),
            apply=False,
            actor="operator",
        )


def test_promotion_rejects_a_self_consistent_source_not_present_in_audit_ledger(
    db_session,
):
    workspace, config = _seed(db_session)

    with pytest.raises(rollout.AuthorizationPromotionError, match="not exhaustive"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=_evidence(config),
            apply=False,
            actor="operator",
        )


def test_proof_must_be_fresh_immutable_and_cover_only_governed_actions(db_session):
    workspace, config = _seed(db_session)
    stale = _evidence(config)
    stale_at = datetime.now(UTC) - timedelta(hours=25)
    stale["validated_at"] = stale_at.isoformat()
    stale["shadow_observation"]["window_started_at"] = (stale_at - timedelta(hours=1)).isoformat()
    stale["shadow_observation"]["window_ended_at"] = (stale_at - timedelta(minutes=5)).isoformat()
    with pytest.raises(rollout.AuthorizationPromotionError, match="older than 24 hours"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=stale,
            apply=False,
            actor="operator",
        )

    stale_window = _evidence(config)
    stale_window["shadow_observation"]["window_started_at"] = (
        datetime.now(UTC) - timedelta(hours=49)
    ).isoformat()
    stale_window["shadow_observation"]["window_ended_at"] = (
        datetime.now(UTC) - timedelta(hours=25)
    ).isoformat()
    with pytest.raises(
        rollout.AuthorizationPromotionError,
        match="window ended more than 24 hours ago",
    ):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=stale_window,
            apply=False,
            actor="operator",
        )

    mutable_ref = _evidence(config)
    mutable_ref["shadow_observation"]["source_ref"] = "metrics-job-42"
    with pytest.raises(rollout.AuthorizationPromotionError, match="sha256"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=mutable_ref,
            apply=False,
            actor="operator",
        )

    tampered_manifest = _evidence(config)
    tampered_manifest["shadow_observation"]["source_manifest"]["rows"][0]["evaluation_count"] = 4
    with pytest.raises(rollout.AuthorizationPromotionError, match="does not match"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=tampered_manifest,
            apply=False,
            actor="operator",
        )

    with pytest.raises(rollout.AuthorizationPromotionError, match="not governed"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=["custom_resource.publish"],
            revision=REVISION,
            evidence=None,
            apply=False,
            actor="operator",
        )

    with pytest.raises(rollout.AuthorizationPromotionError, match="exact 40-character"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision="a" * 12,
            evidence=_evidence(config),
            apply=False,
            actor="operator",
        )


def test_apply_is_atomic_audited_idempotent_and_preserves_custom_configuration(db_session):
    workspace, config = _seed(db_session)
    original_version = config.version
    evidence = _evidence(config, db=db_session)

    applied = rollout.promote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision=REVISION,
        evidence=evidence,
        apply=True,
        actor="operator@example.net",
        trusted_runner=_trusted_runner(),
    )
    assert applied["changed"] is True
    db_session.refresh(config)
    assert config.version == original_version + 1
    overrides = config.capability_overrides
    policy = overrides["authorization_v2"]
    assert overrides["custom_top_level"] == {"preserve": True}
    assert policy["owner_note"] == "preserve this workspace policy"
    assert policy["custom_metadata"] == {"ticket": "SEC-42"}
    assert policy["modes"]["custom_resource.publish"] == "shadow"
    assert all(policy["modes"][action] == "enforce" for action in ACTIONS)
    attestations = policy[rollout.ATTESTATIONS_KEY]
    assert attestations["run.read"] == attestations["system.read"]
    assert attestations["run.read"]["workspace_id"] == workspace.id
    assert attestations["run.read"]["actions"] == sorted(ACTIONS)
    assert attestations["run.read"]["revision"] == REVISION
    assert attestations["run.read"]["promoted_by"] == "operator@example.net"
    assert attestations["run.read"]["trusted_runner"] == _trusted_runner()

    audits = db_session.query(AuditLog).filter_by(
        workspace_id=workspace.id,
        event_type="lot7.authorization.enforce_promoted",
    )
    assert audits.count() == 1
    assert audits.one().details["actions"] == sorted(ACTIONS)

    repeated = rollout.promote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision=REVISION,
        evidence=evidence,
        apply=True,
        actor="retry-operator",
        trusted_runner=_trusted_runner(),
    )
    assert repeated["changed"] is False
    assert repeated["already_enforced"] is True
    db_session.refresh(config)
    assert config.version == original_version + 1
    assert audits.count() == 1

    report = rollout.status(db_session, workspace_id=workspace.id)
    assert report["healthy"] is True
    by_action = {row["action"]: row for row in report["actions"]}
    assert by_action["run.read"]["attested"] is True
    assert by_action["system.read"]["drift"] == []


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (None, "protected GitLab OIDC runner"),
        ({**_trusted_runner(), "issuer": "http://gitlab.invalid"}, "HTTPS"),
        ({**_trusted_runner(), "project_id": "999"}, "configured trust anchor"),
        ({**_trusted_runner(), "ref": "feature/untrusted"}, "configured trust anchor"),
        ({**_trusted_runner(), "commit_sha": "c" * 40}, "match the promoted revision"),
        ({**_trusted_runner(), "ref_protected": False}, "must be protected"),
    ],
)
def test_apply_requires_sha_bound_protected_runner(db_session, runner, message):
    workspace, config = _seed(db_session)
    original = copy.deepcopy(config.capability_overrides)

    with pytest.raises(rollout.AuthorizationPromotionError, match=message):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=_evidence(config),
            apply=True,
            actor="operator@example.net",
            trusted_runner=runner,
        )

    db_session.refresh(config)
    assert config.capability_overrides == original
    assert db_session.query(AuditLog).count() == 0


def test_promotion_and_runtime_reject_all_skipped_junit_contracts(db_session):
    workspace, config = _seed(db_session)
    skipped = _evidence(config)
    skipped["contracts"]["candidate"]["skipped_count"] = skipped["contracts"]["candidate"][
        "test_count"
    ]

    with pytest.raises(rollout.AuthorizationPromotionError, match="no executed test cases"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=skipped,
            apply=True,
            actor="operator@example.net",
            trusted_runner=_trusted_runner(),
        )

    rollout.promote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision=REVISION,
        evidence=_evidence(config, db=db_session),
        apply=True,
        actor="operator@example.net",
        trusted_runner=_trusted_runner(),
    )
    payload = copy.deepcopy(config.capability_overrides)
    for action in ACTIONS:
        contract = payload["authorization_v2"][rollout.ATTESTATIONS_KEY][action]["contracts"][
            "candidate"
        ]
        contract["skipped_count"] = contract["test_count"]
    config.capability_overrides = payload
    db_session.commit()

    report = rollout.status(db_session, workspace_id=workspace.id)
    assert report["healthy"] is False
    assert all(
        any("no executed test cases" in error for error in row["drift"])
        for row in report["actions"]
        if row["action"] in ACTIONS
    )


def test_status_rejects_tampered_trusted_runner_attestation(db_session):
    workspace, config = _seed(db_session)
    rollout.promote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision=REVISION,
        evidence=_evidence(config, db=db_session),
        apply=True,
        actor="operator@example.net",
        trusted_runner=_trusted_runner(),
    )
    payload = copy.deepcopy(config.capability_overrides)
    for action in ACTIONS:
        payload["authorization_v2"][rollout.ATTESTATIONS_KEY][action]["trusted_runner"][
            "ref_protected"
        ] = False
    config.capability_overrides = payload
    db_session.commit()

    report = rollout.status(db_session, workspace_id=workspace.id)
    assert report["healthy"] is False
    assert all(
        "trusted runner ref is not protected" in row["drift"]
        for row in report["actions"]
        if row["action"] in ACTIONS
    )


def test_status_detects_unattested_enforce_and_promotion_fails_closed(db_session):
    workspace, config = _seed(db_session)
    payload = copy.deepcopy(config.capability_overrides)
    payload["authorization_v2"]["modes"]["system.read"] = "enforce"
    config.capability_overrides = payload
    db_session.commit()

    report = rollout.status(db_session, workspace_id=workspace.id)
    assert report["healthy"] is False
    drift = {row["action"]: row["drift"] for row in report["actions"] if row["drift"]}
    assert "enforcement attestations are missing" in drift["system.read"]

    with pytest.raises(rollout.AuthorizationPromotionError, match="unattested or drifted"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=["run.read"],
            revision=REVISION,
            evidence=_evidence(config, ["run.read"]),
            apply=True,
            actor="operator",
            trusted_runner=_trusted_runner(),
        )


def test_restrictive_repair_can_demote_unattested_drift(db_session):
    workspace, config = _seed(db_session, modes={"run.read": "enforce"})

    with pytest.raises(rollout.AuthorizationPromotionError, match="repair-drift"):
        rollout.demote(
            db_session,
            workspace_id=workspace.id,
            actions=["run.read"],
            revision="d" * 40,
            apply=False,
            actor="",
            reason="",
        )

    repaired = rollout.demote(
        db_session,
        workspace_id=workspace.id,
        actions=["run.read"],
        revision="d" * 40,
        apply=True,
        actor="incident-operator@example.net",
        reason="unattested enforcement drift",
        repair_drift=True,
    )

    assert repaired["changed"] is True
    assert repaired["repair_drift"] is True
    db_session.refresh(config)
    policy = config.capability_overrides["authorization_v2"]
    assert policy["modes"]["run.read"] == "shadow"
    assert policy[rollout.ATTESTATIONS_KEY] == {}
    assert policy[rollout.HISTORY_KEY][-1]["operation"] == "repair_to_shadow"
    assert rollout.status(db_session, workspace_id=workspace.id)["healthy"] is True
    audit = (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.authorization.enforce_demoted",
        )
        .one()
    )
    assert audit.details["repair_drift"] is True


def test_audit_failure_rolls_back_policy_and_attestation(db_session, monkeypatch):
    workspace, config = _seed(db_session)
    original_version = config.version
    monkeypatch.setattr(rollout, "emit_audit_event", lambda **_kwargs: None)

    with pytest.raises(rollout.AuthorizationPromotionError, match="audit could not be persisted"):
        rollout.promote(
            db_session,
            workspace_id=workspace.id,
            actions=ACTIONS,
            revision=REVISION,
            evidence=_evidence(config, db=db_session),
            apply=True,
            actor="operator",
            trusted_runner=_trusted_runner(),
        )

    config = db_session.get(WorkspaceIAMConfig, workspace.id)
    assert config.version == original_version
    policy = config.capability_overrides["authorization_v2"]
    assert all(policy["modes"][action] == "shadow" for action in ACTIONS)
    assert rollout.ATTESTATIONS_KEY not in policy
    assert db_session.query(AuditLog).count() == 0


def test_demotion_is_complete_group_only_audited_and_idempotent(db_session):
    workspace, config = _seed(db_session)
    rollout.promote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision=REVISION,
        evidence=_evidence(config, db=db_session),
        apply=True,
        actor="promoter@example.net",
        trusted_runner=_trusted_runner(),
    )
    promoted_version = config.version

    with pytest.raises(rollout.AuthorizationPromotionError, match="complete attested"):
        rollout.demote(
            db_session,
            workspace_id=workspace.id,
            actions=["run.read"],
            revision="c" * 40,
            apply=False,
            actor="",
            reason="",
        )

    preview = rollout.demote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision="c" * 40,
        apply=False,
        actor="",
        reason="",
    )
    assert preview["changed"] is True
    db_session.refresh(config)
    assert config.version == promoted_version

    applied = rollout.demote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision="c" * 40,
        apply=True,
        actor="operator@example.net",
        reason="unexpected denial rate",
    )
    assert applied["changed"] is True
    db_session.refresh(config)
    policy = config.capability_overrides["authorization_v2"]
    assert config.version == promoted_version + 1
    assert all(policy["modes"][action] == "shadow" for action in ACTIONS)
    assert all(action not in policy[rollout.ATTESTATIONS_KEY] for action in ACTIONS)
    assert policy[rollout.HISTORY_KEY][-1]["actions"] == sorted(ACTIONS)
    assert policy[rollout.HISTORY_KEY][-1]["reason"] == "unexpected denial rate"

    audit = (
        db_session.query(AuditLog)
        .filter_by(
            workspace_id=workspace.id,
            event_type="lot7.authorization.enforce_demoted",
        )
        .one()
    )
    assert audit.details["actions"] == sorted(ACTIONS)

    repeated = rollout.demote(
        db_session,
        workspace_id=workspace.id,
        actions=ACTIONS,
        revision="c" * 40,
        apply=True,
        actor="operator@example.net",
        reason="retry",
    )
    assert repeated["changed"] is False
    assert repeated["already_shadow"] is True
    db_session.refresh(config)
    assert config.version == promoted_version + 1
