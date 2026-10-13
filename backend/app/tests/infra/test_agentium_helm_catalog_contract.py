"""Render-only checks: migration precedes canonical catalog reconciliation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[4] / "ops" / "helm" / "agentium"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "agentium", str(CHART), "--namespace", "agentium", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _documents(*args: str) -> dict:
    result = _render(*args)
    assert result.returncode == 0, result.stderr
    return {
        (doc["kind"], doc["metadata"]["name"]): doc
        for doc in yaml.safe_load_all(result.stdout)
        if doc
    }


@pytest.mark.parametrize("values", [None, "values-lab-ovh.yaml", "values-lab-aks.yaml"])
def test_catalog_hook_follows_migration_with_same_runtime(values: str | None) -> None:
    docs = _documents(*(["-f", str(CHART / values)] if values else []))
    migration = docs["Job", "agentium-migrate"]
    catalog = docs["Job", "agentium-catalog-reconcile"]
    annotations = catalog["metadata"]["annotations"]
    assert annotations["helm.sh/hook"] == "post-install,post-upgrade"
    assert annotations["helm.sh/hook"] == migration["metadata"]["annotations"]["helm.sh/hook"]
    assert int(annotations["helm.sh/hook-weight"]) > int(
        migration["metadata"]["annotations"]["helm.sh/hook-weight"]
    )
    assert annotations["helm.sh/hook-delete-policy"] == "before-hook-creation,hook-succeeded"
    pod = catalog["spec"]["template"]["spec"]
    container = pod["containers"][0]
    migrate_container = migration["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["python", "-m", "app.cli.reconcile_catalog", "--apply"]
    for key in ("image", "imagePullPolicy", "resources", "env", "envFrom"):
        assert container[key] == migrate_container[key]
    assert catalog["spec"]["activeDeadlineSeconds"] == 300
    assert catalog["spec"]["backoffLimit"] == 1
    assert pod["restartPolicy"] == "Never"
    assert "MINIO_ROOT_PASSWORD" not in str(container)


@pytest.mark.parametrize("flag", ["migrate.enabled", "catalogReconcile.enabled"])
def test_catalog_hook_can_be_skipped_explicitly(flag: str) -> None:
    assert ("Job", "agentium-catalog-reconcile") not in _documents("--set", f"{flag}=false")


@pytest.mark.parametrize("hook", ["", "pre-upgrade", "post-install"])
def test_unordered_migration_is_refused(hook: str) -> None:
    result = _render("--set", f"migrate.hook={hook}")
    assert result.returncode != 0
    assert "so migrations finish first" in result.stderr


def test_catalog_openbao_role_is_reachable_and_backend_scoped() -> None:
    docs = _documents(
        "-f", str(CHART / "values-lab-ovh.yaml"),
        "--set", "openbao.enabled=true",
        "--set", "openbao.server.enabled=true",
        "--set", "openbao.server.unsealKeySecret=unseal-private",
        "--set", "openbao.appRoleSecrets.backend=backend-private",
        "--set", "openbao.appRoleSecrets.worker=worker-private",
    )
    container = docs["Job", "agentium-catalog-reconcile"]["spec"]["template"]["spec"]["containers"][0]
    secrets = [entry["secretRef"]["name"] for entry in container["envFrom"] if "secretRef" in entry]
    assert secrets == ["agentium-lab", "backend-private"]
    policy = docs["NetworkPolicy", "agentium-openbao"]
    expressions = policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchExpressions"]
    allowed = next(row["values"] for row in expressions if row["key"] == "app.kubernetes.io/component")
    assert "catalog-reconcile" in allowed
