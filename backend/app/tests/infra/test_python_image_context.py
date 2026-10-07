"""What the Python images may and may not receive from the build context.

BuildKit reads ``<Dockerfile>.dockerignore`` instead of the root ``.dockerignore``
when one sits next to the Dockerfile, so the backend and worker images have
their own exclusion list. Two failures are worth a test: a runtime file that
silently stops shipping (a demo seed reading ``docs/``, Sentinel reading
``config/``), and a secret or a laptop venv that silently starts shipping.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PYTHON_IGNORES = [
    ROOT / "docker" / "Dockerfile.agentium-backend.dockerignore",
    ROOT / "docker" / "Dockerfile.agentium-worker.dockerignore",
    ROOT / "docker" / "Dockerfile.agentium-ml-ts.dockerignore",
]

# Files the API or a worker reads at run time from outside backend/.
RUNTIME_READS = [
    "backend/app/main.py",
    "backend/requirements.txt",
    "backend/constraints-demo-app.txt",
    "backend/constraints-demo-giskard.txt",
    "backend/requirements_giskard.txt",
    "backend/requirements_ml_ts.txt",
    "backend/constraints-demo-ml-ts.txt",
    "backend/app/resources/ml_forecast_harness.py",
    "backend/app/resources/ml_forecast_pyfunc.py",
    "backend/scripts/qualify_giskard_raget.py",
    "backend/rag_models.lock.json",
    "backend/scripts/fetch_rag_models.py",
    "backend/scripts/bench_rerank_engines.py",
    "run_celery.sh",
    "docker/run_backend.sh",
    "config/agentium/workspace-app-manifests.v1.json",
    "docs/demo-data/sentinel-ci-kb/rapport-prefet-nawa-2026-05-10.md",
    "docs/showcase-notices-knowledge-guide.md",
    "docs/andritz-notices-techniques-spl-knowledge-guide.md",
    "data/hkunlp_embeddings.npy",
]
RUNTIME_DIRECTORIES = ["src/metadata_extraction", "connections", "sample_data", "frontend"]

NEVER_SHIPPED = [
    "docker/env/agentium.env",
    "docker/env/keycloak.agentium.env",
    "backend/.env",
    "backend/.venv/bin/python",
    "backend/venv/bin/python",
    ".claude/worktrees/agent/backend/app/main.py",
    "frontend-ng/src/main.ts",
    "outputs/report.html",
    "docs/evidence/release/worker-build.md",
    "docs/render/deck.pptx",
    "docs/status/screen.png",
    "docs/compliance-2/pack.pdf",
]


def _patterns(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _regex(pattern: str) -> re.Pattern[str]:
    """moby's pattern semantics: ``**`` crosses separators, ``*`` does not."""
    pattern, out, index = pattern.strip("/"), "", 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out, index = out + "(?:.*/)?", index + 3
        elif pattern.startswith("**", index):
            out, index = out + ".*", index + 2
        elif pattern[index] == "*":
            out, index = out + "[^/]*", index + 1
        elif pattern[index] == "?":
            out, index = out + "[^/]", index + 1
        elif pattern[index] == "[":
            end = pattern.index("]", index)
            out, index = out + pattern[index : end + 1], end + 1
        else:
            out, index = out + re.escape(pattern[index]), index + 1
    return re.compile(out + r"\Z")


def _excluded(path: str, patterns: list[str]) -> bool:
    """Last matching pattern wins; a match on a parent directory counts."""
    parts = path.split("/")
    excluded = False
    for raw in patterns:
        negate = raw.startswith("!")
        regex = _regex(raw[1:] if negate else raw)
        if any(regex.match("/".join(parts[:depth])) for depth in range(1, len(parts) + 1)):
            excluded = not negate
    return excluded


def test_python_ignores_extend_the_root_file_verbatim():
    root = _patterns(ROOT / ".dockerignore")
    first, *others = (_patterns(path) for path in PYTHON_IGNORES)
    assert all(other == first for other in others), "the Python images must see the same context"
    assert first[: len(root)] == root, "the Python ignore file must start with the root file verbatim"


@pytest.mark.parametrize("ignore_file", PYTHON_IGNORES, ids=lambda path: path.name)
def test_runtime_reads_stay_in_the_python_image_context(ignore_file):
    patterns = _patterns(ignore_file)
    for path in RUNTIME_READS:
        assert (ROOT / path).exists(), f"stale runtime read in this test: {path}"
        assert not _excluded(path, patterns), f"{ignore_file.name} drops a runtime file: {path}"
    for directory in RUNTIME_DIRECTORIES:
        files = [p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        assert files, f"stale runtime directory in this test: {directory}"
        sample = files[0].relative_to(ROOT).as_posix()
        assert not _excluded(sample, patterns), f"{ignore_file.name} drops {directory}/"


@pytest.mark.parametrize(
    "ignore_file", [ROOT / ".dockerignore", *PYTHON_IGNORES], ids=lambda path: path.name
)
def test_secrets_and_laptop_state_never_reach_an_image(ignore_file):
    patterns = _patterns(ignore_file)
    for path in ("docker/env/agentium.env", "backend/.env", "backend/.venv/bin/python", ".claude/x"):
        assert _excluded(path, patterns), f"{ignore_file.name} ships {path}"


@pytest.mark.parametrize("ignore_file", PYTHON_IGNORES, ids=lambda path: path.name)
def test_python_images_skip_sources_their_runtime_never_reads(ignore_file):
    patterns = _patterns(ignore_file)
    for path in NEVER_SHIPPED:
        assert _excluded(path, patterns), f"{ignore_file.name} ships {path}"


def test_the_matcher_follows_moby_semantics():
    patterns = ["data/", "!data/keep.npy", "**.log", "docs/**/*.png", "docker/env/*.env"]
    assert _excluded("data/x.csv", patterns)
    assert not _excluded("data/keep.npy", patterns)
    assert _excluded("backend/logs/app.log", patterns)
    assert _excluded("docs/a/b/c.png", patterns)
    assert not _excluded("docs/a/b/c.md", patterns)
    assert _excluded("docker/env/agentium.env", patterns)
    assert not _excluded("docker/env/agentium.env.example", patterns)
