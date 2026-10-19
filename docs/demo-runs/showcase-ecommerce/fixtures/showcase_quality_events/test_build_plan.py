"""Protect publication pins and independently authored drafts during planning."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build_plan import BINDINGS, SYSTEM, build_plan

ROOT = Path(__file__).resolve().parent


@pytest.fixture
def snapshots(tmp_path):
    from app.services.ecommerce.triage import FEATURES, TARGET
    from app.services.run_engine.execution_contract import canonical_flow_sha256

    config = json.loads(
        (ROOT.parent / "showcase_learning/live_learning_plan.json").read_text()
    )["configuration"]
    graph = config["flow_definition"]
    params = next(n for n in graph["nodes"] if n["id"] == "sav.score")["config"][
        "params"
    ]
    contract = next(
        c["props"]["predictionContract"]
        for p in config["pages"]["pages"]
        for c in p["components"]
        if "predictionContract" in c.get("props", {})
    )
    published = {
        "version_id": "published-version",
        "flow_definition": graph,
        "flow_sha256": canonical_flow_sha256(graph),
        "control_policy_snapshot_sha256": "same-policy",
    }
    draft = {
        **copy.deepcopy(published),
        "revision": 25,
        "base_published_version_id": published["version_id"],
    }
    draft["flow_definition"]["nodes"][1]["label"] = "Wording still under review"
    draft["flow_definition"]["nodes"][1]["position"] = {"x": 17, "y": 29}
    draft["flow_sha256"] = canonical_flow_sha256(draft["flow_definition"])
    bindings = [
        {
            "binding_key": key,
            "system_id": SYSTEM,
            "published_flow_version_id": published["version_id"],
            "flow_sha256": published["flow_sha256"],
            "ingress_id": ingress,
            "confirmation_policy": "confirm",
            "on_unavailable": "unavailable",
            "input_schema_sha256": "input-schema",
            "output_schema_sha256": None,
        }
        for key, ingress in BINDINGS.values()
    ]
    experience = {
        "id": "experience",
        "name": "Claims",
        "description": "Existing business app",
        "emblem": None,
        "slug": "reclamations",
        "pattern": "workspace",
        "access_policy": {"roles": ["workspace_member"]},
        "languages": ["fr"],
        "theme": {},
        "updated_at": "2026-10-19T10:00:00Z",
        "draft": {
            "revision": 12,
            "content_sha256": "draft-content",
            "pages": copy.deepcopy(config["pages"]),
            "binding_keys": [b["binding_key"] for b in bindings] + ["draft.only"],
        },
        "deployments": [
            {
                "channel": "live",
                "release_id": "release",
                "audience": {"roles": ["workspace_member"]},
                "updated_at": "2026-10-19T09:00:00Z",
            }
        ],
    }
    experience["draft"]["pages"]["pages"][0]["title"] = "Draft-only title"
    release = {
        "id": "release",
        "experience_id": experience["id"],
        "pages": copy.deepcopy(config["pages"]),
        "bindings_snapshot": copy.deepcopy(bindings),
        "access_snapshot": copy.deepcopy(experience["access_policy"]),
        "languages": experience["languages"],
        "theme": experience["theme"],
        "identity_snapshot": {
            k: experience[k]
            for k in ("name", "description", "emblem", "slug", "pattern")
        },
    }
    work_release = copy.deepcopy(release)
    work_release["bindings_snapshot"] = [
        {
            key: binding[key]
            for key in ("binding_key", "confirmation_policy", "on_unavailable")
        }
        for binding in bindings
    ]
    triage = {
        "model_id": params["model_id"],
        "model_version": params["pinned_version"],
        "prediction_contract": copy.deepcopy(contract),
        "training_system_id": None,
        "scoring_system_id": SYSTEM,
        "scoring_version_id": published["version_id"],
        "scoring_flow_sha256": published["flow_sha256"],
    }
    values = {
        "flow-state": {"system_id": SYSTEM, "published": published, "draft": draft},
        "work-live": {"experience": {"id": experience["id"]}, "release": work_release},
        "work-release": release,
        "experience": experience,
        "model-sla": {
            "model": {
                "id": params["model_id"],
                "slug": params["model_slug"],
                "version": params["pinned_version"],
                "status": "ready",
                "task": "classification",
                "target": TARGET,
                "features": FEATURES,
                "system_id": None,
            },
            "serving": {"callable": True},
        },
        "model-sla-prediction": {
            "served": {
                "model_id": params["model_id"],
                "version": params["pinned_version"],
            },
            "prediction_id": "observed-inference",
            "predictions": [1],
            "target": TARGET,
            "positive_label": "1",
        },
        "collections": [
            {
                "slug": n["config"]["collection_slug"],
                "id": f"00000000-0000-0000-0000-{i:012d}",
            }
            for i, n in enumerate(graph["nodes"], 1)
            if n.get("type") == "source.collection"
        ],
        "triage-settings": {"triage": triage},
    }
    values.update(
        {
            "binding-" + filename: binding
            for filename, binding in zip(BINDINGS, bindings)
        }
    )

    def save():
        for name, value in values.items():
            (tmp_path / f"{name}.json").write_text(
                json.dumps({"status": 200, "data": value})
            )
        return tmp_path

    return values, save


def prepare(snapshots):
    _, save = snapshots
    return build_plan(save(), json.loads((ROOT / "judge_settings.json").read_text()))


def test_live_projection_and_separate_drafts_preserved(snapshots):
    values, _ = snapshots
    before = copy.deepcopy(values)
    plan, review = prepare(snapshots)
    assert values == before
    assert plan["work_pages"] == values["work-release"]["pages"]
    assert plan["preserved_work_draft_pages"] == values["experience"]["draft"]["pages"]
    assert "draft.only" not in plan["work_binding_keys"]
    assert "draft.only" in plan["preserved_work_draft_binding_keys"]
    assert review["work_draft_differs_from_live"] is True
    assert plan["preserved_draft_candidate"]["nodes"][1]["position"] == {
        "x": 17,
        "y": 29,
    }
    assert (
        plan["preserved_draft_candidate"]["nodes"][1]["label"]
        == "Wording still under review"
    )
    assert (
        plan["publication_candidate"]["nodes"][1]["label"]
        != "Wording still under review"
    )
    assert "monitoring" not in plan and "shadow" not in plan
    assert review["model_operations_changed"] is False


@pytest.mark.parametrize(
    "change, error",
    [
        (
            lambda v: v["experience"]["access_policy"]["roles"].append("viewer"),
            "UNREVIEWED_WORK_METADATA_CHANGES",
        ),
        (
            lambda v: v["work-release"]["bindings_snapshot"][0].update(
                input_schema_sha256="different"
            ),
            "WORK_RELEASE_BINDING_DRIFT",
        ),
        (
            lambda v: v["work-live"]["release"]["bindings_snapshot"][0].update(
                confirmation_policy="none"
            ),
            "LIVE_RELEASE_SNAPSHOT_DRIFT",
        ),
    ],
)
def test_unreviewed_live_permissions_or_binding_contract_fail_closed(
    snapshots, change, error
):
    values, _ = snapshots
    change(values)
    with pytest.raises(ValueError, match=error):
        prepare(snapshots)


def test_draft_model_choice_is_not_overwritten(snapshots):
    values, _ = snapshots
    score = next(
        n
        for n in values["flow-state"]["draft"]["flow_definition"]["nodes"]
        if n["id"] == "sav.score"
    )
    score["config"]["params"]["pinned_version"] = 7
    with pytest.raises(ValueError, match="FLOW_MODEL_PIN_DIVERGED"):
        prepare(snapshots)


def test_draft_work_model_choice_is_not_overwritten(snapshots):
    values, _ = snapshots
    for page in values["experience"]["draft"]["pages"]["pages"]:
        for component in page["components"]:
            if "predictionContract" in component.get("props", {}):
                component["props"]["predictionContract"]["model_version"] = 7
    with pytest.raises(ValueError, match="WORK_MODEL_PIN_DIVERGED"):
        prepare(snapshots)


def test_request_templates_keep_cas_and_minimal_non_cas_patches(snapshots):
    plan, _ = prepare(snapshots)
    requests = plan["request_templates"]
    assert requests["flow_draft_save"]["expected_revision"] == 25
    assert (
        requests["flow_draft_restore"]["expected_revision"]
        == "$response.flow_publish.draft.revision"
    )
    assert requests["work_draft_save"]["expected_revision"] == 12
    assert (
        requests["work_draft_restore"]["expected_revision"]
        == "$response.work_draft_save.revision"
    )
    assert (
        requests["work_release"]["expected_bindings_sha256"]
        == "$response.ready_check.bindings_sha256"
    )
    assert requests["work_deployment"]["audience"] == {"roles": ["workspace_member"]}
    assert all(
        set(patch["body"]) == {"published_flow_version_id"}
        for patch in requests["bindings_patch"]
    )


def test_ready_without_inference_does_not_qualify_pin(snapshots):
    values, _ = snapshots
    values["model-sla-prediction"]["served"]["version"] = 99
    with pytest.raises(ValueError, match="PINNED_SLA_INFERENCE_PROOF_REQUIRED"):
        prepare(snapshots)


@pytest.mark.parametrize(
    "field, value",
    [
        ("model_id", "user-model"),
        ("pinned_version", 7),
        ("horizon", 14),
        ("interval_level", 0.95),
    ],
)
def test_four_lots_refuses_authored_forecast_before_overwriting_draft(
    snapshots, field, value
):
    from compose_four_lots import compose, forecast_node

    values, save = snapshots
    draft = values["flow-state"]["draft"]["flow_definition"]
    forecast_node(draft)["config"]["params"][field] = value
    before = copy.deepcopy(values)
    with pytest.raises(ValueError, match="FORECAST_DRAFT_PARAMETERS_DIVERGED"):
        compose(
            save(),
            {"model_id": "qualified-forecast", "pinned_version": 2},
            "challenger",
        )
    assert values == before


def test_four_lots_updates_matching_forecasts_and_preserves_other_draft_edits(
    snapshots,
):
    from compose_four_lots import compose, forecast_node

    values, save = snapshots
    before = copy.deepcopy(values)
    params = copy.deepcopy(
        forecast_node(values["flow-state"]["published"]["flow_definition"])["config"][
            "params"
        ]
    )
    params.update(
        model_id="qualified-forecast", model_slug="qualified-forecast", pinned_version=2
    )
    plan, _review = compose(save(), params, "challenger")
    for key in ("publication_candidate", "preserved_draft_candidate"):
        assert forecast_node(plan[key])["config"]["params"] == params
    assert (
        plan["preserved_draft_candidate"]["nodes"][1]["label"]
        == "Wording still under review"
    )
    assert plan["preserved_draft_candidate"]["nodes"][1]["position"] == {
        "x": 17,
        "y": 29,
    }
    assert values == before


def test_different_qualified_version_does_not_retarget_model(snapshots):
    values, _ = snapshots
    values["model-sla"]["model"]["version"] = 7
    values["model-sla-prediction"]["served"]["version"] = 7
    with pytest.raises(ValueError, match="SLA_MODEL_RETARGET_OUT_OF_SCOPE"):
        prepare(snapshots)


def test_training_provenance_is_unchanged_by_judge_activation(snapshots):
    values, _ = snapshots
    values["triage-settings"]["triage"]["training_system_id"] = "authored-provenance"
    plan, _ = prepare(snapshots)
    assert (
        plan["triage_after_publication"]["training_system_id"] == "authored-provenance"
    )
