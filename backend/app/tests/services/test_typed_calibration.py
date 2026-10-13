"""Persistent human identities and real judge records; transport uses a fixture."""

import copy
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import typed_calibration as api
from app.models.run import Run
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.services import governed_assets as assets
from app.services.evaluation import typed_calibration as calibration
from app.services.evaluation import typed_judge as judge
from app.services.model_plane import execution
from app.services.model_plane.execution import ModelExecution
from app.tests.services import test_service_contracts

setup = test_service_contracts.setup


@pytest.fixture()
def corpus_data(setup):
    s = setup
    units, evidence = [], {}
    for index, partition in enumerate(["dev", "calibration", "calibration", "test", "test"]):
        key = f"segment-{index}"
        text = f"Manual family {index}. This translated segment omits the warning."
        item = {
            "id": "text",
            "kind": "text",
            "text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        asset = assets.register_asset(
            s.db,
            s.workspace.id,
            "document_set",
            key,
            {
                "document_family": f"manual-{index}",
                "source": "showcase-manuals",
                "language": "en-fr",
                "task": "j2450_translation",
                "evidence": [item],
            },
        )
        units.append(
            {
                "key": key,
                "document_family": f"manual-{index}",
                "partition": partition,
                "asset_ref": assets.asset_ref(asset),
            }
        )
        evidence[key] = {**item, "asset_ref": assets.asset_ref(asset)}
    s.db.commit()
    spec = {
        "logical_key": "translation-errors",
        "rubric_id": "j2450",
        "rubric_version": "1",
        "questions": [
            {
                "key": "category",
                "question": "Which J2450 errors occur in the translated segment?",
                "type": "multi_choice",
                "choices": ["WT", "SE", "OM", "SA", "SP", "PE", "ME"],
            }
        ],
        "model": {"provider": "openai", "model": "judge-test", "returned_model": "judge-test"},
        "context": {"source": "showcase-manuals", "language": "en-fr", "task": "j2450_translation"},
        "units": units,
        "policy": {
            "min_calibration_units": 2,
            "min_test_units": 2,
            "min_calibration_families": 2,
            "min_test_families": 2,
            "min_critical_positives": 1,
            "min_precision": 1.0,
            "min_recall": 1.0,
            "max_critical_miss_rate": 0.0,
            "min_coverage": 1.0,
            "min_confidence_lower": 0.2,
            "max_brier": None,
            "max_ece": None,
            "critical_labels": {"category": ["OM"]},
            "numeric_tolerances": {},
        },
    }
    return spec, evidence


def make_corpus(s, data):
    result = calibration.create_corpus(s.db, s.workspace.id, s.owner.id, data)
    s.db.commit()
    return result["asset_ref"]["asset_id"]


def label(s, cid, key, uid=None, values=None, adjudication=False):
    result = calibration.annotate(
        s.db,
        s.workspace.id,
        uid or s.owner.id,
        cid,
        {
            "unit_key": key,
            "values": values or {"category": ["OM"]},
            "outcomes": {},
            "note": "I compared the source and translation; the warning is missing.",
            "adjudication": adjudication,
        },
    )
    s.db.commit()
    return result


