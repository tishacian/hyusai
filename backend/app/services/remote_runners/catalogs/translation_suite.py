"""Translation Suite commands: the machine side of the translation pipeline.

Each command calls one subcommand of the pipeline's runner entry point
(``python -m ts.runner``) in the job directory. The contract each subcommand
honours (inputs, ``result.json``, artifacts) is written in
docs/agentium-translation-suite-runner-contract.md. A lot keeps its working
tree under ``<translation.base_dir>/<lot>`` between commands; job directories
only carry inputs, results and artifacts.

Runner labels: ``translation.repo`` (pipeline checkout), ``translation.python``
(its interpreter) and ``translation.base_dir`` (lot working trees, distinct
from any tree another orchestrator uses on the same machine).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.remote_runners.catalog import CommandSpec, register

PATHS = ("translation.repo", "translation.python", "translation.base_dir")
_LOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")


class _Lot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lot: str

    @field_validator("lot")
    @classmethod
    def _lot(cls, value: str) -> str:
        if not _LOT_RE.match(value):
            raise ValueError("lot must be letters, digits, - or _")
        return value


class _Prepare(_Lot):
    archive: str | None = None
    source_lang: str | None = None
    pivot_lang: str | None = None
    targets: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("archive")
    @classmethod
    def _archive(cls, value: str | None) -> str | None:
        if value is not None and (not _FILE_RE.match(value) or not value.lower().endswith(".zip")):
            raise ValueError("archive must be the name of a staged .zip input")
        return value

    @field_validator("source_lang", "pivot_lang")
    @classmethod
    def _lang(cls, value: str | None) -> str | None:
        if value is not None and not _LANG_RE.match(value):
            raise ValueError("language tags look like fr-FR")
        return value

    @field_validator("targets")
    @classmethod
    def _targets(cls, value: list[str]) -> list[str]:
        if not all(_LANG_RE.match(item) for item in value):
            raise ValueError("language tags look like fr-FR")
        return value


class _Translate(_Lot):
    max_parallel: int = Field(default=2, ge=1, le=8)


class _Package(_Lot):
    producer_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")


def _entry(paths: dict[str, str], subcommand: str, lot: str, *extra: str) -> list[str]:
    return [
        "env",
        f"PYTHONPATH={paths['translation.repo']}",
        paths["translation.python"],
        "-m",
        "ts.runner",
        subcommand,
        "--repo",
        paths["translation.repo"],
        "--base-dir",
        paths["translation.base_dir"],
        "--lot",
        lot,
        *extra,
    ]


def _prepare(p: _Prepare, paths: dict[str, str]) -> list[str]:
    # Without a name the entry point takes the one .zip staged under inputs/.
    extra = ["--archive", f"inputs/{p.archive}"] if p.archive else []
    if p.source_lang:
        extra += ["--source-lang", p.source_lang]
    if p.pivot_lang:
        extra += ["--pivot-lang", p.pivot_lang]
    for target in p.targets:
        extra += ["--target", target]
    return _entry(paths, "prepare", p.lot, *extra)


PREPARE = register(
    CommandSpec(
        key="translation_suite.prepare",
        title="Prepare a translation lot",
        risk="write",
        mode="detached",
        params=_Prepare,
        build=_prepare,
        artifacts=("job.json",),
        runner_paths=PATHS,
        timeout_s=3600,
        description="Parses the staged source pack and provisions one instance per language pair.",
        tags=("translation",),
    )
)

TRANSLATE = register(
    CommandSpec(
        key="translation_suite.translate",
        title="Translate and check a lot",
        risk="compute",
        mode="detached",
        params=_Translate,
        build=lambda p, paths: _entry(
            paths, "translate", p.lot, "--max-parallel", str(p.max_parallel)
        ),
        artifacts=("outcomes.json",),
        runner_paths=PATHS,
        timeout_s=72 * 3600,
        description=(
            "Runs the scheduler in the foreground: translation, deterministic guards and the "
            "agentic QA chain; ends with one outcome per topic and language."
        ),
        tags=("translation", "gpu"),
    )
)

REVIEW_EXPORT = register(
    CommandSpec(
        key="translation_suite.review_export",
        title="Export the segments to review",
        risk="read",
        mode="detached",
        params=_Lot,
        build=lambda p, paths: _entry(paths, "review-export", p.lot),
        artifacts=("review.jsonl", "quality_gate.json"),
        runner_paths=PATHS,
        timeout_s=3 * 3600,
        description="Writes one review item per segment to validate, grouped by target language.",
        tags=("translation", "review"),
    )
)

AUDIT = register(
    CommandSpec(
        key="translation_suite.audit",
        title="Audit a lot before delivery",
        risk="read",
        mode="detached",
        params=_Lot,
        build=lambda p, paths: _entry(paths, "audit", p.lot),
        artifacts=("audit.json",),
        runner_paths=PATHS,
        timeout_s=3 * 3600,
        description="Runs the deterministic audit layers; result.json carries the gate verdict.",
        tags=("translation", "gate"),
    )
)

REINJECT = register(
    CommandSpec(
        key="translation_suite.reinject",
        title="Apply the reviewers' corrections",
        risk="write",
        mode="detached",
        params=_Lot,
        build=lambda p, paths: _entry(
            paths, "reinject", p.lot, "--decisions", "inputs/decisions.jsonl"
        ),
        artifacts=("reinject_report.json",),
        runner_paths=PATHS,
        timeout_s=6 * 3600,
        description="Writes the corrected segments back into the lot and requalifies the topics.",
        tags=("translation", "review"),
    )
)


def _package(p: _Package, paths: dict[str, str]) -> list[str]:
    extra = ["--producer-commit", p.producer_commit] if p.producer_commit else []
    return _entry(paths, "package", p.lot, *extra)


PACKAGE = register(
    CommandSpec(
        key="translation_suite.package",
        title="Package a lot for delivery",
        risk="write",
        mode="detached",
        params=_Package,
        build=_package,
        artifacts=("package.zip", "release_certificate.json"),
        runner_paths=PATHS,
        timeout_s=3 * 3600,
        description="Builds the delivery archive after the outcome gate and the audit pass.",
        tags=("translation", "delivery"),
    )
)

CERTIFY = register(
    CommandSpec(
        key="translation_suite.certify",
        title="Certify a packaged release",
        risk="compute",
        mode="detached",
        params=_Lot,
        build=lambda p, paths: _entry(
            paths, "certify", p.lot, "--profile", "inputs/certify_profile.json"
        ),
        artifacts=(
            "cleanroom_summary.json",
            "cleanroom_rerun_manifest.json",
            "package_receipt.json",
            "release_certificate.json",
        ),
        runner_paths=PATHS,
        timeout_s=24 * 3600,
        description=(
            "Runs the golden release chain on the lot's latest package: cleanroom, 4D canaries, "
            "immutable archive, resolved views and certificate. The first refusing gate is the "
            "verdict."
        ),
        tags=("translation", "delivery", "gate"),
    )
)
