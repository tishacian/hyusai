"""Human annotations and held-out calibration recorded as immutable A1 assets.

No synthetic labels, self-grading, score-to-confidence conversion or automatic
release. Callers own commits. Qualified confidence is a conservative empirical
bound for the declared source/language/model/rubric, not a guarantee per answer.
"""

from __future__ import annotations

import math
from collections import defaultdict

from jsonschema import Draft202012Validator

from app.models.evaluation import EvaluationScore
from app.models.service_contract import AssetVersion
from app.models.workspace import Workspace
from app.schemas.typed_evaluation import (
    CalibrationCorpus,
    CalibrationPrediction,
    HumanAnnotation,
    VisionRouteDefinition,
    VisionRouteQualification,
    compile_question_schema,
)
from app.services import governed_assets as assets
from app.services.service_promises import require_member

Error = assets.GovernanceError
PREFIX = "typed_calibration_"
J2450 = {"WT", "SE", "OM", "SA", "SP", "PE", "ME"}


def _access(db, workspace_id, user_id, *, admin=False):
    user = require_member(db, workspace_id, user_id, admin=admin)
    return assets.native_authorizer(db, db.get(Workspace, workspace_id), user)


def _resolve(db, workspace_id, ref, user_id):
    return assets.resolve_asset_ref(
        db, workspace_id, ref, authorize=_access(db, workspace_id, user_id), verify_objects=False
    )


def _rows(db, workspace_id, kind, corpus_id=None):
    query = (
        db.query(AssetVersion)
        .filter_by(workspace_id=workspace_id, kind="reference")
        .filter(AssetVersion.manifest_json["type"].as_string() == PREFIX + kind)
    )
    if corpus_id:
        query = query.filter(AssetVersion.manifest_json["corpus_id"].as_string() == corpus_id)
    rows = query.order_by(AssetVersion.created_at, AssetVersion.id).all()
    for row in rows:
        _trusted(db, workspace_id, row, kind)
    return rows


def _seal(db, workspace_id, row, kind, user_id):
    """Only server workflow code writes this provenance, never a claimed identity."""
    assets.record_qualification(
        db,
        workspace_id,
        assets.asset_ref(row),
        status="qualified",
        policy={"purpose": PREFIX + "provenance", "kind": kind},
        evidence={"actor_user_id": user_id, "artifact_digest": row.digest},
    )


def _trusted(db, workspace_id, row, kind):
    qualification = assets.validate_qualification(
        assets.current_qualification(db, workspace_id, row.id), row
    )
    actor = (
        row.manifest_json.get("reviewer_user_id")
        if kind == "annotation"
        else row.manifest_json.get("creator_user_id")
    )
    if (
        qualification.policy_json != {"purpose": PREFIX + "provenance", "kind": kind}
        or qualification.evidence_json.get("artifact_digest") != row.digest
        or not actor
        or qualification.evidence_json.get("actor_user_id") != actor
    ):
        raise Error("CALIBRATION_ARTIFACT_PROVENANCE_REQUIRED", 403)


def corpus(db, workspace_id, corpus_id, user_id):
    row = (
        db.query(AssetVersion)
        .filter_by(id=corpus_id, workspace_id=workspace_id, kind="reference")
        .first()
    )
    if row is None or row.manifest_json.get("type") != PREFIX + "corpus":
        raise Error("CALIBRATION_CORPUS_NOT_FOUND", 404)
    _trusted(db, workspace_id, row, "corpus")
    _resolve(db, workspace_id, assets.asset_ref(row), user_id)
    for unit in row.manifest_json["spec"]["units"]:
        _resolve(db, workspace_id, unit["asset_ref"], user_id)
    return row


def _fingerprints(asset):
    manifest = asset.manifest_json
    fingerprints = {"asset:" + asset.digest}
    for item in manifest.get("objects", []):
        fingerprints.add("content:" + item["sha256"])
    for item in manifest.get("evidence", []):
        if isinstance(item, dict):
            if item.get("sha256"):
                fingerprints.add("content:" + item["sha256"])
            elif isinstance(item.get("text"), str):
                import hashlib

                fingerprints.add("content:" + hashlib.sha256(item["text"].encode()).hexdigest())
    return sorted(fingerprints)


