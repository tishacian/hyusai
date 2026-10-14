"""Showcase seeds preserve draft truth; benchmarks execute actual native workers."""

import copy
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import polars as pl
import pytest

from app.core.config import settings
from app.models.decision import Decision
from app.models.run import Run
from app.models.service_contract import ServiceContract
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import governed_assets as assets
from app.services import service_promises
from app.services.object_store import get_object_store
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.tabular_datasets import register_frame
from app.tests.ml_artifacts import churn_frame, fit_churn_artifact
from app.tests.services.test_ml_predict import _register
from scripts import benchmark_dataops_showcase as bench
from scripts import dataops_watchdog as watchdog
from scripts import seed_dataops_showcase as showcase


@pytest.fixture()
def setup(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "narration_enabled", False)
    monkeypatch.setattr(settings, "dataops_enabled", True)
    monkeypatch.setattr(settings, "ml_score_streaming_enabled", True)
    workspace = Workspace(
        id=str(uuid4()),
        name="Showcase",
        slug="dataops-" + uuid4().hex,
        settings={"showcase_seed": True},
    )
    owner = User(id=str(uuid4()), username="dataops-" + uuid4().hex, is_active=True)
    db_session.add_all([workspace, owner])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    required = {"data_prep_v1", "ml_batch_score_v1", "narration_run_v1", "evaluate_v2"}
    for definition in SEED_SKILLS:
        if (
            definition["slug"] in required
            and not db_session.query(Skill).filter_by(slug=definition["slug"]).first()
        ):
            keys = {column.name for column in Skill.__table__.columns}
            db_session.add(
                Skill(
                    **{
                        key: copy.deepcopy(value)
                        for key, value in definition.items()
                        if key in keys
                    }
                )
            )
    db_session.commit()
    return workspace, owner


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    return fit_churn_artifact(tmp_path_factory.mktemp("showcase-fit"))


def test_missing_configuration_stays_draft_and_replay_creates_no_facts(db_session, setup):
    workspace, owner = setup
    first = showcase.seed(db_session, workspace_id=workspace.id, owner_user_id=owner.id)
    second = showcase.seed(
        db_session, workspace_id=workspace.id, owner_user_id=owner.id, publish_services=True
    )
    assert [value["contract_id"] for value in first["workloads"]] == [
        value["contract_id"] for value in second["workloads"]
    ]
    assert all(not row["ready"] and not row["published"] for row in second["workloads"])
    assert second["deferred_workloads"] == ["narration-500"]
    assert (
        db_session.query(System).filter_by(workspace_id=workspace.id, status="draft").count() == 2
    )
    assert db_session.query(SystemVersion).filter_by(workspace_id=workspace.id).count() == 0
    assert db_session.query(ServiceContract).filter_by(workspace_id=workspace.id).count() == 2
    assert db_session.query(Run).filter_by(workspace_id=workspace.id).count() == 0
    assert db_session.query(Decision).filter_by(workspace_id=workspace.id).count() == 0
    for system in db_session.query(System).filter_by(workspace_id=workspace.id):
        draft = db_session.get(SystemFlowDraft, system.id)
        slugs = [
            node.get("config", {}).get("skill_slug") for node in draft.flow_definition["nodes"]
        ]
        assert slugs[1:3] in [
            ["data_prep_v1", "ml_batch_score_v1"],
            ["narration_run_v1", "evaluate_v2"],
        ]
        assert system.published_flow_version_id is None


def test_seed_requires_actual_admin_owner_and_structural_workspace(db_session, setup):
    workspace, owner = setup
    with pytest.raises(ValueError):
        showcase.seed(db_session, workspace_id=workspace.id, owner_user_id=str(uuid4()))
    workspace.settings = {}
    db_session.commit()
    with pytest.raises(RuntimeError, match="structurally"):
        showcase.seed(db_session, workspace_id=workspace.id, owner_user_id=owner.id)


