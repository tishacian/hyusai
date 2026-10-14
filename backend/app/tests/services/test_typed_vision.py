"""Actual OpenAI/Azure message construction, with only the SDK transport mocked."""

import base64
import hashlib
import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from app.models.run import Run
from app.models.workspace_job import WorkspaceJob
from app.services import governed_assets as assets
from app.services.evaluation import typed_calibration as calibration
from app.services.evaluation import typed_judge as judge
from app.services.model_clients.azure_openai_client import AzureOpenAIClient
from app.services.model_clients.openai_client import OpenAIClient
from app.services.model_plane import execution
from app.services.model_plane.execution import ModelExecution, ModelImage
from app.services.object_store import ObjectStore, get_object_store
from app.tests.services import test_service_contracts

setup = test_service_contracts.setup


@pytest.fixture()
def vision(setup, monkeypatch):
    s = setup
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(stream, format="PNG")
    raw = stream.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    key = f"workspaces/{s.workspace.id}/vision/page.png"
    get_object_store().write_bytes(key, raw)
    asset = assets.register_asset(
        s.db,
        s.workspace.id,
        "document_set",
        "vision-page",
        {
            "document_family": "manual-1",
            "source": "showcase",
            "language": "en-fr",
            "task": "j2450_translation",
            "objects": [{"key": key, "sha256": digest, "size_bytes": len(raw)}],
            "evidence": [
                {
                    "id": "page",
                    "kind": "image",
                    "sha256": digest,
                    "mime_type": "image/png",
                    "locator": {"object_key": key},
                }
            ],
        },
    )
    evidence = {
        "id": "page",
        "kind": "image",
        "sha256": digest,
        "asset_ref": assets.asset_ref(asset),
    }
    run = Run(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        initiated_by_user_id=s.owner.id,
        status="running",
        input_ref={"evidence": [evidence]},
    )
    s.db.add(run)
    model = ModelExecution(
        "openai", "vision-model", "workspace", "workspace", _api_key="synthetic-test-key"
    )
    route = assets.register_asset(
        s.db,
        s.workspace.id,
        "reference",
        "vision-route",
        {
            "type": "typed_judge_vision_route",
            "provider": model.provider,
            "model": model.model,
            "returned_model": "vision-model",
            "connection_digest": judge.model_connection_digest(model),
            "max_images": 2,
            "max_image_bytes": 100000,
            "max_total_bytes": 200000,
            "max_image_tokens": 4096,
            "max_pixels": 100000,
        },
    )
    assets.record_qualification(
        s.db,
        s.workspace.id,
        assets.asset_ref(route),
        status="qualified",
        policy={"test_only": True, "purpose": "image_transport"},
        evidence={"reviewer_user_id": s.owner.id},
    )
    s.db.commit()
    payload = {
        "batch_key": "vision-batch",
        "request_key": "page",
        "subject_ref": "page",
        "rubric_id": "image-question",
        "rubric_version": "1",
        "questions": [
            {
                "key": "category",
                "question": "Which visible defect occurs?",
                "type": "choice",
                "choices": ["WT", "OM"],
            }
        ],
        "evidence": [evidence],
        "budget": {"max_calls": 2, "max_tokens": 100000, "max_cost_usd": 1.0},
        "tariff": {
            "provider": "openai",
            "model": model.model,
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
            "run_id": run.id,
            "user_id": s.owner.id,
            "_model_execution": model,
            "_model_policy_check": lambda execution: None,
        },
        vision_route_ref=assets.asset_ref(route),
    )
    calls = []
    response = {
        "answers": {
            "category": {
                "status": "answered",
                "value": "OM",
                "reason": None,
                "explanation": "Visible warning omission.",
                "evidence": [
                    {
                        "kind": "image",
                        "evidence_id": "page",
                        "image_sha256": digest,
                        "region": [0.0, 0.0, 1.0, 1.0],
                        "description": "Warning panel.",
                    }
                ],
            }
        }
    }
    state = {
        "usage": SimpleNamespace(prompt_tokens=120, completion_tokens=30, total_tokens=150),
        "returned_model": model.model,
    }

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))],
            model=state["returned_model"],
            usage=state["usage"],
        )

    monkeypatch.setattr(
        OpenAIClient,
        "_sdk_client",
        lambda self: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    return SimpleNamespace(
        s=s,
        payload=payload,
        ctx=ctx,
        calls=calls,
        raw=raw,
        response=response,
        state=state,
        route=route,
        asset=asset,
    )


async def test_image_bytes_reach_the_actual_multimodal_request_and_have_citable_hash(vision):
    v = vision
    result = await judge.typed_evaluate(v.payload, v.ctx)
    content = v.calls[0]["messages"][0]["content"]
    images = [part for part in content if part["type"] == "image_url"]
    assert len(images) == 1
    assert base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1]) == v.raw
    assert result["status"] == "completed" and result["coverage"]["images_examined"] == 1
    assert result["model_execution"]["returned_model"] == "vision-model"
    assert (
        result["answers"]["category"]["evidence"][0]["image_sha256"]
        == hashlib.sha256(v.raw).hexdigest()
    )
    assert result["disposition"] == "review" and result["confidence"] is None
    assert "base64" not in json.dumps(result)


