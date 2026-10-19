"""The judge sees immutable reviewed fields, not arbitrary Run inputs or old success."""

import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models.run import Run, SkillInvocation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.typed_evaluation import RunEvidenceSnapshot
from app.services import governed_assets as assets
from app.services.evaluation.run_evidence import capture_run_evidence
from app.services.evaluation.typed_judge import TypedEvaluationError


@pytest.fixture()
def setup(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace = Workspace(id=str(uuid4()), name="Review", slug="review-" + uuid4().hex)
    user = User(id=str(uuid4()), username="reviewer-" + uuid4().hex, is_active=True)
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member"))
    run = Run(
        id=str(uuid4()), workspace_id=workspace.id, initiated_by_user_id=user.id, status="running"
    )
    db_session.add(run)
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_slug="proposal_v1",
        status="completed",
        trace={"node_id": "propose"},
        output_ref={"action": "review", "reason": "Missing proof", "password": "do-not-copy"},
    )
    db_session.add(invocation)
    db_session.commit()
    return SimpleNamespace(
        db=db_session,
        workspace=workspace,
        user=user,
        run=run,
        invocation=invocation,
        ctx={"workspace_id": workspace.id, "run_id": run.id, "user_id": user.id},
        config={
            "sources": [
                {"id": "proposal", "skill_slug": "proposal_v1", "paths": ["/action", "/reason"]}
            ]
        },
    )


def capture(s):
    return capture_run_evidence(s.db, s.ctx, s.config, node_id="judge")


def test_freezes_exact_reviewed_fields_and_reuses_identity(setup):
    s = setup
    reference = capture(s)
    assert capture(s) == reference
    asset = assets.resolve_asset_ref(s.db, s.workspace.id, reference)
    assert asset.run_id == s.run.id
    assert (
        asset.manifest_json["evidence"][0]["text"]
        == '{"/action":"review","/reason":"Missing proof"}'
    )
    assert "do-not-copy" not in str(asset.manifest_json)
    assert asset.manifest_json["provenance"][0]["invocation_id"] == s.invocation.id


@pytest.mark.parametrize("status", ["pending", "running", "failed", "cancelled"])
def test_unfinished_or_failed_source_is_not_evidence(setup, status):
    s = setup
    s.invocation.status = status
    s.db.commit()
    with pytest.raises(TypedEvaluationError, match="SOURCE_MISSING"):
        capture(s)


def test_never_uses_another_run_or_mismatched_node(setup):
    s = setup
    s.config["sources"][0]["node_id"] = "other-node"
    with pytest.raises(TypedEvaluationError, match="SOURCE_MISSING"):
        capture(s)
    s.config["sources"][0]["node_id"] = "propose"
    foreign_run = Run(id=str(uuid4()), workspace_id=s.workspace.id, status="running")
    s.db.add(foreign_run)
    s.db.flush()
    s.invocation.run_id = foreign_run.id
    s.db.commit()
    with pytest.raises(TypedEvaluationError, match="SOURCE_MISSING"):
        capture(s)


def test_latest_completed_attempt_and_explicit_json_pointer_are_captured(setup):
    s = setup
    later = SkillInvocation(
        id=str(uuid4()),
        run_id=s.run.id,
        skill_slug="proposal_v1",
        status="completed",
        started_at=datetime.utcnow() + timedelta(seconds=5),
        output_ref={"records": [{"a/b": {"x~y": "latest"}}]},
    )
    s.db.add(later)
    s.db.commit()
    s.config["sources"][0]["paths"] = ["/records/0/a~1b/x~0y"]
    asset = assets.resolve_asset_ref(s.db, s.workspace.id, capture(s))
    assert asset.manifest_json["evidence"][0]["text"] == '{"/records/0/a~1b/x~0y":"latest"}'


def test_later_failed_attempt_does_not_reuse_an_older_success(setup):
    s = setup
    s.db.add(
        SkillInvocation(
            id=str(uuid4()),
            run_id=s.run.id,
            skill_slug="proposal_v1",
            status="failed",
            started_at=datetime.utcnow() + timedelta(seconds=5),
            output_ref={},
        )
    )
    s.db.commit()
    with pytest.raises(TypedEvaluationError, match="SOURCE_MISSING"):
        capture(s)


@pytest.mark.parametrize("path", ["/missing", "/action/child"])
def test_missing_fields_fail_without_silent_truncation(setup, path):
    s = setup
    s.config["sources"][0]["paths"] = [path]
    with pytest.raises(TypedEvaluationError, match="PATH_MISSING"):
        capture(s)


