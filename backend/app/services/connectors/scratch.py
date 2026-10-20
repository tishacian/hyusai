"""Reclaim only expired connector staging directories left by lost processes."""

import re
import shutil
import time
from datetime import UTC
from pathlib import Path

from app.core.config import settings
from app.models.compute_run import ComputeRun
from app.services.compute_runs import TERMINAL_STATUSES

NAME = re.compile(r"^agentium-connector-run-([a-f0-9-]{36})-[a-zA-Z0-9_]+$")


def reclaim(db, *, now=None):
    root = Path(settings.connector_scratch_dir)
    if not root.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - 600
    count = 0
    for path in root.iterdir():
        match = NAME.fullmatch(path.name)
        try:
            if not match or path.is_symlink() or not path.is_dir() or path.stat().st_mtime > cutoff:
                continue
        except FileNotFoundError:
            # A live worker's finally block may win this race.
            continue
        run = db.get(ComputeRun, match[1])
        if run is None or run.status not in TERMINAL_STATUSES:
            continue
        if not run.finished_at or run.finished_at.replace(tzinfo=UTC).timestamp() > cutoff:
            continue
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            continue
        count += 1
    return count
