from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.work_predictions import (
    configuration_issues,
    project_row,
    validate_contract,
    validate_model,
)

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def contract(**changes):
    return {
        "schema_version": 1,
        "model_id": "model-other-domain",
        "model_version": 2,
        "task": "classification",
        "target": "will_renew",
        "positive_label": "yes",
        "label": "Renewal likelihood",
        "value_column": "outcome",
        "score_column": "score_yes",
        "unit": "probability",
        "max_age_seconds": 600,
        "order": "ascending",
        "bands": [
            {"key": "retain", "label": "Contact", "min": 0},
            {"key": "likely", "label": "Likely", "min": 0.8},
        ],
        **changes,
    }


def test_another_business_target_class_and_bands_project_without_sla_assumptions():
    model = SimpleNamespace(
        id="model-other-domain",
        version=2,
        task="classification",
        target="will_renew",
        classes_json=["no", "yes"],
    )
    config = contract()
    validate_model(model, config)
    advice = project_row(
        {"outcome": "no", "score_yes": 0.1, "confidence": 0.9},
        config,
        captured_at=NOW,
        now=NOW,
        provenance={"run_id": "run"},
    )
    assert advice["score"] == 0.1
    assert advice["band"]["key"] == "retain"
    assert advice["model"]["version"] == 2
    assert advice["provenance"]["run_id"] == "run"
    with pytest.raises(ValueError, match="MODEL_MISMATCH"):
        validate_model(model, contract(positive_label="1"))


@pytest.mark.parametrize("age", [-1, 601])
def test_future_and_expired_advice_has_no_actionable_value(age):
    advice = project_row(
        {"outcome": "yes", "score_yes": 0.9},
        contract(),
        captured_at=NOW - timedelta(seconds=age),
        now=NOW,
        provenance={},
    )
    assert advice["status"] == "stale"
    assert advice["value"] is None and advice["score"] is None and advice["band"] is None


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.1, 1.1, None])
def test_confidence_and_invalid_scores_never_replace_positive_class_probability(score):
    with pytest.raises(ValueError, match="SCORE_INVALID"):
        project_row(
            {"outcome": "yes", "score_yes": score, "confidence": 0.99},
            contract(),
            captured_at=NOW,
            now=NOW,
            provenance={},
        )


def test_regression_has_explicit_units_and_validated_interval():
    config = contract(
        task="regression",
        target="repair_days",
        positive_label=None,
        score_column=None,
        unit="days",
        bands=[],
        lower_column="low",
        upper_column="high",
    )
    advice = project_row(
        {"outcome": 3, "low": 1, "high": 5}, config, captured_at=NOW, now=NOW, provenance={}
    )
    assert advice["score"] is None and advice["value"] == 3 and advice["unit"] == "days"
    assert advice["interval"] == {"lower": 1, "upper": 5}
    with pytest.raises(ValueError, match="INTERVAL_INVALID"):
        project_row(
            {"outcome": 3, "low": 4, "high": 5}, config, captured_at=NOW, now=NOW, provenance={}
        )


def test_cluster_identifier_cannot_be_published_as_probability_or_order():
    config = contract(
        task="clustering",
        target=None,
        positive_label=None,
        score_column=None,
        unit="segment",
        order="none",
        bands=[],
    )
    advice = project_row({"outcome": 4}, config, captured_at=NOW, now=NOW, provenance={})
    assert advice["value"] == 4 and advice["score"] is None and advice["band"] is None
    for patch in (
        {"unit": "probability"},
        {"order": "descending"},
        {"bands": [{"key": "high", "label": "High", "min": 3}]},
    ):
        with pytest.raises(ValueError, match="SEGMENT_NOT_ORDERED"):
            validate_contract({**config, **patch})