@pytest.mark.parametrize(
    "value,path,code",
    [
        ({"password": "secret"}, "/password", "SENSITIVE_FIELD"),
        ({"details": {"api_key": "secret"}}, "/details", "SENSITIVE_FIELD"),
        ({"details": {"password": "secret"}}, "/details/password", "SENSITIVE_FIELD"),
        ({"records": list(range(129))}, "/records", "TOO_LARGE"),
        ({"text": "é" * 16001}, "/text", "TOO_LARGE"),
    ],
)
def test_credentials_and_unbounded_values_cannot_be_sent_to_provider(setup, value, path, code):
    s = setup
    s.invocation.output_ref = value
    s.db.commit()
    s.config["sources"][0]["paths"] = [path]
    with pytest.raises(TypedEvaluationError, match=code):
        capture(s)


def test_revoked_membership_or_cross_workspace_is_denied(setup):
    s = setup
    s.db.query(WorkspaceMember).filter_by(user_id=s.user.id).delete()
    s.db.commit()
    with pytest.raises(TypedEvaluationError, match="ACCESS_REVOKED"):
        capture(s)


def test_native_reference_is_not_accepted_from_another_workspace(setup):
    s = setup
    s.config["native_refs"] = [{"kind": "document_set", "id": str(uuid4())}]
    with pytest.raises(assets.GovernanceError, match="ASSET_NATIVE_REF_UNAVAILABLE"):
        capture(s)


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda collection: setattr(collection, "access", {"read": []}), "ACCESS_DENIED"),
        (lambda collection: setattr(collection, "active_generation", "changed"), "VERSION_CHANGED"),
    ],
)
def test_snapshot_does_not_bypass_later_source_revocation_or_revision(setup, change, code):
    from app.models.knowledge_collection import KnowledgeCollection

    s = setup
    collection = KnowledgeCollection(
        id=str(uuid4()),
        workspace_id=s.workspace.id,
        slug="policy",
        name="Policy",
        status="ready",
        vector_collection_name="policy",
        artifact_prefix="policy",
        active_generation="original",
    )
    s.db.add(collection)
    s.db.commit()
    s.config["native_refs"] = [{"kind": "document_set", "id": collection.id}]
    reference = capture(s)
    asset = assets.resolve_asset_ref(s.db, s.workspace.id, reference)
    evidence = [{**entry, "asset_ref": reference} for entry in asset.manifest_json["evidence"]]
    assert assets.authorize_judge_evidence(evidence, s.ctx)
    change(collection)
    s.db.commit()
    with pytest.raises(assets.GovernanceError, match=code):
        assets.authorize_judge_evidence(evidence, s.ctx)


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["sources"][0].update(paths=[""]),
        lambda c: c["sources"][0].update(paths=["/"]),
        lambda c: c["sources"][0].update(paths=["/bad~escape"]),
        lambda c: c["sources"][0].update(paths=["/action", "/action"]),
        lambda c: c["sources"][0].update(required=False),
        lambda c: c["sources"].append(copy.deepcopy(c["sources"][0])),
        lambda c: c["sources"][0].update(run_id="another-run"),
    ],
)
def test_selector_contract_rejects_ambiguous_or_caller_owned_scope(setup, change):
    config = copy.deepcopy(setup.config)
    change(config)
    with pytest.raises(ValidationError):
        RunEvidenceSnapshot.model_validate(config)


async def test_wrapper_rejects_free_input_overriding_run_evidence(setup):
    from app.services.skills_registry.wrappers.skills import _evaluate_v2

    with pytest.raises(ValueError, match="JUDGE_RUN_EVIDENCE_INPUT_CONFLICT"):
        await _evaluate_v2(
            {
                "_typed_evaluation": {
                    "node_id": "judge",
                    "typed_evaluation": {"run_evidence": setup.config},
                },
                "evidence": [{"id": "proposal", "text": "forged"}],
            },
            setup.ctx,
        )