def _validate_policy(spec):
    questions = {q.key: q for q in spec.questions}
    if len(questions) != len(spec.questions) or not any(q.required for q in spec.questions):
        raise Error("CALIBRATION_QUESTIONS_INVALID", 422)
    if spec.context.task == "j2450_translation" and not any(
        q.type in {"choice", "multi_choice"} and set(q.choices) == J2450 for q in spec.questions
    ):
        raise Error("CALIBRATION_J2450_TAXONOMY_REQUIRED", 422)
    if not spec.policy.critical_labels:
        raise Error("CALIBRATION_CRITICAL_CRITERIA_REQUIRED", 422)
    for key, labels in spec.policy.critical_labels.items():
        q = questions.get(key)
        allowed = [True, False] if q and q.type == "boolean" else q.choices if q else []
        if not labels or any(
            label not in allowed or type(label) not in {str, bool} for label in labels
        ):
            raise Error("CALIBRATION_CRITICAL_CRITERIA_INVALID", 422)
    for q in spec.questions:
        if q.type == "score" and (
            q.key not in spec.policy.numeric_tolerances
            or not 0 <= spec.policy.numeric_tolerances[q.key] <= q.maximum - q.minimum
        ):
            raise Error("CALIBRATION_NUMERIC_TOLERANCE_REQUIRED", 422)
        if q.type == "probability" and (
            spec.policy.max_brier is None or spec.policy.max_ece is None
        ):
            raise Error("CALIBRATION_PROBABILITY_GATES_REQUIRED", 422)
    if set(spec.policy.numeric_tolerances) - {q.key for q in spec.questions if q.type == "score"}:
        raise Error("CALIBRATION_NUMERIC_TOLERANCE_INVALID", 422)


def _contamination(units):
    partitions = {}
    for unit in units:
        for identity in ["family:" + unit["document_family"], *unit.get("fingerprints", [])]:
            previous = partitions.setdefault(identity, unit["partition"])
            if previous != unit["partition"]:
                raise Error("CALIBRATION_PARTITION_CONTAMINATED")


def create_corpus(db, workspace_id, user_id, data):
    _access(db, workspace_id, user_id, admin=True)
    # Serialize corpus creation so concurrent requests cannot both claim a holdout.
    db.query(Workspace).filter_by(id=workspace_id).with_for_update().one()
    spec = CalibrationCorpus.model_validate(data)
    _validate_policy(spec)
    if len({u.key for u in spec.units}) != len(spec.units):
        raise Error("CALIBRATION_UNIT_KEYS_INVALID", 422)
    units = []
    for unit in spec.units:
        asset = _resolve(db, workspace_id, unit.asset_ref, user_id)
        manifest = asset.manifest_json
        if manifest.get("document_family") != unit.document_family or any(
            manifest.get(k) != v for k, v in spec.context.model_dump().items()
        ):
            raise Error("CALIBRATION_DOCUMENT_CONTEXT_MISMATCH", 422)
        units.append({**unit.model_dump(), "fingerprints": _fingerprints(asset)})
    _contamination(units)
    # Reusing a previously exposed family/content as a new holdout is forbidden.
    for existing in _rows(db, workspace_id, "corpus"):
        if existing.manifest_json["spec"] == spec.model_dump():
            return {"asset_ref": assets.asset_ref(existing), "spec": spec.model_dump()}
        for new in units:
            identities = {"family:" + new["document_family"], *new["fingerprints"]}
            for old in existing.manifest_json["units"]:
                if identities.intersection(
                    {"family:" + old["document_family"], *old["fingerprints"]}
                ) and "test" in {new["partition"], old["partition"]}:
                    raise Error("CALIBRATION_TEST_ALREADY_EXPOSED")
    for partition in ("calibration", "test"):
        group = [u for u in units if u["partition"] == partition]
        if len(group) < getattr(spec.policy, f"min_{partition}_units") or len(
            {u["document_family"] for u in group}
        ) < getattr(spec.policy, f"min_{partition}_families"):
            raise Error("CALIBRATION_CORPUS_INSUFFICIENT", 422)
    # Chunk parents to retain full lineage without exceeding A1's parent cap.
    parents = _bundles(db, workspace_id, spec.logical_key, [u["asset_ref"] for u in units])
    row = assets.register_asset(
        db,
        workspace_id,
        "reference",
        "calibration:" + spec.logical_key,
        {
            "type": PREFIX + "corpus",
            "spec": spec.model_dump(),
            "units": units,
            "creator_user_id": user_id,
            "rubric_sha256": assets.content_digest([q.model_dump() for q in spec.questions]),
        },
        parents,
    )
    _seal(db, workspace_id, row, "corpus", user_id)
    return {"asset_ref": assets.asset_ref(row), "spec": spec.model_dump()}


