"""Work charts cannot expand a Run reference into arbitrary dataset access."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.core.config import settings
from app.models.run import Run
from app.models.system import System
from app.models.tabular import TabularDataset
from app.models.user import User
from app.models.workspace import Workspace
from app.services import work_datasets as service
from app.services.experience.lifecycle import ExperienceError


@pytest.fixture()
def sample(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace = Workspace(id="ws-chart", name="Chart", slug="chart", settings={})
    user = User(id="user-chart", username="chart", email="chart@example.invalid", role="admin")
    system = System(id="system-chart", workspace_id=workspace.id, name="Forecast")
    release = SimpleNamespace(
        id="release-chart",
        pages={
            "pages": [
                {
                    "id": "capacity",
                    "components": [
                        {
                            "id": "forecast",
                            "type": "action_button",
                            "props": {"bindingKey": "forecast.run"},
                        },
                        {
                            "id": "curve",
                            "type": "chart",
                            "props": {
                                "kind": "timeseries",
                                "datasetSource": {
                                    "source": "run-output",
                                    "selector": "result.dataset_id",
                                    "componentId": "forecast",
                                },
                                "mapping": {"time": "day", "value": "pred"},
                            },
                        },
                    ],
                }
            ]
        },
        bindings_snapshot=[{"binding_key": "forecast.run", "system_id": system.id}],
    )
    experience = SimpleNamespace(id="experience-chart")
    run = Run(
        id="run-chart",
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        completed_at=datetime(2026, 10, 9),
        input_ref={
            "_ingress": {
                "adapter": {
                    "experience_id": experience.id,
                    "experience_release_id": release.id,
                    "binding_key": "forecast.run",
                    "page_id": "capacity",
                    "component_id": "forecast",
                }
            }
        },
        output_ref={"result": {"dataset_id": "dataset-chart"}},
    )
    dataset = TabularDataset(
        id="dataset-chart",
        workspace_id=workspace.id,
        name="Forecast",
        slug="forecast",
        status="ready",
        run_id=run.id,
        storage_key="forecast.parquet",
        row_count=2500,
    )
    pq.write_table(
        pa.table(
            {
                "day": [f"day-{i}" for i in range(2500)],
                "pred": range(2500),
                "private": ["hidden"] * 2500,
            }
        ),
        tmp_path / "forecast.parquet",
        row_group_size=500,
    )
    db_session.add_all([workspace, user, system, run, dataset])
    db_session.commit()
    return SimpleNamespace(
        workspace=workspace,
        user=user,
        experience=experience,
        release=release,
        run=run,
        dataset=dataset,
    )


def _read(db_session, sample):
    return service.work_dataset(
        db_session,
        workspace=sample.workspace,
        user=sample.user,
        experience=sample.experience,
        release=sample.release,
        page_id="capacity",
        component_id="curve",
        run_id=sample.run.id,
    )


def test_bounded_projection_and_explicit_truncation(db_session, sample, monkeypatch):
    # No entire-file read or materialization is allowed in this request path.
    from app.services.object_store import ObjectStore

    monkeypatch.setattr(ObjectStore, "read_bytes", lambda *args: pytest.fail("whole file read"))
    monkeypatch.setattr(ObjectStore, "copy_to_local", lambda *args: pytest.fail("whole file copy"))
    result = _read(db_session, sample)
    assert result["returned_rows"] == 1000
    assert result["total_rows"] == 2500
    assert result["truncated"] is True
    assert result["columns"] == ["day", "pred"]
    assert result["rows"][0] == {"day": "day-0", "pred": 0}
    assert result["rows"][-1]["pred"] == 999
    assert result["provenance"]["run_id"] == sample.run.id
    assert result["provenance"]["model_id"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("experience_id", "another-app"),
        ("experience_release_id", "old-release"),
        ("component_id", "another-action"),
        ("page_id", "another-page"),
        ("binding_key", "another.binding"),
    ],
)
def test_run_must_belong_to_exact_released_action(db_session, sample, field, value):
    changed = deepcopy(sample.run.input_ref)
    changed["_ingress"]["adapter"][field] = value
    sample.run.input_ref = changed
    db_session.flush()
    with pytest.raises(ExperienceError) as exc:
        _read(db_session, sample)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "object_name,field,value",
    [
        ("run", "workspace_id", "another-workspace"),
        ("run", "system_id", "another-system"),
        ("dataset", "workspace_id", "another-workspace"),
        ("dataset", "run_id", "another-run"),
        ("dataset", "status", "deleted"),
    ],
)
def test_dataset_cannot_cross_workspace_or_run(db_session, sample, object_name, field, value):
    setattr(getattr(sample, object_name), field, value)
    db_session.flush()
    with pytest.raises(ExperienceError) as exc:
        _read(db_session, sample)
    assert exc.value.status_code == 404


def test_run_read_denial_does_not_open_storage(db_session, sample, monkeypatch):
    monkeypatch.setattr(service, "readable_runs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        service, "read_projected_rows", lambda *args: pytest.fail("storage read before grant")
    )
    with pytest.raises(ExperienceError) as exc:
        _read(db_session, sample)
    assert exc.value.status_code == 404


def test_pending_producer_and_missing_columns_are_explicit(db_session, sample):
    sample.run.status = "running"
    db_session.flush()
    with pytest.raises(ExperienceError) as exc:
        _read(db_session, sample)
    assert exc.value.code == "WORK_DATASET_RUN_NOT_COMPLETE"
    sample.run.status = "completed"
    sample.release.pages["pages"][0]["components"][1]["props"]["mapping"]["value"] = "absent"
    with pytest.raises(ExperienceError) as exc:
        _read(db_session, sample)
    assert exc.value.code == "WORK_DATASET_COLUMN_MISSING"


@pytest.mark.parametrize("rows", [0, 1001, True, "1000"])
def test_limit_is_a_bounded_published_integer(sample, rows):
    sample.release.pages["pages"][0]["components"][1]["props"]["maxRows"] = rows
    with pytest.raises(ExperienceError) as exc:
        service.component_contract(sample.release, "capacity", "curve")
    assert exc.value.code == "WORK_DATASET_CONFIG_INVALID"


def test_selector_cannot_walk_arbitrary_objects(sample):
    sample.release.pages["pages"][0]["components"][1]["props"]["datasetSource"]["selector"] = (
        "__proto__.dataset_id"
    )
    with pytest.raises(ExperienceError) as exc:
        service.component_contract(sample.release, "capacity", "curve")
    assert exc.value.code == "WORK_DATASET_CONFIG_INVALID"


def test_optional_blank_columns_and_publication_validation(sample):
    props = sample.release.pages["pages"][0]["components"][1]["props"]
    props["mapping"].update({"series": "", "actual": "", "lower": "", "upper": ""})
    assert service.component_contract(sample.release, "capacity", "curve")["columns"] == [
        "day",
        "pred",
    ]
    assert service.validate_dataset_chart_configuration(sample.release.pages) == []
    props["mapping"]["lower"] = "lower_bound"
    issues = service.validate_dataset_chart_configuration(sample.release.pages)
    assert issues[0]["code"] == "WORK_DATASET_CONFIG_INVALID"
    assert issues[0]["component_id"] == "curve"
    props["mapping"]["upper"] = "upper_bound"
    assert service.validate_dataset_chart_configuration(sample.release.pages) == []
    props["datasetSource"]["componentId"] = "unpublished-action"
    assert service.validate_dataset_chart_configuration(sample.release.pages)


@pytest.mark.parametrize("source", ["static", "run-output"])
def test_inline_timeseries_does_not_need_dataset_source(sample, source):
    props = sample.release.pages["pages"][0]["components"][1]["props"]
    props.pop("datasetSource")
    if source == "static":
        props["items"] = [{"day": "2026-10-09", "pred": 42}]
    else:
        props["dataBinding"] = {
            "source": "run-output",
            "componentId": "forecast",
            "selector": "forecast",
        }
    assert service.validate_dataset_chart_configuration(sample.release.pages) == []
    # A null optional source has the same authoring meaning as an absent one.
    props["datasetSource"] = None
    assert service.validate_dataset_chart_configuration(sample.release.pages) == []


def test_remote_projection_uses_seekable_file_without_materialization(
    sample, tmp_path, monkeypatch
):
    calls = []

    def opened(key, mode, **kwargs):
        calls.append((key, mode, kwargs))
        return (tmp_path / "forecast.parquet").open(mode)

    store = SimpleNamespace(
        backend="s3",
        _remote_key=lambda key: "bucket/" + key,
        _fsspec=lambda: SimpleNamespace(open=opened),
    )
    monkeypatch.setattr(service, "get_object_store", lambda: store)
    rows, total = service.read_projected_rows(sample.dataset, ["day", "pred"], 25)
    assert len(rows) == 25
    assert total == 2500
    assert calls == [("bucket/forecast.parquet", "rb", {"block_size": 65536, "cache_type": "none"})]


def test_http_endpoint_resolves_release_and_honours_work_feature_flag(
    db_session, sample, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import work as endpoint

    app = FastAPI()
    app.include_router(endpoint.router, prefix="/work")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: sample.workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: sample.user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    resolved = []

    def resolve(*args, **kwargs):
        resolved.append(kwargs["slug"])
        return sample.experience, None, sample.release

    monkeypatch.setattr(endpoint, "_resolve_for_user", resolve)
    client = TestClient(app)
    url = "/work/capacity/datasets/capacity/curve?run_id=run-chart"
    assert client.get(url).status_code == 404
    assert resolved == []
    sample.workspace.settings = {"features": {"experience_v1": True}}
    db_session.flush()
    response = client.get(url + "&dataset_id=unrelated-dataset&maxRows=999999")
    assert response.status_code == 200, response.text
    assert resolved == ["capacity"]
    assert response.json()["returned_rows"] == 1000
    assert response.json()["provenance"]["dataset_id"] == "dataset-chart"


def test_http_endpoint_preserves_release_audience_refusal(db_session, sample, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import work as endpoint

    sample.workspace.settings = {"features": {"experience_v1": True}}
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/work")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: sample.workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: sample.user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session

    def denied(*args, **kwargs):
        raise ExperienceError(
            code="EXPERIENCE_NOT_FOUND", message="App not found.", status_code=404
        )

    monkeypatch.setattr(endpoint, "_resolve_for_user", denied)
    monkeypatch.setattr(
        service, "read_projected_rows", lambda *args: pytest.fail("read before audience check")
    )
    response = TestClient(app).get("/work/hidden-app/datasets/capacity/curve?run_id=run-chart")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPERIENCE_NOT_FOUND"
