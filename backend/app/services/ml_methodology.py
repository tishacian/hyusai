"""Local, read-only ML methods adapted to Agentium's Skill/Flow contracts.

The selected Probabl practices are release assets, not an agent installation.
No model, rows, report store, generated Python or remote provider is needed to
frame a problem and propose the existing graph-owned training operations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.tabular_datasets import TabularError, get_dataset

METHOD_SKILLS = frozenset({"ml_problem_frame_v1", "ml_experiment_plan_v1"})
RESOURCE = Path(__file__).resolve().parents[1] / "resources/ml_methodology/probabl-v1.json"
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Column = Annotated[str, Field(min_length=1, max_length=200)]
Algorithm = Literal["linear", "gradient_boosting", "random_forest", "knn"]
Metric = Literal["accuracy", "f1_macro", "roc_auc", "mae", "rmse", "r2"]
METRICS = {
    "classification": {"accuracy": "maximize", "f1_macro": "maximize", "roc_auc": "maximize"},
    "regression": {"mae": "minimize", "rmse": "minimize", "r2": "maximize"},
}


def require_enabled() -> None:
    from app.core.config import settings

    if not settings.ml_methodology_enabled:
        raise TabularError(
            code="ML_METHODOLOGY_DISABLED",
            message="ML methodology advice is disabled on this deployment.",
            status_code=409,
        )


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class DatasetRef(StrictContract):
    id: str = Field(min_length=1, max_length=36)
    version: int = Field(ge=1)


class Split(StrictContract):
    kind: Literal["random", "temporal", "group", "predefined"]
    test_size: float = Field(ge=0.05, le=0.5)
    cross_validation: int = Field(ge=2, le=10)
    # Current classic harness has a fixed seed. Do not claim arbitrary seeds.
    random_state: Literal[42] = 42


class Budget(StrictContract):
    max_candidates: int = Field(ge=1, le=4)
    max_training_seconds: int = Field(ge=1, le=86400)
    # These are acceptance criteria, never advertised as enforced runtime caps.
    max_prediction_ms: float | None = Field(default=None, gt=0, le=3600000)
    max_memory_mb: int | None = Field(default=None, ge=128, le=1048576)


class ProblemFrameRequest(StrictContract):
    dataset: DatasetRef
    objective: Text | None = None
    decision_unit: Text | None = None
    prediction_moment: Text | None = None
    error_cost: Text | None = None
    task: Literal["classification", "regression"] | None = None
    target: Column | None = None
    available_features: list[Column] = Field(default_factory=list, max_length=128)
    availability_evidence: Text | None = None
    primary_metric: Metric | None = None
    baseline: Algorithm | None = None
    baseline_reason: Text | None = None
    split: Split | None = None
    budget: Budget | None = None
    acceptance_criteria: Text | None = None
    hypotheses: list[Text] = Field(default_factory=list, max_length=8)


class ExperimentPlanRequest(ProblemFrameRequest):
    candidates: list[Algorithm] = Field(default_factory=list, max_length=4)


class MethodEvidence(StrictContract):
    id: str
    version: str
    revision: str
    sha256: str
    runtime_sha256: str
    license: str


class Blocker(StrictContract):
    code: str
    field: str


class MethodResponse(StrictContract):
    schema_version: Literal[1] = 1
    mode: Literal["proposal_only"] = "proposal_only"
    status: Literal["needs_information", "blocked", "ready_for_review"]
    dataset: DatasetRef
    method: MethodEvidence
    frame: ProblemFrameRequest
    frame_sha256: str
    missing: list[str]
    blockers: list[Blocker]
    constraints: list[str]
    evidence_required: list[str]
    assumptions: list[str]
    metric_direction: Literal["maximize", "minimize"] | None = None
    flow_draft: dict[str, Any] | None = None
    candidates: list[str] = Field(default_factory=list)
    budget_enforcement: dict[str, Any] = Field(default_factory=dict)
    consumption: dict[str, Any] = Field(default_factory=dict)


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def _release_method() -> dict[str, Any]:
    document = json.loads(RESOURCE.read_text(encoding="utf-8"))
    return {
        "document": document,
        "sha256": _sha(document),
        "runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def method_snapshot() -> dict[str, Any]:
    """Detached release asset for SystemVersion's existing executor snapshot."""
    return copy.deepcopy(_release_method())