def _bundles(db, workspace_id, key, refs):
    result = []
    for start in range(0, len(refs), 128):
        group = refs[start : start + 128]
        row = assets.register_asset(
            db,
            workspace_id,
            "reference",
            "calibration-proof:" + assets.content_digest([key, group])[:48],
            {"type": PREFIX + "proof_bundle", "refs": group},
            group,
        )
        result.append(assets.asset_ref(row))
    return result


def _unit(row, key):
    unit = next((u for u in row.manifest_json["spec"]["units"] if u["key"] == key), None)
    if unit is None:
        raise Error("CALIBRATION_UNIT_NOT_FOUND", 404)
    return unit


def _values(spec, annotation):
    schema = compile_question_schema(spec["questions"])["properties"]["answers"]["properties"]
    if set(annotation.values) != set(schema):
        raise Error("CALIBRATION_ANNOTATION_KEYS_INVALID", 422)
    try:
        for key, value in annotation.values.items():
            Draft202012Validator(schema[key]["properties"]["value"]).validate(value)
    except Exception:
        raise Error("CALIBRATION_ANNOTATION_TYPE_INVALID", 422) from None
    for question in spec["questions"]:
        if question["type"] == "multi_choice" and annotation.values[question["key"]] is not None:
            annotation.values[question["key"]] = sorted(annotation.values[question["key"]])
    probability = {q["key"] for q in spec["questions"] if q["type"] == "probability"}
    if set(annotation.outcomes) != probability or not annotation.note.strip():
        raise Error("CALIBRATION_OBSERVED_OUTCOME_REQUIRED", 422)


def annotate(db, workspace_id, user_id, corpus_id, data):
    row = corpus(db, workspace_id, corpus_id, user_id)
    db.query(AssetVersion).filter_by(id=row.id).with_for_update().one()
    annotation = HumanAnnotation.model_validate(data)
    _values(row.manifest_json["spec"], annotation)
    unit = _unit(row, annotation.unit_key)
    saved = [
        r
        for r in _rows(db, workspace_id, "annotation", row.id)
        if r.manifest_json["unit_key"] == annotation.unit_key
    ]
    if any(r.manifest_json["reviewer_user_id"] == user_id for r in saved):
        raise Error("CALIBRATION_ANNOTATION_IMMUTABLE")
    # Labels for a holdout must exist before any prediction is exposed/stored.
    predictions = [
        r
        for r in _rows(db, workspace_id, "prediction", row.id)
        if r.manifest_json["unit_key"] == unit["key"]
    ]
    if predictions and unit["partition"] != "dev":
        raise Error("CALIBRATION_HOLDOUT_ALREADY_PREDICTED")
    if annotation.adjudication:
        if len(saved) != 2 or _annotation_truth(saved[0]) == _annotation_truth(saved[1]):
            raise Error("CALIBRATION_ADJUDICATION_NOT_REQUIRED")
    elif len(saved) >= 2:
        raise Error("CALIBRATION_ADJUDICATION_REQUIRED")
    result = assets.register_asset(
        db,
        workspace_id,
        "reference",
        f"calibration-label:{row.id}:{unit['key'][:40]}:{user_id}",
        {
            "type": PREFIX + "annotation",
            "corpus_id": row.id,
            **annotation.model_dump(),
            "reviewer_user_id": user_id,
            "authority": "authenticated_human",
            "corpus_digest": row.digest,
            "unit_ref": unit["asset_ref"],
        },
        [unit["asset_ref"], *[assets.asset_ref(r) for r in saved]],
    )
    _seal(db, workspace_id, result, "annotation", user_id)
    return {"asset_ref": assets.asset_ref(result), "reviewer_user_id": user_id}


def _annotation_truth(row):
    return {key: row.manifest_json[key] for key in ("values", "outcomes")}


