from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.models.knowledge_collection import KnowledgeCollectionSource
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, create_worker_job
from app.services.notice_campaign_guard import NoticeCampaignGateError
from scripts import run_notice_campaign


def _plan_with_wave():
    wave = SimpleNamespace(
        index=1,
        items=(SimpleNamespace(logical_name="needlepunch__61038__manual.pdf"),),
    )
    plan = SimpleNamespace(
        profile_slug="needlepunch",
        campaign="direct",
        plan_hash="a" * 64,
        waves=(wave,),
    )
    return plan, wave


def test_mark_postflight_verified_releases_persistent_lease(db_session):
    workspace = Workspace(
        id="ws-runner-lease",
        name="Andritz",
        slug="andritz-runner-lease",
    )
    actor = User(
        id="user-runner-lease",
        username="runner-lease",
        email="reviewer@example.test",
    )
    db_session.add_all([workspace, actor])
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=workspace,
        name="Notices",
        slug="andritz-notices-techniques-spl-pilot",
    )
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.status = "completed"
    job.result = {
        "postflight_required": True,
        "postflight_status": "pending",
        "ingest_options": {
            "mode": "incremental",
            "source_profile": "needlepunch",
            "wave_id": "wave-lease",
            "document_names": ["needlepunch__61038__manual.pdf"],
        },
    }
    access = DepositAccessLink(
        id="link-runner-lease",
        workspace_id=workspace.id,
        created_by_user_id=actor.id,
        label="Needlepunch",
        access_id="runner-lease",
        password_hash="hash",
    )
    deposit = DepositFile(
        id="deposit-runner-lease",
        workspace_id=workspace.id,
        access_link_id=access.id,
        filename=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61038 Line/manual.pdf"
        ),
        object_key="secure-deposit/runner-lease",
        size_bytes=123,
        sha256="a" * 64,
        status="received",
        worker_job_id=job.id,
        promotion_result={
            "status": "worker_completed_pending_postflight",
            "indexing_status": "indexed",
            "postflight_status": "pending",
            "indexing_verification": {"awaiting_document_count": 0},
        },
    )
    source = KnowledgeCollectionSource(
        workspace_id=workspace.id,
        collection_id=collection.id,
        filename="needlepunch__61038__manual.pdf",
        normalized_name="needlepunch__61038__manual.pdf",
        status="ready",
        source_metadata={
            "wave_id": "wave-lease",
            "source_deposit_file_id": deposit.id,
        },
    )
    db_session.add_all([access, deposit, source])
    db_session.commit()

    run_notice_campaign._mark_postflight_verified(
        db_session,
        workspace=workspace,
        collection=collection,
        job=job,
        wave_id="wave-lease",
        actor="reviewer@example.test",
        snapshot_ref="qdrant://snapshot-123",
        actor_user_id=actor.id,
    )

    db_session.refresh(job)
    db_session.refresh(deposit)
    assert job.status == "completed"
    assert job.result["postflight_status"] == "verified"
    assert job.result["postflight_snapshot_ref"] == "qdrant://snapshot-123"
    assert job.result["stage"] == "postflight_verified"
    assert deposit.status == "promoted"
    assert deposit.promoted_by_user_id == actor.id
    assert deposit.promoted_collection_slug == collection.slug
    assert deposit.promotion_result["postflight_status"] == "verified"


@pytest.mark.asyncio
async def test_start_wave_requires_completed_prior_job_and_rechecks_sources(
    db_session,
    monkeypatch,
):
    workspace = Workspace(id="ws-runner", name="Andritz", slug="andritz-runner")
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=workspace,
        name="Notices",
        slug="andritz-notices-techniques-spl-pilot",
    )
    collection.status = "ready"
    plan, wave = _plan_with_wave()
    wave_id = run_notice_campaign._notice_wave_id(plan, wave)
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.status = "completed"
    job.result = {
        "ingest_options": {
            "wave_id": wave_id,
            "document_names": ["needlepunch__61038__manual.pdf"],
        }
    }
    db_session.commit()

    calls = []

    async def fake_verify(_db, **kwargs):
        calls.append(kwargs)
        return {"collection_status": "ready"}

    monkeypatch.setattr(run_notice_campaign, "verify_notice_collection_gate", fake_verify)

    reports = await run_notice_campaign._verify_prior_waves(
        db_session,
        workspace=workspace,
        collection=collection,
        plan=plan,
        start_wave=2,
    )

    assert reports[0]["job_id"] == job.id
    assert reports[0]["wave_id"] == wave_id
    assert calls == [
        {
            "workspace": workspace,
            "collection": collection,
            "document_names": ["needlepunch__61038__manual.pdf"],
            "wave_id": wave_id,
        }
    ]


@pytest.mark.asyncio
async def test_start_wave_rejects_unproven_prior_wave(db_session):
    workspace = Workspace(
        id="ws-runner-missing",
        name="Andritz",
        slug="andritz-runner-missing",
    )
    db_session.add(workspace)
    db_session.flush()
    collection = create_collection(
        db_session,
        workspace=workspace,
        name="Notices",
        slug="andritz-notices-techniques-spl-pilot",
    )
    plan, _wave = _plan_with_wave()

    with pytest.raises(NoticeCampaignGateError, match="prior_wave_not_completed"):
        await run_notice_campaign._verify_prior_waves(
            db_session,
            workspace=workspace,
            collection=collection,
            plan=plan,
            start_wave=2,
        )


@pytest.mark.asyncio
async def test_wave_execution_keeps_existing_wave_provenance(monkeypatch):
    workspace = SimpleNamespace(id="ws", slug="andritz")
    collection = SimpleNamespace(id="collection")
    calls = []

    async def fake_verify(_db, **kwargs):
        calls.append(kwargs)
        return {"sources": kwargs["document_names"]}

    monkeypatch.setattr(run_notice_campaign, "verify_notice_collection_gate", fake_verify)

    result = await run_notice_campaign._verify_wave_execution(
        object(),
        workspace=workspace,
        collection=collection,
        queued={
            "document_names": ["new.pdf"],
            "already_known": [
                {"document_name": "existing.pdf", "status": "ready"}
            ],
        },
        wave_id="new-wave-id",
        expected_names=["new.pdf", "existing.pdf"],
    )

    assert set(result) == {"indexed", "already_known"}
    assert calls[0]["document_names"] == ["new.pdf"]
    assert calls[0]["wave_id"] == "new-wave-id"
    assert calls[1]["document_names"] == ["existing.pdf"]
    assert "wave_id" not in calls[1]


def test_bulk_runner_requires_measured_growth_before_database(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_notice_campaign",
            "--workspace",
            "andritz",
            "--range",
            "60000-69999",
            "--plan-hash",
            "a" * 64,
        ],
    )
    monkeypatch.setattr(
        run_notice_campaign,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )

    with pytest.raises(SystemExit) as exc_info:
        run_notice_campaign.main()

    assert exc_info.value.code == 2


def test_bulk_runner_rejects_zero_docker_growth_before_database(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_notice_campaign",
            "--workspace",
            "andritz",
            "--range",
            "60000-69999",
            "--plan-hash",
            "a" * 64,
            "--estimated-docker-growth-bytes",
            "0",
            "--estimated-deposit-growth-bytes",
            "0",
        ],
    )
    monkeypatch.setattr(
        run_notice_campaign,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )

    with pytest.raises(SystemExit) as exc_info:
        run_notice_campaign.main()

    assert exc_info.value.code == 2