async def test_unknown_image_usage_keeps_cost_unknown_and_reservation_unsettled(vision):
    v = vision
    v.state["usage"] = None
    result = await judge.typed_evaluate(v.payload, v.ctx)
    assert result["cost"]["amount"] is None and result["budget"]["includes_unsettled_reservations"]
    assert result["provider_usage"]["provider_calls"] == 1
    v.s.db.expire_all()
    assert (
        v.s.db.query(WorkspaceJob).filter_by(kind=judge.KIND).one().result["charged_tokens"] > 4096
    )


async def test_unqualified_route_and_wrong_image_bytes_fail_before_any_call(vision):
    v = vision
    v.ctx["_typed_judge_resolve_image"] = lambda evidence, ctx: {
        "bytes": b"wrong",
        "mime_type": "image/png",
    }
    with pytest.raises(judge.TypedEvaluationError, match="HASH_OR_SIZE"):
        await judge.typed_evaluate(v.payload, v.ctx)
    assert not v.calls
    v.ctx["_typed_judge_resolve_image"] = judge.resolve_judge_image
    assets.record_qualification(
        v.s.db,
        v.s.workspace.id,
        assets.asset_ref(v.route),
        status="needs_requalification",
        policy={},
        evidence={},
    )
    v.s.db.commit()
    with pytest.raises(assets.GovernanceError, match="QUALIFICATION_REQUIRED"):
        await judge.typed_evaluate(v.payload, v.ctx)
    assert not v.calls


async def test_vision_abstention_and_model_identity_change_remain_reviewable_and_measured(vision):
    v = vision
    v.response["answers"]["category"].update(
        status="abstained", value=None, reason="ambiguous", evidence=[]
    )
    first = await judge.typed_evaluate(v.payload, v.ctx)
    assert first["status"] == "partial" and first["confidence"] is None
    v.payload["request_key"] = "different-page"
    v.state["returned_model"] = "unqualified-revision"
    second = await judge.typed_evaluate(v.payload, v.ctx)
    assert (
        second["status"] == "failed" and second["reason"] == "JUDGE_VISION_RETURNED_MODEL_CHANGED"
    )
    assert second["cost"]["amount"] > 0


async def test_image_citation_cannot_name_another_hash_or_reverse_a_region(vision):
    v = vision
    v.response["answers"]["category"]["evidence"][0]["region"] = [0.9, 0.1, 0.2, 0.8]
    result = await judge.typed_evaluate(v.payload, v.ctx)
    assert result["reason"] == "JUDGE_RESPONSE_INVALID"


@pytest.mark.parametrize("missing_model", [True, False])
async def test_missing_model_identity_or_measured_budget_overrun_fails_without_erasing_cost(
    vision, missing_model
):
    v = vision
    if missing_model:
        v.state["returned_model"] = None
        reason = "JUDGE_VISION_RETURNED_MODEL_UNMEASURED"
    else:
        v.state["usage"] = SimpleNamespace(
            prompt_tokens=200000, completion_tokens=30, total_tokens=200030
        )
        reason = "JUDGE_MEASURED_BUDGET_EXCEEDED"
    result = await judge.typed_evaluate(v.payload, v.ctx)
    assert len(v.calls) == 1 and result["status"] == "failed" and result["reason"] == reason
    assert result["cost"]["amount"] > 0 and result["confidence"] is None