def frozen_method_executor(slug: str) -> dict[str, Any] | None:
    slug = str(slug or "").strip()
    if slug not in METHOD_SKILLS:
        return None
    return {
        "kind": "registry_call",
        "params": {"skill_slug": slug, "frozen_input": {"_method": method_snapshot()}},
    }


def freeze_method_in_binding(executor: dict) -> dict:
    result = copy.deepcopy(executor)
    if result.get("kind") == "registry_call":
        params = result.get("params") or {}
        method_binding = frozen_method_executor(params.get("skill_slug"))
        if method_binding is not None:
            result["params"] = {
                **params,
                "frozen_input": {
                    **(params.get("frozen_input") or {}),
                    **method_binding["params"]["frozen_input"],
                },
            }
    return result


def _method(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    release = method_snapshot()
    if snapshot is not None and snapshot != release:
        # A changed implementation must never silently reinterpret a published
        # method. Keep its producer runtime or explicitly republish the Flow.
        raise TabularError(
            code="ML_METHOD_VERSION_UNAVAILABLE",
            message="The published method needs its qualified producer runtime or republication.",
            status_code=409,
        )
    return release


def parse_request(payload: Any, *, planning: bool) -> ProblemFrameRequest:
    request_type = ExperimentPlanRequest if planning else ProblemFrameRequest
    try:
        return request_type.model_validate(payload)
    except ValidationError as exc:
        raise TabularError(
            code="ML_METHOD_INPUT_INVALID",
            message="The methodology input does not satisfy its typed contract.",
            details={"fields": [".".join(map(str, row["loc"])) for row in exc.errors()[:16]]},
        ) from exc


def _frame(db, *, workspace_id: str, request: ProblemFrameRequest, method) -> dict[str, Any]:
    if not workspace_id:
        raise TabularError(code="ML_METHOD_WORKSPACE_REQUIRED", message="Workspace is required.")
    dataset = get_dataset(
        db, dataset_id=request.dataset.id, workspace_id=workspace_id, ready_only=True
    )
    if dataset.version != request.dataset.version:
        raise TabularError(
            code="ML_METHOD_DATASET_VERSION_MISMATCH",
            message="The dataset version differs from the frozen problem definition.",
            status_code=409,
        )
    # Do not inspect previews, statistics or target distributions: those may
    # include the held-out test. Only the authorized table's schema is needed.
    columns = {column.get("name") for column in dataset.schema_json or []}
    missing = [
        key
        for key in ProblemFrameRequest.model_fields
        if key not in {"dataset", "hypotheses"} and not getattr(request, key)
    ]
    blockers: list[dict[str, str]] = []
    if request.target and request.target not in columns:
        blockers.append({"code": "ML_METHOD_TARGET_UNKNOWN", "field": "target"})
    if set(request.available_features) - columns:
        blockers.append({"code": "ML_METHOD_FEATURE_UNKNOWN", "field": "available_features"})
    if request.target in request.available_features:
        blockers.append({"code": "ML_METHOD_TARGET_LEAKAGE", "field": "available_features"})
    if len(request.available_features) != len(set(request.available_features)):
        blockers.append({"code": "ML_METHOD_FEATURE_DUPLICATE", "field": "available_features"})
    if (
        request.primary_metric
        and request.task
        and request.primary_metric not in METRICS[request.task]
    ):
        blockers.append({"code": "ML_METHOD_METRIC_TASK_MISMATCH", "field": "primary_metric"})
    if request.split and request.split.kind != "random":
        blockers.append({"code": "ML_METHOD_SPLIT_UNSUPPORTED", "field": "split.kind"})
    document = method["document"]
    frame = ProblemFrameRequest.model_validate(
        request.model_dump(exclude={"candidates"})
    ).model_dump()
    return {
        "schema_version": 1,
        "mode": "proposal_only",
        "status": "blocked" if blockers else "needs_information" if missing else "ready_for_review",
        "dataset": request.dataset.model_dump(),
        "method": {
            "id": document["id"],
            "version": document["version"],
            "revision": document["upstream"]["revision"],
            "sha256": method["sha256"],
            "runtime_sha256": method["runtime_sha256"],
            "license": document["upstream"]["license"],
        },
        "frame": frame,
        "frame_sha256": _sha(frame),
        "missing": missing,
        "blockers": blockers,
        "constraints": document["constraints"],
        "evidence_required": document["expected_evidence"],
        "assumptions": [
            "feature_availability_is_declared_not_verified",
            "business_value_not_measured",
        ],
        "metric_direction": METRICS.get(request.task, {}).get(request.primary_metric),
    }


def problem_frame(db, *, workspace_id: str, payload: Any, method: dict | None = None) -> dict:
    require_enabled()
    started = time.perf_counter()
    result = _frame(
        db,
        workspace_id=workspace_id,
        request=parse_request(payload, planning=False),
        method=_method(method),
    )
    return _finish(result, started)


def _draft(request: ExperimentPlanRequest, candidates: list[str], snapshot: dict) -> dict:
    """Existing explicit ML nodes only; acceptance/publication remains external."""
    source = {
        "id": "source.experiment",
        "type": "source",
        "kind": "source",
        "config": {
            "ingress_kind": "manual",
            "input_schema": {"type": "object", "additionalProperties": False},
        },
    }
    nodes, edges = [source], []
    for index, algo in enumerate(candidates):
        train_id, review_id = f"train.{index}", f"review.{index}"
        nodes.extend(
            [
                {
                    "id": train_id,
                    "kind": "task",
                    "type": "skill",
                    "config": {
                        "skill_slug": "ml_train_sklearn_v1",
                        "params": {
                            "task": request.task,
                            "target": request.target,
                            "features": request.available_features,
                            "algo": algo,
                            "test_size": request.split.test_size,
                            "cross_validation": request.split.cross_validation,
                            "spec": {"text_encoder": "auto", "tuning": "off"},
                            "sources": [{"dataset_id": request.dataset.id}],
                            "methodology": {
                                "frame": request.model_dump(exclude={"candidates"}),
                                "method": snapshot,
                                "candidate_count": len(candidates),
                            },
                        },
                    },
                },
                {
                    "id": review_id,
                    "kind": "task",
                    "type": "skill",
                    "config": {
                        "skill_slug": "ml_evaluation_review_v1",
                        "inputs_map": {"model_id": {"node_id": train_id, "path": ["model_id"]}},
                    },
                },
            ]
        )
        edges.extend(
            [
                {"from": source["id"], "to": train_id, "kind": "data"},
                {"from": train_id, "to": review_id, "kind": "data"},
                {"from": review_id, "to": "result", "kind": "data"},
            ]
        )
    nodes.append(
        {
            "id": "result",
            "kind": "sink",
            "type": "sink",
            "inputs": [
                {"name": f"review_{index}", "schema": "object", "required": True}
                for index in range(len(candidates))
            ],
            "config": {
                "inputs_map": {
                    f"review_{index}": {"node_id": f"review.{index}", "path": []}
                    for index in range(len(candidates))
                }
            },
        }
    )
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "methodology": {
                "frame": request.model_dump(exclude={"candidates"}),
                "method": snapshot,
                "state": "proposal",
                "required_capability": "tabular_models",
                "requires": [
                    "review_flow_plan",
                    "publish_system_version",
                    "explicit_run",
                    "explicit_promotion",
                ],
            }
        },
    }