async def predict(
    s,
    cid,
    spec,
    evidence,
    key,
    monkeypatch,
    *,
    value=None,
    abstain=False,
    attach=True,
    request_key=None,
):
    source = evidence[key]
    run = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        initiated_by_user_id=s.owner.id,
        status="running",
        input_ref={"evidence": [source]},
    )
    s.db.add(run)
    s.db.commit()

    class Client:
        async def generate(self, **kwargs):
            answer = {
                "status": "abstained" if abstain else "answered",
                "value": None if abstain else value if value is not None else ["OM"],
                "reason": "ambiguous" if abstain else None,
                "explanation": "The supplied segment omits the warning.",
                "evidence": []
                if abstain
                else [
                    {
                        "evidence_id": "text",
                        "start": 0,
                        "end": len(source["text"]),
                        "quote": source["text"],
                    }
                ],
            }
            return {
                "content": json.dumps({"answers": {"category": answer}}),
                "model": "judge-test",
                "usage": {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50},
            }

    monkeypatch.setattr(execution, "build_model_client", lambda *args, **kwargs: Client())
    payload = {
        "batch_key": cid,
        "request_key": request_key or key,
        "subject_ref": key,
        "rubric_id": spec["rubric_id"],
        "rubric_version": spec["rubric_version"],
        "questions": spec["questions"],
        "evidence": [source],
        "budget": {"max_calls": 20, "max_tokens": 500000, "max_cost_usd": 1.0},
        "tariff": {
            "provider": "openai",
            "model": "judge-test",
            "input_per_million": 1.0,
            "output_per_million": 2.0,
            "currency": "USD",
            "reference": "test-only",
        },
    }
    ctx = judge.prepare_typed_judge_context(
        payload,
        {
            "workspace_id": s.workspace.id,
            "user_id": s.owner.id,
            "run_id": run.id,
            "_model_execution": ModelExecution("openai", "judge-test", "workspace", "workspace"),
            "_model_policy_check": lambda candidate: None,
        },
    )
    result = await judge.typed_evaluate(payload, ctx)
    if not attach:
        return result
    calibration.attach_prediction(
        s.db,
        s.workspace.id,
        s.owner.id,
        cid,
        {"unit_key": key, "evaluation_id": result["evaluation_id"]},
    )
    s.db.commit()
    return result


def test_double_annotation_uses_distinct_persisted_identities_and_an_immutable_corpus(
    setup, corpus_data
):
    s = setup
    spec, _ = corpus_data
    cid = make_corpus(s, spec)
    first = label(s, cid, "segment-1")
    assert first["reviewer_user_id"] == s.owner.id
    with pytest.raises(assets.GovernanceError, match="ANNOTATION_IMMUTABLE"):
        label(s, cid, "segment-1")
    label(s, cid, "segment-1", s.member.id)
    report = calibration.report(s.db, s.workspace.id, s.owner.id, cid)
    assert not report["qualified"] and any(
        "PREDICTION_REQUIRED" in reason for reason in report["reasons"]
    )
    assert spec["questions"][0].get("required") is None  # caller draft was not mutated
    assert report["partitions"]["calibration"]["coverage"] == 0
    assert report["partitions"]["calibration"]["missing_units"] == 2


def test_disagreement_requires_third_human_adjudication(setup, corpus_data):
    s = setup
    spec, _ = corpus_data
    cid = make_corpus(s, spec)
    label(s, cid, "segment-1")
    label(s, cid, "segment-1", s.member.id, {"category": ["WT"]})
    report = calibration.report(s.db, s.workspace.id, s.owner.id, cid)
    assert any("ADJUDICATION_REQUIRED" in r for r in report["reasons"])
    third = User(id=str(uuid4()), username="adjudicator-" + uuid4().hex)
    s.db.add(third)
    s.db.flush()
    s.db.add(WorkspaceMember(workspace_id=s.workspace.id, user_id=third.id, role="member"))
    s.db.commit()
    label(s, cid, "segment-1", third.id, adjudication=True)
    report = calibration.report(s.db, s.workspace.id, s.owner.id, cid)
    assert not any("segment-1:CALIBRATION_ADJUDICATION_REQUIRED" in r for r in report["reasons"])


def test_partition_and_family_contamination_are_refused_before_registration(setup, corpus_data):
    s = setup
    spec, _ = corpus_data
    leaked = copy.deepcopy(spec)
    leaked["units"][3]["asset_ref"] = leaked["units"][1]["asset_ref"]
    leaked["units"][3]["document_family"] = leaked["units"][1]["document_family"]
    with pytest.raises(assets.GovernanceError, match="PARTITION_CONTAMINATED"):
        make_corpus(s, leaked)
    make_corpus(s, spec)
    swapped = copy.deepcopy(spec)
    swapped["logical_key"] = "new-test"
    swapped["units"][1]["partition"], swapped["units"][3]["partition"] = "test", "calibration"
    with pytest.raises(assets.GovernanceError, match="TEST_ALREADY_EXPOSED"):
        make_corpus(s, swapped)


