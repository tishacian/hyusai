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


def _create_mock_config():
    """Create a mock Config object with sensible test defaults."""
    from common_config.fsspec_storage import FsspecStorageConfig

    from configurations.components.backend import BackendConfig
    from configurations.components.qdrant import QdrantConfig
    from configurations.components.vlm import VLMConfig

    mock_config = MagicMock()

    # Use actual config classes with defaults
    mock_config.backend = BackendConfig()
    mock_config.vlm = VLMConfig()
    mock_config.storage = FsspecStorageConfig()
    # Explicit QdrantConfig so that connections/qdrant/__init__.py receives
    # typed values (host="localhost", port=6333) rather than auto-MagicMocks.
    mock_config.qdrant = QdrantConfig()

    return mock_config


# Install the mock Config globally before any imports
# This prevents issues with missing environment variables and allows tests to run
# with standard defaults
mock_config_instance = _create_mock_config()
sys.modules["configurations"] = Mock()
sys.modules["configurations"].Config = Mock()
sys.modules["configurations"].Config.get = Mock(return_value=mock_config_instance)


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (deselect with '-m \"not integration\"')",
    )
