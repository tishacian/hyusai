"""Shared structural validation for content-addressed JUnit evidence."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def junit_count_errors(contract: Mapping[str, Any]) -> tuple[str, ...]:
    """Return fail-closed counter errors for one JUnit contract summary."""

    errors: list[str] = []

    def counter(name: str, *, positive: bool = False) -> int | None:
        value = contract.get(name)
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{name} is not an integer")
            return None
        if value < (1 if positive else 0):
            errors.append(f"{name} is {'not positive' if positive else 'negative'}")
            return None
        return value

    tests = counter("test_count", positive=True)
    failures = counter("failure_count")
    execution_errors = counter("error_count")
    skipped = counter("skipped_count")
    if failures not in (None, 0) or execution_errors not in (None, 0):
        errors.append("JUnit contract is not green")
    if tests is not None and skipped is not None:
        if skipped > tests:
            errors.append("skipped_count exceeds test_count")
        elif tests - skipped <= 0:
            errors.append("JUnit contract has no executed test cases")
    if tests is not None:
        known = [value for value in (failures, execution_errors, skipped) if value is not None]
        if len(known) == 3 and sum(known) > tests:
            errors.append("JUnit outcome counters exceed test_count")
    return tuple(dict.fromkeys(errors))
