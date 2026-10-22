"""A readable annotation workflow never reuses exposed cases as blind truth."""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest

from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.services import governed_assets as assets
from app.services.evaluation import typed_calibration as calibration
from app.tests.services import test_typed_calibration as existing

setup = existing.setup
corpus_data = existing.corpus_data


def test_list_corpora_respects_workspace_and_source_visibility(setup, corpus_data, monkeypatch):
    s = setup
    cid = existing.make_corpus(s, corpus_data[0])
    listed = calibration.list_corpora(s.db, s.workspace.id, s.owner.id)
    assert listed["total"] == 1 and listed["items"][0]["id"] == cid
    assert listed["items"][0]["unit_count"] == 5
    assert "spec" not in listed["items"][0]
    with pytest.raises(assets.GovernanceError):
        calibration.list_corpora(s.db, s.foreign.id, s.owner.id)
    monkeypatch.setattr(calibration, "_access", lambda *args, **kwargs: lambda kind, row: False)
    assert calibration.list_corpora(s.db, s.workspace.id, s.owner.id)["items"] == []


def test_annotation_reader_is_blind_and_preserves_independent_humans(setup, corpus_data):
    s = setup
    spec = deepcopy(corpus_data[0])
    spec["questions"][0]["acceptable_values"] = []
    cid = existing.make_corpus(s, spec)
    index = calibration.review_units(s.db, s.workspace.id, s.owner.id, cid)
    assert index["total"] == len(spec["units"])
    assert index["items"] == [
        {key: unit[key] for key in ("key", "document_family", "partition")}
        for unit in spec["units"]
    ]
    assert not {"acceptable_values", "questions", "predictions", "gold", "answers"}.intersection(
        index
    )
    first = calibration.review_unit(s.db, s.workspace.id, s.owner.id, cid, "segment-1")
    assert first["can_annotate"] and first["own_annotation"] is None
    assert first["evidence"][0]["text"]
    assert "acceptable_values" not in first["questions"][0]
    assert not {"predictions", "gold", "answers", "evaluation_id"}.intersection(first)
    existing.label(s, cid, "segment-1")
    own = calibration.review_unit(s.db, s.workspace.id, s.owner.id, cid, "segment-1")
    assert not own["can_annotate"] and own["own_annotation"]["id"]
    other = calibration.review_unit(s.db, s.workspace.id, s.member.id, cid, "segment-1")
    assert other["can_annotate"] and other["annotation_count"] == 1
    assert "values" not in json.dumps(other)
    existing.label(s, cid, "segment-1", s.member.id, values={"category": ["WT"]})
    own = calibration.review_unit(s.db, s.workspace.id, s.owner.id, cid, "segment-1")
    assert own["adjudication_required"] and not own["can_adjudicate"]


def exported_case(s, text="Customer proof retained before evaluation"):
    evidence = {
        "id": "source",
        "kind": "text",
        "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    run = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        system_id=s.system.id,
        initiated_by_user_id=s.owner.id,
        status="failed",
        input_ref={"evidence": [evidence]},
    )
    s.db.add(run)
    s.db.flush()
    identifier = str(uuid4())
    typed = {
        "schema_version": 2,
        "evaluation_id": identifier,
        "status": "failed",
        "quality_status": "unassessed",
        "rubric_id": "claims",
        "rubric_version": "1",
        "rubric_sha256": "a" * 64,
        "evidence": [{key: value for key, value in evidence.items() if key != "text"}],
        "answers": {"secret": "MODEL PREDICTION MUST NOT BECOME GOLD"},
        "questions": [],
        "coverage": {},
    }
    s.db.add(
        EvaluationScore(
            id=identifier,
            workspace_id=s.workspace.id,
            run_id=run.id,
            metadata_={"source": "evaluate_v2", "typed_evaluation": typed},
        )
    )
    s.db.commit()
    body = {
        "evaluation_id": identifier,
        "logical_key": "claim",
        "document_family": "claims-1",
        "source": "support",
        "language": "fr",
        "task": "typed_questions",
    }
    result = calibration.create_case_from_evaluation(s.db, s.workspace.id, s.owner.id, body)
    s.db.commit()
    return result, run, body


def test_export_freezes_original_evidence_not_model_answers_and_is_dev_only(setup):
    s = setup
    result, run, body = exported_case(s)
    before = deepcopy(run.input_ref)
    case = assets.resolve_asset_ref(s.db, s.workspace.id, result["asset_ref"])
    assert result["eligible_partitions"] == ["dev"]
    assert case.manifest_json["source"] == "support"
    assert case.manifest_json["document_family"] == "claims-1"
    assert case.manifest_json["evidence"] == before["evidence"]
    assert "MODEL PREDICTION" not in json.dumps(case.manifest_json)
    assert run.input_ref == before
    assert not s.db.query(EvaluationScore).count() > 1  # export calls no Judge
    repeated = calibration.create_case_from_evaluation(s.db, s.workspace.id, s.owner.id, body)
    assert repeated["asset_ref"] == result["asset_ref"]


def test_exported_or_copied_exposed_bytes_cannot_enter_a_holdout(setup, corpus_data):
    s = setup
    exported, _, _ = exported_case(s)
    spec = deepcopy(corpus_data[0])
    case = assets.resolve_asset_ref(s.db, s.workspace.id, exported["asset_ref"])
    # Context agrees but the exposed-case marker still refuses a test partition.
    spec["context"] = exported["context"]
    spec["units"][0] = {
        "key": exported["unit_key"],
        "asset_ref": exported["asset_ref"],
        "document_family": exported["document_family"],
        "partition": "test",
    }
    with pytest.raises(assets.GovernanceError, match="CASE_ALREADY_EXPOSED"):
        calibration.create_corpus(s.db, s.workspace.id, s.owner.id, spec)
    # A new asset identity with the same bytes may not erase prior exposure.
    original = deepcopy(corpus_data[0])
    unit = original["units"][3]
    copied = assets.register_asset(
        s.db,
        s.workspace.id,
        "reference",
        "copy-of-exposed",
        {
            **original["context"],
            "document_family": unit["document_family"],
            "evidence": case.manifest_json["evidence"],
        },
    )
    original["units"][3] = {**unit, "asset_ref": assets.asset_ref(copied)}
    s.db.commit()
    with pytest.raises(assets.GovernanceError, match="CASE_ALREADY_EXPOSED"):
        calibration.create_corpus(s.db, s.workspace.id, s.owner.id, original)


def test_export_rechecks_evidence_access_and_does_not_accept_a_foreign_record(setup):
    s = setup
    _, run, body = exported_case(s)
    run.input_ref = {"evidence": []}
    s.db.commit()
    with pytest.raises(assets.GovernanceError, match="EVIDENCE_UNAVAILABLE"):
        calibration.create_case_from_evaluation(s.db, s.workspace.id, s.owner.id, body)
    body["evaluation_id"] = str(uuid4())
    with pytest.raises(assets.GovernanceError, match="EVALUATION_NOT_FOUND"):
        calibration.create_case_from_evaluation(s.db, s.workspace.id, s.owner.id, body)
