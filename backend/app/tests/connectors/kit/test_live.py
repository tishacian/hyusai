"""Opt-in real bench; normal unit runs never contact a supplier."""

import os

import pytest

from app.services.connectors.certification import required_suites
from app.tests.connectors.kit.live import Bench, load_config


@pytest.fixture(scope="module")
def live_bench():
    config = os.environ.get("AGENTIUM_CONNECTOR_KIT_CONFIG")
    reports = os.environ.get("AGENTIUM_CONNECTOR_KIT_REPORTS")
    if not config or not reports:
        pytest.skip("KIT_OPT_IN_REQUIRED")
    try:
        return Bench(load_config(config), reports)
    except Exception:
        pytest.fail("KIT_PRIVATE_CONFIGURATION_INVALID", pytrace=False)


def test_live_required_suites(live_bench):
    reports = [
        live_bench.run(suite)
        for suite in sorted(
            required_suites(live_bench.profile.capabilities),
            key=lambda value: (value.startswith("outcome:"), value),
        )
    ]
    if any(report.status != "passed" for report in reports) or live_bench.identity is None:
        pytest.fail("KIT_INCOMPLETE_OR_FAILED_SEE_CLOSED_REPORTS", pytrace=False)
