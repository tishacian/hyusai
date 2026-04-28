"""Pytest configuration to ensure the project root is on `sys.path`.

This lets us `import src.*` without installing the package.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

# Add the project root directory (one level above `tests/`) to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


mock_config_instance = MagicMock()

# Mock configurations so module-level .get() calls (connections/qdrant/__init__.py,
# connections/storage/__init__.py, connections/celery/app.py) never touch real env vars.
_mock_configurations = Mock()
for _cls_name in ("BackendConfig", "WorkerConfig", "FastAPIConfig", "FrontendConfig"):
    _mock_cls = Mock()
    _mock_cls.get = Mock(return_value=mock_config_instance)
    setattr(_mock_configurations, _cls_name, _mock_cls)
sys.modules["configurations"] = _mock_configurations

# Mock external-service singletons so their modules never run real initialization.
# Integration tests patch these with real clients in tests/integration/conftest.py.
_mock_qdrant = Mock()
_mock_qdrant.qdrant_client = MagicMock()
sys.modules["connections.qdrant"] = _mock_qdrant

_mock_storage = Mock()
_mock_storage.fs = MagicMock()
_mock_storage.WORKSPACE_UUID = "a0000000-0000-0000-0000-000000000001"
_mock_storage.BUCKET_FOLDER = "buckets"
_mock_storage.KNOWLEDGE_BASE_FOLDER = "knowledge-bases"
_mock_storage.KB_ORIGINAL_FOLDER = "original"
_mock_storage.KB_INGESTED_FOLDER = "ingested"
_mock_storage.KB_VECTOR_STORE_FOLDER = "vector-store"
sys.modules["connections.storage"] = _mock_storage


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (deselect with '-m \"not integration\"')",
    )
    config.addinivalue_line(
        "markers",
        "benchmark: marks tests as benchmarks that require external services and produce graphs",
    )
