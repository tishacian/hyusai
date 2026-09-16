"""The demo's constraints must support its declared requirements on Python 3.12."""
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("kind", ["backend", "worker"])
def test_demo_constraints_cover_declared_requirements(kind):
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
    required = (ROOT / "backend" / "requirements.txt").read_text().splitlines()
    if kind == "worker":
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
