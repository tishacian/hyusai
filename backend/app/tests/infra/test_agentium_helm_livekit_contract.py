"""The chart's LiveKit and sidecar are the Compose realtime profile, off by
default. ops/scripts/check-k8s-scaffold.sh checks the rendered manifests in
depth; this pins the chart to the Compose source of truth."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "ops" / "helm" / "agentium"
COMPOSE = yaml.safe_load((ROOT / "docker" / "compose.agentium.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def _values(name: str) -> dict:
    return yaml.safe_load((CHART / name).read_text(encoding="utf-8"))


def _compose_default(expr: str) -> str:
    match = re.fullmatch(r"(.*)\$\{[A-Z_]+:-([^}]*)\}(.*)", expr)
    assert match is not None, expr
    return "".join(match.groups())


@pytest.mark.parametrize(
    "name", ["values.yaml", "values-local.yaml", "values-lab-ovh.yaml", "values-lab-aks.yaml"]
)
def test_realtime_is_off_in_every_values_file(name: str) -> None:
    assert _values(name)["livekit"]["enabled"] is False


def test_lab_values_pick_the_network_mode_their_provider_supports() -> None:
    ovh = _values("values-lab-ovh.yaml")["livekit"]
    aks = _values("values-lab-aks.yaml")["livekit"]
    assert ovh["network"]["mode"] == "hostNetwork"
    assert ovh["network"]["hostNetwork"]["nodeSelector"] == {"agentium.io/media": "livekit"}
    assert (
        ovh["network"]["loadBalancer"]["annotations"]["loadbalancer.ovhcloud.com/class"]
        == "octavia"
    )
    assert aks["network"]["mode"] == "loadBalancer"
    assert (
        "service.beta.kubernetes.io/azure-pip-name" in aks["network"]["loadBalancer"]["annotations"]
    )
    for lab in (ovh, aks):
        assert lab["existingSecret"] == "agentium-lab-livekit"


def test_chart_livekit_follows_the_compose_services() -> None:
    values = _values("values.yaml")
    assert values["livekit"]["image"] == _compose_default(SERVICES["agentium-livekit"]["image"])
    assert values["image"]["livekitAgent"] == "agentium-livekit-agent:local"

    agent = SERVICES["agentium-livekit-agent"]
    template = (CHART / "templates" / "livekit-agent.yaml").read_text(encoding="utf-8")
    assert "127.0.0.1:8090/healthz" in agent["healthcheck"]["test"][1]
    assert "path: /healthz" in template and "containerPort: 8090" in template
    assert not re.search(r"volumes:|volumeMounts:|hostPath|hostNetwork|envFrom:", template)
    start = json.loads((ROOT / "livekit-agent" / "package.json").read_text(encoding="utf-8"))[
        "scripts"
    ]["start"]
    command = re.search(r"command: (\[.*\])", template)
    assert command is not None and json.loads(command.group(1)) == start.split()

    backend = SERVICES["agentium-backend"]["environment"]
    configmap = (CHART / "templates" / "configmap.yaml").read_text(encoding="utf-8")
    dispatch = _compose_default(backend["LIVEKIT_AGENT_DISPATCH_URL"])
    assert f"LIVEKIT_AGENT_DISPATCH_URL: {dispatch}" in configmap
    gateway = _compose_default(backend["LIVEKIT_VOICE_GATEWAY_WS_URL"])
    assert gateway == "ws://agentium-backend:8000/api/v1/voice/sessions"
    assert (
        'printf "ws://agentium-backend:%v/api/v1/voice/sessions" .Values.backend.port' in configmap
    )


def test_lab_images_build_the_sidecar() -> None:
    script = (ROOT / "ops" / "scripts" / "build-lab-images.sh").read_text(encoding="utf-8")
    assert "livekit-agent) printf 'livekitAgent'" in script
    assert "declare -A" not in script
    assert (ROOT / "docker" / "Dockerfile.agentium-livekit-agent").is_file()


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_rendered_livekit_config_is_the_compose_one() -> None:
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "agentium",
            str(CHART),
            "--namespace",
            "agentium",
            "-f",
            str(CHART / "values-lab-ovh.yaml"),
            "--set",
            "livekit.enabled=true",
            "--show-only",
            "templates/livekit.yaml",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    configmap = next(
        doc for doc in yaml.safe_load_all(rendered) if doc and doc["kind"] == "ConfigMap"
    )
    chart = yaml.safe_load(configmap["data"]["livekit.yaml"])

    env = SERVICES["agentium-livekit"]["environment"]
    source = (ROOT / "docker" / "livekit" / "agentium-livekit.yaml").read_text(encoding="utf-8")
    for placeholder, key in (
        ("__LIVEKIT_RTC_TCP_PORT__", "LIVEKIT_RTC_TCP_PORT"),
        ("__LIVEKIT_RTC_UDP_RANGE_START__", "LIVEKIT_RTC_UDP_RANGE_START"),
        ("__LIVEKIT_RTC_UDP_RANGE_END__", "LIVEKIT_RTC_UDP_RANGE_END"),
    ):
        source = source.replace(placeholder, _compose_default(env[key]))
    source = source.replace("__LIVEKIT_REDIS_BLOCK__", "")
    compose = yaml.safe_load(source)

    assert chart == compose
    assert "LIVEKIT_API_SECRET" not in configmap["data"]["livekit.yaml"]
