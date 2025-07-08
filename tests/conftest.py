"""Pytest configuration to ensure the project root is on `sys.path`.

This lets us `import src.*` without installing the package.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add the project root directory (one level above `tests/`) to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT)) 