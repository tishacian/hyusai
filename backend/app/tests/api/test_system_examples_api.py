from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chains import dag_validator
from app.services.systems import examples
from app.tests.iam_baseline import OPEN_IAM_FEATURES


def _seed(db_session, *, role: str = "admin", iam: dict | None = None):
    workspace = Workspace(
        id="ws-examples",
        slug="examples",
        name="Examples",
        settings={"family": "generic", "features": iam if iam is not None else dict(OPEN_IAM_FEATURES)},
    )
    user = User(id="u-examples", username="creator@example.invalid", email="creator@example.invalid", role=role)
    db_session.add_all([workspace, user])
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="admin" if role == "admin" else "member",
            role_template="workspace_admin" if role == "admin" else "workspace_viewer",
        )
    )
    db_session.commit()
    return workspace, user


def _client(db_session, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def test_every_builtin_example_is_a_valid_neutral_envelope():
    rows = examples.list_examples()
    assert rows, "the catalogue must not be empty"
    for row in rows:
        flow = row["envelope"]["system"]["flow_definition"]
        assert not dag_validator.has_errors(dag_validator.validate_flow(flow)), row["id"]
        assert row["provenance"] == {
            "publisher": "Agentium",
            "source": "builtin",
            "example_id": row["id"],
            "version": row["version"],
        }
        text = str(row).lower()
        for marker in ("northforge", "nawa", "andritz", "showcase"):
            assert marker not in text


def test_examples_are_listed_without_creating_anything(db_session):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).get("/systems/examples")
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["examples"]] == ["internal_procedures_assistant"]
    assert db_session.query(System).count() == 0


def test_preview_lists_objects_and_unresolved_dependencies_without_creating(db_session):
    workspace, user = _seed(db_session)
    envelope = examples.list_examples()[0]["envelope"]
    response = _client(db_session, workspace, user).post("/systems/import/preview", json={"envelope": envelope})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [node["id"] for node in body["nodes"]] == ["trigger", "answer", "output"]
    assert body["unresolved_skills"] == ["llm_rag_answer_v1"]
    assert body["resolved_skills"] == []
    assert body["valid"] is True
    assert body["source"] == {"example_id": "internal_procedures_assistant", "example_version": "1"}
    assert db_session.query(System).count() == 0


def test_preview_resolves_a_skill_the_catalogue_has(db_session):
    workspace, user = _seed(db_session)
    db_session.add(Skill(id="skill-rag", slug="llm_rag_answer_v1", name="RAG Answer", version="1"))
    db_session.commit()
    envelope = examples.list_examples()[0]["envelope"]
    body = _client(db_session, workspace, user).post("/systems/import/preview", json={"envelope": envelope}).json()
    assert body["resolved_skills"] == ["llm_rag_answer_v1"]
    assert body["unresolved_skills"] == []


def test_preview_rejects_a_malformed_envelope(db_session):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).post(
        "/systems/import/preview", json={"envelope": {"kind": "other"}}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_envelope"


def test_preview_goes_through_the_import_gate(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    seen = []

    def refuse(db, **kwargs):
        seen.append((kwargs["resource_kind"], kwargs["action"], kwargs["resource_attrs"]))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(systems, "enforce_action", refuse)
    envelope = examples.list_examples()[0]["envelope"]
    client = _client(db_session, workspace, user)
    assert client.post("/systems/import/preview", json={"envelope": envelope}).status_code == 403
    assert client.post("/systems/import", json={"envelope": envelope}).status_code == 403
    assert seen == [("system", "admin", {"mutation": "import"})] * 2
    assert db_session.query(System).count() == 0
