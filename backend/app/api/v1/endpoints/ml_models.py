"""Model plane API: the algorithm catalog, training runs and the registry.

Workspace-scoped. The endpoint never fits anything: a training request is
validated synchronously — so a bad target is a form error and not the terminal
status of a job — then handed to ``agentium.ml_train``, which folds the metrics,
the curves and the input contract back into the row. Every read here is one
indexed SELECT, which is what lets the Models page poll a run without cost.

``/plan`` exists for the same reason the SQL workshop resolves its catalog before
any run: the form has to be able to say what a choice implies (the task a target
suggests, the features it leaves, the columns that will not generalize) before
the author commits to a fit.

The serving half of the plane lives here too — ``/predict`` for the playground,
``/keys`` to mint the credential a customer's system uses, ``/publish`` to turn a
lineage into a Skill an agent can call — with one shared rule: a prediction is
answered by the version the lineage promoted, and the answer says which one that
was. Pinning a version stays possible, explicitly, per request.

``/predict`` is deliberately **one** route with two ways to prove who you are: a
workspace session for the playground, or a model-scoped API key in ``X-API-Key``
for a customer's system. Two routes would be two contracts to keep honest, and
the demo's whole point is that the cURL on the slide hits the same endpoint the
UI does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace, security
from app.core.config import settings
from app.db.base import get_db
from app.models.tabular import MLModel, TabularDataset
from app.models.user import User
from app.models.workspace import Workspace
from app.services import ml_comparison
from app.services.tabular_datasets import (
    TabularError,
    resolve_dataset_ref,
    serialize_dataset,
)
from app.services.tabular_ml import (
    catalog_payload,
    delete_model,
    get_model,
    infer_task,
    pipeline_provenance,
    request_cancel,
    runner_up,
    serialize_model,
    set_champion,
    submit_training,
    validate_training,
)
from app.services.tabular_monitoring import (
    attach_feedback,
    badges_for,
    materialize_labeled,
    report as monitoring_report,
    serialize_prediction,
)
from app.services.tabular_predict import (
    API_KEY_HEADER,
    authenticate_key,
    mint_api_key,
    predict_rows,
    publish_as_skill,
    revoke_api_key,
    serialize_api_key,
    serving_block,
    unpublish_skill,
)

router = APIRouter()


def _raise_tabular(exc: TabularError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _lineage(db: DBSession, *, workspace: Workspace, model: MLModel) -> dict[str, Any]:
    """Every version of a lineage, and which of them is the challenger.

    The challenger is named here rather than worked out in the browser because
    it is the same fact the registry's ``@challenger`` alias records, and one
    rule that two places implement is a rule that will disagree with itself.
    """

    versions = (
        db.query(MLModel)
        .filter(MLModel.workspace_id == workspace.id, MLModel.slug == model.slug)
        .order_by(MLModel.version.desc())
        .limit(50)
        .all()
    )
    champion = next((row for row in versions if row.is_champion), model)
    contender = runner_up(db, champion)
    return {
        "versions": [serialize_model(row, include_scores=True) for row in versions],
        "challenger_id": contender.id if contender is not None else None,
    }


class TrainBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: Optional[str] = Field(default=None, max_length=36)
    dataset_slug: Optional[str] = Field(default=None, max_length=200)
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2_000)
    task: Optional[str] = Field(default=None, max_length=20)
    target: str = Field(default="", max_length=200)
    features: list[str] = Field(default_factory=list, max_length=512)
    algo: Optional[str] = Field(default=None, max_length=80)
    knobs: dict[str, float] = Field(default_factory=dict)
    test_size: Optional[float] = Field(default=None, ge=0.05, le=0.5)
    cross_validation: Optional[int] = Field(default=None, ge=0, le=10)

    def dataset_ref(self) -> dict[str, Any]:
        if self.dataset_id:
            return {"dataset_id": self.dataset_id}
        return {"slug": self.dataset_slug or ""}


@router.get("")
async def list_models(
    task: Optional[str] = Query(default=None, max_length=20),
    status: Optional[str] = Query(default=None, max_length=16),
    dataset_id: Optional[str] = Query(default=None, max_length=36),
    limit: int = Query(default=100, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    query = db.query(MLModel).filter(MLModel.workspace_id == workspace.id)
    if task:
        query = query.filter(MLModel.task == task)
    if status:
        query = query.filter(MLModel.status == status)
    if dataset_id:
        query = query.filter(MLModel.dataset_id == dataset_id)
    models = query.order_by(MLModel.created_at.desc()).limit(limit).all()
    badges = badges_for(db, models)
    return {
        "models": [
            serialize_model(row, monitor_status=badges.get(row.id)) for row in models
        ],
        "catalog": catalog_payload(),
    }


@router.get("/catalog")
async def get_catalog(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """Algorithms, their knobs and the platform's training limits."""

    return {"catalog": catalog_payload()}


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: Optional[str] = Field(default=None, max_length=36)
    dataset_slug: Optional[str] = Field(default=None, max_length=200)
    target: Optional[str] = Field(default=None, max_length=200)
    task: Optional[str] = Field(default=None, max_length=20)
    features: list[str] = Field(default_factory=list, max_length=512)
    algo: Optional[str] = Field(default=None, max_length=80)

    def dataset_ref(self) -> dict[str, Any]:
        if self.dataset_id:
            return {"dataset_id": self.dataset_id}
        return {"slug": self.dataset_slug or ""}