@pytest.mark.parametrize("unattended", [False, True, "delegated"])
@pytest.mark.parametrize("revoke", [False, True])
async def test_wrapper_runs_existing_typed_judge_with_frozen_evidence_and_real_questions(
    setup, monkeypatch, unattended, revoke
):
    from app.models.evaluation import EvaluationScore
    from app.services.model_plane import execution
    from app.services.model_plane.execution import ModelExecution
    from app.services.skills_registry.wrappers.skills import _evaluate_v2

    s = setup
    if unattended == "delegated":
        from app.services.run_engine import execution_principal

        s.run.initiated_by_user_id = None
        s.run.execution_principal = {"kind": "delegated_user", "user_id": s.user.id}
        s.db.commit()
        monkeypatch.setattr(execution_principal, "execution_user_id", lambda db, run: s.user.id)
    calls = []
    collection = None
    if revoke:
        from app.models.knowledge_collection import KnowledgeCollection

        collection = KnowledgeCollection(
            id=str(uuid4()),
            workspace_id=s.workspace.id,
            slug="policy",
            name="Policy",
            status="ready",
            vector_collection_name="policy",
            artifact_prefix="policy",
        )
        s.db.add(collection)
        # Source discovery must retain ACLs even without any declared native_refs.
        s.invocation.output_ref = {
            **s.invocation.output_ref,
            "citations": [{"collection": "policy"}],
        }
        s.db.commit()

    class Provider:
        async def generate(self, *, model, prompt, **options):
            calls.append(prompt)
            if collection:
                collection.access = {"read": []}
                s.db.commit()
            return {
                "model": model,
                "content": json.dumps(
                    {
                        "answers": {
                            "supported": {
                                "status": "abstained",
                                "value": None,
                                "reason": "insufficient_evidence",
                                "explanation": "The proposal records missing proof.",
                                "evidence": [],
                            }
                        }
                    }
                ),
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            }

    monkeypatch.setattr(execution, "build_model_client", lambda *args, **kwargs: Provider())
    ctx = {
        **s.ctx,
        "_model_execution": ModelExecution("openai", "test-judge", "workspace", "workspace"),
        "_model_policy_check": lambda candidate: None,
    }
    if unattended:
        ctx.pop("user_id")
    config = {
        "rubric_id": "proposal-policy",
        "rubric_version": "1",
        "run_evidence": s.config,
        "questions": [
            {
                "key": "supported",
                "question": "Does the supplied proof support the proposal?",
                "type": "boolean",
                "acceptable_values": [True],
            }
        ],
        "budget": {"max_calls": 1, "max_tokens": 10000, "max_cost_usd": 1.0},
        "tariff": {
            "provider": "openai",
            "model": "test-judge",
            "input_per_million": 1.0,
            "output_per_million": 2.0,
            "reference": "test-only",
        },
    }
    request = {"_typed_evaluation": {"node_id": "judge", "typed_evaluation": config}}
    if revoke:
        with pytest.raises(TypedEvaluationError, match="JUDGE_ACCESS_REVOKED"):
            await _evaluate_v2(request, ctx)
        persisted = s.db.query(EvaluationScore).filter_by(run_id=s.run.id).one()
        result = persisted.metadata_["typed_evaluation"]
        assert result["status"] == "failed" and result["reason"] == "JUDGE_ACCESS_REVOKED"
        assert result["usage"]["total_tokens"] == 70 and len(calls) == 1
        assert result["answers"]["supported"]["evidence"] == []
        return
    result = await _evaluate_v2(request, ctx)
    assert len(calls) == 1 and "Missing proof" in calls[0] and "do-not-copy" not in calls[0]
    assert result["status"] == "partial" and result["disposition"] == "review"
    assert result["quality_status"] == "unassessed" and result["confidence"] is None
    assert result["questions"][0]["question"] == config["questions"][0]["question"]
    assert result["evidence"][0]["asset_ref"]["workspace_id"] == s.workspace.id
    persisted = s.db.get(EvaluationScore, result["evaluation_id"])
    assert persisted.metadata_["typed_evaluation"]["subject_ref"] == result["subject_ref"]
    repeat = await _evaluate_v2(request, ctx)
    assert repeat["cached"] and len(calls) == 1
    if unattended == "delegated":
        s.db.refresh(s.run)
        assert s.run.initiated_by_user_id is None


def test_evidence_capture_refuses_revoked_delegation_even_with_user_context(setup, monkeypatch):
    from app.services.run_engine import execution_principal

    s = setup
    s.run.execution_principal = {"kind": "delegated_user", "user_id": s.user.id}
    s.db.commit()

    def deny(db, run):
        raise execution_principal.ExecutionPrincipalError("EXECUTION_PRINCIPAL_REVOKED")

    monkeypatch.setattr(execution_principal, "execution_user_id", deny)
    with pytest.raises(TypedEvaluationError, match="EXECUTION_PRINCIPAL_REVOKED"):
        capture(s)
