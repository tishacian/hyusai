"""Pytest bootstrap for the SharePoint connector tests.

Scoped locally so they can run without the top-level ``tests/conftest.py``,
which depends on internal Datategy packages that aren't always available in
a fresh dev venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: SharePoint end-to-end smoke tests (need a real tenant).",
    )
