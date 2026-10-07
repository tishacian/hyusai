"""Which interpreter fits a model, and which model-family runtimes are listening.

Two facts the plane needs once families train in images of their own:

* **what fitted a row** — the runtime name, the image revision and a digest of
  every installed package, stored on the row (``runtime_json``) and on its
  MLflow run, so "the image that trains has the stack of the one that serves"
  is checked against a record rather than assumed;
* **whether anyone can train a family right now** — an image other than the
  general worker announces itself in ``ml_runtime_heartbeats``; the catalog
  offers a family only while one of its workers was seen recently.
"""

from __future__ import annotations

import hashlib
import os
import platform
import socket
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.services.ml.families.base import Family

GENERAL_RUNTIME = "worker"
# The versions a model artifact's loading depends on, recorded by name. The
# digest covers everything else.
KEY_PACKAGES = (
    "numpy",
    "scipy",
    "pandas",
    "scikit-learn",
    "skrub",
    "skore",
    "skops",
    "mlflow",
    "joblib",
    "pyarrow",
)


@lru_cache(maxsize=1)
def runtime_fingerprint() -> dict[str, Any]:
    """This interpreter's identity; computed once per process."""

    from importlib import metadata

    installed = sorted(
        {
            f"{(dist.metadata['Name'] or '').lower()}=={dist.version}"
            for dist in metadata.distributions()
            if dist.metadata["Name"]
        }
    )
    packages = {}
    for name in KEY_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return {
        "runtime": settings.ml_runtime,
        "image_revision": os.environ.get("AGENTIUM_IMAGE_REVISION") or None,
        "python": platform.python_version(),
        "fingerprint": hashlib.sha256("\n".join(installed).encode()).hexdigest(),
        "packages": packages,
    }


def beat(db: Any, *, queues: list[str], hostname: str | None = None, now: datetime | None = None) -> None:
    """Upsert this worker's heartbeat row (the caller commits)."""

    from app.models.tabular import MLRuntimeHeartbeat

    now = now or datetime.utcnow()
    host = (hostname or socket.gethostname())[:200]
    identity = runtime_fingerprint()
    row = db.get(MLRuntimeHeartbeat, (settings.ml_runtime[:40], host))
    if row is None:
        row = MLRuntimeHeartbeat(runtime=settings.ml_runtime[:40], hostname=host, started_at=now)
        db.add(row)
    row.queues = sorted(set(queues))
    row.image_revision = (identity["image_revision"] or "")[:80] or None
    row.fingerprint = identity["fingerprint"]
    row.packages_json = identity["packages"]
    row.seen_at = now


def family_availability(
    family: Family, db: Any = None, *, now: datetime | None = None
) -> tuple[bool, str | None]:
    """Whether a training request for this family can be served, and why not.

    The general worker runs on every deployment and has always trained the
    tabular family, so a family on it is available without a heartbeat — a
    missed beat must never hide the models that already work. Any other
    runtime has to have been seen on the family's queue within the TTL.
    """

    if not (settings.ml_train_enabled and settings.tabular_data_enabled):
        return False, "disabled"
    if settings.worker_eager_mode:
        missing = family.missing_modules()
        return (False, "runtime_missing") if missing else (True, None)
    if family.runtime == GENERAL_RUNTIME:
        return True, None
    if db is None:
        return False, "no_worker"
    from app.models.tabular import MLRuntimeHeartbeat

    cutoff = (now or datetime.utcnow()) - timedelta(seconds=float(settings.ml_runtime_heartbeat_ttl_s))
    queue = family.train_queue()
    rows = (
        db.query(MLRuntimeHeartbeat)
        .filter(MLRuntimeHeartbeat.runtime == family.runtime, MLRuntimeHeartbeat.seen_at >= cutoff)
        .all()
    )
    if any(queue in (row.queues or []) for row in rows):
        return True, None
    return False, "no_worker"
