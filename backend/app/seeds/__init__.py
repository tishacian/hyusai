"""Scripted demo content: what the demo and pilot workspaces are seeded with.

ADR 0003 files this content as ``demo`` and moves it here, out of the
services. A service may read a seed module, for a fixture or a fallback; it
never carries the content itself. The tenant-neutral contract enforces it:
a ``demo`` entry lives under ``app/seeds/`` unless it is declared as the
scenario of a product pack.
"""