def _gold(annotations):
    if len({r.manifest_json["reviewer_user_id"] for r in annotations}) < 2:
        raise Error("CALIBRATION_DOUBLE_ANNOTATION_REQUIRED")
    regular = [r for r in annotations if not r.manifest_json["adjudication"]]
    if len(regular) != 2 or len({r.manifest_json["reviewer_user_id"] for r in regular}) != 2:
        raise Error("CALIBRATION_DOUBLE_ANNOTATION_REQUIRED")
    if _annotation_truth(regular[0]) == _annotation_truth(regular[1]):
        return _annotation_truth(regular[0])
    adjudicated = [r for r in annotations if r.manifest_json["adjudication"]]
    if len(adjudicated) != 1 or adjudicated[0].manifest_json["reviewer_user_id"] in {
        r.manifest_json["reviewer_user_id"] for r in regular
    }:
        raise Error("CALIBRATION_ADJUDICATION_REQUIRED")
    return _annotation_truth(adjudicated[0])


def _model_identity(result):
    model = result.get("model_execution", {})
    return {key: model.get(key) for key in ("provider", "model", "returned_model")}


def attach_prediction(db, workspace_id, user_id, corpus_id, data):
    row = corpus(db, workspace_id, corpus_id, user_id)
    db.query(AssetVersion).filter_by(id=row.id).with_for_update().one()
    body = CalibrationPrediction.model_validate(data)
    unit = _unit(row, body.unit_key)
    spec = row.manifest_json["spec"]
    score = (
        db.query(EvaluationScore)
        .filter_by(id=body.evaluation_id, workspace_id=workspace_id)
        .first()
    )
    result = (score.metadata_ or {}).get("typed_evaluation") if score else None
    if not isinstance(result, dict) or score.metadata_.get("source") != "evaluate_v2":
        raise Error("CALIBRATION_PREDICTION_NOT_CANONICAL", 404)
    from app.models.workspace_job import WorkspaceJob

    jobs = (
        db.query(WorkspaceJob)
        .filter_by(workspace_id=workspace_id, kind="typed_evaluation_v2")
        .all()
    )
    if not any(
        any(
            u.get("evaluation_id") == score.id and u.get("status") == "completed"
            for u in (job.result or {}).get("units", {}).values()
        )
        for job in jobs
    ):
        raise Error("CALIBRATION_PREDICTION_NOT_CANONICAL")
    if (
        result.get("rubric_sha256") != row.manifest_json["rubric_sha256"]
        or (result.get("model_execution") or {}).get("returned_model_reported") is not True
        or _model_identity(result) != spec["model"]
        or result.get("evaluation_context") != spec["context"]
    ):
        raise Error("CALIBRATION_PREDICTION_BINDING_CHANGED")
    evidence = result.get("evidence", [])
    if (
        result.get("subject_ref") != unit["key"]
        or not evidence
        or any(e.get("asset_ref") != unit["asset_ref"] for e in evidence)
    ):
        raise Error("CALIBRATION_PREDICTION_UNIT_MISMATCH")
    if (
        result.get("calibration")
        or result.get("confidence") is not None
        or (result.get("usage") or result.get("provider_usage") or {}).get("provider_calls", 0) < 1
    ):
        raise Error("CALIBRATION_INDEPENDENT_RAW_PREDICTION_REQUIRED")
    annotations = [
        r
        for r in _rows(db, workspace_id, "annotation", row.id)
        if r.manifest_json["unit_key"] == unit["key"]
    ]
    _gold(annotations)
    if unit["partition"] != "dev" and (
        score.created_at <= row.created_at
        or any(a.created_at >= score.created_at for a in annotations)
    ):
        raise Error("CALIBRATION_HOLDOUT_LABELS_NOT_BLIND")
    attempts = (
        db.query(EvaluationScore)
        .filter(
            EvaluationScore.workspace_id == workspace_id,
            EvaluationScore.created_at >= row.created_at,
            EvaluationScore.metadata_["typed_evaluation"]["subject_ref"].as_string() == unit["key"],
        )
        .order_by(EvaluationScore.created_at, EvaluationScore.id)
        .all()
    )
    for attempt in attempts:
        saved_result = (attempt.metadata_ or {}).get("typed_evaluation", {})
        model = saved_result.get("model_execution", {})
        evidence = saved_result.get("evidence", [])
        calls = saved_result.get("usage") or saved_result.get("provider_usage") or {}
        if (
            saved_result.get("rubric_sha256") == row.manifest_json["rubric_sha256"]
            and all(model.get(k) == spec["model"][k] for k in ("provider", "model"))
            and evidence
            and all(e.get("asset_ref") == unit["asset_ref"] for e in evidence)
            and calls.get("provider_calls", 0) > 0
        ):
            if attempt.id != score.id:
                raise Error("CALIBRATION_FIRST_ATTEMPT_REQUIRED")
            break
    previous = [
        r
        for r in _rows(db, workspace_id, "prediction", row.id)
        if r.manifest_json["unit_key"] == unit["key"]
    ]
    if previous:
        if previous[0].manifest_json["evaluation_id"] == body.evaluation_id:
            return {"asset_ref": assets.asset_ref(previous[0])}
        raise Error("CALIBRATION_PREDICTION_IMMUTABLE")
    prediction = assets.register_asset(
        db,
        workspace_id,
        "reference",
        f"calibration-prediction:{row.id}:{unit['key'][:80]}",
        {
            "type": PREFIX + "prediction",
            "corpus_id": row.id,
            "corpus_digest": row.digest,
            "creator_user_id": user_id,
            "unit_key": unit["key"],
            "evaluation_id": score.id,
            "evaluation_digest": assets.content_digest(result),
            "answers": result["answers"],
            "evaluation_created_at": score.created_at.isoformat(),
            "model": _model_identity(result),
            "evaluation_context": result["evaluation_context"],
        },
        [unit["asset_ref"], *[assets.asset_ref(a) for a in annotations]],
    )
    _seal(db, workspace_id, prediction, "prediction", user_id)
    return {"asset_ref": assets.asset_ref(prediction)}