async def test_azure_client_transports_inline_images_without_a_remote_url(monkeypatch, vision):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            model="azure-deployment",
            usage=None,
        )

    monkeypatch.setattr(
        AzureOpenAIClient,
        "_sdk_client",
        lambda self: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    model = ModelExecution(
        "azure_openai",
        "azure-deployment",
        "workspace",
        "workspace",
        _api_key="synthetic",
        _endpoint="https://unit.openai.azure.com",
        _api_version="2024-02-01",
    )
    image = ModelImage("page", vision.raw, "image/png", hashlib.sha256(vision.raw).hexdigest())
    result = await execution.complete_model(
        model, "Inspect page", {}, stream=False, images=(image,)
    )
    assert calls[0]["messages"][0]["content"][2]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert result["provider_usage"]["measurement_coverage"] == "unavailable"


async def test_arbitrary_image_generation_options_are_refused_before_dispatch(vision):
    with pytest.raises(execution.ModelExecutionError, match="server-resolved"):
        await execution.complete_model(
            vision.ctx["_model_execution"],
            "text",
            {},
            stream=False,
            generation_options={"image_parts": [{"image_url": "https://untrusted"}]},
        )
    assert not vision.calls


async def test_image_reads_are_bounded_even_when_stored_object_has_grown(vision, monkeypatch):
    v = vision
    key = v.asset.manifest_json["objects"][0]["key"]
    reads = []
    original = ObjectStore._local_path

    class BoundedStream(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert size == len(v.raw) + 1
            return super().read(size)

    monkeypatch.setattr(
        ObjectStore,
        "_local_path",
        lambda self, name: (
            SimpleNamespace(open=lambda mode: BoundedStream(v.raw + b"unexpected"))
            if name == key
            else original(self, name)
        ),
    )
    with pytest.raises(judge.TypedEvaluationError, match="HASH_MISMATCH"):
        await judge.typed_evaluate(v.payload, v.ctx)
    assert reads == [len(v.raw) + 1] and not v.calls


async def test_image_cannot_cross_workspace_and_work_review_is_not_a_vision_qualification(vision):
    v = vision
    original = v.payload["evidence"][0]["asset_ref"]
    v.payload["evidence"][0]["asset_ref"] = {**original, "workspace_id": v.s.foreign.id}
    with pytest.raises(assets.GovernanceError, match="SCOPE_DENIED"):
        await judge.typed_evaluate(v.payload, v.ctx)
    assert not v.calls
    v.payload["evidence"][0]["asset_ref"] = original
    assets.record_qualification(
        v.s.db,
        v.s.workspace.id,
        assets.asset_ref(v.route),
        status="qualified",
        policy={"human_work_review": True},
        evidence={"reviewer_user_id": v.s.owner.id},
    )
    v.s.db.commit()
    with pytest.raises(judge.TypedEvaluationError, match="TRANSPORT_QUALIFICATION_REQUIRED"):
        await judge.typed_evaluate(v.payload, v.ctx)
    assert not v.calls


def test_vision_route_workflow_requires_configured_route_and_real_human_trace_review(
    vision, monkeypatch
):
    v, s = vision, vision.s
    monkeypatch.setattr(
        execution, "resolve_model_execution", lambda *args, **kwargs: v.ctx["_model_execution"]
    )
    body = {
        key: value
        for key, value in v.route.manifest_json.items()
        if key not in {"type", "connection_digest"}
    }
    body["logical_key"] = "reviewed-route"
    created = calibration.create_vision_route(s.db, s.workspace.id, s.owner.id, body)
    assert not created["qualified"] and not v.calls
    route_ref = created["asset_ref"]
    note = "I inspected the sanitized provider trace and the returned image description."
    with pytest.raises(assets.GovernanceError, match="PERMISSION_DENIED"):
        calibration.qualify_vision_route(
            s.db,
            s.workspace.id,
            s.member.id,
            route_ref["asset_id"],
            {"verification_ref": assets.asset_ref(v.asset), "note": note},
        )
    with pytest.raises(assets.GovernanceError, match="TRANSPORT_PROOF_REQUIRED"):
        calibration.qualify_vision_route(
            s.db,
            s.workspace.id,
            s.owner.id,
            route_ref["asset_id"],
            {"verification_ref": assets.asset_ref(v.asset), "note": note},
        )
    proof = assets.register_asset(
        s.db,
        s.workspace.id,
        "reference",
        "transport-proof",
        {
            "type": "vision_transport_verification",
            "route_digest": route_ref["digest"],
            "provider_response_model": "vision-model",
            "observed_transport": "inline_image",
            "passed": True,
            "reviewed_image_sha256": hashlib.sha256(v.raw).hexdigest(),
            "objects": v.asset.manifest_json["objects"],
        },
    )
    qualified = calibration.qualify_vision_route(
        s.db,
        s.workspace.id,
        s.owner.id,
        route_ref["asset_id"],
        {"verification_ref": assets.asset_ref(proof), "note": note},
    )
    assert not qualified["quality_calibration"] and not v.calls
    saved = assets.current_qualification(s.db, s.workspace.id, route_ref["asset_id"])
    assert saved.evidence_json["reviewer_user_id"] == s.owner.id
    assert saved.policy_json["purpose"] == "image_transport"
