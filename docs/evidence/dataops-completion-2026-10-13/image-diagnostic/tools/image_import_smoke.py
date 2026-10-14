"""Offline import check in the release interpreter, never application startup."""

import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='agentium-image-import-') as directory:
        local = Path(directory)
        os.environ.update({
            'AGENTIUM_DISABLE_DOTENV': '1',
            'DATABASE_URL': f'sqlite:///{local / "test_import.db"}',
            'ML_REGISTRY_URI': f'sqlite:///{local / "test_registry.db"}',
            'ML_REGISTRY_ENABLED': 'false',
            'STARTUP_RECONCILIATION': 'disabled',
            'CELERY_BROKER_URL': 'memory://',
            'CELERY_RESULT_BACKEND': 'cache+memory://',
            'REDIS_URL': 'redis://127.0.0.1:9/0',
            'QDRANT_HOST': '127.0.0.1',
            'QDRANT_PORT': '9',
            'QDRANT_TIMEOUT_SECONDS': '0.1',
            'QDRANT_API_KEY': '',
            'OBJECT_STORE_BACKEND': 'local',
            'OBJECT_STORE_BASE_PATH': str(local / 'object-store'),
            'SECURE_DEPOSIT_STORAGE_DIR': str(local / 'secure-deposit'),
            'INTELLIGENCE_SCHEDULER_ENABLED': 'false',
            'RAG_CROSS_ENCODER_PRELOAD': 'false',
            'DATAOPS_ENABLED': 'true',
            'DATAOPS_WRITE_DELTA_ENABLED': 'true',
            'SERVICE_CONTRACTS_ENABLED': 'true',
            'NARRATION_ENABLED': 'false',
            'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1',
            'HF_HOME': str(local / 'hf'),
            'AWS_EC2_METADATA_DISABLED': 'true',
            'OPENAI_API_KEY': '',
            'AZURE_OPENAI_API_KEY': '',
            'GOOGLE_API_KEY': '',
            'GEMINI_API_KEY': '',
            'ANTHROPIC_API_KEY': '',
            'OMP_NUM_THREADS': '1',
            'TOKENIZERS_PARALLELISM': 'false',
            'LOG_LEVEL': 'WARNING',
        })
        blocked_network_events = []

        def deny_network(event, args):
            if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
                blocked_network_events.append(event)
                raise RuntimeError('Network calls are disabled in the image import smoke')

        # The BuildKit RUN also has --network=none. This hook records attempted
        # Python socket activity without logging destinations or credentials.
        sys.addaudithook(deny_network)
        versions = {}
        for distribution, module_name, expected in (
            ('sqlglot', 'sqlglot', '30.22.0'),
            ('deltalake', 'deltalake', '1.6.6'),
            ('arro3-core', 'arro3.core', '0.9.1'),
        ):
            importlib.import_module(module_name)
            actual = importlib.metadata.version(distribution)
            if actual != expected:
                raise RuntimeError(f'{distribution} version does not match the qualified constraint')
            versions[distribution] = actual
        from deltalake import DeltaTable, convert_to_deltalake
        from sqlglot import parse_one

        assert callable(DeltaTable) and callable(convert_to_deltalake)
        assert parse_one('SELECT 1', dialect='duckdb') is not None
        main_module = importlib.import_module('app.main')
        from app.core.config import settings
        from app.db.base import engine
        from fastapi import FastAPI

        assert isinstance(main_module.app, FastAPI)
        assert main_module.app.routes
        assert main_module.orchestrator is None
        assert engine.url.get_backend_name() == 'sqlite'
        assert settings.startup_reconciliation == 'disabled'
        assert settings.celery_broker_url == 'memory://'
        assert settings.object_store_backend == 'local'
        assert not settings.narration_enabled
        engine.dispose()
        print('AGENTIUM_IMAGE_IMPORT_SMOKE=' + json.dumps({
            'status': 'passed',
            'dependencies': versions,
            'python_version': sys.version,
            'runtime_package_versions': {
                name: importlib.metadata.version(name)
                for name in ('fastapi', 'pydantic', 'numpy', 'scipy', 'pandas', 'pyarrow', 'scikit-learn', 'skops', 'torch', 'torchvision')
            },
            'app_main_imported': True,
            'routes': len(main_module.app.routes),
            'lifespan_started': False,
            'database': 'temporary local SQLite',
            'broker': 'memory-only',
            'network': 'BuildKit none; Python socket calls denied',
            'blocked_python_network_attempt_count': len(blocked_network_events),
            'seconds': round(time.monotonic() - started, 3),
            'limit': 'Import and native extension loading only; no HTTP, worker, external service, migration, or lifespan qualification.',
        }, sort_keys=True))


if __name__ == '__main__':
    main()
