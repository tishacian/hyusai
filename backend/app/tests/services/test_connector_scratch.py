"""A reaper must not delete another run's active staging or follow links."""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.services.connectors import scratch


def test_scratch_cleanup_requires_terminal_old_known_run(tmp_path, monkeypatch):
    monkeypatch.setattr(scratch.settings, "connector_scratch_dir", str(tmp_path))
    rows, paths = {}, {}
    for label, status, finished, mtime in [
        ("old", "failed", 100, 100),
        ("active", "running", None, 100),
        ("recent", "succeeded", 950, 100),
        ("touched", "succeeded", 100, 950),
        ("unknown", None, None, 100),
    ]:
        identifier = str(uuid4())
        path = tmp_path / f"agentium-connector-run-{identifier}-test"
        path.mkdir()
        (path / "data").write_text("fixture")
        os.utime(path, (mtime, mtime))
        paths[label] = path
        if status:
            rows[identifier] = SimpleNamespace(
                status=status,
                finished_at=datetime.fromtimestamp(finished, UTC) if finished else None,
            )
    link = tmp_path / f"agentium-connector-run-{next(iter(rows))}-link"
    link.symlink_to(paths["active"], target_is_directory=True)
    other = tmp_path / "unrelated"
    other.mkdir()
    db = SimpleNamespace(get=lambda model, identifier: rows.get(identifier))
    assert scratch.reclaim(db, now=1000) == 1
    assert not paths["old"].exists()
    assert all(path.exists() for key, path in paths.items() if key != "old")
    assert link.is_symlink() and other.exists()
    assert scratch.reclaim(db, now=1000) == 0
