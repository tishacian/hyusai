"""Published scheduled Flow -> real workers/model -> human Work receipt/export.

No Skill, provider, HANA, execution output, or prediction is replaced by a stub.
Only runtime deployment settings use local ObjectStore and eager worker dispatch.
"""

import copy
import hashlib
import json
import zipfile
from datetime import datetime

import polars as pl
import pytest

from app.core.config import settings
from app.models.recipe import RecipeExecution
from app.models.run import Run, SkillInvocation
from app.models.service_contract import AssetVersion, ServiceAttempt, ServiceWindow
from app.models.skill import Skill
from app.models.system_version import SystemVersion
from app.models.tabular import MLPrediction, TabularDataset
from app.schemas.data_prep import DataPrepSpec
from app.services import governed_assets as assets
from app.services import service_engine, service_promises, tabular_predict
from app.services.dataops.asset_lineage import dataset_manifest
from app.services.dataops.exports import receipt_bundle
from app.services.dataops.storage import dataset_digest, is_delta
from app.services.run_engine.dag import execute_run_dag
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.systems import flow_publication
from app.services.tabular_datasets import read_frame, register_frame
from app.tests.ml_artifacts import churn_frame, fit_churn_artifact
from app.tests.services import test_service_contracts
from app.tests.services.test_ml_predict import _register
from scripts import seed_dataops_showcase as seed

setup = test_service_contracts.setup


@pytest.fixture(scope="module")
def trained_artifact(tmp_path_factory):
    # The same production training harness as native serving tests, on 240 rows.
    return fit_churn_artifact(tmp_path_factory.mktemp("published-pipeline-fit"))