def wilson_lower(successes, count):
    if not count:
        return None
    z, rate = 1.959963984540054, successes / count
    return max(
        0.0,
        (
            rate
            + z * z / (2 * count)
            - z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count))
        )
        / (1 + z * z / count),
    )


def _labels(q, value):
    if value is None:
        return set()
    if q["type"] == "multi_choice":
        return set(value)
    if q["type"] == "choice":
        return {value}
    if q["type"] == "boolean":
        return {True} if value is True else set()
    return set()


def _correct(q, value, gold, active, policy):
    if not active or gold is None:
        return False
    if q["type"] == "score":
        return abs(value - gold) <= policy["numeric_tolerances"][q["key"]]
    return set(value) == set(gold) if q["type"] == "multi_choice" else value == gold


def _probability_metrics(pairs):
    if not pairs:
        return None, None
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    ece = 0.0
    for index in range(10):
        bucket = [(p, y) for p, y in pairs if min(int(p * 10), 9) == index]
        if bucket:
            ece += (
                len(bucket)
                / len(pairs)
                * abs(
                    sum(p for p, _ in bucket) / len(bucket)
                    - sum(y for _, y in bucket) / len(bucket)
                )
            )
    return brier, ece


def partition_metrics(spec, records):
    tp = fp = fn = answered = total = critical_total = critical_missed = 0
    family_correct = defaultdict(lambda: defaultdict(list))
    probabilities = []
    questions = {q["key"]: q for q in spec["questions"]}
    for unit, truth, prediction in records:
        for key, q in questions.items():
            total += 1
            answer = prediction["answers"][key]
            gold = truth["values"][key]
            known = gold is not None
            active = answer["status"] == "answered" and answer["value"] is not None
            answered += int(active)
            value = answer["value"] if active else None
            expected, actual = _labels(q, gold), _labels(q, value)
            if known and q["type"] in {"boolean", "choice", "multi_choice"}:
                tp += len(expected & actual)
                fp += len(actual - expected)
                fn += len(expected - actual)
            critical = set(spec["policy"]["critical_labels"].get(key, []))
            critical_expected = (
                set(gold) if q["type"] == "multi_choice" and known else {gold} if known else set()
            )
            critical_actual = (
                set(value)
                if q["type"] == "multi_choice" and active
                else {value}
                if active
                else set()
            )
            positives = critical_expected & critical
            critical_total += len(positives)
            critical_missed += len(positives - critical_actual)
            correct = _correct(q, value, gold, active, spec["policy"])
            if q["type"] == "probability":
                if active:
                    probabilities.append((value, int(truth["outcomes"][key])))
                # A probability is assessed by Brier/ECE, never treated as its own confidence.
                continue
            family_correct[key][unit["document_family"]].append(bool(correct))
            if q["required"]:
                family_correct["_overall"][unit["document_family"]].append(bool(correct))
    count = len(probabilities)
    brier, ece = _probability_metrics(probabilities)
    bounds = {
        key: {
            "lower_95": wilson_lower(
                sum(all(outcomes) for outcomes in families.values()), len(families)
            ),
            "families": len(families),
            "successful_families": sum(all(outcomes) for outcomes in families.values()),
        }
        for key, families in family_correct.items()
    }
    return {
        "units": len(records),
        "families": len({u["document_family"] for u, _, _ in records}),
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "critical_positives": critical_total,
        "critical_misses": critical_missed,
        "critical_miss_rate": critical_missed / critical_total if critical_total else None,
        "coverage": answered / total if total else None,
        "answered": answered,
        "questions": total,
        "brier": brier,
        "ece_10_equal_width": ece,
        "probability_observations": count,
        "confidence_bounds": bounds,
    }


