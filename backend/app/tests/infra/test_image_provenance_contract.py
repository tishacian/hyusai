from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_PATH = REPO_ROOT / "docker" / "compose.agentium.yml"
REVISION_BUILD_ARG = "${AGENTIUM_IMAGE_REVISION:-unknown}"
REVISION_LABEL = 'LABEL org.opencontainers.image.revision="${AGENTIUM_IMAGE_REVISION}"'
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
IMAGE_CONTRACTS = {
    "agentium-backend": "docker/Dockerfile.agentium-backend",
    "agentium-frontend": "docker/Dockerfile.agentium-frontend",
    "agentium-worker-cpu": "docker/Dockerfile.agentium-worker",
    "agentium-worker-ml-ts": "docker/Dockerfile.agentium-ml-ts",
    "agentium-livekit-agent": "docker/Dockerfile.agentium-livekit-agent",
}


def test_agentium_images_accept_the_revision_arg_and_emit_the_oci_label() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

    for service_name, dockerfile_path in IMAGE_CONTRACTS.items():
        build = compose["services"][service_name]["build"]
        assert build["dockerfile"] == f"./{dockerfile_path}"
        assert build["args"]["AGENTIUM_IMAGE_REVISION"] == REVISION_BUILD_ARG

        dockerfile = (REPO_ROOT / dockerfile_path).read_text(encoding="utf-8")
        # The multi-stage frontend must consume the same argument in both the
        # Node build stage (served build-info) and final nginx stage (OCI
        # label). Backend/worker are single-stage images.
        expected_arg_declarations = 2 if service_name == "agentium-frontend" else 1
        assert dockerfile.count("ARG AGENTIUM_IMAGE_REVISION=unknown") == expected_arg_declarations
        assert dockerfile.count(REVISION_LABEL) == 1

    frontend = (REPO_ROOT / IMAGE_CONTRACTS["agentium-frontend"]).read_text(encoding="utf-8")
    assert "RUN node scripts/write-build-info.mjs" in frontend
    for service_name in ("agentium-backend", "agentium-worker-cpu", "agentium-worker-ml-ts"):
        dockerfile = (REPO_ROOT / IMAGE_CONTRACTS[service_name]).read_text(encoding="utf-8")
        assert "ENV AGENTIUM_IMAGE_REVISION=${AGENTIUM_IMAGE_REVISION}" in dockerfile

    # The migration tool can also build and retag the backend image.
    migrate_build = compose["services"]["agentium-migrate"]["build"]
    assert migrate_build["dockerfile"] == "./docker/Dockerfile.agentium-backend"
    assert migrate_build["args"]["AGENTIUM_IMAGE_REVISION"] == REVISION_BUILD_ARG


def test_an_image_with_transformers_carries_the_torchvision_it_assumes() -> None:
    """Both halves of a pair, from the index that makes them a pair.

    transformers treats torchvision as a peer of torch: several of its image
    processors import it at module scope, and its lazy ``__getattr__`` imports
    those modules whenever something asks the package for a name. A module scan
    therefore walks into them — and ``skops.io`` runs exactly such a scan while
    building its trusted-type tables at import, the same walk
    ``pickle.whichmodule`` does. Without torchvision that scan raised
    ``ModuleNotFoundError`` and no artifact could be deserialised: every
    ``/predict`` on the demo host answered 409 while a laptop, whose venv has
    neither library, passed.

    The index matters as much as the package. torchvision ships compiled ops
    built against one torch; installing the PyPI default next to a ``+cpu``
    torch yields a torchvision whose import raises "operator torchvision::nms
    does not exist", which trades one broken scan for another.
    """

    for service in ("agentium-backend", "agentium-worker-cpu"):
        dockerfile = (REPO_ROOT / IMAGE_CONTRACTS[service]).read_text(encoding="utf-8")
        if "transformers" not in dockerfile:
            continue

        # The optional API layer nests pip in a RUN if block. Constraints pin
        # versions; the index decides which build (+cpu) those versions come from.
        cpu_install = re.search(
            r"(?m)^(?:RUN |\s+)pip install --no-cache-dir (?P<packages>[\w\s.=<>-]+?)\s*\\\s*\n"
            r"(?:\s*--constraint=\S+\s*\\\s*\n)*"
            r"\s*--index-url=" + re.escape(TORCH_CPU_INDEX),
            dockerfile,
        )
        assert cpu_install is not None, f"{service} installs transformers without a CPU-index torch"
        packages = set(cpu_install.group("packages").split())
        assert {"torch", "torchvision"} <= packages, (
            f"{service} installs {sorted(packages)} from the CPU index: "
            "transformers assumes torchvision alongside torch"
        )

        pypi_installs = re.findall(
            r"(?m)^\s*--index-url=\$\{PIP_INDEX_URL\}\s*\\\s*\n(?P<packages>(?:\s*\"?[\w.=<>-]+\"?\s*\\?\s*\n)+)",
            dockerfile,
        )
        for block in pypi_installs:
            assert "torchvision" not in block, (
                f"{service} installs torchvision from PyPI, whose wheel is built "
                "against a different torch than the CPU index serves"
            )