async def test_real_predictions_and_human_labels_qualify_only_matching_context_and_model(
    setup, corpus_data, monkeypatch
):
    s = setup
    spec, evidence = corpus_data
    cid = make_corpus(s, spec)
    outputs = []
    for unit in spec["units"][1:]:
        label(s, cid, unit["key"])
        label(s, cid, unit["key"], s.member.id)
        outputs.append(await predict(s, cid, spec, evidence, unit["key"], monkeypatch))
    qualified = calibration.qualify(s.db, s.workspace.id, s.owner.id, cid)
    s.db.commit()
    assert qualified["qualified"] and qualified["partitions"]["test"]["critical_miss_rate"] == 0
    assert qualified["partitions"]["test"]["confidence_brier"] is not None
    report = qualified["partitions"]["calibration"]
    assert report["precision"] == report["recall"] == report["coverage"] == 1
    assert report["confidence_bounds"]["_overall"]["families"] == 2
    result = copy.deepcopy(outputs[0])
    calibration.bind_confidence(s.db, s.workspace.id, s.owner.id, qualified["profile_ref"], result)
    assert result["confidence"] == pytest.approx(calibration.wilson_lower(2, 2))
    assert result["confidence"] < 1 and result["disposition"] == "review"
    for path, value in [
        ("model_execution", {**result["model_execution"], "returned_model": "different"}),
        ("rubric_sha256", "0" * 64),
        ("evaluation_context", {**spec["context"], "language": "de-fr"}),
    ]:
        changed = copy.deepcopy(result)
        changed[path] = value
        calibration.bind_confidence(
            s.db, s.workspace.id, s.owner.id, qualified["profile_ref"], changed
        )
        assert changed["confidence"] is None and "calibration" not in changed
    assets.record_qualification(
        s.db,
        s.workspace.id,
        qualified["profile_ref"],
        status="qualified",
        policy={"human_work_review": True},
        evidence={"reviewer_user_id": s.owner.id},
    )
    calibration.bind_confidence(s.db, s.workspace.id, s.owner.id, qualified["profile_ref"], result)
    assert result["confidence"] is None and "calibration" not in result


async def test_abstention_counts_as_missed_critical_coverage_and_never_qualifies(
    setup, corpus_data, monkeypatch
):
    s = setup
    spec, evidence = corpus_data
    cid = make_corpus(s, spec)
    for unit in spec["units"][1:]:
        label(s, cid, unit["key"])
        label(s, cid, unit["key"], s.member.id)
        await predict(
            s, cid, spec, evidence, unit["key"], monkeypatch, abstain=unit["partition"] == "test"
        )
    result = calibration.qualify(s.db, s.workspace.id, s.owner.id, cid)
    assert not result["qualified"] and "profile_ref" not in result
    assert result["partitions"]["test"]["critical_miss_rate"] == 1
    assert result["partitions"]["test"]["coverage"] == 0


def test_probability_metrics_use_observed_outcomes_and_not_the_judges_own_confidence():
    spec = {
        "questions": [{"key": "event", "type": "probability", "required": True}],
        "policy": {"critical_labels": {}, "numeric_tolerances": {}},
    }
    records = [
        (
            {"document_family": str(n)},
            {"values": {"event": 0.5}, "outcomes": {"event": bool(y)}},
            {"answers": {"event": {"status": "answered", "value": p}}},
        )
        for n, (p, y) in enumerate([(0.8, 1), (0.2, 0)])
    ]
    result = calibration.partition_metrics(spec, records)
    assert result["brier"] == pytest.approx(0.04) and result["ece_10_equal_width"] == pytest.approx(
        0.2
    )
    assert not result["confidence_bounds"]