def report(db, workspace_id, user_id, corpus_id):
    row = corpus(db, workspace_id, corpus_id, user_id)
    spec = row.manifest_json["spec"]
    _contamination(row.manifest_json["units"])
    annotations = _rows(db, workspace_id, "annotation", row.id)
    predictions = _rows(db, workspace_id, "prediction", row.id)
    reasons, partitions, partition_records = [], {}, {}
    for partition in ("calibration", "test"):
        records = []
        for unit in spec["units"]:
            if unit["partition"] != partition:
                continue
            labels = [a for a in annotations if a.manifest_json["unit_key"] == unit["key"]]
            saved = [p for p in predictions if p.manifest_json["unit_key"] == unit["key"]]
            try:
                truth = _gold(labels)
                if any(
                    truth["values"].get(q["key"]) is None
                    for q in spec["questions"]
                    if q["required"] and q["type"] != "probability"
                ):
                    raise Error("CALIBRATION_HUMAN_REFERENCE_INCOMPLETE")
                if not saved:
                    raise Error("CALIBRATION_PREDICTION_REQUIRED")
                for proof in [*labels, *saved]:
                    _resolve(db, workspace_id, assets.asset_ref(proof), user_id)
                records.append((unit, truth, saved[0].manifest_json))
            except Error as exc:
                reasons.append(f"{partition}:{unit['key']}:{exc.code}")
        metrics = partition_metrics(spec, records)
        expected_units = sum(unit["partition"] == partition for unit in spec["units"])
        metrics["expected_units"] = expected_units
        metrics["missing_units"] = expected_units - len(records)
        metrics["expected_questions"] = expected_units * len(spec["questions"])
        metrics["coverage"] = (
            metrics["answered"] / metrics["expected_questions"]
            if metrics["expected_questions"]
            else None
        )
        partitions[partition] = metrics
        partition_records[partition] = records
        policy = spec["policy"]
        lower_gates = {
            "units": policy[f"min_{partition}_units"],
            "families": policy[f"min_{partition}_families"],
            "precision": policy["min_precision"],
            "recall": policy["min_recall"],
            "coverage": policy["min_coverage"],
            "critical_positives": policy["min_critical_positives"],
        }
        upper_gates = {
            "critical_miss_rate": policy["max_critical_miss_rate"],
            "brier": policy["max_brier"],
            "ece_10_equal_width": policy["max_ece"],
        }
        for key, limit in lower_gates.items():
            if metrics[key] is None or metrics[key] < limit:
                reasons.append(f"{partition}:{key}:below_threshold")
        for key, limit in upper_gates.items():
            if limit is not None and (metrics[key] is None or metrics[key] > limit):
                reasons.append(f"{partition}:{key}:above_threshold")
    for q in spec["questions"]:
        if not q["required"] or q["type"] == "probability":
            continue
        bound = partitions["calibration"]["confidence_bounds"].get(q["key"], {}).get("lower_95")
        if bound is None or bound < spec["policy"]["min_confidence_lower"]:
            reasons.append(f"calibration:{q['key']}:confidence_below_threshold")
    bound = partitions["calibration"]["confidence_bounds"].get("_overall", {}).get("lower_95")
    if bound is None or bound < spec["policy"]["min_confidence_lower"]:
        reasons.append("calibration:overall_confidence:below_threshold")
    # Validate the frozen empirical confidence against held-out TEST families.
    family_outcomes = defaultdict(list)
    for unit, truth, prediction in partition_records["test"]:
        for q in spec["questions"]:
            if q["required"] and q["type"] != "probability":
                answer = prediction["answers"][q["key"]]
                family_outcomes[unit["document_family"]].append(
                    _correct(
                        q,
                        answer["value"],
                        truth["values"][q["key"]],
                        answer["status"] == "answered",
                        spec["policy"],
                    )
                )
    confidence_brier, confidence_ece = _probability_metrics(
        [(bound, int(all(values))) for values in family_outcomes.values()]
        if bound is not None
        else []
    )
    partitions["test"].update(
        confidence_brier=confidence_brier,
        confidence_ece_10_equal_width=confidence_ece,
        confidence_validation_families=len(family_outcomes),
    )
    return {
        "corpus_ref": assets.asset_ref(row),
        "qualified": not reasons,
        "reasons": sorted(set(reasons)),
        "partitions": partitions,
        "method": "family_all_correct_wilson_95_lower",
        "confidence_scope": "Empirical bound on held-out document families within this exact model, rubric, source and language. No per-answer guarantee.",
    }