def validate_methodology_flow(flow: dict) -> None:
    """Check that a published graph actually respects its candidate envelope."""
    from app.services.flow_node_kind import flow_node_kind

    groups: dict[str, list[tuple[dict, dict]]] = {}
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        params = config.get("params") or {}
        if not isinstance(params, dict) or params.get("methodology") is None:
            continue
        block = params["methodology"]
        if (
            config.get("skill_slug") != "ml_train_sklearn_v1"
            or not isinstance(block, dict)
            or set(block) != {"frame", "method", "candidate_count"}
            or not isinstance(block["method"], dict)
        ):
            raise TabularError(
                code="ML_METHOD_FLOW_INVALID", message="Invalid method training node."
            )
        _method(block["method"])
        frame = parse_request(block["frame"], planning=False)
        key = _sha({"frame": frame.model_dump(), "method": block["method"]})
        groups.setdefault(key, []).append((block, params))
    if not groups:
        metadata = flow.get("metadata")
        if isinstance(metadata, dict) and metadata.get("methodology") is not None:
            raise TabularError(
                code="ML_METHOD_FLOW_INVALID",
                message="The method proposal has no bound training nodes.",
            )
        return
    # A method envelope counts explicit one-shot training nodes. Repeating a
    # subtree would require a shared runtime budget mechanism, not another hint.
    if any(
        isinstance(node, dict)
        and flow_node_kind(node) in {"loop", "retry", "subflow", "agent_loop"}
        for node in nodes
    ):
        raise TabularError(
            code="ML_METHOD_FLOW_REPETITION_UNSUPPORTED",
            message="Method plans require explicit one-shot training nodes.",
        )
    for group in groups.values():
        frame = parse_request(group[0][0]["frame"], planning=False)
        algorithms = [params.get("algo") for _, params in group]
        if (
            frame.budget is None
            or len(group) > frame.budget.max_candidates
            or any(not isinstance(algo, str) for algo in algorithms)
            or len(set(algorithms)) != len(algorithms)
            or frame.baseline not in algorithms
            or any(
                type(block["candidate_count"]) is not int or block["candidate_count"] != len(group)
                for block, _ in group
            )
        ):
            raise TabularError(
                code="ML_METHOD_FLOW_CANDIDATE_BUDGET",
                message="The graph differs from its frozen candidate envelope.",
            )


