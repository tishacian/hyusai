"""The demo's constraints must support its declared requirements on Python 3.12."""
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[4]
PREFIX_END = "# ---- image-specific layers ----"
GISKARD_PIP = "/opt/agentium-giskard/bin/pip"


def _constraints(kind: str) -> dict[str, str]:
    constraints = {}
    for line in (ROOT / "backend" / f"constraints-demo-{kind}.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        assert requirement.url is None and requirement.marker is None
        pins = list(requirement.specifier)
        assert len(pins) == 1 and pins[0].operator == "==" and "*" not in pins[0].version
        name = canonicalize_name(requirement.name)
        assert name not in constraints
        constraints[name] = pins[0].version
    return constraints


def _instructions(dockerfile: str) -> list[str]:
    """Dockerfile instructions with comments and blank lines dropped.

    Comments are not part of a layer's cache key, so two files that differ
    only in their prose still share every layer.
    """
    return [
        line.rstrip()
        for line in dockerfile.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


@pytest.mark.parametrize("kind", ["app", "giskard"])
def test_demo_constraints_cover_declared_requirements(kind):
    constraints = _constraints(kind)
    required = (ROOT / "backend" / "requirements.txt").read_text().splitlines()
    if kind == "giskard":
        required += (ROOT / "backend" / "requirements_giskard.txt").read_text().splitlines()
    required += ["torch", "torchvision", "transformers>=4.41.0"]
    for line in required:
        line = line.strip()
        if not line or line.startswith(("#", "-r")):
            continue
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        assert name in constraints, f"Unqualified dependency: {name}"
        assert requirement.specifier.contains(constraints[name]), f"Incompatible {name}: {constraints[name]}"


def test_api_and_worker_build_one_shared_python_stack():
    """The worker fits what the API unpickles, so they share one interpreter build.

    Identical instructions down to the marker give identical layers: BuildKit
    builds the Python stack once, and the two images cannot drift apart on the
    numpy, scipy or scikit-learn a model artifact depends on.
    """
    prefixes = {}
    for name in ("backend", "worker"):
        dockerfile = (ROOT / "docker" / f"Dockerfile.agentium-{name}").read_text(encoding="utf-8")
        assert dockerfile.count(PREFIX_END) == 1, f"{name} lost its shared-prefix marker"
        prefixes[name] = _instructions(dockerfile.split(PREFIX_END, 1)[0])
    assert prefixes["backend"] == prefixes["worker"]
    shared = "\n".join(prefixes["backend"])
    assert "constraints-demo-app.txt" in shared
    assert "torch torchvision" in shared
    # The baked cross-encoder files are shared too, and sit before torch so the
    # API image can stop installing torch without leaving the shared prefix.
    assert "fetch_rag_models.py" in shared
    assert shared.index("fetch_rag_models.py") < shared.index("torch torchvision")


def _run_instructions(dockerfile: str) -> list[str]:
    """Each RUN instruction with its continuation lines joined."""
    runs, current = [], None
    for line in _instructions(dockerfile):
        if current is None and line.startswith("RUN "):
            current = line
        elif current is not None:
            current += " " + line.strip()
        if current is not None and not current.endswith("\\"):
            runs.append(current)
            current = None
    return runs


def test_giskard_constraints_only_reach_the_giskard_venv():
    """Giskard's older numpy/scipy may exist only inside its own venv."""
    for name in ("backend", "worker"):
        dockerfile = (ROOT / "docker" / f"Dockerfile.agentium-{name}").read_text(encoding="utf-8")
        for run in _run_instructions(dockerfile):
            kinds = set(re.findall(r"--constraint=\S*constraints-demo-(\w+)\.txt", run))
            assert kinds <= {"app", "giskard"}, f"{name} installs with unknown constraints {kinds}"
            if "giskard" not in kinds:
                continue
            assert kinds == {"giskard"}, f"{name} mixes Giskard and app pins in one install"
            installs = re.findall(r"(\S*pip) install", run)
            assert installs and all(pip == GISKARD_PIP for pip in installs), (
                f"{name} applies Giskard pins outside {GISKARD_PIP}: {installs}"
            )
    worker = (ROOT / "docker" / "Dockerfile.agentium-worker").read_text(encoding="utf-8")
    assert "python -m venv --system-site-packages /opt/agentium-giskard" in worker
    assert '! python -c "import giskard"' in worker


def test_giskard_venv_only_overrides_what_giskard_pins_differently():
    """Every app pin the venv does not override must be the app's own version.

    The venv inherits the system site-packages, so a package pinned identically
    is reused rather than reinstalled; the override set is exactly the packages
    Giskard needs at another version. Keeping that set small and explicit keeps
    the RAGET interpreter close to the one the rest of the worker runs.
    """
    app = _constraints("app")
    giskard = _constraints("giskard")
    assert set(app) <= set(giskard), "the Giskard venv would miss a package the app installs"
    overridden = {name for name in app if giskard[name] != app[name]}
    assert overridden <= {
        "faiss-cpu",
        "fsspec",
        "importlib-metadata",
        "numpy",
        "openai",
        "pydantic",
        "pydantic-core",
        "s3fs",
        "scipy",
    }, f"Giskard now overrides more of the app stack: {sorted(overridden)}"
    for name in ("torch", "torchvision", "transformers", "scikit-learn", "skops", "mlflow"):
        assert giskard[name] == app[name], f"Giskard venv must reuse the system {name}"
