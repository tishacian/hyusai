"""Content-addressed Python virtual environments for recipe nodes.

Identity
--------
An environment is identified by the sha256 fingerprint of its *normalized*
specification: Python version + sorted requirement lines + registry
configuration. Two nodes (or two flows) declaring the same dependencies share
one venv; editing the requirements produces a new fingerprint, which is the
versioning model — no in-place mutation of a built env, ever.

Reproducibility
---------------
After the first successful build, ``pip freeze`` is captured as
``lock_text``. A rebuild after eviction installs from that lock, so the env
comes back with the exact same resolved versions even when the loose spec
would now resolve differently.

Storage governor
----------------
Venvs live under ``settings.recipe_envs_path`` next to a shared pip cache
(``PIP_CACHE_DIR``). The sweep evicts least-recently-used ready envs above the
global quota (down to a low watermark) plus idle envs past the TTL, and caps
the pip cache. Eviction removes bytes only: the row, its spec and its lock
stay, so the next use rebuilds transparently — mostly from the local wheel
cache instead of the network.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.recipe import PythonEnv, RecipeExecution

logger = get_logger(__name__)

RECIPE_SKILL_SLUG = "python_recipe_v1"

_MAX_REQUIREMENT_LINES = 200
_MAX_REQUIREMENT_LINE_CHARS = 300
_MAX_EXTRA_INDEX_URLS = 4
# Requirement specifiers only (PEP 508 names + extras/markers/pins). Pip
# option lines (-r, -e, --index-url, …) must go through the dedicated spec
# fields so the fingerprint and the execution surface stay reviewable.
_REQUIREMENT_LINE_RE = re.compile(r"^[A-Za-z0-9]")
_INDEX_URL_RE = re.compile(r"^https?://[^\s]+$")


@dataclass(slots=True)
class RecipeError(Exception):
    """Business error with the canonical ``{code, message}`` payload."""

    code: str
    message: str
    status_code: int = 422
    details: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "error": self.code.lower(),
            "code": self.code,
            "message": self.message,
            **dict(self.details or {}),
        }

    def __str__(self) -> str:  # pragma: no cover - repr convenience
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class EnvSpec:
    """Normalized environment specification (the fingerprint input)."""

    python_version: str
    requirements: tuple[str, ...] = ()
    index_url: str | None = None
    extra_index_urls: tuple[str, ...] = field(default_factory=tuple)

    @property
    def requirements_text(self) -> str:
        return "\n".join(self.requirements)

    def fingerprint(self) -> str:
        payload = "\n".join(
            (
                f"python={self.python_version}",
                *self.requirements,
                f"index={self.index_url or ''}",
                *(f"extra-index={url}" for url in self.extra_index_urls),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def runtime_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def normalize_requirements(text: Any) -> tuple[str, ...]:
    """Normalize a requirements block into a canonical sorted tuple.

    Comments and blank lines are dropped, inline comments stripped, internal
    whitespace collapsed. Duplicate lines collapse. Option lines fail closed.
    """

    if text is None:
        return ()
    if not isinstance(text, str):
        raise RecipeError(
            code="RECIPE_REQUIREMENTS_INVALID",
            message="requirements must be provided as text (one requirement per line).",
        )
    lines: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        line = " ".join(line.split())
        if len(line) > _MAX_REQUIREMENT_LINE_CHARS:
            raise RecipeError(
                code="RECIPE_REQUIREMENT_LINE_TOO_LONG",
                message="A requirement line exceeds the allowed length.",
                details={"line": line[:80]},
            )
        if not _REQUIREMENT_LINE_RE.match(line):
            raise RecipeError(
                code="RECIPE_REQUIREMENT_OPTION_FORBIDDEN",
                message=(
                    "Only plain requirement specifiers are allowed; pip options "
                    "(-r, -e, --index-url, …) must use the registry fields."
                ),
                details={"line": line[:80]},
            )
        lines.add(line)
    if len(lines) > _MAX_REQUIREMENT_LINES:
        raise RecipeError(
            code="RECIPE_REQUIREMENTS_TOO_MANY",
            message=f"At most {_MAX_REQUIREMENT_LINES} requirement lines are allowed.",
        )
    return tuple(sorted(lines, key=str.casefold))


def _normalize_index_url(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecipeError(
            code="RECIPE_REGISTRY_INVALID",
            message=f"{field_name} must be an http(s) URL.",
        )
    url = value.strip()
    if not url:
        return None
    if not _INDEX_URL_RE.match(url) or len(url) > 500:
        raise RecipeError(
            code="RECIPE_REGISTRY_INVALID",
            message=f"{field_name} must be an http(s) URL.",
            details={"value": url[:120]},
        )
    return url


def build_env_spec(
    *,
    requirements_text: Any = None,
    index_url: Any = None,
    extra_index_urls: Any = None,
    python_version: str | None = None,
) -> EnvSpec:
    """Validate + normalize an author-declared environment specification."""

    requirements = normalize_requirements(requirements_text)
    normalized_index = _normalize_index_url(index_url, field_name="index_url")
    if normalized_index is None and settings.recipe_pip_default_index_url.strip():
        normalized_index = _normalize_index_url(
            settings.recipe_pip_default_index_url, field_name="recipe_pip_default_index_url"
        )
    extras_raw = extra_index_urls if isinstance(extra_index_urls, (list, tuple)) else []
    if extra_index_urls not in (None, "", []) and not isinstance(
        extra_index_urls, (list, tuple)
    ):
        raise RecipeError(
            code="RECIPE_REGISTRY_INVALID",
            message="extra_index_urls must be a list of http(s) URLs.",
        )
    extras: list[str] = []
    for item in extras_raw:
        normalized = _normalize_index_url(item, field_name="extra_index_urls")
        if normalized and normalized not in extras:
            extras.append(normalized)
    if len(extras) > _MAX_EXTRA_INDEX_URLS:
        raise RecipeError(
            code="RECIPE_REGISTRY_INVALID",
            message=f"At most {_MAX_EXTRA_INDEX_URLS} extra registries are allowed.",
        )
    return EnvSpec(
        python_version=python_version or runtime_python_version(),
        requirements=requirements,
        index_url=normalized_index,
        extra_index_urls=tuple(extras),
    )


# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------


def envs_root() -> Path:
    return Path(settings.recipe_envs_path)


def pip_cache_dir() -> Path:
    return envs_root() / ".pip-cache"


def env_dir(workspace_id: str, fingerprint: str) -> Path:
    return envs_root() / workspace_id / fingerprint


def env_python(workspace_id: str, fingerprint: str) -> Path:
    return env_dir(workspace_id, fingerprint) / "venv" / "bin" / "python"


def _directory_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _tail(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[-max_chars:]


# ---------------------------------------------------------------------------
# Env row lifecycle
# ---------------------------------------------------------------------------


def resolve_env(db: DBSession, *, workspace_id: str, spec: EnvSpec) -> PythonEnv:
    """Get-or-create the PythonEnv row for a spec (no build side effects)."""

    fingerprint = spec.fingerprint()
    env = (
        db.query(PythonEnv)
        .filter(
            PythonEnv.workspace_id == workspace_id,
            PythonEnv.fingerprint == fingerprint,
        )
        .first()
    )
    if env is not None:
        return env
    env = PythonEnv(
        id=str(uuid4()),
        workspace_id=workspace_id,
        fingerprint=fingerprint,
        python_version=spec.python_version,
        requirements_text=spec.requirements_text,
        index_url=spec.index_url,
        extra_index_urls=list(spec.extra_index_urls),
        status="pending",
    )
    db.add(env)
    db.flush()
    return env


def mark_env_used(db: DBSession, env: PythonEnv) -> None:
    env.last_used_at = datetime.utcnow()
    env.use_count = int(env.use_count or 0) + 1


def _pip_install_args(env: PythonEnv, python_bin: Path, requirements_file: Path) -> list[str]:
    args = [
        str(python_bin),
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--cache-dir",
        str(pip_cache_dir()),
        "-r",
        str(requirements_file),
    ]
    if env.index_url:
        args.extend(["--index-url", str(env.index_url)])
    for extra in env.extra_index_urls or []:
        args.extend(["--extra-index-url", str(extra)])
    return args


def _run_build_step(
    args: list[str],
    *,
    log_parts: list[str],
    deadline: float,
) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("recipe env build deadline expired")
    completed = subprocess.run(  # noqa: S603 - fixed binaries, validated args
        args,
        capture_output=True,
        text=True,
        timeout=remaining,
        check=False,
    )
    if completed.stdout:
        log_parts.append(completed.stdout)
    if completed.stderr:
        log_parts.append(completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(
            f"step failed with exit code {completed.returncode}: {' '.join(args[:6])}"
        )


def _claim_env_build(db: DBSession, env_id: str) -> Optional[PythonEnv]:
    """Move one env to ``building`` under a row lock; None when not claimable."""

    env = (
        db.query(PythonEnv)
        .filter(PythonEnv.id == env_id)
        .with_for_update()
        .first()
    )
    if env is None:
        raise RecipeError(
            code="RECIPE_ENV_NOT_FOUND",
            message="The Python environment no longer exists.",
            status_code=404,
        )
    if env.status in {"pending", "evicted", "failed"}:
        env.status = "building"
        env.build_error = None
        db.commit()
        db.refresh(env)
        return env
    db.commit()
    return None


def build_env(db: DBSession, env_id: str) -> PythonEnv:
    """Build (or wait for) one env; returns the row in a settled state.

    Concurrency: the first caller claims ``building`` under a row lock and
    performs the pip work; concurrent callers wait on the status. A crashed
    builder leaves ``building`` behind — the waiter times out and the sweep /
    next explicit build reclaims it via ``reclaim_stale_builds``.
    """

    claimed = _claim_env_build(db, env_id)
    if claimed is None:
        return _wait_for_env(db, env_id)
    return _perform_env_build(db, claimed)


def _wait_for_env(db: DBSession, env_id: str) -> PythonEnv:
    deadline = time.monotonic() + float(settings.recipe_env_build_timeout_s)
    while True:
        db.expire_all()
        env = db.query(PythonEnv).filter(PythonEnv.id == env_id).first()
        if env is None:
            raise RecipeError(
                code="RECIPE_ENV_NOT_FOUND",
                message="The Python environment no longer exists.",
                status_code=404,
            )
        if env.status in {"ready", "failed", "evicted", "pending"}:
            return env
        if time.monotonic() > deadline:
            raise RecipeError(
                code="RECIPE_ENV_BUILD_TIMEOUT",
                message="Timed out waiting for a concurrent environment build.",
                status_code=409,
            )
        time.sleep(1.0)


def _perform_env_build(db: DBSession, env: PythonEnv) -> PythonEnv:
    started = time.monotonic()
    directory = env_dir(env.workspace_id, env.fingerprint)
    venv_dir = directory / "venv"
    log_parts: list[str] = []
    deadline = started + float(settings.recipe_env_build_timeout_s)
    try:
        if venv_dir.exists():
            shutil.rmtree(venv_dir, ignore_errors=True)
        directory.mkdir(parents=True, exist_ok=True)
        pip_cache_dir().mkdir(parents=True, exist_ok=True)
        requirements_file = directory / "requirements.txt"
        # A captured lock wins over the loose spec: the rebuild after an
        # eviction restores the exact same resolved versions.
        install_source = env.lock_text or env.requirements_text or ""
        requirements_file.write_text(install_source, encoding="utf-8")

        _run_build_step(
            [sys.executable, "-m", "venv", str(venv_dir)],
            log_parts=log_parts,
            deadline=deadline,
        )
        python_bin = venv_dir / "bin" / "python"
        if install_source.strip():
            _run_build_step(
                _pip_install_args(env, python_bin, requirements_file),
                log_parts=log_parts,
                deadline=deadline,
            )
        if not env.lock_text:
            freeze = subprocess.run(  # noqa: S603
                [str(python_bin), "-m", "pip", "freeze", "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=max(deadline - time.monotonic(), 5.0),
                check=False,
            )
            if freeze.returncode == 0:
                env.lock_text = freeze.stdout
        env.size_bytes = _directory_size_bytes(directory)
        env.status = "ready"
        env.built_at = datetime.utcnow()
        env.build_duration_ms = (time.monotonic() - started) * 1000
        env.build_error = None
        env.build_log_tail = _tail(
            "".join(log_parts), settings.recipe_execution_log_tail_chars
        )
        db.commit()
        db.refresh(env)
        logger.info(
            "recipe_envs: build ready",
            env_id=env.id,
            fingerprint=env.fingerprint,
            size_bytes=env.size_bytes,
            duration_ms=env.build_duration_ms,
        )
        return env
    except Exception as exc:  # noqa: BLE001 - the row is the failure ledger
        shutil.rmtree(venv_dir, ignore_errors=True)
        env.status = "failed"
        env.size_bytes = 0
        env.build_error = str(exc)[:500]
        env.build_duration_ms = (time.monotonic() - started) * 1000
        env.build_log_tail = _tail(
            "".join(log_parts), settings.recipe_execution_log_tail_chars
        )
        db.commit()
        db.refresh(env)
        logger.warning(
            "recipe_envs: build failed",
            env_id=env.id,
            fingerprint=env.fingerprint,
            error=env.build_error,
        )
        return env


def evict_env(db: DBSession, env: PythonEnv, *, reason: str) -> None:
    """Remove the on-disk venv; the row, spec and lock stay for rebuilds."""

    directory = env_dir(env.workspace_id, env.fingerprint)
    shutil.rmtree(directory, ignore_errors=True)
    env.status = "evicted"
    env.size_bytes = 0
    db.commit()
    logger.info(
        "recipe_envs: evicted",
        env_id=env.id,
        fingerprint=env.fingerprint,
        reason=reason,
    )


def reclaim_stale_builds(db: DBSession, *, older_than_minutes: int = 30) -> int:
    """Reset ``building`` rows whose builder died; returns the reclaim count."""

    threshold = datetime.utcnow() - timedelta(minutes=older_than_minutes)
    stale = (
        db.query(PythonEnv)
        .filter(PythonEnv.status == "building", PythonEnv.updated_at < threshold)
        .all()
    )
    for env in stale:
        env.status = "pending"
        env.build_error = "recipe_env_build_reclaimed"
    if stale:
        db.commit()
    return len(stale)


# ---------------------------------------------------------------------------
# Sweep — storage governor
# ---------------------------------------------------------------------------


def _active_env_ids(db: DBSession) -> set[str]:
    rows = (
        db.query(RecipeExecution.env_id)
        .filter(
            RecipeExecution.status.in_(("queued", "env_building", "running")),
            RecipeExecution.env_id.isnot(None),
        )
        .all()
    )
    return {row[0] for row in rows if row[0]}


def _reconcile_orphan_dirs(db: DBSession) -> int:
    """Remove on-disk env directories whose row is gone or ``evicted``.

    The API containers do not mount the venv store (only the Celery worker
    does), so a manual eviction flips the row without freeing worker-side
    bytes. This pass makes the hourly sweep — and the sweep dispatched right
    after a manual eviction — the disk reconciler. The row status is re-read
    immediately before each removal so a rebuild that just re-claimed
    ``building`` is never raced beyond its own first-step cleanup.
    """

    root = envs_root()
    if not root.exists():
        return 0
    removed = 0
    for workspace_dir in root.iterdir():
        if not workspace_dir.is_dir() or workspace_dir.name.startswith("."):
            continue
        for fingerprint_dir in workspace_dir.iterdir():
            if not fingerprint_dir.is_dir():
                continue
            env = (
                db.query(PythonEnv)
                .filter(
                    PythonEnv.workspace_id == workspace_dir.name,
                    PythonEnv.fingerprint == fingerprint_dir.name,
                )
                .first()
            )
            if env is not None:
                db.refresh(env)
            if env is None or env.status == "evicted":
                shutil.rmtree(fingerprint_dir, ignore_errors=True)
                removed += 1
        try:
            next(workspace_dir.iterdir())
        except StopIteration:
            workspace_dir.rmdir()
        except OSError:
            pass
    return removed


def _cap_pip_cache(max_bytes: int) -> int:
    """Delete oldest pip cache files until under the cap; returns bytes freed."""

    cache = pip_cache_dir()
    if max_bytes <= 0 or not cache.exists():
        return 0
    files: list[tuple[float, int, Path]] = []
    total = 0
    for child in cache.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                stat = child.stat()
                files.append((stat.st_mtime, stat.st_size, child))
                total += stat.st_size
        except OSError:
            continue
    freed = 0
    if total <= max_bytes:
        return 0
    for _mtime, size, path in sorted(files):
        try:
            path.unlink()
        except OSError:
            continue
        freed += size
        if total - freed <= max_bytes:
            break
    return freed


def sweep_envs(db: DBSession) -> dict[str, Any]:
    """One governor pass: TTL eviction, LRU-to-watermark eviction, cache cap."""

    reclaimed = reclaim_stale_builds(db)
    now = datetime.utcnow()
    protected = _active_env_ids(db)
    min_idle = timedelta(minutes=settings.recipe_envs_min_idle_minutes)
    ttl = timedelta(days=settings.recipe_envs_idle_ttl_days)

    ready = (
        db.query(PythonEnv)
        .filter(PythonEnv.status == "ready")
        .order_by(PythonEnv.last_used_at.asc().nullsfirst())
        .all()
    )

    evicted_ttl = 0
    for env in ready:
        anchor = env.last_used_at or env.built_at or env.created_at
        if env.id in protected or anchor is None:
            continue
        if now - anchor > ttl:
            evict_env(db, env, reason="idle_ttl")
            evicted_ttl += 1

    still_ready = [env for env in ready if env.status == "ready"]
    total_bytes = sum(int(env.size_bytes or 0) for env in still_ready)
    evicted_lru = 0
    quota = int(settings.recipe_envs_max_total_bytes)
    watermark = min(int(settings.recipe_envs_low_watermark_bytes), quota)
    if quota > 0 and total_bytes > quota:
        for env in still_ready:
            if total_bytes <= watermark:
                break
            anchor = env.last_used_at or env.built_at or env.created_at
            if env.id in protected:
                continue
            if anchor is not None and now - anchor < min_idle:
                continue
            size = int(env.size_bytes or 0)
            evict_env(db, env, reason="lru_quota")
            total_bytes -= size
            evicted_lru += 1

    orphan_dirs_removed = _reconcile_orphan_dirs(db)
    cache_freed = _cap_pip_cache(int(settings.recipe_pip_cache_max_bytes))
    report = {
        "reclaimed_builds": reclaimed,
        "evicted_ttl": evicted_ttl,
        "evicted_lru": evicted_lru,
        "ready_bytes": total_bytes,
        "orphan_dirs_removed": orphan_dirs_removed,
        "pip_cache_bytes_freed": cache_freed,
    }
    logger.info("recipe_envs: sweep", **report)
    return report


def serialize_env(env: PythonEnv) -> dict[str, Any]:
    return {
        "id": env.id,
        "fingerprint": env.fingerprint,
        "python_version": env.python_version,
        "requirements_text": env.requirements_text or "",
        "has_lock": bool(env.lock_text),
        "index_url": env.index_url,
        "extra_index_urls": list(env.extra_index_urls or []),
        "status": env.status,
        "size_bytes": int(env.size_bytes or 0),
        "build_error": env.build_error,
        "build_log_tail": env.build_log_tail,
        "built_at": env.built_at.isoformat() if env.built_at else None,
        "build_duration_ms": env.build_duration_ms,
        "last_used_at": env.last_used_at.isoformat() if env.last_used_at else None,
        "use_count": int(env.use_count or 0),
        "created_at": env.created_at.isoformat() if env.created_at else None,
    }


def spec_from_params(params: dict[str, Any]) -> EnvSpec:
    """Build the EnvSpec from recipe node params (fail-closed on bad shapes)."""

    return build_env_spec(
        requirements_text=params.get("requirements_text"),
        index_url=params.get("index_url"),
        extra_index_urls=params.get("extra_index_urls"),
    )


__all__ = [
    "EnvSpec",
    "RECIPE_SKILL_SLUG",
    "RecipeError",
    "build_env",
    "build_env_spec",
    "env_dir",
    "env_python",
    "envs_root",
    "evict_env",
    "mark_env_used",
    "normalize_requirements",
    "pip_cache_dir",
    "reclaim_stale_builds",
    "resolve_env",
    "runtime_python_version",
    "serialize_env",
    "spec_from_params",
    "sweep_envs",
]