def qualify(db, workspace_id, user_id, corpus_id):
    _access(db, workspace_id, user_id, admin=True)
    row = corpus(db, workspace_id, corpus_id, user_id)
    db.query(AssetVersion).filter_by(id=row.id).with_for_update().one()
    result = report(db, workspace_id, user_id, corpus_id)
    if not result["qualified"]:
        return result
    proofs = [
        assets.asset_ref(p)
        for kind in ("annotation", "prediction")
        for p in _rows(db, workspace_id, kind, row.id)
    ]
    parents = [assets.asset_ref(row), *_bundles(db, workspace_id, row.id, proofs)]
    spec = row.manifest_json["spec"]
    profile = assets.register_asset(
        db,
        workspace_id,
        "reference",
        f"calibration-profile:{row.id}",
        {
            "type": PREFIX + "profile",
            "corpus_id": row.id,
            "report": result,
            "model": spec["model"],
            "context": spec["context"],
            "rubric_id": spec["rubric_id"],
            "rubric_version": spec["rubric_version"],
            "rubric_sha256": row.manifest_json["rubric_sha256"],
            "questions": spec["questions"],
            "qualified_by_user_id": user_id,
        },
        parents,
    )
    qualification = assets.record_qualification(
        db,
        workspace_id,
        assets.asset_ref(profile),
        status="qualified",
        policy={"type": PREFIX + "profile", "thresholds": spec["policy"]},
        evidence={
            "report_sha256": assets.content_digest(result),
            "qualified_by_user_id": user_id,
            "proofs": proofs,
        },
    )
    return {
        **result,
        "profile_ref": assets.asset_ref(profile),
        "qualification_digest": qualification.digest,
    }


def bind_confidence(db, workspace_id, user_id, profile_ref, result):
    """Changing or revoking a binding yields unknown confidence, never guessed values."""
    try:
        profile = _resolve(db, workspace_id, profile_ref, user_id)
        qualification = assets.validate_qualification(
            assets.current_qualification(db, workspace_id, profile.id), profile
        )
        manifest = profile.manifest_json
        if (
            manifest.get("type") != PREFIX + "profile"
            or qualification.policy_json.get("type") != PREFIX + "profile"
            or qualification.evidence_json.get("report_sha256")
            != assets.content_digest(manifest.get("report"))
            or manifest.get("report", {}).get("qualified") is not True
            or manifest["model"] != _model_identity(result)
            or (result.get("model_execution") or {}).get("returned_model_reported") is not True
            or manifest["context"] != result.get("evaluation_context")
            or manifest["rubric_sha256"] != result["rubric_sha256"]
            or manifest["rubric_id"] != result["rubric_id"]
            or manifest["rubric_version"] != result["rubric_version"]
        ):
            raise Error("CALIBRATION_PROFILE_BINDING_CHANGED")
        if result["status"] != "completed":
            raise Error("CALIBRATION_RESULT_INCOMPLETE")
        if not result.get("evidence"):
            raise Error("CALIBRATION_SOURCE_CONTEXT_CHANGED")
        for evidence in result.get("evidence", []):
            source = _resolve(db, workspace_id, evidence.get("asset_ref"), user_id)
            if any(
                source.manifest_json.get(key) != value for key, value in manifest["context"].items()
            ):
                raise Error("CALIBRATION_SOURCE_CONTEXT_CHANGED")
        bounds = manifest["report"]["partitions"]["calibration"]["confidence_bounds"]
        required = []
        for q in manifest["questions"]:
            answer = result["answers"][q["key"]]
            bound = bounds.get(q["key"], {}).get("lower_95")
            answer["confidence"] = bound if answer["status"] == "answered" else None
            if q["required"]:
                required.append(answer["confidence"])
        result["confidence"] = (
            bounds.get("_overall", {}).get("lower_95")
            if required and all(v is not None for v in required)
            else None
        )
        result["confidence_reason"] = (
            "qualified_family_empirical_bound"
            if result["confidence"] is not None
            else "probability_question_has_no_correctness_bound"
        )
        result["calibration"] = {
            "profile_ref": assets.asset_ref(profile),
            "qualification_digest": qualification.digest,
            "method": manifest["report"]["method"],
            "scope": manifest["report"]["confidence_scope"],
        }
    except (Error, KeyError, TypeError):
        result.pop("calibration", None)
        result["confidence"], result["confidence_reason"] = (
            None,
            "calibration_unavailable_or_binding_changed",
        )
        for answer in result["answers"].values():
            answer["confidence"] = None
    return result


