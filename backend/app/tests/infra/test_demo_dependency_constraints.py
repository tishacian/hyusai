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


PYTHON_IMAGES = ("backend", "worker", "ml-ts", "ml-deep")


def test_api_and_worker_build_one_shared_python_stack():
    """The worker fits what the API unpickles, so they share one interpreter build.

    Identical instructions down to the marker give identical layers: BuildKit
    builds the Python stack once, and the images cannot drift apart on the
    numpy, scipy or scikit-learn a model artifact depends on. The forecasting
    image shares it too: its regressors are the tabular catalog's, and the API
    reads the evidence it writes.
    """
    prefixes = {}
    for name in PYTHON_IMAGES:
        dockerfile = (ROOT / "docker" / f"Dockerfile.agentium-{name}").read_text(encoding="utf-8")
        assert dockerfile.count(PREFIX_END) == 1, f"{name} lost its shared-prefix marker"
        prefixes[name] = _instructions(dockerfile.split(PREFIX_END, 1)[0])
    assert all(prefix == prefixes["backend"] for prefix in prefixes.values())
    shared = "\n".join(prefixes["backend"])
    assert "constraints-demo-app.txt" in shared
    # The baked cross-encoder files are shared; torch is not.
    assert "fetch_rag_models.py" in shared
    assert "torch" not in shared and "transformers" not in shared


def test_the_existing_worker_torch_install_stays_cpu_only():
    """The API reranks on ONNX Runtime; torch is the worker's, for Giskard's venv
    and the fallback rerank engine, and comes from the CPU-only index."""

    backend = (ROOT / "docker" / "Dockerfile.agentium-backend").read_text(encoding="utf-8")
    worker = (ROOT / "docker" / "Dockerfile.agentium-worker").read_text(encoding="utf-8")
    installs = "\n".join(_run_instructions(backend))
    assert "torch" not in installs and "transformers" not in installs
    worker_runs = _run_instructions(worker.split(PREFIX_END, 1)[1])
    torch_runs = [run for run in worker_runs if "pip install --no-cache-dir torch torchvision" in run]
    assert len(torch_runs) == 1
    assert "--index-url=https://download.pytorch.org/whl/cpu" in torch_runs[0]
    # The Giskard venv inherits it rather than resolving a CUDA build from PyPI.
    giskard = next(run for run in worker_runs if "/opt/agentium-giskard" in run)
    assert worker_runs.index(torch_runs[0]) < worker_runs.index(giskard)


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
    for name in PYTHON_IMAGES:
        dockerfile = (ROOT / "docker" / f"Dockerfile.agentium-{name}").read_text(encoding="utf-8")
        for run in _run_instructions(dockerfile):
            kinds = set(re.findall(r"--constraint=\S*constraints-demo-([\w-]+)\.txt", run))
            assert kinds <= {"app", "giskard", "ml-ts", "ml-deep"}, f"{name} installs with unknown constraints {kinds}"
            if "ml-ts" in kinds:
                assert name in {"ml-ts", "ml-deep"} and {"app", "ml-ts"} <= kinds, f"{name} applies forecasting pins"
            if "ml-deep" in kinds:
                assert name == "ml-deep" and kinds == {"app", "ml-ts", "ml-deep"}
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


def test_the_forecasting_image_only_adds_packages_and_never_moves_an_app_pin():
    """ml-ts installs on top of the app stack with both constraint files.

    A package in both files at different versions would make pip refuse the
    install — or, worse, a later edit would quietly fit forecasts on another
    numpy than the API reads them with. So the ml-ts file only adds.
    """
    app = _constraints("app")
    ml_ts = _constraints("ml-ts")
    assert not set(ml_ts) & set(app), f"ml-ts re-pins app packages: {sorted(set(ml_ts) & set(app))}"
    for line in (ROOT / "backend" / "requirements_ml_ts.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = canonicalize_name(Requirement(line).name)
        assert name in ml_ts, f"Unqualified forecasting dependency: {name}"
    assert {"skforecast", "statsmodels", "numba"} <= set(ml_ts)


def test_the_forecasting_image_has_no_torch_and_runs_the_ml_worker():
    dockerfile = (ROOT / "docker" / "Dockerfile.agentium-ml-ts").read_text(encoding="utf-8")
    specific = dockerfile.split(PREFIX_END, 1)[1]
    runs = _run_instructions(specific)
    installs = [run for run in runs if "pip install" in run]
    assert len(installs) == 1
    assert "torch" not in installs[0].replace('! python -c "import torch"', "")
    assert '! python -c "import torch"' in installs[0], "the image must prove torch did not ride along"
    assert "/opt/agentium-giskard" not in specific and "build-essential" not in specific
    assert "CELERY_APP=app.workers.celery_ml:celery_ml" in specific
    assert "ML_RUNTIME=ml-ts" in specific and "CELERY_QUEUES=ml_ts" in specific


def test_deep_dependencies_only_add_to_the_qualified_application_stack():
    app, ts, deep = _constraints("app"), _constraints("ml-ts"), _constraints("ml-deep")
    assert not set(deep) & (set(app) | set(ts))
    for line in (ROOT / "backend" / "requirements_ml_deep.txt").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            name = canonicalize_name(Requirement(line).name)
            assert name in app or name in deep
    assert {"chronos-forecasting", "sentence-transformers", "accelerate", "einops"} <= set(deep)
    image = (ROOT / "docker" / "Dockerfile.agentium-ml-deep").read_text()
    specific = image.split(PREFIX_END, 1)[1]
    assert "ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu" in specific
    assert "--index-url=${TORCH_INDEX_URL} torch" in specific
    assert specific.index("--index-url=${TORCH_INDEX_URL} torch") < specific.index("-r /tmp/requirements/requirements_ml_deep.txt")
    assert "ML_RUNTIME=ml-deep" in specific and "CELERY_QUEUES=ml_deep" in specific
    assert "HF_HUB_OFFLINE=1" in specific and "TRANSFORMERS_OFFLINE=1" in specific
    assert "/opt/agentium-giskard" not in specific
