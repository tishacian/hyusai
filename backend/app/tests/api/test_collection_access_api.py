"""L35 — per-collection access, enforced on every path a collection's content can leak.

Default: every member reads, every role except viewer writes. A restricted
collection does not exist (404) for a member without read, is absent from
lists, and is never retrieved nor cited — in chat, the assistant, a skill,
deep retrieval or ``/documents/search`` — whatever the client sends.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.v1.endpoints import chat, documents, knowledge
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import collection_access as access
from app.services.knowledge_collections import create_collection
from app.services.rag import context as rag_context

ADMIN_ONLY = {"read": ["role:workspace_admin"], "write": ["role:workspace_admin"]}


def _client(db_session, workspace: Workspace, user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")
    user = db_session.get(User, user_id) or SimpleNamespace(id=user_id, email=None, username=user_id)
    app.dependency_overrides[documents.get_current_workspace] = lambda: workspace
    app.dependency_overrides[documents.get_current_user] = lambda: user
    app.dependency_overrides[documents.get_db] = lambda: db_session
    return TestClient(app)


def _knowledge_client(db_session, workspace: Workspace, user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/knowledge")
    app.dependency_overrides[knowledge.get_current_workspace] = lambda: workspace
    app.dependency_overrides[knowledge.get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[knowledge.get_db] = lambda: db_session
    return TestClient(app)


def _member(db_session, workspace: Workspace, *, user_id: str, role_template: str, labels=None) -> User:
    user = User(id=user_id, username=user_id, email=f"{user_id}@example.test")
    db_session.add(user)
    db_session.add(
        WorkspaceMember(
            user_id=user_id,
            workspace_id=workspace.id,
            role="member" if role_template not in {"workspace_admin", "workspace_owner"} else "admin",
            role_template=role_template,
            custom_labels=labels or [],
        )
    )
    return user


def _workspace(db_session, wid: str, **kwargs) -> Workspace:
    workspace = Workspace(id=wid, name=wid, slug=wid, **kwargs)
    db_session.add(workspace)
    return workspace


def _stub_ingest(monkeypatch):
    async def _fake_queue(*, db, workspace, collection, files):
        return {"collection_id": collection.id, "collection_slug": collection.slug, "job_id": "job-1",
                "celery_task_id": None, "status": "queued", "collection_status": "queued", "files": []}

    monkeypatch.setattr(documents, "_queue_collection_ingest", _fake_queue)


def _upload(client, collection_id):
    return client.post(
        f"/documents/collections/{collection_id}/documents",
        files={"files": ("note.txt", b"read me", "text/plain")},
    )


# --------------------------------------------------------------- default


def test_default_policy_every_member_reads_viewer_cannot_upload_writer_can(db_session, monkeypatch):
    _stub_ingest(monkeypatch)
    workspace = _workspace(db_session, "ws-default")
    _member(db_session, workspace, user_id="viewer", role_template="workspace_viewer")
    _member(db_session, workspace, user_id="writer", role_template="workspace_contributor")
    collection = create_collection(db_session, workspace=workspace, name="Open")
    db_session.commit()

    for user_id in ("viewer", "writer"):
        client = _client(db_session, workspace, user_id)
        assert client.get("/documents/collections").json()["collections"] == [collection.slug]
        assert client.get(f"/documents/collections/{collection.id}/inventory").status_code == 200

    viewer = _upload(_client(db_session, workspace, "viewer"), collection.id)
    assert viewer.status_code == 403
    assert viewer.json()["detail"]["code"] == "COLLECTION_WRITE_DENIED"
    # The legacy name-based upload used to let viewers through.
    legacy = _client(db_session, workspace, "viewer").post(
        "/documents/upload-batch",
        data={"collection_name": collection.slug},
        files={"files": ("note.txt", b"x", "text/plain")},
    )
    assert legacy.status_code == 403
    assert _upload(_client(db_session, workspace, "writer"), collection.id).status_code == 200


# ------------------------------------------------------------ restricted


def test_restricted_collection_is_404_and_absent_for_a_member_without_read(db_session, monkeypatch):
    _stub_ingest(monkeypatch)
    workspace = _workspace(db_session, "ws-restricted")
    _member(db_session, workspace, user_id="contrib", role_template="workspace_contributor")
    open_collection = create_collection(db_session, workspace=workspace, name="Open")
    hidden = create_collection(db_session, workspace=workspace, name="Hidden Contracts")
    hidden.access = ADMIN_ONLY
    db_session.commit()
    client = _client(db_session, workspace, "contrib")

    listed = client.get("/documents/collections").json()
    assert listed["collections"] == [open_collection.slug]
    assert hidden.id not in {item["id"] for item in listed["items"]}

    for url, params in [
        (f"/documents/collections/{hidden.id}", {}),
        (f"/documents/collections/{hidden.slug}/inventory", {}),
        (f"/documents/collections/{hidden.id}/diagnostics", {}),
        ("/documents/list", {"collection_name": hidden.slug}),
        ("/documents/preview/doc-1", {"collection_name": hidden.slug}),
        ("/documents/file/doc-1", {"collection_name": hidden.slug}),
        ("/documents/doc-1/raw", {"collection_name": hidden.slug, "filename": "a.pdf"}),
        ("/documents/doc-1/metadata", {"collection_name": hidden.slug}),
        ("/documents/chunks", {"collection_name": hidden.slug}),
        ("/documents/stats", {"collection_name": hidden.slug}),
        ("/documents/document-facts", {"collection_name": hidden.slug}),
        ("/documents/jobs", {"collection_id": hidden.id}),
    ]:
        response = client.get(url, params=params)
        assert response.status_code == 404, (url, response.status_code, response.text)
    assert client.post("/documents/search", json={"query": "q", "collection_name": hidden.slug}).status_code == 404
    assert client.post(
        "/documents/search", json={"query": "q", "filters": {"collection_slug": hidden.id}}
    ).status_code == 404
    # Upload is refused without disclosing the collection, by id or by its name.
    assert _upload(client, hidden.id).status_code == 404
    assert client.post(
        "/documents/upload-batch",
        data={"collection_name": "Hidden Contracts"},
        files={"files": ("n.txt", b"x", "text/plain")},
    ).status_code == 404
    assert client.delete(f"/documents/collections/{hidden.slug}").status_code == 404


def test_grants_by_role_user_and_group_and_write_needs_its_own_grant(db_session, monkeypatch):
    _stub_ingest(monkeypatch)
    workspace = _workspace(db_session, "ws-grants")
    _member(db_session, workspace, user_id="reviewer", role_template="workspace_reviewer")
    _member(db_session, workspace, user_id="named", role_template="workspace_contributor")
    _member(db_session, workspace, user_id="buyer", role_template="workspace_contributor", labels=["buyers"])
    _member(db_session, workspace, user_id="outsider", role_template="workspace_contributor")
    _member(db_session, workspace, user_id="viewer", role_template="workspace_viewer", labels=["buyers"])
    collection = create_collection(db_session, workspace=workspace, name="Suppliers")
    collection.access = {
        "read": ["role:workspace_reviewer", "user:named", "group:buyers"],
        "write": ["user:named", "group:buyers"],
    }
    db_session.commit()

    for user_id in ("reviewer", "named", "buyer", "viewer"):
        assert _client(db_session, workspace, user_id).get(
            f"/documents/collections/{collection.id}"
        ).status_code == 200, user_id
    assert _client(db_session, workspace, "outsider").get(f"/documents/collections/{collection.id}").status_code == 404

    # Readable but not writable: 403. Viewers never write, even when granted.
    assert _upload(_client(db_session, workspace, "reviewer"), collection.id).status_code == 403
    assert _upload(_client(db_session, workspace, "viewer"), collection.id).status_code == 403
    assert _upload(_client(db_session, workspace, "named"), collection.id).status_code == 200
    assert _upload(_client(db_session, workspace, "buyer"), collection.id).status_code == 200
    detail = _client(db_session, workspace, "reviewer").get(f"/documents/collections/{collection.id}").json()
    assert detail["permissions"] == {"can_read": True, "can_write": False, "can_manage": False}


def test_write_implies_read_and_legacy_role_column_grants_nothing():
    viewer = WorkspaceMember(user_id="v", workspace_id="w", role="member", role_template="workspace_viewer")
    contrib = WorkspaceMember(user_id="c", workspace_id="w", role="member", role_template="workspace_contributor")
    write_only = SimpleNamespace(access={"read": ["role:workspace_reviewer"], "write": ["role:workspace_contributor"]})
    assert access.can_write_collection(contrib, write_only) is False
    assert access.can_read_collection(contrib, write_only) is False
    # ``role:member`` is not a canonical role: rejected, and never matched.
    with pytest.raises(ValueError):
        access.normalize_collection_access({"read": ["role:member"]})
    assert access.can_read_collection(viewer, SimpleNamespace(access={"read": ["role:member"]})) is False
    # A write restriction alone keeps reading open.
    assert access.normalize_collection_access({"write": ["user:c"], "read": None}) == {"write": ["user:c"]}
    assert access.can_read_collection(viewer, SimpleNamespace(access={"write": ["user:c"]})) is True


def test_another_workspace_collection_is_never_visible(db_session):
    mine = _workspace(db_session, "ws-mine")
    theirs = _workspace(db_session, "ws-theirs")
    _member(db_session, mine, user_id="admin-mine", role_template="workspace_admin")
    foreign = create_collection(db_session, workspace=theirs, name="Theirs")
    db_session.commit()
    client = _client(db_session, mine, "admin-mine")

    assert client.get("/documents/collections").json()["items"] == []
    assert client.get(f"/documents/collections/{foreign.id}").status_code == 404
    assert client.get(f"/documents/collections/{foreign.id}/inventory").status_code == 404


def test_admin_restricts_a_collection_and_the_change_is_audited(db_session):
    workspace = _workspace(db_session, "ws-admin")
    _member(db_session, workspace, user_id="admin", role_template="workspace_admin")
    _member(db_session, workspace, user_id="contrib", role_template="workspace_contributor")
    collection = create_collection(db_session, workspace=workspace, name="Contracts")
    db_session.commit()
    client = _client(db_session, workspace, "admin")
    policy = {"read": ["user:admin", "role:workspace_reviewer"], "write": ["user:admin"]}

    patched = client.patch(f"/documents/collections/{collection.id}", json={"access": policy})
    assert patched.status_code == 200, patched.text
    assert patched.json()["access"] == policy
    assert patched.json()["permissions"]["can_manage"] is True
    # Same policy again: nothing changes, nothing is audited twice.
    assert client.patch(f"/documents/collections/{collection.id}", json={"access": policy}).status_code == 200
    reopened = client.patch(f"/documents/collections/{collection.id}", json={"access": None})
    assert reopened.json()["access"] is None

    events = (
        db_session.query(AuditLog)
        .filter_by(workspace_id=workspace.id, event_type="knowledge.collection.access_changed")
        .order_by(AuditLog.timestamp.asc())
        .all()
    )
    assert [(e.details["before"], e.details["after"]) for e in events] == [(None, policy), (policy, None)]
    assert events[0].actor == "admin@example.test"
    assert events[0].details["collection"]["id"] == collection.id

    # Only admins edit, members are validated, legacy roles are refused.
    assert _client(db_session, workspace, "contrib").patch(
        f"/documents/collections/{collection.id}", json={"access": policy}
    ).status_code == 403
    unknown = client.patch(f"/documents/collections/{collection.id}", json={"access": {"read": ["user:ghost"]}})
    assert unknown.status_code == 422
    assert client.patch(
        f"/documents/collections/{collection.id}", json={"access": {"read": ["role:member"]}}
    ).status_code == 422


def test_collection_listing_query_count_is_flat(db_session):
    from app.db.base import engine

    workspace = _workspace(db_session, "ws-flat")
    _member(db_session, workspace, user_id="contrib", role_template="workspace_contributor")
    db_session.commit()

    def count_queries(n: int) -> int:
        for index in range(n - db_session.query(KnowledgeCollection).filter_by(workspace_id=workspace.id).count()):
            row = create_collection(db_session, workspace=workspace, name=f"C{n}-{index}")
            if index % 2:
                row.access = {"read": ["role:workspace_contributor"]}
            elif index % 3:
                row.access = ADMIN_ONLY
        db_session.commit()
        statements: list[str] = []

        def _count(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", _count)
        try:
            response = _client(db_session, workspace, "contrib").get("/documents/collections")
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        assert response.status_code == 200
        return len(statements)

    assert count_queries(4) == count_queries(24)


# ------------------------------------------------------------ retrieval


def _retrieval_workspace(db_session):
    workspace = _workspace(
        db_session,
        "ws-rag-access",
        settings={"knowledge_scopes": [{"key": "all", "collection_slugs": [], "is_default": True}]},
    )
    _member(db_session, workspace, user_id="granted", role_template="workspace_contributor", labels=["legal"])
    _member(db_session, workspace, user_id="denied", role_template="workspace_contributor")
    open_collection = create_collection(db_session, workspace=workspace, name="Open")
    hidden = create_collection(db_session, workspace=workspace, name="Hidden")
    hidden.access = {"read": ["group:legal"]}
    workspace.settings = {
        "knowledge_scopes": [
            {"key": "all", "collection_slugs": [open_collection.slug, hidden.slug, "legacy-docs"], "is_default": True}
        ]
    }
    db_session.commit()
    return workspace, open_collection, hidden


def _request(workspace, user_id=None, **extra):
    request = {"query": "Quelles clauses ?", "workspace_id": workspace.id, "workspace_slug": workspace.slug, **extra}
    if user_id:
        access.bind_retrieval_identity(request, workspace_id=workspace.id, user_id=user_id)
    return request


def test_retrieval_without_identity_excludes_restricted_collections(db_session):
    workspace, open_collection, hidden = _retrieval_workspace(db_session)

    anonymous = rag_context.get_retrieval_profile(_request(workspace, knowledge_scope="all"))
    assert hidden.slug not in anonymous["collections"]
    assert open_collection.slug in anonymous["collections"]
    # A legacy vector-only collection (no ledger row) has no policy: still searched.
    assert "legacy-docs" in anonymous["collections"]

    granted = rag_context.get_retrieval_profile(_request(workspace, "granted", knowledge_scope="all"))
    assert hidden.slug in granted["collections"]
    denied = rag_context.get_retrieval_profile(_request(workspace, "denied", knowledge_scope="all"))
    assert hidden.slug not in denied["collections"]


def test_client_injected_access_keys_are_ignored(db_session):
    workspace, _open, hidden = _retrieval_workspace(db_session)
    forged = {
        "query": "q",
        "workspace_id": workspace.id,
        "context_collection": hidden.slug,
        "context_mode": "replace",
        # Neither an allow-list nor a hand-made identity is trusted.
        "accessible_collection_refs": [hidden.slug, hidden.id],
        "collection_identity": {"v": 1, "workspace_id": workspace.id, "user_id": "granted",
                                "system_id": None, "iat": int(time.time()), "sig": "0" * 64},
    }
    profile = rag_context.get_retrieval_profile(forged)
    assert profile["collections"] == [] and profile["collection_access_blocked"] is True

    # An identity signed for another workspace or long expired is refused too.
    other = access.sign_retrieval_identity(workspace_id="ws-other", user_id="granted")
    assert access.verify_retrieval_identity(other, workspace_id=workspace.id) is None
    stale = access.sign_retrieval_identity(workspace_id=workspace.id, user_id="granted", issued_at=int(time.time()) - 10**6)
    assert access.verify_retrieval_identity(stale, workspace_id=workspace.id) is None

    # The chat edge drops the client key and signs the real member.
    request_dict = {"accessible_collection_refs": [hidden.slug], "collection_identity": forged["collection_identity"]}
    chat._apply_collection_access(db_session, workspace=workspace, user=SimpleNamespace(id="denied"), request_dict=request_dict)
    assert "accessible_collection_refs" not in request_dict
    assert access.verify_retrieval_identity(request_dict["collection_identity"], workspace_id=workspace.id) == ("denied", None)


def test_chat_edge_answers_404_for_an_explicit_unreadable_collection(db_session):
    workspace, open_collection, hidden = _retrieval_workspace(db_session)
    for request_dict in (
        {"retrieval_filters": {"collection_slug": hidden.slug}},
        {"retrieval_filters": {"collection": [hidden.id]}},
        {"context_collection": hidden.slug},  # the selected (ephemeral) chat Context
    ):
        with pytest.raises(HTTPException) as denied:
            chat._apply_collection_access(
                db_session, workspace=workspace, user=SimpleNamespace(id="denied"), request_dict=request_dict
            )
        assert denied.value.status_code == 404
    ok = {"retrieval_filters": {"collection_slug": hidden.slug}}
    chat._apply_collection_access(db_session, workspace=workspace, user=SimpleNamespace(id="granted"), request_dict=ok)
    ok = {"context_collection": open_collection.slug}
    chat._apply_collection_access(db_session, workspace=workspace, user=SimpleNamespace(id="denied"), request_dict=ok)


def _mixed_retrieval(monkeypatch, hidden, open_collection, seen: list):
    """Stand in for the vector search: one passage per collection in scope."""

    async def _fake(request, *, doc_svc=None, fallback_reason=None):
        profile = rag_context.get_retrieval_profile(request)
        seen.append(list(profile["collections"]))
        if profile.get("collection_access_blocked"):
            return {"chunks": [], "scores": [], "metadatas": []}
        # Deliberately leak a hidden passage to prove the final pass drops it.
        return {
            "chunks": ["open passage", "hidden passage"],
            "scores": [0.9, 0.8],
            "metadatas": [{"collection": open_collection.slug}, {"collection_name": hidden.slug}],
            "metrics": {},
        }

    monkeypatch.setattr(rag_context, "_retrieve_rag_context", _fake)


def test_retrieval_final_pass_never_returns_restricted_chunks(db_session, monkeypatch):
    workspace, open_collection, hidden = _retrieval_workspace(db_session)
    seen: list = []
    _mixed_retrieval(monkeypatch, hidden, open_collection, seen)

    denied = asyncio.run(rag_context.retrieve_rag_context(_request(workspace, "denied", knowledge_scope="all")))
    assert denied["chunks"] == ["open passage"]
    assert hidden.slug not in seen[-1]
    granted = asyncio.run(rag_context.retrieve_rag_context(_request(workspace, "granted", knowledge_scope="all")))
    assert granted["chunks"] == ["open passage", "hidden passage"]


def test_everything_denied_gives_an_empty_context_not_an_error(db_session):
    workspace, _open, hidden = _retrieval_workspace(db_session)
    request = _request(workspace, "denied", authoritative_collections=[hidden.slug])
    result = asyncio.run(rag_context.retrieve_rag_context(request))
    assert result["chunks"] == [] and result["collections"] == []
    assert result["metrics"]["collection_access_blocked"] is True


def test_assistant_search_reads_with_the_asking_member_rights(db_session, monkeypatch):
    from app.services.assistant import tools

    workspace, open_collection, hidden = _retrieval_workspace(db_session)
    seen: list = []
    _mixed_retrieval(monkeypatch, hidden, open_collection, seen)

    def _ctx(user_id):
        config = SimpleNamespace(top_k=5, workspace_id=workspace.id, workspace_slug=workspace.slug,
                                 latency_profile="fast", knowledge_scope="all",
                                 collection_slugs=[open_collection.slug, hidden.slug])
        return SimpleNamespace(db=db_session, user=db_session.get(User, user_id), workspace=workspace, config=config)

    denied = asyncio.run(tools._search_knowledge(_ctx("denied"), {"query": "clauses"}))
    granted = asyncio.run(tools._search_knowledge(_ctx("granted"), {"query": "clauses"}))
    assert "hidden passage" not in str(denied)
    assert denied["collections"] == [open_collection.slug]
    assert "hidden passage" in str(granted)


def test_skill_reads_with_the_launching_user_rights_and_scheduled_runs_read_open_only(db_session, monkeypatch):
    from app.services.skills_registry import wrappers

    workspace, open_collection, hidden = _retrieval_workspace(db_session)
    seen: list = []
    _mixed_retrieval(monkeypatch, hidden, open_collection, seen)

    def _run(ctx_user, system_id="sys-1"):
        ctx = {"workspace_id": workspace.id, "workspace_slug": workspace.slug, "user_id": ctx_user,
               "system_id": system_id, "knowledge_scope": "all"}
        # A payload cannot smuggle an identity of its own.
        payload = {"query": "clauses", "collection_identity": access.sign_retrieval_identity(
            workspace_id=workspace.id, user_id="granted")}
        return asyncio.run(wrappers._semantic_search_v1(payload, ctx))

    assert "hidden passage" not in str(_run("denied"))
    assert "hidden passage" in str(_run("granted"))
    assert "hidden passage" not in str(_run(None))  # scheduled, nobody launched it
    hidden.access = {"read": ["group:legal", "system:sys-1"]}
    db_session.commit()
    assert "hidden passage" in str(_run(None))  # explicitly granted to the System
    assert "hidden passage" not in str(_run("denied"))  # a user run keeps the user's rights


def test_deep_retrieval_worker_reads_with_the_job_creator_rights(db_session, monkeypatch):
    from app.models.workspace_job import WorkspaceJob
    from app.services import worker_deep_retrieval

    workspace, _open, hidden = _retrieval_workspace(db_session)
    injected = access.sign_retrieval_identity(workspace_id=workspace.id, user_id="granted")
    job = WorkspaceJob(
        id="job-deep-1",
        workspace_id=workspace.id,
        kind="rag_deep_retrieval",
        title="Deep",
        status="queued",
        input_ref={"request": {"query": "q", "workspace_id": workspace.id, "collection_identity": injected,
                               "accessible_collection_refs": [hidden.slug]}},
        created_by_user_id="denied",
    )
    db_session.add(job)
    db_session.commit()
    captured: dict = {}

    async def _capture(payload, **_kwargs):
        captured.update(payload)
        raise RuntimeError("stop after retrieval")

    monkeypatch.setattr(worker_deep_retrieval, "retrieve_rag_context", _capture)
    try:
        asyncio.run(worker_deep_retrieval._run_workspace_deep_retrieval_async(job.id))
    except Exception:  # noqa: BLE001 - only the payload matters here.
        pass
    assert "accessible_collection_refs" not in captured
    assert access.verify_retrieval_identity(captured["collection_identity"], workspace_id=workspace.id) == ("denied", None)
    assert hidden.slug in access.retrieval_collection_access(captured).denied


def test_documents_search_binds_the_member_identity_for_the_planner(db_session, monkeypatch):
    workspace, open_collection, _hidden = _retrieval_workspace(db_session)
    seen: dict = {}

    def _plan(**kwargs):
        seen.update(kwargs["request"])
        raise RuntimeError("planner reached")

    monkeypatch.setattr("app.services.rag.corpus_planner.plan_corpus", _plan)
    response = _client(db_session, workspace, "granted").post(
        "/documents/search", json={"query": "q", "collection_name": open_collection.slug}
    )
    assert response.status_code == 500  # the stub stops the search once the planner is reached
    assert access.verify_retrieval_identity(seen["collection_identity"], workspace_id=workspace.id) == ("granted", None)


def test_planner_keeps_legacy_collections_and_drops_unreadable_ones(db_session):
    from app.services.rag.corpus_planner import plan_corpus

    workspace, open_collection, hidden = _retrieval_workspace(db_session)
    request = _request(workspace, "denied")
    profile = {"collections": [hidden.slug, open_collection.slug, "legacy-docs"], "collection": hidden.slug,
               "workspace_id": workspace.id, "latency_profile": "fast", "top_k": 5, "candidate_pool_k": 20,
               "synthesis_k": 8, "source_display_k": 5}
    plan = plan_corpus(db=db_session, profile=profile, query="q", request=request)
    planned = plan.retrieval_scope["collections"]
    assert hidden.slug not in planned
    assert "legacy-docs" in planned


def test_knowledge_scopes_and_structured_queries_follow_collection_access(db_session):
    workspace = _workspace(db_session, "ws-knowledge-access", settings={"knowledge_scopes": []})
    _member(db_session, workspace, user_id="scope-viewer", role_template="workspace_viewer")
    open_collection = create_collection(db_session, workspace=workspace, name="Open")
    hidden = create_collection(db_session, workspace=workspace, name="Hidden")
    hidden.access = ADMIN_ONLY
    workspace.settings = {
        "knowledge_scopes": [
            {"key": "mixed", "label": "Mixed", "collection_slugs": [open_collection.slug, hidden.slug], "is_default": True}
        ]
    }
    db_session.commit()
    client = _knowledge_client(db_session, workspace, "scope-viewer")

    scope = client.get("/knowledge/scopes").json()["scopes"][0]
    assert [item["slug"] for item in scope["collections"]] == [open_collection.slug]
    assert scope["collection_slugs"] == [open_collection.slug]
    assert client.post("/knowledge/table-query", json={"collection_or_scope": hidden.slug, "question": "x?"}).status_code == 404
    # A scope with one restricted member collection still answers, without it.
    assert client.post("/knowledge/table-query", json={"collection_or_scope": "mixed", "question": "x?"}).status_code == 200


def test_the_signed_identity_never_leaves_the_api(db_session):
    from app.models.workspace_job import WorkspaceJob
    from app.services.workspace_jobs import serialize_job

    identity = access.sign_retrieval_identity(workspace_id="w", user_id="u")
    job = WorkspaceJob(id="j", workspace_id="w", kind="rag_deep_retrieval", title="t", status="queued",
                       input_ref={"request": {"query": "q", "collection_identity": identity}})
    assert "collection_identity" not in serialize_job(job)["input_ref"]["request"]