def create_vision_route(db, workspace_id, user_id, data):
    """Creating a route never qualifies it and performs no remote request."""
    from app.services.evaluation.typed_judge import model_connection_digest
    from app.services.model_plane.execution import ModelExecutionError, resolve_model_execution

    _access(db, workspace_id, user_id, admin=True)
    spec = VisionRouteDefinition.model_validate(data)
    try:
        execution = resolve_model_execution(
            db.get(Workspace, workspace_id), provider=spec.provider, model=spec.model
        )
    except ModelExecutionError:
        raise Error("JUDGE_VISION_CONNECTION_REQUIRED", 422) from None
    if execution.credential_source == "not_configured":
        raise Error("JUDGE_VISION_CONNECTION_REQUIRED", 422)
    row = assets.register_asset(
        db,
        workspace_id,
        "reference",
        "vision-route:" + spec.logical_key,
        {
            "type": "typed_judge_vision_route",
            **spec.model_dump(exclude={"logical_key"}),
            "connection_digest": model_connection_digest(execution),
        },
    )
    return {"asset_ref": assets.asset_ref(row), "definition": row.manifest_json, "qualified": False}


def qualify_vision_route(db, workspace_id, user_id, route_id, data):
    """Record human review of an immutable real transport trace, not a quality claim."""
    import re

    _access(db, workspace_id, user_id, admin=True)
    body = VisionRouteQualification.model_validate(data)
    route = (
        db.query(AssetVersion)
        .filter_by(id=route_id, workspace_id=workspace_id)
        .with_for_update()
        .first()
    )
    if route is None or route.manifest_json.get("type") != "typed_judge_vision_route":
        raise Error("JUDGE_VISION_ROUTE_NOT_FOUND", 404)
    _resolve(db, workspace_id, assets.asset_ref(route), user_id)
    proof = assets.resolve_asset_ref(
        db,
        workspace_id,
        body.verification_ref,
        authorize=_access(db, workspace_id, user_id),
        verify_objects=True,
    )
    manifest = proof.manifest_json
    if (
        manifest.get("type") != "vision_transport_verification"
        or manifest.get("route_digest") != route.digest
        or manifest.get("provider_response_model") != route.manifest_json["returned_model"]
        or manifest.get("observed_transport") != "inline_image"
        or manifest.get("passed") is not True
        or not manifest.get("objects")
        or not body.note.strip()
        or not isinstance(manifest.get("reviewed_image_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", manifest["reviewed_image_sha256"])
    ):
        raise Error("JUDGE_VISION_TRANSPORT_PROOF_REQUIRED", 422)
    qualification = assets.record_qualification(
        db,
        workspace_id,
        assets.asset_ref(route),
        status="qualified",
        policy={
            "purpose": "image_transport",
            "route_digest": route.digest,
            "method": "human_verified_transport_trace",
        },
        evidence={
            "verification_ref": assets.asset_ref(proof),
            "reviewer_user_id": user_id,
            "note": body.note.strip(),
            "quality_calibration": False,
        },
    )
    return {
        "asset_ref": assets.asset_ref(route),
        "qualification_digest": qualification.digest,
        "method": "human_verified_transport_trace",
        "quality_calibration": False,
    }
