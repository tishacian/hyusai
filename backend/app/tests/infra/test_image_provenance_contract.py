from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_PATH = REPO_ROOT / "docker" / "compose.agentium.yml"
DEPLOY_SCRIPT_PATH = REPO_ROOT / "scripts" / "deploy-vm.sh"
REVISION_BUILD_ARG = "${AGENTIUM_IMAGE_REVISION:-unknown}"
REVISION_LABEL = 'LABEL org.opencontainers.image.revision="${AGENTIUM_IMAGE_REVISION}"'
IMAGE_CONTRACTS = {
    "agentium-backend": "docker/Dockerfile.agentium-backend",
    "agentium-frontend": "docker/Dockerfile.agentium-frontend",
    "agentium-worker-cpu": "docker/Dockerfile.agentium-worker",
}


def test_agentium_images_accept_the_revision_arg_and_emit_the_oci_label() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

    for service_name, dockerfile_path in IMAGE_CONTRACTS.items():
        build = compose["services"][service_name]["build"]
        assert build["dockerfile"] == f"./{dockerfile_path}"
        assert build["args"]["AGENTIUM_IMAGE_REVISION"] == REVISION_BUILD_ARG

        dockerfile = (REPO_ROOT / dockerfile_path).read_text(encoding="utf-8")
        assert dockerfile.count("ARG AGENTIUM_IMAGE_REVISION=unknown") == 1
        assert dockerfile.count(REVISION_LABEL) == 1

    # The migration tool can also build and retag the backend image.
    migrate_build = compose["services"]["agentium-migrate"]["build"]
    assert migrate_build["dockerfile"] == "./docker/Dockerfile.agentium-backend"
    assert migrate_build["args"]["AGENTIUM_IMAGE_REVISION"] == REVISION_BUILD_ARG


def test_vm_deploy_exports_full_head_and_audits_selected_container_labels() -> None:
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")

    assert '[[ -n "$EXPECTED_SHA" ]] || die' in script
    assert '[[ "$1" =~ ^[0-9a-f]{40}$ ]]' in script
    assert 'REMOTE_SHA="$(git rev-parse "origin/$BRANCH")"' in script
    assert '[[ "$REMOTE_SHA" == "$EXPECTED_SHA" ]]' in script
    assert 'git reset --hard "$EXPECTED_SHA"' in script
    assert 'DEPLOY_SHA="$(git rev-parse HEAD)"' in script
    assert 'export AGENTIUM_IMAGE_REVISION="$DEPLOY_SHA"' in script
    assert 'head="$(git rev-parse HEAD)"' in script
    assert "for svc in agentium-backend agentium-frontend agentium-worker-cpu" in script
    assert 'service_is_selected "$svc" || continue' in script
    assert "docker image inspect" in script
    assert "org.opencontainers.image.revision" in script
    assert 'elif [[ "$image_revision" == "$expected_sha" ]]' in script
    assert "git rev-parse --short HEAD" not in script


def test_vm_deploy_has_fail_closed_health_and_immutable_rollback_state() -> None:
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'wait_for_http_200 "frontend /healthz' in script
    assert 'die "$label pas sain' in script
    assert 'read_env_value AGENTIUM_FRONTEND_HOST_PORT' in script
    assert 'read_env_value AGENTIUM_BACKEND_HOST_PORT' in script
    assert 'printf \'previous_sha\\t%s\\n\'' in script
    assert 'printf \'service\\t%s\\t%s\\t%s\\t%s\\n\'' in script
    assert 'rollback_ref="agentium-rollback/${svc}:${target_sha}"' in script
    assert 'docker tag "$image_id" "$rollback_ref"' in script
    assert 'validate_rollback_state "$state_file"' in script
    assert 'if ln "$tmp_file" "$state_file"' in script
    assert 'docker tag "$rollback_ref" "$image_ref"' in script
    assert '--no-build --force-recreate' in script
    assert '[[ "$current_head" == "$target_sha" ]]' in script
    assert '[[ "$runtime_revision" != "$target_sha"' in script
    assert '"$runtime_image_id" != "$image_id"' in script


def test_vm_check_only_audit_never_fetches_the_remote() -> None:
    script = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    audit = script[script.index("drift_audit() {") : script.index("read_env_value() {")]

    assert "git fetch" not in audit
    assert 'head="$(git rev-parse HEAD)"' in audit
    assert 'if [[ "$head" == "$expected_sha" ]]' in audit
