"""Every source file on disk is a file the repository actually carries.

This exists because of a failure that no other gate can see. ``.gitignore`` had
an unanchored ``data/`` rule, which git matches against a directory of that name
at *any* depth — so ``frontend-ng/src/app/features/data/``, a whole feature, was
excluded from the repo while remaining on disk. Every local gate stayed green:
the compiler, the unit tests and the production build all read the working tree,
which was complete. Only a clone was broken, and nothing clones during a review.

So the check has to be about the ignore rules rather than about the code. For
each source file in the trees below, ``git check-ignore`` is asked whether the
repo would refuse it. Tracked paths are not reported by default, which makes the
question exactly the useful one: *is this file on its way into the repo?*

The intended reaction to a failure is almost never "add an exception here". It is
to anchor the offending rule with a leading slash, so it means the directory it
was written for and not every namesake beneath it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]

# Trees that hold nothing but source. Deployment scripts and docs live under
# their own ignore rules for generated captures and binaries, so they are
# checked by suffix rather than wholesale.
SOURCE_TREES = (
    "backend/app",
    "backend/alembic",
    "backend/scripts",
    "frontend-ng/src",
    "frontend-ng/e2e",
)
SOURCE_SUFFIXES = {
    ".css",
    ".html",
    ".mjs",
    ".py",
    ".scss",
    ".sql",
    ".ts",
    ".yaml",
    ".yml",
}
# Build output and caches are ignored on purpose and are not source.
NOT_SOURCE = {
    ".angular",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}


def _candidates() -> list[Path]:
    found: list[Path] = []
    for tree in SOURCE_TREES:
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if NOT_SOURCE.intersection(path.relative_to(ROOT).parts):
                continue
            found.append(path)
    return found


def test_no_source_file_is_excluded_from_the_repository():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    candidates = _candidates()
    # A guard that silently measured nothing would be worse than no guard.
    assert len(candidates) > 500, f"only {len(candidates)} source files discovered"

    payload = "\0".join(str(path.relative_to(ROOT)) for path in candidates)
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z", "--verbose"],
        cwd=ROOT,
        input=payload.encode(),
        capture_output=True,
    )
    # 0 = something is ignored, 1 = nothing is, anything else = git failed.
    if result.returncode == 1:
        return
    assert result.returncode == 0, result.stderr.decode()[:400]

    fields = result.stdout.decode().split("\0")
    excluded = [
        f"{fields[index + 3]} (by {fields[index]}:{fields[index + 1]} "
        f"pattern {fields[index + 2]!r})"
        for index in range(0, len(fields) - 3, 4)
    ]
    assert not excluded, (
        "source on disk that a clone would not receive — anchor the pattern "
        "with a leading slash instead of adding an exception:\n  "
        + "\n  ".join(sorted(excluded))
    )


@pytest.mark.parametrize(
    "runtime",
    ["data/assets", "backend/data/object_store", "backend/data/recipe_envs"],
)
def test_the_runtime_data_directories_stay_ignored(runtime: str):
    """The anchored rules still do the job they were written for.

    Anchoring is only safe if it did not accidentally invite gigabytes of local
    object store into the index, so the other half of the fix is asserted too.
    """

    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", "--", runtime],
        cwd=ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, f"{runtime} is no longer ignored"
