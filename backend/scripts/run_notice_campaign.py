"""Run approved Needlepunch waves sequentially with fail-closed health gates.

This is intentionally a deployed-operator command.  It never approves its own
plan: ``--plan-hash`` must come from ``scripts.promote_notice_wave --dry-run``.
By default it performs preflight only; mutation requires ``--execute`` plus an
explicit reviewer/admin/owner actor and an off-host snapshot reference.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.secure_deposit import DepositFile
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.knowledge_collections import update_job
from app.services.notice_campaign_guard import (
    NoticeCampaignGateError,
    assert_notice_disk_capacity,
    verify_notice_collection_gate,
)
from app.services.notice_campaign_recovery import (
    quarantine_notice_collection,
    rollback_rejected_notice_wave,
)
from app.services.notice_wave_importer import (
    DEFAULT_NOTICE_COLLECTION,
    NOTICE_SOURCE_PROFILES,
    NoticePlanDriftError,
    NoticeWave,
    NoticeWavePlan,
    build_notice_wave_plan,
    execute_notice_wave_plan,
    fail_queued_notice_job,
)
from app.services.notice_wave_state import (
    NoticeWaveBaselineError,
    notice_wave_baseline,
)
from scripts.promote_notice_wave import _resolve_actor

_BULK_MIN_FREE_BYTES = 250 * 1024 * 1024 * 1024


def _mark_postflight_verified(
    db,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    job: WorkerJob,
    wave_id: str,
    actor: str,
    snapshot_ref: str,
    actor_user_id: str | None = None,
) -> None:
    result = dict(job.result or {})
    if not bool(result.get("postflight_required")):
        return
    if str(result.get("postflight_status") or "") == "verified":
        return
    if str(result.get("postflight_status") or "") != "pending":
        raise NoticeCampaignGateError(
            f"postflight_job_not_pending:{job.id}:"
            f"{result.get('postflight_status') or 'missing'}"
        )
    if (
        str(job.workspace_id) != str(workspace.id)
        or str(job.collection_id) != str(collection.id)
        or job.status != "completed"
        or job.kind != "document_ingest_index"
    ):
        raise NoticeCampaignGateError(f"postflight_job_scope_mismatch:{job.id}")

    options = dict(result.get("ingest_options") or {})
    document_names = {
        str(name)
        for name in (options.get("document_names") or [])
        if str(name or "").strip()
    }
    if (
        str(options.get("mode") or "") != "incremental"
        or str(options.get("source_profile") or "") != "needlepunch"
        or str(options.get("wave_id") or "") != wave_id
        or not document_names
    ):
        raise NoticeCampaignGateError(f"postflight_manifest_scope_mismatch:{job.id}")

    sources = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.normalized_name.in_(sorted(document_names)),
        )
        .all()
    )
    if {str(source.normalized_name) for source in sources} != document_names:
        raise NoticeCampaignGateError(f"postflight_source_scope_mismatch:{job.id}")
    deposit_ids: set[str] = set()
    for source in sources:
        metadata = dict(source.source_metadata or {})
        deposit_id = str(metadata.get("source_deposit_file_id") or "").strip()
        if str(metadata.get("wave_id") or "") != wave_id or not deposit_id:
            raise NoticeCampaignGateError(
                f"postflight_source_provenance_mismatch:{source.normalized_name}"
            )
        deposit_ids.add(deposit_id)

    deposits = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.id.in_(sorted(deposit_ids)),
        )
        .all()
    )
    if {str(deposit.id) for deposit in deposits} != deposit_ids or any(
        str(deposit.worker_job_id or "") != str(job.id) for deposit in deposits
    ):
        raise NoticeCampaignGateError(f"postflight_deposit_scope_mismatch:{job.id}")
    if any(
        str(deposit.status or "") not in {"received", "promoted"}
        or (
            str(deposit.status or "") == "promoted"
            and str(deposit.promoted_collection_slug or "") != str(collection.slug)
        )
        for deposit in deposits
    ):
        raise NoticeCampaignGateError(f"postflight_deposit_status_mismatch:{job.id}")

    now = datetime.utcnow()
    deposit_reports: list[dict] = []
    for deposit in deposits:
        if str(deposit.status or "") not in {"received", "promoted"}:
            raise NoticeCampaignGateError(
                f"postflight_deposit_status_invalid:{deposit.id}:{deposit.status}"
            )
        assigned_collection = str(deposit.promoted_collection_slug or "").strip()
        if assigned_collection and assigned_collection != str(collection.slug):
            raise NoticeCampaignGateError(
                f"postflight_deposit_collection_mismatch:{deposit.id}"
            )
        promotion = dict(deposit.promotion_result or {})
        indexing_status = str(promotion.get("indexing_status") or "")
        verification = dict(promotion.get("indexing_verification") or {})
        try:
            awaiting_count = int(verification.get("awaiting_document_count") or 0)
        except (TypeError, ValueError) as exc:
            raise NoticeCampaignGateError(
                f"postflight_deposit_verification_invalid:{deposit.id}"
            ) from exc
        promotable = (
            indexing_status in {"indexed", "deduplicated"}
            and awaiting_count == 0
        )
        if not promotable and not (
            indexing_status == "partial" and awaiting_count > 0
        ):
            raise NoticeCampaignGateError(
                f"postflight_deposit_not_verified:{deposit.id}:{indexing_status or 'missing'}"
            )
        promotion.update(
            {
                "postflight_status": "verified",
                "postflight_verified_at": now.isoformat(),
                "postflight_snapshot_ref": snapshot_ref,
                "postflight_job_id": job.id,
                "postflight_wave_id": wave_id,
                "status": (
                    "promoted"
                    if promotable
                    else "postflight_verified_awaiting_remaining_documents"
                ),
            }
        )
        if promotable:
            deposit.status = "promoted"
            deposit.promoted_at = now
            deposit.promoted_by_user_id = actor_user_id
            deposit.promoted_collection_slug = collection.slug
        else:
            deposit.status = "received"
            deposit.promoted_at = None
            deposit.promoted_by_user_id = None
            deposit.promoted_collection_slug = None
        deposit.promotion_result = promotion
        deposit_reports.append(
            {
                "deposit_file_id": str(deposit.id),
                "status": str(deposit.status),
                "indexing_status": indexing_status,
                "awaiting_document_count": awaiting_count,
            }
        )

    result.update(
        {
            "postflight_status": "verified",
            "postflight_verified_at": now.isoformat(),
            "postflight_snapshot_ref": snapshot_ref,
            "postflight_deposits": deposit_reports,
        }
    )
    update_job(
        db,
        job.id,
        status="completed",
        progress=100,
        result=result,
        stage="postflight_verified",
    )
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="notice.wave.postflight_verified",
        actor=actor,
        details={
            "collection_slug": collection.slug,
            "job_id": job.id,
            "wave_id": wave_id,
            "snapshot_ref": snapshot_ref,
            "deposits": deposit_reports,
        },
    )
    db.commit()


def _notice_wave_id(plan: NoticeWavePlan, wave: NoticeWave) -> str:
    return (
        f"{plan.profile_slug}-{plan.campaign}-"
        f"{plan.plan_hash[:12]}-{wave.index:03d}"
    )


async def _verify_prior_waves(
    db,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    plan: NoticeWavePlan,
    start_wave: int,
) -> list[dict]:
    """Prove every skipped wave completed and is still authoritative."""

    reports: list[dict] = []
    if start_wave <= 1:
        return reports
    completed_jobs = (
        db.query(WorkerJob)
        .filter(
            WorkerJob.collection_id == collection.id,
            WorkerJob.kind == "document_ingest_index",
            WorkerJob.status == "completed",
        )
        .all()
    )
    jobs_by_wave: dict[str, list[WorkerJob]] = {}
    for job in completed_jobs:
        job_result = dict(job.result or {})
        if bool(job_result.get("postflight_required")) and str(
            job_result.get("postflight_status") or ""
        ) != "verified":
            continue
        options = dict((job.result or {}).get("ingest_options") or {})
        wave_id = str(options.get("wave_id") or "")
        if wave_id:
            jobs_by_wave.setdefault(wave_id, []).append(job)

    for wave in plan.waves[: start_wave - 1]:
        wave_id = _notice_wave_id(plan, wave)
        candidates = jobs_by_wave.get(wave_id) or []
        if not candidates:
            raise NoticeCampaignGateError(
                f"prior_wave_not_completed:{wave.index}:{wave_id}"
            )
        # A later successful retry is the strongest available evidence.
        job = max(candidates, key=lambda row: row.completed_at or row.updated_at)
        expected_names = {
            str(item.logical_name) for item in wave.items if item.logical_name
        }
        options = dict((job.result or {}).get("ingest_options") or {})
        indexed_names = {
            str(name)
            for name in (options.get("document_names") or [])
            if str(name or "").strip()
        }
        unexpected = sorted(indexed_names - expected_names)
        if unexpected:
            raise NoticeCampaignGateError(
                "prior_wave_job_manifest_mismatch:" + ",".join(unexpected[:10])
            )
        already_known_names = expected_names - indexed_names
        verification: dict = {}
        if indexed_names:
            verification["indexed"] = await verify_notice_collection_gate(
                db,
                workspace=workspace,
                collection=collection,
                document_names=sorted(indexed_names),
                wave_id=wave_id,
            )
        if already_known_names:
            verification["already_known"] = await verify_notice_collection_gate(
                db,
                workspace=workspace,
                collection=collection,
                document_names=sorted(already_known_names),
            )
        if not verification:
            raise NoticeCampaignGateError(f"prior_wave_has_no_sources:{wave_id}")
        reports.append(
            {
                "wave_index": wave.index,
                "wave_id": wave_id,
                "job_id": job.id,
                "verification": verification,
            }
        )
    return reports


async def _verify_wave_execution(
    db,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    queued: dict,
    wave_id: str,
    expected_names: list[str],
) -> dict:
    """Verify newly indexed and pre-existing sources under distinct provenance."""

    indexed_names = [
        str(name)
        for name in (queued.get("document_names") or [])
        if str(name or "").strip()
    ]
    known_names = [
        str(item.get("document_name") or "")
        for item in (queued.get("already_known") or [])
        if str(item.get("document_name") or "").strip()
    ]
    expected = {str(name) for name in expected_names if str(name or "").strip()}
    actual = set(indexed_names) | set(known_names)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise NoticeCampaignGateError(
            "wave_execution_partition_mismatch:"
            f"missing={','.join(missing[:10]) or '-'}:"
            f"unexpected={','.join(unexpected[:10]) or '-'}"
        )
    verification: dict = {}
    if indexed_names:
        verification["indexed"] = await verify_notice_collection_gate(
            db,
            workspace=workspace,
            collection=collection,
            document_names=indexed_names,
            wave_id=wave_id,
        )
    if known_names:
        # Sources already terminal before this execution keep their original
        # immutable wave provenance.
        verification["already_known"] = await verify_notice_collection_gate(
            db,
            workspace=workspace,
            collection=collection,
            document_names=known_names,
        )
    if not verification:
        raise NoticeCampaignGateError(
            f"wave_execution_has_no_verifiable_sources:{wave_id}"
        )
    return verification


def _wait_for_job(db, *, job_id: str, timeout_seconds: int, poll_seconds: float) -> WorkerJob:
    deadline = time.monotonic() + timeout_seconds
    while True:
        db.expire_all()
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if job is None:
            raise NoticeCampaignGateError(f"worker_job_disappeared:{job_id}")
        if job.status in {"completed", "failed", "cancelled"}:
            return job
        if time.monotonic() >= deadline:
            raise NoticeCampaignGateError(f"worker_job_timeout:{job_id}")
        time.sleep(min(60.0, max(0.25, poll_seconds)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default="andritz")
    parser.add_argument(
        "--collection",
        default=DEFAULT_NOTICE_COLLECTION,
        choices=[DEFAULT_NOTICE_COLLECTION],
    )
    parser.add_argument(
        "--profile", default="needlepunch", choices=sorted(NOTICE_SOURCE_PROFILES)
    )
    parser.add_argument("--campaign", default="direct", choices=("direct", "legacy", "zip"))
    parser.add_argument("--prefix", dest="source_prefix")
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--project", action="append", dest="projects")
    selectors.add_argument("--range", dest="project_range")
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--start-wave", type=int, default=1)
    parser.add_argument(
        "--max-waves",
        type=int,
        default=1,
        help="Maximum sequential waves in this invocation (safe default: 1)",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--actor-email")
    parser.add_argument(
        "--snapshot-ref",
        help="Operator-audited off-host Postgres/Qdrant backup reference",
    )
    parser.add_argument(
        "--docker-capacity-path",
        default=str(settings.object_store_base_path),
    )
    parser.add_argument(
        "--deposit-capacity-path",
        default=str(settings.secure_deposit_storage_dir),
    )
    parser.add_argument("--docker-min-free-ratio", type=float, default=0.25)
    parser.add_argument("--deposit-min-free-ratio", type=float, default=0.15)
    parser.add_argument(
        "--estimated-docker-growth-bytes",
        type=int,
        help="Measured bulk estimate before the mandatory x2 safety margin",
    )
    parser.add_argument(
        "--estimated-deposit-growth-bytes",
        type=int,
        help="Measured bulk estimate before the mandatory x2 safety margin",
    )
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--job-timeout-seconds", type=int, default=7200)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.start_wave < 1:
        parser.error("--start-wave must be >= 1")
    if args.max_waves < 1 or args.max_waves > 100:
        parser.error("--max-waves must be between 1 and 100")
    if not 0 < args.docker_min_free_ratio < 1:
        parser.error("--docker-min-free-ratio must be between 0 and 1")
    if not 0 < args.deposit_min_free_ratio < 1:
        parser.error("--deposit-min-free-ratio must be between 0 and 1")
    for option, value in (
        ("--estimated-docker-growth-bytes", args.estimated_docker_growth_bytes),
        ("--estimated-deposit-growth-bytes", args.estimated_deposit_growth_bytes),
    ):
        if value is not None and value < 0:
            parser.error(f"{option} must be >= 0")
    if args.execute and not str(args.actor_email or "").strip():
        parser.error("--execute requires --actor-email")
    if args.execute and not str(args.snapshot_ref or "").strip():
        parser.error("--execute requires --snapshot-ref")
    bulk_run = (
        bool(args.project_range)
        or args.max_waves > 1
        or len(args.projects or []) > 1
    )
    if bulk_run and args.estimated_docker_growth_bytes is None:
        parser.error("bulk execution requires --estimated-docker-growth-bytes")
    if bulk_run and args.estimated_deposit_growth_bytes is None:
        parser.error("bulk execution requires --estimated-deposit-growth-bytes")
    if bulk_run and int(args.estimated_docker_growth_bytes or 0) <= 0:
        parser.error("bulk execution requires a positive Docker growth estimate")

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if workspace is None:
            raise SystemExit(f"Workspace not found: {args.workspace}")
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id,
                KnowledgeCollection.slug == args.collection,
            )
            .first()
        )
        if collection is None:
            raise SystemExit(f"Collection not found: {args.collection}")
        plan = build_notice_wave_plan(
            db,
            workspace=workspace,
            collection_slug=args.collection,
            profile_slug=args.profile,
            campaign=args.campaign,
            source_prefix=args.source_prefix,
            projects=args.projects,
            project_range=args.project_range,
        )
        approved_hash = str(args.plan_hash or "").strip().lower()
        if plan.plan_hash != approved_hash:
            raise NoticePlanDriftError(
                f"notice plan drift: approved={approved_hash} current={plan.plan_hash}"
            )
        bulk_run = bulk_run or len(plan.waves) > 1
        if bulk_run and args.estimated_docker_growth_bytes is None:
            parser.error("bulk execution requires --estimated-docker-growth-bytes")
        if bulk_run and args.estimated_deposit_growth_bytes is None:
            parser.error("bulk execution requires --estimated-deposit-growth-bytes")
        if bulk_run and int(args.estimated_docker_growth_bytes or 0) <= 0:
            parser.error("bulk execution requires a positive Docker growth estimate")
        if args.start_wave > max(1, len(plan.waves)):
            raise SystemExit(
                f"--start-wave exceeds plan wave count ({len(plan.waves)})"
            )
        minimum_free_bytes = _BULK_MIN_FREE_BYTES if bulk_run else 0
        disk_report = assert_notice_disk_capacity(
            docker_path=Path(args.docker_capacity_path),
            deposit_path=Path(args.deposit_capacity_path),
            docker_min_free_ratio=args.docker_min_free_ratio,
            deposit_min_free_ratio=args.deposit_min_free_ratio,
            docker_min_free_bytes=minimum_free_bytes,
            deposit_min_free_bytes=minimum_free_bytes,
            docker_estimated_growth_bytes=args.estimated_docker_growth_bytes or 0,
            deposit_estimated_growth_bytes=args.estimated_deposit_growth_bytes or 0,
        )
        baseline = asyncio.run(
            verify_notice_collection_gate(
                db,
                workspace=workspace,
                collection=collection,
            )
        )
        prior_waves = asyncio.run(
            _verify_prior_waves(
                db,
                workspace=workspace,
                collection=collection,
                plan=plan,
                start_wave=args.start_wave,
            )
        )
        preflight = {
            "mode": "execute" if args.execute else "preflight",
            "plan_hash": plan.plan_hash,
            "wave_count": len(plan.waves),
            "disk": disk_report,
            "collection": baseline,
            "prior_waves": prior_waves,
            "snapshot_ref": args.snapshot_ref,
        }
        print(json.dumps({"preflight": preflight}, ensure_ascii=False, indent=2))
        if not args.execute or not plan.waves:
            return

        actor = _resolve_actor(db, workspace=workspace, email=args.actor_email)
        actor_identity = actor.email or actor.username or actor.id
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="notice.campaign.started",
            actor=actor_identity,
            details={
                "collection_slug": collection.slug,
                "profile": plan.profile_slug,
                "campaign": plan.campaign,
                "plan_hash": plan.plan_hash,
                "snapshot_ref": args.snapshot_ref,
                "start_wave": args.start_wave,
                "max_waves": args.max_waves,
                "wave_count": len(plan.waves),
            },
        )
        db.commit()
        last_wave = min(len(plan.waves), args.start_wave + args.max_waves - 1)
        for wave_index in range(args.start_wave, last_wave + 1):
            # Recheck capacity and authoritative Qdrant parity before every
            # mutation, not only once at process start.
            assert_notice_disk_capacity(
                docker_path=args.docker_capacity_path,
                deposit_path=args.deposit_capacity_path,
                docker_min_free_ratio=args.docker_min_free_ratio,
                deposit_min_free_ratio=args.deposit_min_free_ratio,
                docker_min_free_bytes=minimum_free_bytes,
                deposit_min_free_bytes=minimum_free_bytes,
                docker_estimated_growth_bytes=args.estimated_docker_growth_bytes or 0,
                deposit_estimated_growth_bytes=args.estimated_deposit_growth_bytes or 0,
            )
            wave_baseline = asyncio.run(
                verify_notice_collection_gate(
                    db,
                    workspace=workspace,
                    collection=collection,
                )
            )
            baseline_document_count = int(collection.document_count or 0)
            baseline_chunk_count = int(
                wave_baseline.get("qdrant_chunk_count") or 0
            )
            baseline_document_names = [
                str(name) for name in (collection.document_names or [])
            ]
            queued = execute_notice_wave_plan(
                db,
                workspace=workspace,
                user=actor,
                plan=plan,
                expected_plan_hash=approved_hash,
                wave_index=wave_index,
            )
            wave = plan.waves[wave_index - 1]
            wave_id = str(
                queued.get("wave_id")
                or _notice_wave_id(plan, wave)
            )
            job_id = str(queued.get("job_id") or "")
            completed_job: WorkerJob | None = None
            recovery_baseline_names = list(baseline_document_names)
            recovery_baseline_document_count = baseline_document_count
            recovery_baseline_chunk_count = baseline_chunk_count
            recovery_baseline_missing = False
            try:
                postflight_stage = "worker_wait"
                if job_id:
                    job = _wait_for_job(
                        db,
                        job_id=job_id,
                        timeout_seconds=args.job_timeout_seconds,
                        poll_seconds=args.poll_seconds,
                    )
                    if job.status != "completed":
                        raise NoticeCampaignGateError(
                            "worker_job_not_completed:"
                            f"{job.id}:{job.status}:{job.error or ''}"
                        )
                    completed_job = job
                    job_result = dict(job.result or {})
                    if bool(job_result.get("postflight_required")):
                        options = dict(job_result.get("ingest_options") or {})
                        try:
                            (
                                recovery_baseline_names,
                                recovery_baseline_document_count,
                                recovery_baseline_chunk_count,
                            ) = notice_wave_baseline(options)
                        except NoticeWaveBaselineError as baseline_exc:
                            recovery_baseline_missing = True
                            raise NoticeCampaignGateError(
                                f"worker_job_baseline_invalid:{job.id}:"
                                f"{baseline_exc}"
                            ) from baseline_exc
                postflight_stage = "source_verification"
                db.expire_all()
                verification = asyncio.run(
                    _verify_wave_execution(
                        db,
                        workspace=workspace,
                        collection=collection,
                        queued=queued,
                        wave_id=wave_id,
                        expected_names=[
                            str(item.logical_name)
                            for item in wave.items
                            if item.logical_name
                        ],
                    )
                )
                postflight_stage = "capacity"
                disk_after = assert_notice_disk_capacity(
                    docker_path=args.docker_capacity_path,
                    deposit_path=args.deposit_capacity_path,
                    docker_min_free_ratio=args.docker_min_free_ratio,
                    deposit_min_free_ratio=args.deposit_min_free_ratio,
                    docker_min_free_bytes=minimum_free_bytes,
                    deposit_min_free_bytes=minimum_free_bytes,
                    docker_estimated_growth_bytes=(
                        args.estimated_docker_growth_bytes or 0
                    ),
                    deposit_estimated_growth_bytes=(
                        args.estimated_deposit_growth_bytes or 0
                    ),
                )
                if completed_job is not None:
                    _mark_postflight_verified(
                        db,
                        workspace=workspace,
                        collection=collection,
                        job=completed_job,
                        wave_id=wave_id,
                        actor=actor_identity,
                        snapshot_ref=str(args.snapshot_ref),
                        actor_user_id=str(actor.id),
                    )
            except Exception as exc:  # noqa: BLE001 - postflight is fail-closed.
                if (
                    postflight_stage == "worker_wait"
                    and str(exc).startswith("worker_job_timeout:")
                    and job_id
                ):
                    rearmed = fail_queued_notice_job(
                        db,
                        workspace=workspace,
                        collection=collection,
                        job_id=job_id,
                        wave_id=wave_id,
                        actor=actor_identity,
                        reason=str(exc),
                    )
                    if rearmed:
                        print(
                            json.dumps(
                                {
                                    "wave": {
                                        "index": wave_index,
                                        "execution": queued,
                                        "worker_wait_error": str(exc),
                                        "queued_job_rearmed": True,
                                    }
                                },
                                ensure_ascii=False,
                                indent=2,
                            )
                        )
                    else:
                        db.expire_all()
                        timed_out_job = (
                            db.query(WorkerJob)
                            .filter(WorkerJob.id == job_id)
                            .first()
                        )
                        if timed_out_job is not None and timed_out_job.status == "queued":
                            quarantine_notice_collection(
                                db,
                                workspace=workspace,
                                collection=collection,
                                wave_id=wave_id,
                                reason=(
                                    f"{exc}; queued job could not be safely rearmed"
                                ),
                                actor=actor_identity,
                            )
                if completed_job is not None and queued.get("document_names"):
                    try:
                        recovery = asyncio.run(
                            rollback_rejected_notice_wave(
                                db,
                                workspace=workspace,
                                collection=collection,
                                job=completed_job,
                                document_names=[
                                    str(name)
                                    for name in (queued.get("document_names") or [])
                                    if name
                                ],
                                wave_id=wave_id,
                                reason=f"{type(exc).__name__}:{exc}",
                                actor=actor_identity,
                                baseline_document_names=recovery_baseline_names,
                                baseline_document_count=(
                                    recovery_baseline_document_count
                                ),
                                baseline_chunk_count=recovery_baseline_chunk_count,
                                baseline_validation_names=[
                                    str(item.get("document_name") or "")
                                    for item in (queued.get("already_known") or [])
                                    if str(item.get("document_name") or "").strip()
                                ],
                                snapshot_ref=str(args.snapshot_ref),
                            )
                        )
                    except Exception as recovery_exc:  # noqa: BLE001
                        recovery = quarantine_notice_collection(
                            db,
                            workspace=workspace,
                            collection=collection,
                            wave_id=wave_id,
                            reason=(
                                f"postflight={type(exc).__name__}:{exc}; "
                                f"recovery={type(recovery_exc).__name__}:"
                                f"{recovery_exc}"
                            ),
                            actor=actor_identity,
                        )
                    print(
                        json.dumps(
                            {
                                "wave": {
                                    "index": wave_index,
                                    "execution": queued,
                                    "postflight_error": str(exc),
                                    "recovery": recovery,
                                }
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                elif (
                    recovery_baseline_missing
                    or postflight_stage == "source_verification"
                ):
                    quarantine_notice_collection(
                        db,
                        workspace=workspace,
                        collection=collection,
                        wave_id=wave_id,
                        reason=str(exc),
                        actor=actor_identity,
                    )
                raise
            print(
                json.dumps(
                    {
                        "wave": {
                            "index": wave_index,
                            "execution": queued,
                            "verification": verification,
                            "disk_after": disk_after,
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