def _training_timeout() -> float:
    from app.core.config import settings

    timeout = float(settings.ml_train_timeout_s)
    if not math.isfinite(timeout) or timeout <= 0:
        raise TabularError(
            code="ML_METHOD_RUNTIME_BUDGET_INVALID",
            message="A finite training timeout is required.",
        )
    return timeout


def validate_training_method(
    db, *, workspace_id: str, train: dict, dataset_ref: dict, flow: dict | None = None
) -> None:
    """Guard a method-generated training node immediately before submission.

    Only the DAG injects ``train``; a public Skill input cannot provide it.
    Ordinary pre-existing training nodes have no method block and keep their
    own contract. A generated node cannot claim a narrower unenforced budget.
    """
    block = train.get("methodology")
    if block is None:
        return
    require_enabled()
    if (
        not isinstance(block, dict)
        or set(block) != {"frame", "method", "candidate_count"}
        or not isinstance(block["method"], dict)
    ):
        raise TabularError(
            code="ML_METHOD_TRAIN_BINDING_INVALID", message="Invalid method binding."
        )
    _method(block["method"])
    if flow is not None:
        validate_methodology_flow(flow)
    frame = parse_request(block["frame"], planning=False)
    framed = _frame(db, workspace_id=workspace_id, request=frame, method=_method(block["method"]))
    count = block["candidate_count"]
    if (
        framed["status"] != "ready_for_review"
        or type(count) is not int
        or count < 1
        or count > frame.budget.max_candidates
        or _training_timeout() * count > frame.budget.max_training_seconds
        or dataset_ref.get("dataset_id") != frame.dataset.id
        or train.get("task") != frame.task
        or train.get("target") != frame.target
        or train.get("features") != frame.available_features
        or train.get("test_size") != frame.split.test_size
        or train.get("cross_validation") != frame.split.cross_validation
        or train.get("algo") not in {"linear", "gradient_boosting", "random_forest", "knn"}
        or train.get("knobs") not in (None, {})
        or train.get("spec") != {"text_encoder": "auto", "tuning": "off"}
    ):
        raise TabularError(
            code="ML_METHOD_TRAIN_BINDING_INVALID",
            message="The training node no longer satisfies its frozen method or budget.",
        )