def test_release_requires_authored_valid_contract_and_runtime_source():
    component = {"id": "advice", "type": "prediction", "props": {"predictionContract": contract()}}
    pages = {"pages": [{"id": "queue", "components": [component]}]}
    assert configuration_issues(pages)[0]["code"] == "PREDICTION_CONFIGURATION_INVALID"
    component["props"]["dataBinding"] = {
        "source": "run-output",
        "componentId": "start",
        "selector": "output",
    }
    assert configuration_issues(pages) == []
    component["props"]["predictionContract"]["bands"].append(
        {"key": "same", "label": "Duplicate limit", "min": 0.8}
    )
    assert configuration_issues(pages)


def test_scored_column_provenance_blocks_input_collisions_and_wrong_positive_class():
    from app.services.work_predictions import validate_dataset_contract

    model = SimpleNamespace(
        id="model-other-domain",
        version=2,
        task="classification",
        target="will_renew",
        classes_json=["no", "yes"],
        metrics_json={},
    )
    config = contract(value_column="prediction")
    dataset = SimpleNamespace(
        lineage_json={
            "model": {"model_id": model.id, "version": 2},
            "added_columns": ["prediction", "score_yes_2"],
            "prediction_output": {
                "task": "classification",
                "target": "will_renew",
                "positive_label": "yes",
                "value_column": "prediction",
                "score_column": "score_yes_2",
            },
        }
    )
    with pytest.raises(ValueError, match="COLUMN_PROVENANCE"):
        validate_dataset_contract(dataset, model, config)
    validate_dataset_contract(dataset, model, {**config, "score_column": "score_yes_2"})
    with pytest.raises(ValueError, match="SEMANTICS_MISMATCH"):
        validate_dataset_contract(
            dataset, model, {**config, "positive_label": "no", "score_column": "score_yes_2"}
        )
    # Legacy metadata only supports proven generated names, never colliding inputs.
    del dataset.lineage_json["prediction_output"]
    with pytest.raises(ValueError, match="COLUMN_PROVENANCE"):
        validate_dataset_contract(dataset, model, config)
    dataset.lineage_json["added_columns"] = ["prediction", "score_yes"]
    validate_dataset_contract(dataset, model, config)


def test_malformed_json_values_block_publication_without_raising_server_errors():
    for patch in (
        {"schema_version": True},
        {"bands": [{"key": "huge", "label": "Huge", "min": 10**1000}]},
        {"lower_column": ["lower"], "upper_column": ["upper"]},
    ):
        pages = {
            "pages": [
                {
                    "id": "home",
                    "components": [
                        {
                            "id": "advice",
                            "type": "prediction",
                            "props": {"predictionContract": contract(**patch)},
                        }
                    ],
                }
            ]
        }
        assert configuration_issues(pages)[0]["code"] == "PREDICTION_CONFIGURATION_INVALID"


def test_node_output_binding_checks_published_node_and_does_not_use_final_result_schema():
    from app.services.experience.lifecycle import _binding_contract_issues, _data_binding_issues

    pages = {
        "pages": [
            {
                "id": "home",
                "components": [
                    {
                        "id": "inquiry",
                        "type": "action_button",
                        "props": {"bindingKey": "business.inquire", "input": {}},
                    },
                    {
                        "id": "advice",
                        "type": "prediction",
                        "props": {
                            "dataBinding": {
                                "source": "run-output",
                                "componentId": "inquiry",
                                "nodeId": "model.context",
                                "selector": "model_advice",
                            }
                        },
                    },
                ],
            }
        ]
    }
    resolved = {
        "business.inquire": {
            "output_node_ids": ["model.context"],
            "output_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"receipt": {"type": "string"}},
            },
        }
    }
    assert _data_binding_issues(pages) == []
    assert _binding_contract_issues(pages, resolved) == []
    pages["pages"][0]["components"][1]["props"]["dataBinding"]["nodeId"] = "missing-node"
    assert _binding_contract_issues(pages, resolved)[0]["code"] == "OUTPUT_NODE_NOT_FOUND"