async def test_published_scoring_flow_delivers_verified_work_receipt_and_portable_bytes(
    setup, monkeypatch, tmp_path, trained_artifact
):
    s = setup
    for key, value in {
        "object_store_backend": "local",
        "object_store_base_path": str(tmp_path / "store"),
        "worker_eager_mode": True,
        "tabular_data_enabled": True,
        "ml_predict_enabled": True,
        "dataops_enabled": True,
        "ml_score_streaming_enabled": True,
        "dataops_write_delta_enabled": True,
        "dataops_batch_rows": 1024,
    }.items():
        monkeypatch.setattr(settings, key, value)
    s.workspace.settings = {
        **s.workspace.settings,
        "showcase_seed": True,
        "features": {
            **s.workspace.settings["features"],
            "flow_publication_v1": True,
            "flow_v3_dag_authoritative": True,
            "dataops_enabled": True,
            "ml_score_streaming_enabled": True,
        },
    }
    skills = {}
    for definition in SEED_SKILLS:
        if definition["slug"] in {"data_prep_v1", "ml_batch_score_v1"}:
            row = Skill(**copy.deepcopy(definition), is_seeded="Y")
            s.db.add(row)
            skills[row.slug] = row
    s.db.commit()
    tabular_predict.reset_cache()
    try:
        model = _register(s.db, s.workspace, trained_artifact)
        original = pl.from_pandas(churn_frame(5000).drop(columns=["churn"])).with_row_index(
            "row_id"
        )
        source = register_frame(
            s.db, workspace_id=s.workspace.id, name="Showcase pipeline input", frame=original
        )
        s.db.commit()
        first_source_asset = assets.register_asset(
            s.db, s.workspace.id, "dataset", "showcase:pipeline-input", dataset_manifest(source)
        )
        assets.record_qualification(
            s.db,
            s.workspace.id,
            assets.asset_ref(first_source_asset),
            status="qualified",
            policy={"authority": "source_integrity"},
            evidence={},
        )
        expected = tabular_predict.predict_rows(
            s.db, model, original.select(model.features).head(8).to_dicts()
        )["predictions"]
        graph = seed.scoring_flow(skills, "pipeline-test", source, model)
        # Two real preparations exercise implicit single-output routing. A
        # consumer of split outputs must still name the selected branch.
        second_prep = copy.deepcopy(next(n for n in graph["nodes"] if n["id"] == "prepare"))
        second_prep["id"] = "prepare-again"
        second_prep["config"]["params"]["data_prep"]["spec"]["outputs"][0]["name"] += " again"
        # Exercise the editor's canonical configuration beside a migrated legacy node.
        canonical = DataPrepSpec.model_validate(
            second_prep["config"]["params"]["data_prep"]["spec"]
        )
        second_prep["config"]["params"] = {
            "spec": canonical.canonical(),
            "outputs": [output.model_dump() for output in canonical.outputs],
            "sources": [],
            "placement": "local",
        }
        graph["nodes"].insert(2, second_prep)
        next(n for n in graph["nodes"] if n["id"] == "score")["config"]["inputs_map"]["dataset_id"][
            "node_id"
        ] = "prepare-again"
        for edge in graph["edges"]:
            if edge["from"] == "prepare":
                edge["from"] = "prepare-again"
        graph["edges"].append({"from": "prepare", "to": "prepare-again"})
        system = seed._system(
            s.db,
            s.workspace,
            s.owner,
            "pipeline-test",
            graph,
            ["data_prep_v1", "ml_batch_score_v1"],
            skills,
            [],
            True,
        )
        s.db.commit()
        publication = flow_publication.flow_state(s.db, system=system, workspace=s.workspace)
        version = s.db.get(SystemVersion, publication["published"]["version_id"])
        assert publication["published"]["execution_contract_ready"]

        # A newer daily source arrives after publication, with an additional
        # delivery column. Neither a node pin nor yesterday's column projection
        # may shadow the source selected and frozen by this service window.
        original = original.with_columns(pl.lit("current-day").alias("context_day"))
        source = register_frame(
            s.db, workspace_id=s.workspace.id, name="Showcase current daily input", frame=original
        )
        source_asset = assets.register_asset(
            s.db, s.workspace.id, "dataset", "showcase:pipeline-input", dataset_manifest(source)
        )
        assets.record_qualification(
            s.db,
            s.workspace.id,
            assets.asset_ref(source_asset),
            status="qualified",
            policy={"authority": "source_integrity"},
            evidence={},
        )
        original_digest = dataset_digest(source)
        now = datetime.utcnow()
        contract = service_promises.create_contract(
            s.db,
            s.workspace.id,
            system.id,
            s.owner.id,
            {
                "starts_on": now.date().isoformat(),
                "deadline": "23:59",
                "inputs": [
                    {
                        "payload_key": "dataset_id",
                        "kind": "dataset",
                        "logical_key": "showcase:pipeline-input",
                        "representation": "native_id",
                    }
                ],
                "output_schema": {
                    "type": "object",
                    "required": ["dataset_id", "scored_rows"],
                    "properties": {
                        "dataset_id": {"type": "string"},
                        "scored_rows": {"const": 5000},
                    },
                },
                "output_policy": {"require_human_review": True, "destination": "work"},
            },
            created_by=s.owner.id,
            logical_key="published-pipeline",
        )
        service_promises.publish_contract(
            s.db, s.workspace.id, contract.id, user_id=s.owner.id, now=now
        )
        s.db.commit()

        # Real schedule adapter creates the immutable published ingress and outbox.
        # The test consumes its Run directly; no Redis/Celery broker is required.
        tick = service_engine.service_tick(now=now)
        assert tick["fired"] == 1 and tick["incidents"] == 0, tick
        s.db.expire_all()
        window = s.db.query(ServiceWindow).filter_by(contract_id=contract.id).one()
        attempt = s.db.query(ServiceAttempt).filter_by(window_id=window.id).one()
        run = s.db.get(Run, attempt.run_id)
        assert run.published_flow_version_id == version.id
        assert run.execution_contract == version.execution_contract
        assert run.flow_snapshot == version.flow_definition
        assert run.execution_surface == "published_schedule"
        assert run.input_ref["_ingress"]["kind"] == "schedule"
        assert run.input_ref["dataset_id"] == source.id
        assert window.input_snapshot_json["refs"] == [assets.asset_ref(source_asset)]
        assert source_asset.id != first_source_asset.id

        outcome = await execute_run_dag(run.id)
        s.db.expire_all()
        assert run.status == "completed", {
            "outcome": outcome,
            "error": run.error,
            "checkpoints": run.checkpoints,
        }
        invocations = (
            s.db.query(SkillInvocation)
            .filter_by(run_id=run.id)
            .order_by(SkillInvocation.started_at)
            .all()
        )
        assert [call.skill_slug for call in invocations] == [
            "data_prep_v1",
            "data_prep_v1",
            "ml_batch_score_v1",
        ]
        assert all(call.status == "completed" for call in invocations), [
            (call.status, call.error) for call in invocations
        ]
        executions = s.db.query(RecipeExecution).filter_by(run_id=run.id).all()
        assert {row.input_json["kind"] for row in executions} == {"data_prep", "ml_stream_score"}
        assert all(row.status == "succeeded" for row in executions)
        prep = next(row for row in executions if row.node_id == "prepare")
        second_prep_execution = next(row for row in executions if row.node_id == "prepare-again")
        score = next(row for row in executions if row.node_id == "score")
        assert prep.input_json["inputs"] == {"in": source.id}
        assert second_prep_execution.input_json["inputs"] == {"in": prep.output_json["dataset_id"]}
        assert score.input_json["dataset_id"] == second_prep_execution.output_json["dataset_id"]
        assert score.input_json["served_id"] == model.id

        output = s.db.get(TabularDataset, run.output_ref["dataset_id"])
        actual = read_frame(output).sort("row_id")
        assert actual.height == 5000 and actual.select(original.columns).equals(original)
        assert actual["prediction"].head(8).to_list() == [
            str(row["prediction"]) for row in expected
        ]
        assert output.run_id == run.id and is_delta(output)
        assert dataset_digest(source) == original_digest
        journal = s.db.get(MLPrediction, score.output_json["prediction_id"])
        assert journal.row_count == 5000 and len(journal.output_json) <= 64

        assert service_engine.reconcile_runs(s.db, s.workspace, now=datetime.utcnow()) == 1
        s.db.commit()
        s.db.refresh(window)
        assert window.status == "awaiting_review"
        candidate = assets.resolve_asset_ref(s.db, s.workspace.id, window.candidate_ref)
        qualification = assets.current_qualification(s.db, s.workspace.id, candidate.id)
        assert qualification.status == "review_required" and candidate.run_id == run.id
        assert candidate.manifest_json["producer"]["flow_version_id"] == version.id
        assert assets.asset_ref(source_asset) in candidate.parents_json
        decision = service_promises.review_delivery(
            s.db,
            s.workspace.id,
            window.id,
            reviewer_user_id=s.owner.id,
            accept=True,
            qualify_candidate=True,
            expected_fence=window.fence,
            expected_asset_digest=candidate.digest,
            expected_qualification_digest=qualification.digest,
            note="Verified all 5,000 identifiers, complete cardinality and native-model outputs in this test corpus.",
        )
        s.db.commit()
        receipt = service_promises.publish_delivery(
            s.db,
            s.workspace.id,
            window.id,
            decision_id=decision.id,
            fence=window.fence,
            lease_token=window.lease_token,
        )
        s.db.commit()
        assert receipt.destination == "work" and receipt.asset_digest == candidate.digest
        assert (
            service_promises.get_receipt(s.db, s.workspace.id, receipt.id, user_id=s.owner.id).id
            == receipt.id
        )
        assert (
            service_promises.publish_delivery(
                s.db,
                s.workspace.id,
                window.id,
                decision_id=decision.id,
                fence=window.fence,
                lease_token=window.lease_token,
            ).id
            == receipt.id
        )

        bundle = receipt_bundle(
            candidate, service_promises.receipt_public(receipt), tmp_path / "delivery.zip"
        )
        with zipfile.ZipFile(bundle) as archive:
            exported = json.loads(archive.read("manifest.json"))
            assert exported["asset_ref"] == assets.asset_ref(candidate)
            assert exported["receipt"]["id"] == receipt.id and exported["objects"]
            for obj in exported["objects"]:
                raw = archive.read(obj["bundle_path"])
                assert len(raw) == obj["size_bytes"]
                assert hashlib.sha256(raw).hexdigest() == obj["sha256"]
        assert (
            s.db.query(AssetVersion).filter_by(workspace_id=s.workspace.id, run_id=run.id).count()
            >= 3
        )
    finally:
        tabular_predict.reset_cache()
