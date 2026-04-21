"""Canonical Skill Registry — wraps the OmniRAG engine into typed Skills.

The registry is the single source of truth the cockpit calls into.
Every Skill exposes:
  - slug + version  (immutable identity)
  - input_schema / output_schema (typed contract)
  - execution { mode, timeout_ms, retryable, idempotent }
  - pricing
  - certification_level (basic | production | enterprise)

Skills are seeded into the DB on application startup (idempotent upsert)
so the `/skills` endpoint returns them without a separate Alembic-level
data migration. Runtime invocation is wired in phase 6 by `run_engine`.
"""
from .seed import SEED_SKILLS, SEED_CAPABILITIES, seed_skills_and_capabilities
from .wrappers import resolve, bound_slugs, registry_snapshot, runtime_status

__all__ = [
    "SEED_SKILLS",
    "SEED_CAPABILITIES",
    "seed_skills_and_capabilities",
    "resolve",
    "bound_slugs",
    "registry_snapshot",
    "runtime_status",
]
