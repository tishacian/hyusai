"""Hub task wiring and recovery do not depend on an inference image."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app.core.config import settings


def test_hub_image_can_inspect_standard_modules_without_inference_dependencies():
    script = r"""
import io, json, sys
from types import SimpleNamespace
class NoInference:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'torch','transformers','polars','pyarrow','numpy','qdrant_client','openai','django'}:
            raise ModuleNotFoundError('Dependency unavailable in Hub image: ' + name)
sys.meta_path.insert(0, NoInference())
from app.workers.celery_hub import celery_hub
celery_hub.loader.import_default_modules()
from app.services.huggingface.fetch import _inspect_configuration
from app.services.huggingface.registry import run_import
from app.services.huggingface.offline import recover_bundle_jobs
from app.services.huggingface.purge_job import drain_revoked_deployments
content = json.dumps([{'type':'sentence_transformers.base.modules.transformer.Transformer'}]).encode()
store = SimpleNamespace(open=lambda key: io.BytesIO(content))
_inspect_configuration(store, 'hub/modules', 'modules.json', len(content))
print(json.dumps(sorted(task for task in celery_hub.tasks if task.startswith('agentium.hf_'))))
"""
    root = Path(__file__).resolve().parents[4]
    env = {**os.environ, "PYTHONPATH": str(root / "backend"), "DATABASE_URL": "sqlite:///:memory:"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    tasks = json.loads(result.stdout)
    assert "agentium.hf_import" in tasks and "agentium.hf_recover" in tasks
    assert "agentium.hf_dataset_materialize" not in tasks


def test_recovery_warns_and_continues_cleanup_when_broker_is_unavailable(
    db_session, monkeypatch, tmp_path, caplog
):
    import shutil

    from app.services.huggingface import activation, offline, registry
    from app.workers.hub_fetch import recover_imports

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    monkeypatch.setattr(settings, "hf_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "hf_disk_min_free_bytes", 10)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=5, used=95, total=100))
    checks = []

    def unavailable(db):
        raise RuntimeError("Broker is not available")

    monkeypatch.setattr(registry, "recover_imports", unavailable)
    monkeypatch.setattr(activation, "recover_activations", lambda db: checks.append("activation"))
    monkeypatch.setattr(offline, "recover_bundle_jobs", lambda db: checks.append("bundle"))
    result = recover_imports.run()
    assert checks == ["activation", "bundle"]
    assert result["failures"] == 1 and result["disk_free_bytes"] == 5
    assert result["abandoned_uploads"] == result["abandoned_sources"] == 0
    warning = next(row for row in caplog.records if "HF_DISK_PRESSURE" in row.message)
    assert warning.free_bytes == 5 and warning.used_percent == 95.0


def test_beat_and_task_routes_keep_acquisition_on_its_dedicated_queue():
    from app.workers.celery_app import celery_app
    from app.workers.celery_hub import celery_hub

    periodic = celery_app.conf.beat_schedule["hf-import-recovery-60s"]
    assert periodic["schedule"] == 60.0 and periodic["options"]["queue"] == "hub_fetch"
    assert celery_app.amqp.router.route({}, "agentium.hf_import")["queue"].name == "hub_fetch"
    assert (
        celery_hub.amqp.router.route({}, "agentium.hf_dataset_materialize")["queue"].name
        == settings.celery_task_default_queue
    )
