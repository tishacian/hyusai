from __future__ import annotations

from app.models.capability import Capability
from app.models.context import Context
from app.models.knowledge_collection import KnowledgeCollection
from app.models.rag_preset import RagPreset
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services import workspace_blueprints


def _workspace(db_session, *, id_: str, slug: str) -> Workspace:
    workspace = Workspace(id=id_, name=slug.title(), slug=slug, mode="executive")
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _user(db_session) -> User:
    user = User(id="user-1", username="builder", email="builder@example.test")
    db_session.add(user)
    db_session.flush()
    return user


def _reference_workspace(db_session) -> tuple[Workspace, User]:
    workspace = _workspace(db_session, id_="ws-source", slug="andritz")
    user = _user(db_session)
    skill = Skill(
        id="skill-rag",
        slug="llm_rag_answer_v1",
        name="RAG answer",
        workspace_id=None,
    )
    capability = Capability(
        id="cap-capture",
        workspace_id=workspace.id,
        slug="expert_knowledge_capture",
        name="Expert Knowledge Capture",
        description="Capture tacit expert knowledge.",
        skill_ids=[skill.id],
        pricing={"unit": "session", "unit_price": 0},
    )
    context = Context(
        id="ctx-andritz",
        workspace_id=workspace.id,
        name="Andritz MVP Knowledge Context",
        data_refs=["collection:andritz-secure-deposit"],
        environment_state={"site": "pilot"},
        ephemeral=False,
    )
    system = System(
        id="sys-capture",
        workspace_id=workspace.id,
        name="Expert Knowledge Capture",
        objective="Capture troubleshooting decisions from senior experts.",
        capability_id=capability.id,
        context_id=context.id,
        skill_ids=[skill.id],
        flow_definition={
            "nodes": [
                {
                    "id": "n1",
                    "kind": "task",
                    "config": {"skill_id": skill.id, "skill_slug": skill.slug},
                }
            ],
            "edges": [],
        },
        execution_mode="human_augmented",
        execution_profile={"voice_sla_ms": 1500},
        status="active",
    )
    collection = KnowledgeCollection(
        id="col-secure",
        workspace_id=workspace.id,
        slug="andritz-secure-deposit",
        name="Andritz Secure Deposit",
        description="Staged supplier files.",
        status="ready",
        document_names=["manual.pdf"],
        vector_collection_name="andritz_andritz-secure-deposit",
        artifact_prefix="workspaces/ws-source/collections/col-secure",
        document_count=1,
        chunk_count=12,
    )
    preset = RagPreset(
        id="preset-rag",
        workspace_id=workspace.id,
        name="Andritz default RAG",
        scope="workspace",
        config={"mode": "hybrid", "topK": 5},
        is_default=True,
    )
    db_session.add_all([skill, capability, context, system, collection, preset])
    db_session.flush()
    return workspace, user


def test_export_workspace_blueprint_excludes_sensitive_data(db_session):
    workspace, user = _reference_workspace(db_session)

    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=workspace,
        exported_by=user,
    )

    assert blueprint["kind"] == workspace_blueprints.BLUEPRINT_KIND
    assert blueprint["workspace"]["slug"] == "andritz"
    assert blueprint["systems"][0]["name"] == "Expert Knowledge Capture"
    assert blueprint["systems"][0]["capability_slug"] == "expert_knowledge_capture"
    assert blueprint["capabilities"][0]["skill_slugs"] == ["llm_rag_answer_v1"]
    assert blueprint["knowledge"]["collections"][0]["slug"] == "andritz-secure-deposit"
    assert blueprint["knowledge"]["exports_raw_documents"] is False
    assert blueprint["connectors"]["secure_deposit"]["exports_passwords"] is False
    assert blueprint["data_policy"]["workspace_members"] == "excluded"


def test_dry_run_reports_actions_without_writing(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=True,
    )

    assert report["dry_run"] is True
    assert report["created"]["systems"] == 1
    assert db_session.query(System).filter(System.workspace_id == target.id).count() == 0


def test_apply_workspace_blueprint_creates_draft_system_and_metadata(db_session):
    source, user = _reference_workspace(db_session)
    blueprint = workspace_blueprints.export_workspace_blueprint(
        db=db_session,
        workspace=source,
        exported_by=user,
    )
    target = _workspace(db_session, id_="ws-target", slug="target")

    report = workspace_blueprints.apply_workspace_blueprint(
        db=db_session,
        workspace=target,
        blueprint=blueprint,
        actor=user,
        dry_run=False,
    )
    db_session.commit()

    imported = (
        db_session.query(System)
        .filter(System.workspace_id == target.id, System.name == "Expert Knowledge Capture")
        .one()
    )
    collection = (
        db_session.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == target.id,
            KnowledgeCollection.slug == "andritz-secure-deposit",
        )
        .one()
    )

    assert report["created"]["systems"] == 1
    assert report["created"]["capabilities"] == 1
    assert imported.status == "draft"
    assert imported.execution_mode == "human_augmented"
    assert imported.capability_id is not None
    assert collection.document_count == 0
    assert collection.status == "created"