def test_seed_does_not_overwrite_operator_draft(db_session, setup):
    workspace, owner = setup
    result = showcase.seed(db_session, workspace_id=workspace.id, owner_user_id=owner.id)
    draft = db_session.get(SystemFlowDraft, result["workloads"][0]["system_id"])
    draft.updated_by = owner.id
    draft.flow_definition = {**draft.flow_definition, "operator_annotation": "keep"}
    draft.flow_sha256 = showcase.canonical_flow_sha256(draft.flow_definition)
    db_session.commit()
    again = showcase.seed(db_session, workspace_id=workspace.id, owner_user_id=owner.id)
    assert "OPERATOR_DRAFT_PRESERVED" in again["workloads"][0]["reasons"]
    assert (
        db_session.get(SystemFlowDraft, draft.system_id).flow_definition["operator_annotation"]
        == "keep"
    )


@pytest.mark.parametrize("malformed", [False, True])
def test_narration_draft_explains_image_route_and_malformed_source(
    db_session, setup, monkeypatch, malformed
):
    workspace, owner = setup
    monkeypatch.setattr(settings, "narration_enabled", True)
    content = b"actual source image fixture"
    key = f"workspaces/{workspace.id}/sources/image.bin"
    get_object_store().write_once(key, content)
    sha = hashlib.sha256(content).hexdigest()
    manifest = {
        "objects": [{"key": key, "sha256": sha, "size_bytes": len(content)}],
        "units": [
            "invalid"
            if malformed
            else {"id": "one", "kind": "image", "object_key": key, "sha256": sha}
        ],
        "evidence": [{"id": "one", "kind": "image", "sha256": sha, "locator": {"object_key": key}}],
    }
    source = assets.register_asset(
        db_session, workspace.id, "document_set", "showcase-source", manifest
    )
    db_session.commit()
    monkeypatch.setattr(showcase, "WORKLOADS", (("narration-500", 1),))
    result = showcase.seed(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=owner.id,
        source_ref=assets.asset_ref(source),
        publish_services=True,
    )
    entry = result["workloads"][0]
    assert not entry["published"] and not entry["ready"]
    assert "JUDGE_IMAGE_VISION_ROUTE_REQUIRED" in entry["reasons"]
    if malformed:
        assert "NARRATION_SOURCE_UNITS_INVALID" in entry["reasons"]


def test_ready_scoring_publishes_real_compiled_flow_and_versioned_service(
    db_session, setup, artifact, monkeypatch
):
    workspace, owner = setup
    model = _register(db_session, workspace, artifact)
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="True source",
        frame=pl.from_pandas(churn_frame(20).drop(columns=["churn"])),
    )
    db_session.commit()
    monkeypatch.setattr(showcase, "WORKLOADS", (("scoring-2m", 20),))
    report = showcase.seed(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=owner.id,
        model_id=model.id,
        dataset_id=dataset.id,
        publish_services=True,
    )
    entry = report["workloads"][0]
    assert entry["ready"] and entry["published"]
    system = db_session.get(System, entry["system_id"])
    version = db_session.get(SystemVersion, system.published_flow_version_id)
    assert version.execution_contract["ingresses"][0]["kind"] == "schedule"
    score = next(node for node in version.flow_definition["nodes"] if node["id"] == "score")
    assert score["config"]["params"]["pinned_version"] == model.version
    assert (
        db_session.get(ServiceContract, entry["contract_id"]).definition_json["output_policy"][
            "require_human_review"
        ]
        is True
    )
    repeated = showcase.seed(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=owner.id,
        model_id=model.id,
        dataset_id=dataset.id,
        publish_services=True,
    )
    assert repeated["workloads"][0]["contract_id"] == entry["contract_id"]
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 1


