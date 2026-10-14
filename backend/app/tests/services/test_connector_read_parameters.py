"""Public read requests reach workers with typed, server-owned checkpoint boundaries."""

import asyncio

import jsonschema
import pytest

from app.models.compute_run import ComputeRun
from app.services import compute_runs
from app.services.connectors.connections import ConnectionError
from app.services.connectors.profiles import get_profile
from app.services.connectors.skill_reads import validate_parameters
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.skills_registry.wrappers import _connector_read_v1
from app.tests.services import test_connection_registry as fixtures


@pytest.fixture()
def setup(db_session, monkeypatch):
    yield from fixtures.setup.__wrapped__(db_session, monkeypatch)


PARAMETERS = {
    "schema": "public",
    "table": "events",
    "columns": ["id", "updated_at"],
    "partitions": {"column": "id", "count": 8},
    "incremental": {
        "watermark_column": "updated_at",
        "key_column": "id",
        "type": "timestamp",
        "overlap": 300,
    },
    "require_consistency": "snapshot",
}


@pytest.mark.parametrize("gateway", ["api", "skill"])
def test_partition_incremental_contract_reaches_registry(db_session, setup, monkeypatch, gateway):
    connection = fixtures.create(db_session, setup)
    monkeypatch.setattr(compute_runs, "dispatch_run", lambda db, row: "test-task")
    if gateway == "api":
        response = fixtures.client(db_session, setup).post(
            f"/connections/{connection.id}/import", json=PARAMETERS
        )
        assert response.status_code == 202, response.text
    else:
        payload = {"connection_id": connection.id, "operation": "import", "parameters": PARAMETERS}
        entry = next(s for s in SEED_SKILLS if s["slug"] == "connector_read_v1")
        jsonschema.validate(payload, entry["input_schema"])
        result = asyncio.run(
            _connector_read_v1(
                payload, {"db": db_session, "workspace_id": setup[0].id, "user_id": setup[2][0].id}
            )
        )
        assert result["status"] == "queued"
    row = db_session.query(ComputeRun).one()
    assert row.input_json == PARAMETERS


@pytest.mark.parametrize(
    "invalid",
    [
        {"after": [123, 456]},
        {"upper": [123, 456]},
        {"partitions": {"column": "id", "count": True}},
        {"partitions": {"column": "id", "count": 33}},
        {"partitions": {"column": "id", "count": 0}},
        {"partitions": {"column": "id", "count": 2, "lower": 0, "upper": 10}},
        {
            "incremental": {
                "watermark_column": "ts",
                "key_column": "id",
                "type": "integer",
                "after": [123, 456],
            }
        },
        {
            "incremental": {
                "watermark_column": "ts",
                "key_column": "id",
                "type": "timestamp",
                "upper": "secret-checkpoint",
            }
        },
        {
            "incremental": {
                "watermark_column": "ts",
                "key_column": "id",
                "type": "integer",
                "overlap": True,
            }
        },
        {"incremental": {"watermark_column": "ts", "key_column": "id", "type": "text"}},
        {"require_consistency": "best_effort"},
    ],
)
def test_api_and_skill_reject_forged_bounds_or_invalid_types_before_queue(
    db_session, setup, monkeypatch, invalid
):
    connection = fixtures.create(db_session, setup)
    monkeypatch.setattr(
        compute_runs, "dispatch_run", lambda *args: pytest.fail("invalid request dispatched")
    )
    response = fixtures.client(db_session, setup).post(
        f"/connections/{connection.id}/import", json=invalid
    )
    assert response.status_code == 400, response.text
    assert "secret-checkpoint" not in response.text
    with pytest.raises(ValueError, match="CONNECTOR_PARAMETERS_INVALID"):
        asyncio.run(
            _connector_read_v1(
                {"connection_id": connection.id, "operation": "import", "parameters": invalid},
                {"db": db_session, "workspace_id": setup[0].id, "user_id": setup[2][0].id},
            )
        )
    assert db_session.query(ComputeRun).count() == 0


def test_advanced_reads_require_capability_and_matching_operation():
    profile = get_profile("postgresql")
    with pytest.raises(ConnectionError, match="CONNECTOR_OPERATION_UNSUPPORTED"):
        validate_parameters(profile, PARAMETERS, operation="preview")
    restricted = profile.model_copy(
        update={"capabilities": profile.capabilities.model_copy(update={"read_partitioned": False})}
    )
    with pytest.raises(ConnectionError, match="CONNECTOR_OPERATION_UNSUPPORTED"):
        validate_parameters(restricted, PARAMETERS, operation="import")
    with pytest.raises(ConnectionError, match="CONNECTOR_PARAMETERS_INVALID"):
        validate_parameters(
            get_profile("s3"), {"partitions": {"column": "id", "count": 2}}, operation="import"
        )
    with pytest.raises(ConnectionError, match="CONNECTOR_PARAMETERS_INVALID"):
        validate_parameters(
            get_profile("mcp"), {"require_consistency": "none"}, operation="preview"
        )
    with pytest.raises(ConnectionError, match="CONNECTOR_CONSISTENCY_UNAVAILABLE"):
        validate_parameters(profile, {"require_consistency": "snapshot"}, operation="catalog")
    assert validate_parameters(
        get_profile("iceberg_rest"), {"require_consistency": "snapshot"}, operation="import"
    ) == {"require_consistency": "snapshot"}