def experiment_plan(db, *, workspace_id: str, payload: Any, method: dict | None = None) -> dict:
    from app.services.tabular_ml import validate_training

    require_enabled()
    started = time.perf_counter()
    request = parse_request(payload, planning=True)
    snapshot = _method(method)
    result = _frame(db, workspace_id=workspace_id, request=request, method=snapshot)
    candidates = list(dict.fromkeys([request.baseline, *request.candidates]))
    candidates = [candidate for candidate in candidates if candidate]
    result["candidates"] = candidates
    if result["status"] != "ready_for_review":
        return _finish(result, started)
    if len(candidates) > request.budget.max_candidates:
        result["blockers"].append({"code": "ML_METHOD_CANDIDATE_BUDGET", "field": "candidates"})
    if request.primary_metric == "f1_macro":
        # The current cards expose f1 (positive-class for binary tasks), not
        # a guaranteed macro-averaged development metric. Do not rename it.
        result["blockers"].append(
            {"code": "ML_METHOD_METRIC_UNAVAILABLE", "field": "primary_metric"}
        )
    # The current training supervisor enforces an instance-wide timeout. A
    # smaller desired total cannot honestly be promised by adding graph prose.
    per_model = _training_timeout()
    ceiling = per_model * len(candidates)
    result["budget_enforcement"] = {
        "max_candidates": len(candidates),
        "per_training_timeout_s": per_model,
        "total_training_ceiling_s": ceiling,
        "prediction_latency": "acceptance_only",
        "memory": "acceptance_only",
        "recheck_runtime_policy_at_execution": True,
    }
    if ceiling > request.budget.max_training_seconds:
        result["blockers"].append(
            {
                "code": "ML_METHOD_TRAINING_BUDGET_UNENFORCEABLE",
                "field": "budget.max_training_seconds",
            }
        )
    dataset = get_dataset(
        db, dataset_id=request.dataset.id, workspace_id=workspace_id, ready_only=True
    )
    for index, algo in enumerate(candidates):
        try:
            validate_training(
                dataset,
                task=request.task,
                target=request.target,
                features=request.available_features,
                algo=algo,
                test_size=request.split.test_size,
                cross_validation=request.split.cross_validation,
                spec={"text_encoder": "auto", "tuning": "off"},
                db=db,
            )
        except TabularError as exc:
            result["blockers"].append({"code": exc.code, "field": f"candidates.{index}"})
    if result["blockers"]:
        result["status"] = "blocked"
    else:
        result["flow_draft"] = _draft(request, candidates, snapshot)
    return _finish(result, started)


def _finish(result: dict, started: float) -> dict:
    result["consumption"] = {
        "provider_calls": 0,
        "tokens": 0,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "estimated_training_cost": None,
    }
    return MethodResponse.model_validate(result).model_dump()


def skill_definitions() -> list[dict[str, Any]]:
    descriptions = [
        (
            "ml_problem_frame_v1",
            "Frame ML Problem",
            ProblemFrameRequest,
            "Frame a workspace dataset's prediction objective, feature availability, baseline, metric, split and budget. Unknown facts remain explicit. Local, read-only and development-only.",
        ),
        (
            "ml_experiment_plan_v1",
            "Plan ML Experiment",
            ExperimentPlanRequest,
            "Propose a bounded draft Flow using existing explicit training and development-review nodes. Never trains, publishes, promotes, installs packages or reads final-test scores.",
        ),
    ]
    return [
        {
            "slug": slug,
            "version": "1",
            "name": name,
            "description": description,
            "type": "workflow",
            "provider": "internal",
            "certification_level": "beta",
            "execution": {
                "mode": "sync",
                "timeout_ms": 30000,
                "retryable": False,
                "idempotent": True,
            },
            "pricing": {"unit": "per_call", "unit_price": 0.0, "currency": "USD"},
            "input_schema": model.model_json_schema(),
            "output_schema": MethodResponse.model_json_schema(),
        }
        for slug, name, model, description in descriptions
    ]
