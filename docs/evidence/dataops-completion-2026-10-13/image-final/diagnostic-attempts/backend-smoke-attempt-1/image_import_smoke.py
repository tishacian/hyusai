"""Offline imports and bounded real previews in the release interpreter."""

import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4


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
        preview_child_launches = []

        def deny_network(event, args):
            if event == 'subprocess.Popen':
                command = args[1]
                if isinstance(command, (tuple, list)) and any(str(part).endswith('/dataops/preview_runner.py') for part in command):
                    preview_child_launches.append(True)
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

        # Exercise the public compiler and persisted-sample preview boundary.
        # No SQL reimplementation, lifespan, broker, or external service is used.
        import pyarrow as pa
        import pyarrow.parquet as pq
        from app.schemas.data_prep import DataPrepSpec
        from app.services.dataops.compiler import compile_prep
        from app.services.dataops.preview import preview
        from app.services.dataops.preview_runner import NATIVE_RESERVE_MB
        from app.services.dataops.storage import file_digest
        from app.services.dataops.types import describe
        from app.services.object_store import get_object_store

        assert settings.dataops_preview_memory_mb == 512
        assert settings.dataops_preview_timeout_s == 5
        preview_started = time.monotonic()
        table = pa.table({'n': [1, 2], 'label': ['alpha', None]})
        source = local / 'sample.parquet'
        pq.write_table(table, source)
        workspace_id = uuid4().hex
        key = f'workspaces/{workspace_id}/image-smoke/sample.parquet'
        get_object_store().write_file(key, source)
        dataset = SimpleNamespace(
            id=uuid4().hex, workspace_id=workspace_id, version=1, row_count=2,
            lineage_json={'sample': {
                'key': key, 'sha256': file_digest(source),
                'method': 'reservoir_seeded', 'version': 1,
            }},
        )

        def execute_preview(expression):
            spec = DataPrepSpec(
                operation='prepare',
                steps=[{'id': 'formula', 'action': 'formula',
                        'params': {'output': 'value', 'expression': expression}}],
                outputs=[{'name': 'Image smoke'}],
            )
            compiled = compile_prep(
                spec, {'in': describe(table.schema)}, arrow_schemas={'in': table.schema},
            )
            return preview(compiled, {'in': dataset}, spec, limit=2)

        initial_launches = len(preview_child_launches)
        first = execute_preview('n*2')
        assert [row['value'] for row in first['rows']] == [2, 4]
        assert first['cache_hit'] is False
        refused = None
        try:
            execute_preview("lpad('x',1000000000,'x')")
        except ValueError as exc:
            refused = str(exc)
        assert refused == 'DATAPREP_PREVIEW_MEMORY_LIMIT', 'Expansion did not produce the expected closed memory refusal'
        recovered = execute_preview('n*3')
        assert [row['value'] for row in recovered['rows']] == [3, 6]
        assert recovered['cache_hit'] is False
        launches = len(preview_child_launches) - initial_launches
        assert launches == 3, 'Each preview must start a fresh bounded child'
        preview_check = {
            'status': 'passed',
            'compiler': 'app.services.dataops.compiler.compile_prep',
            'execution': 'app.services.dataops.preview.preview',
            'ordinary_before': {'status': 'passed', 'rows': len(first['rows']), 'cache_hit': first['cache_hit']},
            'expansion': {'status': 'refused', 'code': refused},
            'different_ordinary_after': {'status': 'passed', 'rows': len(recovered['rows']), 'cache_hit': recovered['cache_hit']},
            'fresh_child_launches_observed': launches,
            'configured_duckdb_memory_mb': settings.dataops_preview_memory_mb,
            'configured_native_reserve_mb': NATIVE_RESERVE_MB,
            'configured_child_address_space_bytes': (settings.dataops_preview_memory_mb + NATIVE_RESERVE_MB) * 1024**2,
            'configured_timeout_seconds': settings.dataops_preview_timeout_s,
            'seconds': round(time.monotonic() - preview_started, 3),
        }
        print('AGENTIUM_IMAGE_IMPORT_SMOKE=' + json.dumps({
            'status': 'passed',
            'dependencies': versions,
            'python_version': sys.version,
            'runtime_package_versions': {
                name: importlib.metadata.version(name)
                for name in ('fastapi', 'pydantic', 'numpy', 'scipy', 'pandas', 'pyarrow', 'scikit-learn', 'skops', 'torch', 'torchvision')
            },
            'app_main_imported': True,
            'isolated_preview': preview_check,
            'routes': len(main_module.app.routes),
            'lifespan_started': False,
            'database': 'temporary local SQLite',
            'broker': 'memory-only',
            'network': 'BuildKit none; Python socket calls denied',
            'blocked_python_network_attempt_count': len(blocked_network_events),
            'seconds': round(time.monotonic() - started, 3),
            'limit': 'Imports, native extension loading, and three bounded real sample previews only; no HTTP, worker task, external service, migration, or lifespan qualification.',
        }, sort_keys=True))


if __name__ == '__main__':
    main()