@pytest.mark.skipif(
    sys.platform != "linux", reason="Process-tree RSS sampling requires Linux /proc"
)
def test_benchmark_uses_real_preparation_and_native_model(db_session, setup, artifact):
    workspace, owner = setup
    model = _register(db_session, workspace, artifact)
    rows = int(os.environ.get("AGENTIUM_VOLUME_BENCHMARK_ROWS", "4096"))
    extras = int(os.environ.get("AGENTIUM_VOLUME_BENCHMARK_EXTRA_COLUMNS", "2"))
    destination = os.environ.get("AGENTIUM_VOLUME_BENCHMARK_REPORT")
    result = bench.benchmark(
        db_session,
        workspace_id=workspace.id,
        owner_user_id=owner.id,
        model_id=model.id,
        synthetic_input=True,
        rows=rows,
        extra_columns=extras,
        varied_inputs=os.environ.get("AGENTIUM_VOLUME_BENCHMARK_VARIED", "1") == "1",
        progress_path=destination + ".progress.json" if destination else None,
    )
    assert result["cardinality"] == {"expected": rows, "processed": rows, "excluded": 0}
    assert result["synthetic_input"] is True and result["business_quality_claim"] is False
    assert result["output"]["format"] == "delta" and result["output"]["part_count"] >= 1
    assert result["memory"]["peak_tree_sampled_rss_bytes"] > 0
    assert result["phases"]["preparation_seconds"] > 0 and result["phases"]["scoring_seconds"] > 0
    assert result["input"]["column_count"] == result["prepared"]["column_count"] == 4 + extras
    assert result["output"]["column_count"] > result["prepared"]["column_count"]
    if destination:
        Path(destination).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def test_varied_generator_is_reproducible_independent_of_batch_boundaries(monkeypatch):
    from types import SimpleNamespace

    import pyarrow as pa

    model = SimpleNamespace(input_example_json=[{"a": 1.0}, {"a": 10.0}])
    monkeypatch.setattr(bench, "contract_fields", lambda model: [{"name": "a"}])

    def generate(size):
        schema, batches = bench.synthetic_batches(
            model, 1001, size, extra_columns=28, varied_inputs=True
        )
        batches = list(batches)
        assert max(batch.num_rows for batch in batches) <= size
        return pa.Table.from_batches(batches, schema=schema)

    first, second = generate(128), generate(300)
    assert first.equals(second)
    assert len(set(first.column("benchmark_extra_00").to_pylist())) == 1001
    assert len(set(first.column("a").to_pylist())) == 1001


def test_external_watchdog_reports_absent_run_and_remains_alert_without_new_incident(
    db_session, setup
):
    workspace, owner = setup
    workspace.settings = {**workspace.settings, "features": {"service_contracts": True}}
    system = System(workspace_id=workspace.id, name="Missing delivery")
    db_session.add(system)
    db_session.commit()
    definition = {"starts_on": "2026-10-13", "ends_on": "2026-10-13", "deadline": "08:00"}
    contract = service_promises.create_contract(
        db_session, workspace.id, system.id, owner.id, definition, created_by=owner.id
    )
    service_promises.publish_contract(db_session, workspace.id, contract.id, user_id=owner.id)
    db_session.commit()
    at = datetime(2026, 10, 13, 9, tzinfo=UTC)
    first = watchdog.watchdog_pass(db_session, workspace_id=workspace.id, at=at)
    second = watchdog.watchdog_pass(db_session, workspace_id=workspace.id, at=at)
    assert first["status"] == second["status"] == "attention"
    assert first["new_incidents"][0]["code"] == "SERVICE_RUN_MISSING"
    assert second["new_incidents"] == [] and second["unresolved_incidents"] == 1
    assert db_session.query(Run).filter_by(workspace_id=workspace.id).count() == 0


def test_watchdog_freshness_detects_absence_and_stale_state(tmp_path):
    path = tmp_path / "watchdog.json"
    at = datetime.now(UTC)
    assert watchdog.check_state(path, at=at)["status"] == "stale"
    watchdog.write_state(path, {"status": "healthy", "observed_at": at.isoformat()})
    assert watchdog.check_state(path, at=at)["status"] == "healthy"
    assert (
        watchdog.check_state(path, at=at + timedelta(minutes=16))["code"]
        == "DATAOPS_WATCHDOG_STALE"
    )
