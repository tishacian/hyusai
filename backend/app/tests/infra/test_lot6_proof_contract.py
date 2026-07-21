"""Static and unit contracts for the Lot 6 protected proof chain."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]
SHA = "a" * 40
CLAIM = "LOT6-SYSTEM360-PERSPECTIVES"


def _load(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve annotations through sys.modules while decorating.
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ci_identity() -> dict[str, str]:
    return {
        "issuer": "https://gitlab.example.test",
        "project_id": "42",
        "pipeline_id": "101",
        "job_id": "202",
        "commit_sha": SHA,
        "ref": "demo/agentic",
        "ref_protected": "true",
    }


def _artifact(kind: str, result: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": kind,
        "commit_sha": SHA,
        "environment": "production",
        "outcome": "passed",
        "runner": "playwright",
        "claims": {CLAIM: result},
        "ci": {
            **_ci_identity(),
            "server_url": "https://gitlab.example.test",
            "job_url": "https://gitlab.example.test/job/202",
        },
        "checks": {"sha": {"passed": True}},
    }


def test_deployment_preflight_requires_every_revision_and_build_info() -> None:
    module = _load("agentium_deployment_attestation_test", "scripts/agentium_deployment_attestation.py")
    services = module.DEFAULT_SERVICES
    snapshot = {
        "repo_head": SHA,
        "branch": "demo/agentic",
        "clean": True,
        "database_heads": ["060_system360"],
        "rollout": {
            "phase": "projection_active",
            "ready": True,
            "marker_count": 1,
            "marker_on_target": True,
            "strict_flow": True,
            "features": {
                "flow_v3_dag_authoritative": True,
                "cockpit_router_axes_v4": True,
                "system_360_projection_v1": True,
            },
            "membrane_mode": "enforce",
            "exercise": {
                "status": "completed",
                "required_skills_observed": True,
                "grounded_output_verified": True,
                "canonical_provenance_verified": True,
            },
        },
        "services": [
            {
                "service": service,
                "running": True,
                "image_id": "sha256:" + str(index) * 64,
                "revision": SHA,
            }
            for index, service in enumerate(services, start=1)
        ],
    }
    checks = module.evaluate_deployment(
        expected_sha=SHA,
        expected_branch="demo/agentic",
        expected_services=services,
        snapshot=snapshot,
        backend_build={"service": "backend", "revision": SHA, "revision_verified": True},
        frontend_build={"service": "frontend", "revision": SHA, "revision_verified": True},
    )
    assert checks
    assert all(check.passed for check in checks)

    snapshot["rollout"]["exercise"]["canonical_provenance_verified"] = False
    ungrounded = module.evaluate_deployment(
        expected_sha=SHA,
        expected_branch="demo/agentic",
        expected_services=services,
        snapshot=snapshot,
        backend_build={"service": "backend", "revision": SHA, "revision_verified": True},
        frontend_build={"service": "frontend", "revision": SHA, "revision_verified": True},
    )
    assert not next(
        check for check in ungrounded if check.name == "rollout.exercise_provenance"
    ).passed
    snapshot["rollout"]["exercise"]["canonical_provenance_verified"] = True

    snapshot["services"][1]["revision"] = "b" * 40
    failed = module.evaluate_deployment(
        expected_sha=SHA,
        expected_branch="demo/agentic",
        expected_services=services,
        snapshot=snapshot,
        backend_build={"service": "backend", "revision": SHA, "revision_verified": True},
        frontend_build={"service": "frontend", "revision": SHA, "revision_verified": True},
    )
    assert not next(
        check for check in failed if check.name == "oci.agentium-frontend.revision"
    ).passed


def test_deployment_preflight_refuses_unprotected_or_incomplete_ci() -> None:
    module = _load("agentium_deployment_attestation_ci_test", "scripts/agentium_deployment_attestation.py")
    env = {
        "CI_SERVER_URL": "https://gitlab.example.test",
        "CI_PROJECT_ID": "42",
        "CI_PIPELINE_ID": "101",
        "CI_JOB_ID": "202",
        "CI_JOB_URL": "https://gitlab.example.test/job/202",
        "CI_COMMIT_SHA": SHA,
        "CI_COMMIT_REF_NAME": "demo/agentic",
        "CI_COMMIT_REF_PROTECTED": "false",
    }
    with pytest.raises(module.AttestationError, match="protected GitLab ref"):
        module.protected_ci_identity(env)


def test_runner_attestation_refuses_unprotected_ci() -> None:
    module = _load(
        "agentium_runner_attestation_test",
        "scripts/agentium_runner_attestation.py",
    )
    env = {
        "CI_SERVER_URL": "https://gitlab.example.test",
        "CI_PROJECT_ID": "42",
        "CI_PIPELINE_ID": "101",
        "CI_JOB_ID": "202",
        "CI_JOB_URL": "https://gitlab.example.test/job/202",
        "CI_COMMIT_SHA": SHA,
        "CI_COMMIT_REF_NAME": "demo/agentic",
        "CI_COMMIT_REF_PROTECTED": "false",
    }
    with pytest.raises(module.RunnerAttestationError, match="protected GitLab ref"):
        module.protected_ci_identity(env)


def test_unsigned_oidc_token_cannot_activate_trusted_collector() -> None:
    module = _load("agentium_trusted_compliance_oidc_test", "scripts/agentium_trusted_compliance.py")

    def encoded(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    token = f"{encoded({'alg': 'none', 'kid': 'fake'})}.{encoded({'iss': 'https://gitlab.example.test'})}."
    with pytest.raises(module.TrustedComplianceError, match="RS256"):
        module.verify_gitlab_oidc(
            token,
            server_url="https://gitlab.example.test",
            audience="https://gitlab.example.test",
            fetch_json=lambda _url: pytest.fail("unsigned tokens must fail before network access"),
        )


def test_signed_claim_identity_must_match_protected_running_job() -> None:
    module = _load("agentium_trusted_compliance_identity_test", "scripts/agentium_trusted_compliance.py")
    env = {
        "CI_SERVER_URL": "https://gitlab.example.test",
        "CI_PROJECT_ID": "42",
        "CI_PIPELINE_ID": "101",
        "CI_JOB_ID": "202",
        "CI_COMMIT_SHA": SHA,
        "CI_COMMIT_REF_NAME": "demo/agentic",
        "CI_COMMIT_REF_PROTECTED": "true",
    }
    claims = {
        "iss": "https://gitlab.example.test",
        "project_id": "42",
        "pipeline_id": "101",
        "job_id": "202",
        "sha": SHA,
        "ref": "demo/agentic",
        "ref_protected": "true",
    }
    assert module.bound_ci_identity(claims, env)["commit_sha"] == SHA
    claims["job_id"] = "another-job"
    with pytest.raises(module.TrustedComplianceError, match="job_id"):
        module.bound_ci_identity(claims, env)


def test_formal_state_requires_runner_then_deployment_then_behavior(tmp_path: Path) -> None:
    module = _load("agentium_trusted_compliance_state_test", "scripts/agentium_trusted_compliance.py")
    identity = _ci_identity()
    runner = _artifact("runner", "passed")
    deployment = _artifact("deployment", "deployed")
    behavior = _artifact("behavior", "passed")
    behavior_path = tmp_path / "behavior.json"
    behavior_path.write_text(json.dumps(behavior), encoding="utf-8")

    validated = module.validate_evidence(
        behavior,
        path=behavior_path,
        kind="behavior",
        sha=SHA,
        identity=identity,
    )
    static = {
        "commit_sha": SHA,
        "claims": [
            {
                "id": CLAIM,
                "computed_state": "static_verified",
                "required_runners": ["playwright"],
            }
        ],
    }
    report = module.derive_formal_report(
        static_report=static,
        sha=SHA,
        identity=identity,
        runners=[runner],
        deployments=[deployment],
        behaviors=[validated],
        artifact_hashes={"behavior.json": "f" * 64},
    )
    assert report["formal_promotion"] == "authenticated_gitlab_oidc"
    assert report["claims"][0]["state"] == "behavior_verified"

    without_runner = module.derive_formal_report(
        static_report=static,
        sha=SHA,
        identity=identity,
        runners=[],
        deployments=[deployment],
        behaviors=[validated],
        artifact_hashes={},
    )
    assert without_runner["claims"][0]["state"] == "static_verified"


def test_failed_or_cross_job_json_cannot_promote(tmp_path: Path) -> None:
    module = _load("agentium_trusted_compliance_evidence_test", "scripts/agentium_trusted_compliance.py")
    identity = _ci_identity()
    forged = _artifact("behavior", "passed")
    forged["ci"]["job_id"] = "999"
    path = tmp_path / "forged.json"
    path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(module.TrustedComplianceError, match="job_id"):
        module.validate_evidence(
            forged,
            path=path,
            kind="behavior",
            sha=SHA,
            identity=identity,
        )


def test_lot6_job_is_manual_protected_and_does_not_embed_credentials() -> None:
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    canary = (ROOT / "frontend-ng/e2e/tests/11-system360-canary.spec.ts").read_text(
        encoding="utf-8"
    )
    assert "agentium-lot6-system360-production:" in pipeline
    assert 'CI_COMMIT_REF_PROTECTED == "true"' in pipeline
    assert "when: manual" in pipeline
    assert "AGENTIUM_ATTESTATION_ID_TOKEN" in pipeline
    assert "E2E_PASSWORD" in pipeline
    assert "ponfib" not in pipeline
    assert "AGENTIUM_LOT6_WORKSPACE_SLUG" not in pipeline
    assert "E2E_LOT6_WORKSPACE_SLUG" not in canary
    assert "showcase_contract_risk" not in canary
    assert "video_contract_risk" not in canary
    assert "Contract Risk" not in canary
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        canary,
        re.IGNORECASE,
    )
    assert "trace: 'off', video: 'off', screenshot: 'off'" in canary
    assert "marker(system) === 'v1'" in canary


def test_lot6_vm_wrapper_enforces_quiesced_order_and_stdin_exercise() -> None:
    wrapper = (ROOT / "scripts/deploy-lot6-system360.sh").read_text(encoding="utf-8")
    ordered = [
        '--build-only --branch "$BRANCH"',
        'create_backup "pre-quiescence"',
        'STAGE="writer quiescence"',
        'create_backup "quiesced"',
        'run_candidate alembic upgrade head',
        'rollout_system360_canary prepare --apply',
        'backfill_flow_v3_variables --cohort showcase',
        '--activate-only --branch "$BRANCH"',
        'rollout_system360_canary activate-flow --apply',
        'rollout_system360_canary exercise --apply --exercise-query-stdin',
        'rollout_system360_canary activate-membrane --apply',
        'rollout_system360_canary activate-axes --apply',
        'rollout_system360_canary activate-projection --apply',
    ]
    positions = [wrapper.index(fragment) for fragment in ordered]
    assert positions == sorted(positions)
    assert "--exercise-query-stdin est obligatoire" in wrapper
    assert "La requête d'exercice" in wrapper
    assert 'e["grounded_output_verified"] is True' in wrapper
    assert 'e["canonical_provenance_verified"] is True' in wrapper
    assert "aucune restauration DB/image implicite" in wrapper
    assert "rollout-failure-rollback.json" in wrapper
    assert 'local backup="$1"\n\tlocal checksum="$backup.sha256"' in wrapper
    assert (
        'local label="$1"\n\tlocal backup="$DEPLOY_DIR/postgres-${label}.dump"'
        in wrapper
    )


def test_lot6_rollout_locks_only_concrete_postgres_tables() -> None:
    rollout = (ROOT / "backend/scripts/rollout_system360_canary.py").read_text(
        encoding="utf-8"
    )
    assert ".with_for_update()" not in rollout
    for model in (
        "Workspace",
        "System",
        "Capability",
        "ControlPolicy",
        "Skill",
        "Context",
    ):
        assert f".with_for_update(of={model})" in rollout


def test_p4_protected_gate_uses_real_postgres_rabbitmq_and_worker() -> None:
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    job = pipeline.split("agentium-p4-rabbitmq-integration:", 1)[1].split(
        "agentium-lot6-system360-production:", 1
    )[0]
    assert "postgres:16-bookworm" in job
    assert "rabbitmq:4.1-management" in job
    assert 'ENABLE_SUBFLOW_CELERY: "true"' in job
    assert 'RUN_RABBITMQ_INTEGRATION: "1"' in job
    assert "celery -A app.workers.celery_app:celery_app worker" in job
    assert "app/tests/integration/test_subflow_celery_rabbitmq.py" in job
    assert 'CI_COMMIT_REF_PROTECTED == "true"' in job
    assert "junit: backend/test-results/p4/junit.xml" in job
    assert "agentium_runner_attestation.py" in job
    assert "agentium_trusted_compliance.py" in job
    assert "LOT6-P4-DURABLE-SUBFLOWS" in job