def test_calibration_api_refuses_forged_reviewer_and_cross_workspace_membership(setup, corpus_data):
    s = setup
    spec, _ = corpus_data
    cid = make_corpus(s, spec)
    app = FastAPI()
    app.include_router(api.router, prefix="/typed-calibration")
    app.dependency_overrides[api.get_db] = lambda: s.db
    app.dependency_overrides[api.get_current_workspace] = lambda: s.workspace
    app.dependency_overrides[api.get_current_user] = lambda: s.member
    client = TestClient(app)
    body = {
        "unit_key": "segment-1",
        "values": {"category": ["OM"]},
        "outcomes": {},
        "note": "Inspected",
        "reviewer_user_id": s.owner.id,
    }
    assert (
        client.post(f"/typed-calibration/corpora/{cid}/annotations", json=body).status_code == 422
    )
    body.pop("reviewer_user_id")
    response = client.post(f"/typed-calibration/corpora/{cid}/annotations", json=body)
    assert response.status_code == 200 and response.json()["reviewer_user_id"] == s.member.id
    assert client.post(f"/typed-calibration/corpora/{cid}/qualify").status_code == 403
    app.dependency_overrides[api.get_current_workspace] = lambda: s.foreign
    assert client.get(f"/typed-calibration/corpora/{cid}").status_code in {403, 404}


def test_generic_asset_registration_cannot_forge_a_human_annotation(setup, corpus_data):
    s = setup
    spec, _ = corpus_data
    cid = make_corpus(s, spec)
    assets.register_asset(
        s.db,
        s.workspace.id,
        "reference",
        "forged-label",
        {
            "type": "typed_calibration_annotation",
            "corpus_id": cid,
            "unit_key": "segment-1",
            "reviewer_user_id": s.owner.id,
            "values": {"category": ["OM"]},
            "outcomes": {},
            "adjudication": False,
        },
    )
    with pytest.raises(assets.GovernanceError, match="QUALIFICATION_REQUIRED"):
        calibration.report(s.db, s.workspace.id, s.owner.id, cid)


async def test_holdout_does_not_allow_cherry_picking_a_second_model_attempt(
    setup, corpus_data, monkeypatch
):
    s = setup
    spec, evidence = corpus_data
    cid = make_corpus(s, spec)
    label(s, cid, "segment-1")
    label(s, cid, "segment-1", s.member.id)
    await predict(s, cid, spec, evidence, "segment-1", monkeypatch, value=["WT"], attach=False)
    second = await predict(
        s, cid, spec, evidence, "segment-1", monkeypatch, attach=False, request_key="retry"
    )
    with pytest.raises(assets.GovernanceError, match="FIRST_ATTEMPT_REQUIRED"):
        calibration.attach_prediction(
            s.db,
            s.workspace.id,
            s.owner.id,
            cid,
            {"unit_key": "segment-1", "evaluation_id": second["evaluation_id"]},
        )


async def test_holdout_labels_created_after_model_prediction_are_not_blind(
    setup, corpus_data, monkeypatch
):
    s = setup
    spec, evidence = corpus_data
    cid = make_corpus(s, spec)
    first = await predict(s, cid, spec, evidence, "segment-1", monkeypatch, attach=False)
    label(s, cid, "segment-1")
    label(s, cid, "segment-1", s.member.id)
    with pytest.raises(assets.GovernanceError, match="HOLDOUT_LABELS_NOT_BLIND"):
        calibration.attach_prediction(
            s.db,
            s.workspace.id,
            s.owner.id,
            cid,
            {"unit_key": "segment-1", "evaluation_id": first["evaluation_id"]},
        )


def test_unresolved_human_abstention_is_not_a_ground_truth_label(setup, corpus_data):
    s = setup
    spec, _ = corpus_data
    cid = make_corpus(s, spec)
    label(s, cid, "segment-1", values={"category": None})
    label(s, cid, "segment-1", s.member.id, values={"category": None})
    report = calibration.report(s.db, s.workspace.id, s.owner.id, cid)
    assert any("HUMAN_REFERENCE_INCOMPLETE" in reason for reason in report["reasons"])
    assert not report["qualified"]