@router.post("/plan")
async def plan_training(
    body: PlanBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """What a training request would be, without running it.

    With a target: the resolved plan (task, features, knob defaults, warnings) or
    the coded refusal the form should render inline. Without one: the dataset's
    candidate targets, each carrying the task it suggests, so the first choice
    the author makes is already informed.
    """

    try:
        dataset = resolve_dataset_ref(
            db, workspace_id=workspace.id, ref=body.dataset_ref()
        )
    except TabularError as exc:
        _raise_tabular(exc)

    profiles = dataset.stats_json if isinstance(dataset.stats_json, dict) else {}
    columns = []
    for column in dataset.schema_json or []:
        name = str(column.get("name") or "")
        if not name:
            continue
        profile = profiles.get(name)
        profile = profile if isinstance(profile, dict) else {}
        columns.append(
            {
                "name": name,
                "kind": str(column.get("kind") or "other"),
                "distinct": int(profile.get("distinct") or 0),
                "nulls": int(profile.get("nulls") or 0),
                # The whole profile, in the shape `<ck-data-table>` already reads,
                # so the picker draws the same sparkline as the dataset page
                # instead of asking for the dataset a second time. Bounded by the
                # histogram-bin and top-value settings, so it stays small enough
                # to ride along on a form that is re-planned on every keystroke.
                "profile": profile,
                "suggested_task": infer_task(dataset, name),
            }
        )
    payload: dict[str, Any] = {
        "dataset": serialize_dataset(dataset),
        "columns": columns,
        "catalog": catalog_payload(),
        "plan": None,
        "refusal": None,
    }
    if not (body.target or "").strip():
        return payload

    try:
        spec = validate_training(
            dataset,
            task=body.task,
            target=body.target,
            features=body.features,
            algo=body.algo,
        )
    except TabularError as exc:
        # A refusal is an answer here, not an error: the form renders it against
        # the field that caused it while the author keeps editing.
        payload["refusal"] = exc.payload()
        return payload

    payload["plan"] = {
        "task": spec.task,
        "target": spec.target,
        "features": spec.features,
        "algo": spec.algo.key,
        "estimator": spec.algo.estimator_for(spec.task),
        "knobs": spec.knobs,
        "test_size": spec.test_size,
        "cross_validation": spec.cross_validation,
        "name": spec.name,
        "warnings": spec.warnings,
        "rows": int(dataset.row_count or 0),
    }
    return payload


@router.post("")
async def train_model(
    body: TrainBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Validate a training request and dispatch it; the row is the tracker."""

    if not settings.ml_train_enabled:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ml_train_disabled",
                "code": "ML_TRAIN_DISABLED",
                "message": "Model training is not enabled on this deployment.",
            },
        )
    try:
        model = submit_training(
            db,
            workspace_id=workspace.id,
            dataset_ref=body.dataset_ref(),
            task=body.task,
            target=body.target,
            features=body.features,
            algo=body.algo,
            knobs=body.knobs,
            test_size=body.test_size,
            cross_validation=body.cross_validation,
            name=body.name,
            description=body.description,
            created_by=getattr(user, "id", None),
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {"model": serialize_model(model, include_detail=True)}


@router.get("/{model_id}")
async def get_model_detail(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """The model card: metrics, curves, the input contract and the lineage."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    dataset = (
        db.query(TabularDataset)
        .filter(TabularDataset.id == model.dataset_id)
        .first()
        if model.dataset_id
        else None
    )
    badges = badges_for(db, [model])
    return {
        "model": serialize_model(
            model, include_detail=True, monitor_status=badges.get(model.id)
        ),
        "dataset": serialize_dataset(dataset) if dataset is not None else None,
        "provenance": pipeline_provenance(db, model=model),
        **_lineage(db, workspace=workspace, model=model),
        "catalog": catalog_payload(),
        "serving": serving_block(db, model),
    }


@router.get("/{model_id}/comparison")
async def compare_model_versions(
    model_id: str,
    against: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Two versions scored on one test split, as skore's comparison table.

    Distinct from the deltas on the card, which subtract two recorded results:
    this re-scores both pipelines over the same rows, so the gap is a property of
    the models rather than of two different samples.

    In a worker thread for the same reason as ``predict``, only more so: this
    reads a Parquet holdout and runs two pipelines over all of it.
    """

    try:
        left = get_model(db, model_id=against, workspace_id=workspace.id)
        right = get_model(db, model_id=model_id, workspace_id=workspace.id)
        table = await run_in_threadpool(ml_comparison.compare, db, left=left, right=right)
    except TabularError as exc:
        _raise_tabular(exc)
    return table


@router.post("/{model_id}/cancel")
async def cancel_model_training(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Flip the cooperative stop flag; the worker kills the fit's process group."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    model = request_cancel(db, model)
    return {"model": serialize_model(model)}


@router.post("/{model_id}/champion")
async def promote_model(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Point the lineage's serving alias at this version."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        model = set_champion(db, model)
    except TabularError as exc:
        _raise_tabular(exc)
    return {
        "model": serialize_model(model, include_detail=True),
        **_lineage(db, workspace=workspace, model=model),
    }


@router.delete("/{model_id}")
async def remove_model(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    return {"deleted": delete_model(db, model)}


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------


class PredictBody(BaseModel):
    """MLflow's serving shape, so the demo cURL is the one the audience knows.

    ``inputs`` is what ``mlflow models serve`` takes and what this reads first;
    ``dataframe_records`` is MLflow's other record-oriented name for the same
    thing and is accepted so a client written against either lands. ``rows`` is
    this platform's own spelling, kept because the Playground and the Flow node
    speak it.
    """

    model_config = ConfigDict(extra="forbid")

    inputs: Optional[list[dict[str, Any]]] = Field(default=None, max_length=1_000)
    dataframe_records: Optional[list[dict[str, Any]]] = Field(
        default=None, max_length=1_000
    )
    rows: Optional[list[dict[str, Any]]] = Field(default=None, max_length=1_000)
    # Absent means "whatever serves this lineage", which is the behaviour an
    # integration wants; a number is a caller asking for reproducibility.
    version: Optional[int] = Field(default=None, ge=1)
    # Off by default: a counterfactual explanation costs a second predict, and a
    # batch integration scoring a thousand rows never wants it.
    explain: bool = False

    def records(self) -> list[dict[str, Any]]:
        for candidate in (self.inputs, self.dataframe_records, self.rows):
            if candidate is not None:
                return candidate
        return []


@dataclass(slots=True)
class PredictCaller:
    """Who is asking, once either credential has been resolved to a workspace."""

    workspace_id: str
    kind: str
    user_id: Optional[str] = None
    # Set for a key: the one lineage it may call. A version within that lineage
    # is fair game, because following a promotion is what the key is for.
    lineage: Optional[str] = None

    def authorize(self, model: MLModel) -> None:
        if self.kind != "api_key" or self.lineage is None:
            return
        if str(model.slug) != self.lineage:
            raise TabularError(
                code="ML_KEY_WRONG_MODEL",
                message="That key is not scoped to this model.",
                status_code=403,
            )


def predict_caller(
    x_api_key: Optional[str] = Header(default=None, alias=API_KEY_HEADER),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_workspace_slug: Optional[str] = Header(default=None, alias="X-Workspace-Slug"),
    db: DBSession = Depends(get_db),
) -> PredictCaller:
    """Resolve either credential to the workspace whose models may be called.

    A model-scoped key wins when present, and it carries its own workspace: that
    is the whole point of minting it per model — the holder of a churn key cannot
    read a dataset, list a Skill, or call another model, because nothing else on
    this API accepts the header at all. Absent a key, this is an ordinary
    workspace session and the ordinary session rules apply, unchanged.
    """

    if x_api_key:
        try:
            _, model = authenticate_key(db, x_api_key)
        except TabularError as exc:
            _raise_tabular(exc)
        return PredictCaller(
            workspace_id=model.workspace_id, kind="api_key", lineage=str(model.slug)
        )

    user = get_current_user(credentials=credentials, db=db)
    workspace = get_current_workspace(user=user, x_workspace_slug=x_workspace_slug, db=db)
    return PredictCaller(
        workspace_id=workspace.id, kind="session", user_id=getattr(user, "id", None)
    )


@router.post("/{model_id}/predict")
async def predict(
    model_id: str,
    body: PredictBody,
    caller: PredictCaller = Depends(predict_caller),
    db: DBSession = Depends(get_db),
):
    """Score rows now, in the request. The Playground's call and the cURL's.

    Runs in a worker thread: a fitted pipeline's ``predict`` is C code that does
    not yield, so scoring on the event loop would stall every other request for
    its duration.
    """

    try:
        model = get_model(db, model_id=model_id, workspace_id=caller.workspace_id)
        caller.authorize(model)
        answer = await run_in_threadpool(
            predict_rows,
            db,
            model,
            body.records(),
            version=body.version,
            caller=caller.kind,
            explain=body.explain,
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return answer


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str = Field(min_length=8, max_length=36)
    label: str = Field(min_length=1, max_length=200)


@router.get("/{model_id}/monitoring")
async def get_monitoring(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """PSI, score drift and the rolling AUC, from the serving journal."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    return {"monitoring": monitoring_report(db, model=model)}


@router.post("/{model_id}/feedback")
async def post_feedback(
    model_id: str,
    body: FeedbackBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Attach the ground truth to the prediction_id /predict handed back."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        row = attach_feedback(
            db,
            model=model,
            prediction_id=body.prediction_id,
            label=body.label,
            labeled_by=getattr(user, "id", None),
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {
        "prediction": serialize_prediction(row),
        "monitoring": monitoring_report(db, model=model),
    }


@router.post("/{model_id}/feedback/dataset")
async def post_feedback_dataset(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Materialize labeled journal rows as a dataset the studio can retrain on."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        dataset = materialize_labeled(
            db, model=model, created_by=getattr(user, "id", None)
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {"dataset": serialize_dataset(dataset)}


class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, max_length=200)


@router.get("/{model_id}/keys")
async def list_keys(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
    except TabularError as exc:
        _raise_tabular(exc)
    return {"serving": serving_block(db, model)}


@router.post("/{model_id}/keys")
async def create_key(
    model_id: str,
    body: KeyBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Mint a key for this lineage. The secret is in this response and nowhere else."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        row, secret = mint_api_key(
            db, model=model, name=body.name, created_by=getattr(user, "id", None)
        )
    except TabularError as exc:
        _raise_tabular(exc)
    return {
        "key": serialize_api_key(row, secret=secret),
        "serving": serving_block(db, model),
    }


@router.delete("/{model_id}/keys/{key_id}")
async def revoke_key(
    model_id: str,
    key_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        revoke_api_key(db, model=model, key_id=key_id)
    except TabularError as exc:
        _raise_tabular(exc)
    return {"serving": serving_block(db, model)}


@router.post("/{model_id}/publish")
async def publish(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Expose the lineage as a workspace Skill, typed from the model's contract."""

    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        skill = publish_as_skill(
            db, model=model, created_by=getattr(user, "id", None)
        )
    except TabularError as exc:
        _raise_tabular(exc)
    db.expire(model)
    return {
        "skill": skill,
        "model": serialize_model(model, include_detail=True),
        "serving": serving_block(db, model),
    }


@router.delete("/{model_id}/publish")
async def unpublish(
    model_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        model = get_model(db, model_id=model_id, workspace_id=workspace.id)
        withdrawn = unpublish_skill(db, model=model)
    except TabularError as exc:
        _raise_tabular(exc)
    db.expire(model)
    return {
        "withdrawn": withdrawn,
        "model": serialize_model(model, include_detail=True),
        "serving": serving_block(db, model),
    }
