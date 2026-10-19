"""A delegated Run never resumes effects using an obsolete actor context."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.decision import Decision
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.webhook_hook import WebhookHook
from app.models.workspace import Workspace, WorkspaceMember
from app.services import governed_assets
from app.services.collection_access import require_named_collection_read
from app.services.ecommerce import claims
from app.services.evaluation.run_evidence import capture_run_evidence
from app.services.run_engine import dag, engine
from app.services.run_engine.dag import execute_run_dag, resume_run_dag
from app.services.run_engine.execution_principal import (
    ExecutionPrincipalError,
    configure_identity,
    principal_for_source,
)
from app.services.systems.flow_ingress import create_published_ingress_run
from app.tests.publication_baseline import baseline_flow_publication


def _delegated_run(db, *, nodes, edges, egress_review=False):
    workspace = Workspace(id=str(uuid4()), name="Delegated runtime", slug=uuid4().hex)
    user = User(id=str(uuid4()), username="runtime-" + uuid4().hex, is_active=True)
    skill = Skill(
        id=str(uuid4()),
        slug="delegate_" + uuid4().hex,
        name="Delegated task",
        version="1",
        input_schema={},
        output_schema={},
        pricing={"unit_price": 0.0},
        execution={"mode": "sync", "retryable": True, "idempotent": True},
    )
    db.add_all([workspace, user, skill])
    db.flush()
    membership = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member")
    if not any(node["kind"] == "source" for node in nodes):
        edges = [("source", nodes[0]["id"]), *edges]
        nodes = [{"id": "source", "kind": "source"}, *nodes]
    flow = {
        "schema_version": 2,
        "nodes": [
            {**node, "config": {**node.get("config", {}), "skill_slug": skill.slug}}
            if node["kind"] in {"task", "retry", "loop"}
            else {**node, "type": "source.webhook"}
            if node["kind"] == "source"
            else node
            for node in nodes
        ],
        "edges": [{"from": start, "to": end} for start, end in edges],
    }
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Delegated flow",
        status="active",
        skill_ids=[skill.id],
        flow_definition=flow,
    )
    source = WebhookHook(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        name="Runtime test source",
        secret="unit-test-only",
        enabled=True,
    )
    db.add_all([membership, system, source])
    if egress_review:
        control = ControlPolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="Review all results",
            scope="system",
            target_id=system.id,
            extra={
                "membrane_spec": {
                    "version": 2,
                    "enforcement_mode": "enforce",
                    "outbound": {"expert_review_required": True},
                }
            },
        )
        system.control_policy_id = control.id
        db.add(control)
    db.commit()
    baseline_flow_publication(db, system)
    configure_identity(
        db,
        source=source,
        command="current_user",
        user=user,
        workspace=workspace,
        system=system,
    )
    run = create_published_ingress_run(
        db,
        system_id=system.id,
        workspace=workspace,
        ingress_id="source",
        kind="http",
        payload={"user_id": "untrusted-input"},
        execution_principal=principal_for_source(db, source=source, source_type="webhook"),
    )
    db.commit()
    return SimpleNamespace(run=run, source=source, user=user, skill=skill, system=system)


def _revoke(db, source, mode):
    if mode == "delete":
        db.delete(source)
    else:
        source.execution_identity = {**source.execution_identity, "grant_id": str(uuid4())}
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [None, "grant", "delete"])
async def test_task_revalidates_after_context_was_built(db_session, monkeypatch, revoke):
    s = _delegated_run(db_session, nodes=[{"id": "task", "kind": "task"}], edges=[])
    ctx = engine._build_initial_ctx(db_session, s.run, s.system, None)
    assert ctx["user_id"] == s.user.id
    ctx.update(
        {
            "user_id": "forged-admin",
            "run_id": "other-run",
            "workspace_id": "other-workspace",
            "system_id": "other-system",
        }
    )
    calls = []
    secrets = []

    async def fn(payload, context):
        assert context["run_id"] == s.run.id
        assert context["system_id"] == s.system.id
        assert context["workspace_id"] == s.run.workspace_id
        calls.append(context["user_id"])
        return {"ok": True}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: fn)
    monkeypatch.setattr(
        engine, "build_secret_grants", lambda *args, **kwargs: secrets.append(True) or {}
    )
    if revoke:
        _revoke(db_session, s.source, revoke)
        with pytest.raises(ExecutionPrincipalError, match="EXECUTION_PRINCIPAL_REVOKED"):
            await engine._execute_task_node(
                db_session,
                s.run,
                ctx,
                s.skill.slug,
                control=None,
                last_output={},
                node_id="task",
            )
    else:
        await engine._execute_task_node(
            db_session,
            s.run,
            ctx,
            s.skill.slug,
            control=None,
            last_output={},
            node_id="task",
        )
    invocation = db_session.query(SkillInvocation).filter_by(run_id=s.run.id).one()
    assert invocation.status == ("failed" if revoke else "completed")
    assert calls == ([] if revoke else [s.user.id])
    assert secrets == ([] if revoke else [True])
    assert s.run.initiated_by_user_id is None
    if revoke:
        assert invocation.error == "EXECUTION_PRINCIPAL_REVOKED"
        assert invocation.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tail_kind,revoke",
    [
        ("task", "grant"),
        ("task", "delete"),
        ("subflow", "grant"),
        ("subflow", "delete"),
        ("subflow", None),
    ],
)
async def test_hitl_resume_refuses_stale_authority_and_undelegated_children(
    db_session,
    monkeypatch,
    tail_kind,
    revoke,
):
    target = System(id=str(uuid4()), name="Child that must never start", skill_ids=[])
    db_session.add(target)
    db_session.commit()
    s = _delegated_run(
        db_session,
        nodes=[
            {"id": "source", "kind": "source"},
            {"id": "approval", "kind": "hitl", "config": {"prompt": "Approve?"}},
            {
                "id": "tail",
                "kind": tail_kind,
                "config": {"system_id": target.id, "on_error": "continue"},
            },
            {"id": "sink", "kind": "sink"},
        ],
        edges=[("source", "approval"), ("approval", "tail"), ("tail", "sink")],
    )
    calls = []

    async def fn(payload, context):
        calls.append(True)
        return {"ok": True}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: fn)
    run_id = s.run.id
    paused = await execute_run_dag(run_id)
    assert paused["status"] == "hitl_pending", paused
    db_session.expire_all()
    run = db_session.get(Run, run_id)
    checkpoint = next(cp for cp in run.checkpoints if cp["kind"] == "hitl_pause")
    assert checkpoint["state"]["ctx"]["user_id"] == s.user.id
    if revoke:
        _revoke(db_session, db_session.get(WebhookHook, s.source.id), revoke)
    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = "accepted"
    db_session.commit()

    result = await resume_run_dag(run_id, decision_id=decision.id)

    expected = (
        "EXECUTION_PRINCIPAL_REVOKED" if revoke else "EXECUTION_PRINCIPAL_SUBFLOW_UNSUPPORTED"
    )
    assert result["status"] == "failed", result
    assert result["error"] == expected
    db_session.expire_all()
    run = db_session.get(Run, run_id)
    assert run.status == "failed" and run.initiated_by_user_id is None
    assert calls == []
    assert db_session.query(Run).filter_by(parent_run_id=run_id).count() == 0
    assert db_session.query(SkillInvocation).filter_by(run_id=run_id).count() == 0
    if revoke:
        assert run.checkpoints[-1]["kind"] == "run_end"
        assert run.checkpoints[-1]["error"] == expected
        assert not any(
            cp.get("kind") == "node_start" and cp.get("node_id") == "tail" for cp in run.checkpoints
        )
    else:
        assert any(
            cp.get("kind") == "node_end"
            and cp.get("node_id") == "tail"
            and cp.get("status") == "failed"
            and cp.get("error") == expected
            for cp in run.checkpoints
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["retry", "loop"])
async def test_revocation_between_attempts_is_terminal_despite_continue_policy(
    db_session, monkeypatch, kind
):
    s = _delegated_run(
        db_session,
        nodes=[
            {"id": "source", "kind": "source"},
            {
                "id": "work",
                "kind": kind,
                "config": {
                    "max_attempts": 3,
                    "backoff_ms": 1,
                    "max_iterations": 3,
                    "on_error": "continue",
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        edges=[("source", "work"), ("work", "sink")],
    )
    calls = []

    async def fn(payload, context):
        calls.append(context["user_id"])
        _revoke(db_session, db_session.get(WebhookHook, s.source.id), "grant")
        if kind == "retry":
            raise RuntimeError("transient first attempt")
        return {"ok": True}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: fn)
    result = await execute_run_dag(s.run.id)
    assert result["status"] == "failed", result
    assert result["error"] == "EXECUTION_PRINCIPAL_REVOKED"
    assert calls == [s.user.id]
    invocations = db_session.query(SkillInvocation).filter_by(run_id=s.run.id).all()
    assert len(invocations) == 2
    assert sum(inv.error == "EXECUTION_PRINCIPAL_REVOKED" for inv in invocations) == 1
    assert all(inv.completed_at for inv in invocations)
    db_session.expire_all()
    assert db_session.get(Run, s.run.id).initiated_by_user_id is None


@pytest.mark.asyncio
async def test_egress_hitl_revalidates_even_when_all_nodes_are_settled(db_session, monkeypatch):
    s = _delegated_run(
        db_session,
        nodes=[
            {"id": "source", "kind": "source"},
            {"id": "work", "kind": "task"},
            {"id": "sink", "kind": "sink"},
        ],
        edges=[("source", "work"), ("work", "sink")],
        egress_review=True,
    )
    calls = []
    publications = []

    async def fn(payload, context):
        calls.append(True)
        return {"proposal": "awaiting review", "confidence": 0.9}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: fn)
    monkeypatch.setattr(
        dag, "persist_provenance_artifact", lambda *args, **kwargs: publications.append(True)
    )
    run_id = s.run.id
    paused = await execute_run_dag(run_id)
    assert paused["status"] == "hitl_pending", paused
    db_session.expire_all()
    run = db_session.get(Run, run_id)
    checkpoint = next(cp for cp in run.checkpoints if cp["kind"] == "hitl_pause")
    assert checkpoint["membrane_egress"] is True
    assert set(checkpoint["state"]["done"]) == {"source", "work", "sink"}
    assert run.output_ref in (None, {})
    _revoke(db_session, db_session.get(WebhookHook, s.source.id), "grant")
    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = "accepted"
    db_session.commit()

    result = await resume_run_dag(run_id, decision_id=decision.id)

    assert result["status"] == "failed", result
    assert result["error"] == "EXECUTION_PRINCIPAL_REVOKED"
    assert calls == [True] and publications == []
    db_session.expire_all()
    assert db_session.get(Run, run_id).output_ref in (None, {})


@pytest.mark.asyncio
async def test_upstream_identifiers_cannot_select_another_run_or_judge_actor(
    db_session, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    s = _delegated_run(
        db_session,
        nodes=[
            {"id": "source", "kind": "source"},
            {"id": "proposal", "kind": "task"},
            {"id": "evidence", "kind": "task"},
            {"id": "sink", "kind": "sink"},
        ],
        edges=[("source", "proposal"), ("proposal", "evidence"), ("evidence", "sink")],
    )
    other = Run(
        id=str(uuid4()),
        workspace_id=s.run.workspace_id,
        system_id=s.system.id,
        status="running",
        initiated_by_user_id=s.user.id,
    )
    db_session.add(other)
    db_session.commit()
    forged = {
        "run_id": other.id,
        "user_id": "forged-admin",
        "workspace_id": "other-workspace",
        "system_id": "other-system",
    }
    s.run.input_ref = {**s.run.input_ref, **forged}
    db_session.commit()
    evidence = []

    async def fn(payload, context):
        assert context["run_id"] == s.run.id
        assert context["user_id"] == s.user.id
        assert context["workspace_id"] == s.run.workspace_id
        assert context["system_id"] == s.system.id
        if context["_skill_node_id"] == "proposal":
            # The graph can carry these as business data, never authority.
            return {**forged, "action": "review"}
        reference = capture_run_evidence(
            db_session,
            context,
            {
                "sources": [
                    {
                        "id": "proposal",
                        "node_id": "proposal",
                        "skill_slug": s.skill.slug,
                        "paths": ["/action"],
                    }
                ]
            },
            node_id="evidence",
        )
        asset = governed_assets.resolve_asset_ref(db_session, s.run.workspace_id, reference)
        evidence.append(asset.run_id)
        return {"evidence": reference}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: fn)
    result = await execute_run_dag(s.run.id)
    assert result["status"] == "completed", result
    assert evidence == [s.run.id]
    db_session.expire_all()
    run = db_session.get(Run, s.run.id)
    assert run.input_ref["run_id"] == run.id
    assert run.input_ref["system_id"] == s.system.id
    assert run.initiated_by_user_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["collection_acl", "delegation"])
async def test_claims_retrieval_honors_delegated_collection_access(
    db_session, monkeypatch, revocation
):
    from app.services.skills_registry import wrappers

    s = _delegated_run(db_session, nodes=[{"id": "work", "kind": "task"}], edges=[])
    workspace = db_session.get(Workspace, s.run.workspace_id)
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=workspace.id,
        slug="restricted-policy",
        name="Restricted policy",
        status="ready",
        vector_collection_name="restricted-policy",
        artifact_prefix="restricted-policy",
        access={"read": [f"user:{s.user.id}"]},
    )
    source = KnowledgeCollectionSource(
        id=str(uuid4()),
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="policy.pdf",
        normalized_name="policy.pdf",
        status="ready",
        source_metadata={"document_id": str(uuid4()), "content_sha256": "a" * 64},
    )
    config = {
        "allowed_claim_ids": ["RC-1043"],
        "policy_sha256": "a" * 64,
        "allowed_collection_slugs": [collection.slug],
    }
    workspace.settings = {
        **(workspace.settings or {}),
        "ecommerce_claims": config,
        "features": {**(workspace.settings or {}).get("features", {}), "ecommerce_claims_v1": True},
    }
    db_session.add_all([collection, source])
    db_session.commit()
    reference = {
        "document_key": "refund-policy-v2",
        "document_type": "policy",
        "knowledge_source_id": source.id,
        "source_filename": source.filename,
        "sha256": "a" * 64,
    }
    snapshot = {
        "data": {"documents": [reference], "context": [{"order_id": "LM-1043"}]},
        "provenance": {"snapshot_sha256": "b" * 64},
    }
    ctx = {"run_id": s.run.id, "workspace_id": workspace.id, "user_id": "forged-admin"}
    seen = []

    async def search(payload, retrieval_ctx):
        assert retrieval_ctx["user_id"] == s.user.id
        assert retrieval_ctx["retrieval_contract"]["collection"] == collection.slug
        assert payload["retrieval_filters"] == {
            "document_id": source.source_metadata["document_id"]
        }
        # Exercise the same restricted ACL again at the nested retrieval boundary.
        assert (
            require_named_collection_read(
                db_session,
                workspace=workspace,
                user_id=retrieval_ctx["user_id"],
                collection_ref=collection.slug,
            ).id
            == collection.id
        )
        seen.append(retrieval_ctx["user_id"])
        return {
            "results": [
                {
                    "content": "Refund requires a recorded human approval.",
                    "metadata": source.source_metadata,
                }
            ],
            "usage": {"measurement_coverage": "complete", "provider_calls": 0},
        }

    monkeypatch.setattr(wrappers, "_semantic_search_v1", search)
    assert (
        claims._sources(db_session, workspace, s.run, snapshot, ("policy",))[0][2].id
        == collection.id
    )
    evidence = await claims._evidence(db_session, workspace, s.run, config, snapshot, "policy", ctx)
    assert evidence["references"] == ["refund-policy-v2"]
    assert evidence["citations"][0]["collection"] == collection.slug
    assert evidence["snapshot_sha256"] == snapshot["provenance"]["snapshot_sha256"]
    assert s.run.initiated_by_user_id is None

    if revocation == "collection_acl":
        collection.access = {"read": []}
        db_session.commit()
        error = HTTPException
    else:
        _revoke(db_session, s.source, "grant")
        error = ExecutionPrincipalError
    with pytest.raises(error) as rejected:
        await claims._evidence(db_session, workspace, s.run, config, snapshot, "policy", ctx)
    if revocation == "collection_acl":
        assert rejected.value.status_code == 404
    else:
        assert rejected.value.code == "EXECUTION_PRINCIPAL_REVOKED"
    assert seen == [s.user.id]
    assert s.run.initiated_by_user_id is None
