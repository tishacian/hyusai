from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services import notice_wave_importer as notice_wave_importer_service
from app.services.knowledge_collections import document_manifest_key, original_key
from app.services.notice_wave_importer import (
    DEFAULT_NOTICE_COLLECTION,
    LARGE_SOURCE_BYTES,
    MAX_BYTES_PER_WAVE,
    MAX_LOGICAL_NAME_LENGTH,
    NoticePlanDriftError,
    build_notice_wave_plan,
    execute_notice_wave_plan,
    fail_queued_notice_job,
    logical_document_name,
)
from app.services.object_store import get_object_store


def _seed_operator(db_session):
    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz")
    user = User(id="user-operator", username="operator", email="operator@example.test")
    link = DepositAccessLink(
        id="link-needlepunch",
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        label="Needlepunch SFTP",
        access_id="needlepunch-sftp",
        password_hash="not-used-by-importer",
        status="active",
        max_file_size_mb=4096,
        allowed_extensions=[],
    )
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(link)
    db_session.flush()
    return workspace, user, link


def _add_deposit(
    db_session,
    *,
    workspace: Workspace,
    link: DepositAccessLink,
    file_id: str,
    path: str,
    sha_char: str = "a",
    size_bytes: int = 1024,
    status: str = "received",
) -> DepositFile:
    row = DepositFile(
        id=file_id,
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename=path,
        content_type="application/pdf" if path.lower().endswith(".pdf") else None,
        object_key=f"staged/{file_id}",
        size_bytes=size_bytes,
        sha256=sha_char * 64,
        status=status,
    )
    db_session.add(row)
    return row


def _add_authoritative_collection(
    db_session,
    *,
    workspace: Workspace,
) -> KnowledgeCollection:
    row = KnowledgeCollection(
        id="collection-notices",
        workspace_id=workspace.id,
        slug=DEFAULT_NOTICE_COLLECTION,
        name="Andritz technical notices",
        description="",
        status="ready",
        document_names=[],
        vector_collection_name="andritz-notices-test",
        artifact_prefix="workspaces/ws-andritz/knowledge-collections/collection-notices",
        document_count=0,
        chunk_count=12,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_plan_classifies_structural_paths_and_never_scans_deeper_numbers(db_session):
    workspace, _user, link = _seed_operator(db_session)
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="valid-61001",
        path=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61001CdFreudenberg USA du 22 05 2003/manual.pdf"
        ),
    )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="deeper-number",
        path=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "unknown/manuals/61038/pump.pdf"
        ),
        sha_char="b",
    )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="range-mismatch",
        path=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "70170 Card/document.pdf"
        ),
        sha_char="c",
    )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="unrelated-spl",
        path="Notices_Techniques_SPL/B/Manual_BCX200.pdf",
        sha_char="d",
    )
    db_session.commit()

    plan = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        project_range="60000-69999",
    )

    by_id = {item.deposit_file_id: item for item in plan.items}
    assert set(by_id) == {"valid-61001", "deeper-number", "range-mismatch"}
    assert by_id["valid-61001"].disposition == "eligible"
    assert by_id["valid-61001"].project_metadata == {
        "project_code": "61001",
        "project_reference_kind": "andritz_project",
        "project_code_scheme": "needlepunch_numeric5",
        "business_scope": "needlepunch",
        "project_range": "60000-69999",
        "project_folder": "61001CdFreudenberg USA du 22 05 2003",
    }
    assert by_id["deeper-number"].reason == "invalid_needlepunch_project_path"
    assert by_id["range-mismatch"].reason == "invalid_needlepunch_project_path"
    assert plan.disposition_counts == {"eligible": 1, "unsupported": 2}


def test_plan_prefix_is_confined_and_covered_by_hash(db_session):
    workspace, _user, link = _seed_operator(db_session)
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="p61001",
        path=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61001CdFreudenberg USA du 22 05 2003/a.pdf"
        ),
    )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="p70170",
        path="Notices_Techniques_Needlepunch/70000-79999/70170 B/b.pdf",
        sha_char="b",
    )
    db_session.commit()

    narrowed = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61001"],
        source_prefix="Notices_Techniques_Needlepunch/60000-69999",
    )
    root = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61001"],
    )
    assert [item.deposit_file_id for item in narrowed.items] == ["p61001"]
    assert narrowed.source_prefix.endswith("60000-69999/")
    assert narrowed.plan_hash != root.plan_hash

    with pytest.raises(ValueError, match="must stay under"):
        build_notice_wave_plan(
            db_session,
            workspace=workspace,
            projects=["61001"],
            source_prefix="Notices_Techniques_SPL/",
        )


def test_plan_keeps_reuploads_and_bounds_collision_resistant_names(db_session):
    workspace, _user, link = _seed_operator(db_session)
    leaf = f"{'manual-' * 45}final.PDF"
    path = f"Notices_Techniques_Needlepunch/60000-69999/61035 Card/{leaf}"
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="upload-one",
        path=path,
        sha_char="1",
    )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="upload-two",
        path=path,
        sha_char="2",
    )
    db_session.commit()

    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61035"])

    assert len(plan.items) == 2
    names = {item.logical_name for item in plan.items}
    assert len(names) == 2
    assert all(name and len(name) <= MAX_LOGICAL_NAME_LENGTH for name in names)
    assert all(name.endswith(".pdf") for name in names)
    assert any("111111111111" in name for name in names)
    assert any("222222222222" in name for name in names)

    deposit = db_session.query(DepositFile).filter_by(id="upload-one").one()
    same_content = "f" * 64
    colliding_stems = {
        logical_document_name(
            deposit,
            project_code="61035",
            source_name=member_path,
            content_sha256=same_content,
        )
        for member_path in ("manual/a+b.pdf", "manual/a b.pdf")
    }
    assert len(colliding_stems) == 2


def test_plan_bounds_waves_and_isolates_large_sources(db_session):
    workspace, _user, link = _seed_operator(db_session)
    for index in range(101):
        _add_deposit(
            db_session,
            workspace=workspace,
            link=link,
            file_id=f"small-{index:03d}",
            path=(
                "Notices_Techniques_Needlepunch/60000-69999/"
                f"61009 Line/manual-{index:03d}.pdf"
            ),
            sha_char=f"{index % 10}",
            size_bytes=1024,
        )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="large",
        path="Notices_Techniques_Needlepunch/60000-69999/61009 Line/large.pdf",
        sha_char="e",
        size_bytes=LARGE_SOURCE_BYTES + 1,
    )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="ledger-boundary",
        path="Notices_Techniques_Needlepunch/60000-69999/61009 Line/boundary.pdf",
        sha_char="d",
        size_bytes=MAX_BYTES_PER_WAVE,
    )
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="too-large",
        path="Notices_Techniques_Needlepunch/60000-69999/61009 Line/huge.pdf",
        sha_char="f",
        size_bytes=MAX_BYTES_PER_WAVE + 1,
    )
    db_session.commit()

    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61009"])

    assert all(len(wave.items) <= 100 for wave in plan.waves)
    assert all(wave.total_bytes <= MAX_BYTES_PER_WAVE for wave in plan.waves)
    large_wave = next(wave for wave in plan.waves if wave.items[0].deposit_file_id == "large")
    assert len(large_wave.items) == 1
    too_large = next(item for item in plan.items if item.deposit_file_id == "too-large")
    assert too_large.disposition == "unsupported"
    assert too_large.reason == "source_exceeds_source_ledger_limit"
    boundary = next(
        item for item in plan.items if item.deposit_file_id == "ledger-boundary"
    )
    assert boundary.disposition == "unsupported"
    assert boundary.reason == "source_exceeds_source_ledger_limit"


def test_invalid_hash_and_zip_are_explicitly_classified(db_session):
    workspace, _user, link = _seed_operator(db_session)
    invalid_hash = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="bad-hash",
        path="Notices_Techniques_Needlepunch/60000-69999/61035 A/a.pdf",
    )
    invalid_hash.sha256 = "not-a-sha"
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="zip",
        path="Notices_Techniques_Needlepunch/60000-69999/61035 A/archive.zip",
        sha_char="b",
    )
    db_session.commit()

    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61035"])
    by_id = {item.deposit_file_id: item for item in plan.items}
    assert (by_id["bad-hash"].disposition, by_id["bad-hash"].reason) == (
        "unsupported",
        "invalid_sha256",
    )
    assert (by_id["zip"].disposition, by_id["zip"].reason) == (
        "deferred_zip",
        "zip_requires_safe_member_campaign",
    )


def test_zip_archive_size_is_not_written_to_the_integer_source_ledger(monkeypatch):
    deposit = DepositFile(
        id="large-archive",
        workspace_id="ws-andritz",
        access_link_id="link-needlepunch",
        filename=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61035 A/large-archive.zip"
        ),
        object_key="staged/large-archive",
        size_bytes=MAX_BYTES_PER_WAVE + 1,
        sha256="a" * 64,
        status="received",
    )
    sentinel = object()
    monkeypatch.setattr(
        notice_wave_importer_service,
        "_inspect_zip_members",
        lambda *_args, **_kwargs: [sentinel],
    )

    items = notice_wave_importer_service._classify_deposit(
        deposit,
        profile=notice_wave_importer_service.NOTICE_SOURCE_PROFILES["needlepunch"],
        project_metadata={"project_code": "61035"},
        campaign="zip",
    )

    assert items == [sentinel]


def test_execute_requires_unchanged_hash_and_exact_authoritative_collection(db_session):
    workspace, user, link = _seed_operator(db_session)
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="drift-source",
        path="Notices_Techniques_Needlepunch/60000-69999/61035 A/a.pdf",
    )
    _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()

    with pytest.raises(ValueError, match="authoritative collection"):
        build_notice_wave_plan(
            db_session,
            workspace=workspace,
            collection_slug="some-other-collection",
            projects=["61035"],
        )

    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61035"])
    deposit.sha256 = "b" * 64
    db_session.commit()

    with pytest.raises(NoticePlanDriftError):
        execute_notice_wave_plan(
            db_session,
            workspace=workspace,
            user=user,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
            dispatch=False,
        )
    assert db_session.query(WorkerJob).count() == 0
    assert db_session.query(KnowledgeCollectionSource).count() == 0


def test_execute_queues_incremental_no_copy_manifest_and_keeps_received(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    workspace, user, link = _seed_operator(db_session)
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="source-61035",
        path="Notices_Techniques_Needlepunch/60000-69999/61035 Card/manual.pdf",
        sha_char="a",
        size_bytes=2048,
    )
    collection = _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()

    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61035"])
    result = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )

    assert result["status"] == "queued"
    assert result["source_count"] == 1
    source = db_session.query(KnowledgeCollectionSource).one()
    job = db_session.query(WorkerJob).one()
    locator = source.source_metadata["source_locator"]
    assert locator == {
        "kind": "secure_deposit_file",
        "deposit_file_id": deposit.id,
        "size_bytes": 2048,
        "sha256": "a" * 64,
    }
    assert source.source_metadata["project_code"] == "61035"
    assert source.source_metadata["source_deposit_path"] == deposit.filename
    assert job.kind == "document_ingest_index"
    assert job.result["ingest_options"] == {
        "mode": "incremental",
        "document_names": [source.normalized_name],
        "already_known_document_names": [],
        "baseline_document_names": [],
        "baseline_document_count": 0,
        "baseline_chunk_count": 12,
        "wave_id": result["wave_id"],
        "source_profile": "needlepunch",
        "source_campaign": "direct",
    }
    assert deposit.status == "received"
    assert deposit.worker_job_id == job.id

    store = get_object_store()
    manifest = json.loads(
        store.read_bytes(document_manifest_key(collection)).decode("utf-8")
    )
    assert manifest[source.normalized_name]["source_locator"] == locator
    assert not store.exists(original_key(collection, source.normalized_name))

    repeated = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )
    assert repeated["status"] == "noop"
    assert repeated["reason"] == "wave_already_active"
    assert repeated["document_names"] == [source.normalized_name]
    assert db_session.query(WorkerJob).count() == 1

    job.status = "completed"
    job.result = {
        **dict(job.result or {}),
        "postflight_required": True,
        "postflight_status": "pending",
    }
    source.status = "ready"
    db_session.commit()
    awaiting = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )
    assert awaiting["status"] == "noop"
    assert awaiting["reason"] == "wave_awaiting_postflight"
    assert awaiting["job_id"] == job.id
    assert awaiting["document_names"] == [source.normalized_name]


def test_execute_serializes_collection_ingestion_jobs(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    workspace, user, link = _seed_operator(db_session)
    for code, sha_char in (("61035", "a"), ("61036", "b")):
        _add_deposit(
            db_session,
            workspace=workspace,
            link=link,
            file_id=f"source-{code}",
            path=(
                "Notices_Techniques_Needlepunch/60000-69999/"
                f"{code} Card/manual.pdf"
            ),
            sha_char=sha_char,
        )
    collection = _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()

    first_plan = build_notice_wave_plan(
        db_session, workspace=workspace, projects=["61035"]
    )
    first = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=first_plan,
        expected_plan_hash=first_plan.plan_hash,
        dispatch=False,
    )
    second_plan = build_notice_wave_plan(
        db_session, workspace=workspace, projects=["61036"]
    )

    with pytest.raises(ValueError, match="already active"):
        execute_notice_wave_plan(
            db_session,
            workspace=workspace,
            user=user,
            plan=second_plan,
            expected_plan_hash=second_plan.plan_hash,
            dispatch=False,
        )
    assert db_session.query(WorkerJob).count() == 1

    first_job = db_session.query(WorkerJob).filter_by(id=first["job_id"]).one()
    first_job.status = "completed"
    db_session.commit()
    second = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=second_plan,
        expected_plan_hash=second_plan.plan_hash,
        dispatch=False,
    )
    assert second["status"] == "queued"

    db_session.query(WorkerJob).filter_by(id=second["job_id"]).update(
        {"status": "completed"}
    )
    collection.status = "error"
    db_session.commit()
    with pytest.raises(ValueError, match="must be ready"):
        execute_notice_wave_plan(
            db_session,
            workspace=workspace,
            user=user,
            plan=second_plan,
            expected_plan_hash=second_plan.plan_hash,
            dispatch=False,
        )


def test_legacy_campaign_is_explicit_and_xls_is_never_taken_by_direct(db_session):
    workspace, _user, link = _seed_operator(db_session)
    _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="legacy-xls",
        path="Notices_Techniques_Needlepunch/60000-69999/61009 Line/spares.xls",
        sha_char="c",
    )
    db_session.commit()

    direct = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61009"],
        campaign="direct",
    )
    legacy = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61009"],
        campaign="legacy",
    )

    assert (direct.items[0].disposition, direct.items[0].reason) == (
        "deferred_legacy",
        "legacy_campaign_required",
    )
    assert legacy.items[0].disposition == "eligible"
    assert direct.plan_hash != legacy.plan_hash


def test_zip_campaign_hashes_safe_members_and_never_recurses(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    workspace, _user, link = _seed_operator(db_session)
    archive_path = tmp_path / "manuals.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manual/chapter.pdf", b"chapter 61038")
        archive.writestr("nested/archive.zip", b"PK nested archive")
        archive.writestr("../escape.txt", b"unsafe")
        archive.writestr("manual\\windows.pdf", b"ambiguous separator")
        archive.writestr("manual//double.pdf", b"double separator")
        archive.writestr("manual/./dot.pdf", b"dot segment")
        archive.writestr("software/setup.exe", b"binary")
    archive_bytes = archive_path.read_bytes()
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="zip-61038",
        path="Notices_Techniques_Needlepunch/60000-69999/61038 Line/manuals.zip",
        size_bytes=len(archive_bytes),
    )
    deposit.sha256 = hashlib.sha256(archive_bytes).hexdigest()
    db_session.commit()
    monkeypatch.setattr(
        "app.services.notice_wave_importer._staged_path",
        lambda _deposit: archive_path,
    )

    direct = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61038"],
        campaign="direct",
    )
    assert direct.items[0].disposition == "deferred_zip"

    plan = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61038"],
        campaign="zip",
    )
    by_member = {item.member_path: item for item in plan.items}
    valid = by_member["manual/chapter.pdf"]
    assert valid.disposition == "eligible"
    assert valid.member_sha256 == hashlib.sha256(b"chapter 61038").hexdigest()
    assert valid.logical_name and valid.logical_name.endswith(".pdf")
    assert by_member["nested/archive.zip"].reason == "nested_archive_not_recursed"
    assert by_member["../escape.txt"].reason == "unsafe_zip_member_path"
    assert by_member["manual\\windows.pdf"].reason == "unsafe_zip_member_path"
    assert by_member["manual//double.pdf"].reason == "unsafe_zip_member_path"
    assert by_member["manual/./dot.pdf"].reason == "unsafe_zip_member_path"
    assert by_member["software/setup.exe"].reason.startswith(
        "unsupported_zip_member_extension"
    )
    assert len(plan.waves) == 1
    approved_hash = plan.plan_hash

    # The central-directory member inventory and member digest are part of the
    # approved plan, independently from mutable operator output formatting.
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manual/chapter.pdf", b"chapter changed")
        archive.writestr("nested/archive.zip", b"PK nested archive")
        archive.writestr("../escape.txt", b"unsafe")
        archive.writestr("manual\\windows.pdf", b"ambiguous separator")
        archive.writestr("manual//double.pdf", b"double separator")
        archive.writestr("manual/./dot.pdf", b"dot segment")
        archive.writestr("software/setup.exe", b"binary")
    changed = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61038"],
        campaign="zip",
    )
    assert changed.plan_hash != approved_hash


def test_zip_campaign_rejects_high_ratio_archive_as_a_whole(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    workspace, _user, link = _seed_operator(db_session)
    archive_path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manual.txt", b"0" * (1024 * 1024))
    archive_bytes = archive_path.read_bytes()
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="zip-bomb",
        path="Notices_Techniques_Needlepunch/60000-69999/61038 Line/bomb.zip",
        size_bytes=len(archive_bytes),
    )
    deposit.sha256 = hashlib.sha256(archive_bytes).hexdigest()
    db_session.commit()
    monkeypatch.setattr(
        "app.services.notice_wave_importer._staged_path",
        lambda _deposit: archive_path,
    )

    plan = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61038"],
        campaign="zip",
    )
    assert plan.waves == ()
    assert plan.items[0].reason == "zip_total_compression_ratio_exceeded"


def test_zip_archive_that_spans_waves_keeps_members_eligible_and_bounded(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    workspace, _user, link = _seed_operator(db_session)
    archive_path = tmp_path / "many-members.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(101):
            archive.writestr(f"manuals/chapter-{index:03d}.txt", f"chapter {index}")
    archive_bytes = archive_path.read_bytes()
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="zip-many",
        path="Notices_Techniques_Needlepunch/60000-69999/61038 Line/many.zip",
        size_bytes=len(archive_bytes),
    )
    deposit.sha256 = hashlib.sha256(archive_bytes).hexdigest()
    db_session.commit()
    monkeypatch.setattr(
        "app.services.notice_wave_importer._staged_path",
        lambda _deposit: archive_path,
    )

    plan = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61038"],
        campaign="zip",
    )

    assert len(plan.items) == 101
    assert {item.disposition for item in plan.items} == {"eligible"}
    assert len(plan.waves) == 2
    assert [len(wave.items) for wave in plan.waves] == [100, 1]
    assert all(
        {item.deposit_file_id for item in wave.items} == {deposit.id}
        for wave in plan.waves
    )


def test_zip_waves_never_mix_members_from_distinct_deposits(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    workspace, _user, link = _seed_operator(db_session)
    archive_by_id: dict[str, Path] = {}
    for file_id, sha_char in (("zip-a", "a"), ("zip-b", "b")):
        archive_path = tmp_path / f"{file_id}.zip"
        with zipfile.ZipFile(
            archive_path, "w", compression=zipfile.ZIP_STORED
        ) as archive:
            for index in range(60):
                archive.writestr(
                    f"manuals/chapter-{index:03d}.txt",
                    f"{file_id} chapter {index}",
                )
        archive_bytes = archive_path.read_bytes()
        deposit = _add_deposit(
            db_session,
            workspace=workspace,
            link=link,
            file_id=file_id,
            path=(
                "Notices_Techniques_Needlepunch/60000-69999/"
                f"61038 Line/{file_id}.zip"
            ),
            sha_char=sha_char,
            size_bytes=len(archive_bytes),
        )
        deposit.sha256 = hashlib.sha256(archive_bytes).hexdigest()
        archive_by_id[file_id] = archive_path
    db_session.commit()
    monkeypatch.setattr(
        "app.services.notice_wave_importer._staged_path",
        lambda deposit: archive_by_id[str(deposit.id)],
    )

    plan = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61038"],
        campaign="zip",
    )

    assert [len(wave.items) for wave in plan.waves] == [60, 60]
    assert [
        {item.deposit_file_id for item in wave.items} for wave in plan.waves
    ] == [{"zip-a"}, {"zip-b"}]


def test_execute_zip_wave_writes_validated_member_locator(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    workspace, user, link = _seed_operator(db_session)
    archive_path = tmp_path / "one-member.zip"
    member = b"Needlepunch chapter 61038"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manual/chapter.pdf", member)
    archive_bytes = archive_path.read_bytes()
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="zip-execute",
        path="Notices_Techniques_Needlepunch/60000-69999/61038 Line/manual.zip",
        size_bytes=len(archive_bytes),
    )
    deposit.sha256 = hashlib.sha256(archive_bytes).hexdigest()
    collection = _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()
    monkeypatch.setattr(
        "app.services.notice_wave_importer._staged_path",
        lambda _deposit: archive_path,
    )

    plan = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61038"],
        campaign="zip",
    )
    result = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )

    source = db_session.query(KnowledgeCollectionSource).one()
    locator = source.source_metadata["source_locator"]
    assert result["status"] == "queued"
    assert locator == {
        "kind": "secure_deposit_zip_member",
        "deposit_file_id": deposit.id,
        "size_bytes": len(archive_bytes),
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "member_path": "manual/chapter.pdf",
        "member_size_bytes": len(member),
        "member_sha256": hashlib.sha256(member).hexdigest(),
    }
    assert source.source_metadata["content_sha256"] == hashlib.sha256(member).hexdigest()
    assert deposit.status == "received"
    manifest = json.loads(
        get_object_store().read_bytes(document_manifest_key(collection)).decode("utf-8")
    )
    assert manifest[source.normalized_name]["source_locator"] == locator
    assert not get_object_store().exists(original_key(collection, source.normalized_name))


def test_execute_persists_full_classification_without_promoting_deferred_source(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    workspace, user, link = _seed_operator(db_session)
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="deferred-xls",
        path="Notices_Techniques_Needlepunch/60000-69999/61009 Line/spares.xls",
        sha_char="d",
    )
    _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()

    plan = build_notice_wave_plan(
        db_session,
        workspace=workspace,
        projects=["61009"],
        campaign="direct",
    )
    result = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )

    db_session.refresh(deposit)
    assert result["status"] == "noop"
    assert deposit.status == "received"
    classification = deposit.promotion_result["notice_classification"]
    assert classification["disposition_counts"] == {"deferred_legacy": 1}
    report = json.loads(get_object_store().read_bytes(result["report_key"]))
    assert report["items"][0]["reason"] == "legacy_campaign_required"
    assert db_session.query(WorkerJob).count() == 0


def test_execute_rearms_failed_source_instead_of_treating_it_as_terminal(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    workspace, user, link = _seed_operator(db_session)
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="retry-source",
        path="Notices_Techniques_Needlepunch/60000-69999/61035 Card/manual.pdf",
    )
    _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()
    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61035"])
    first = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )
    source = db_session.query(KnowledgeCollectionSource).one()
    first_job = db_session.query(WorkerJob).filter_by(id=first["job_id"]).one()
    source.status = "error"
    source.last_error = "parser failed"
    first_job.status = "failed"
    deposit.status = "received"
    db_session.commit()

    retried = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )

    db_session.refresh(source)
    assert retried["status"] == "queued"
    assert retried["job_id"] != first["job_id"]
    assert source.status == "queued"
    assert source.last_error is None
    assert db_session.query(WorkerJob).count() == 2


def test_dispatch_failure_is_terminal_and_same_plan_can_be_reexecuted(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "object-store"))
    workspace, user, link = _seed_operator(db_session)
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="dispatch-retry-source",
        path=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61035 Card/dispatch-retry.pdf"
        ),
    )
    collection = _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()
    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61035"])

    def unavailable_dispatch(db, job, *, allow_inline_fallback=True):
        assert allow_inline_fallback is False
        job.result = {
            **(job.result or {}),
            "stage": "dispatch_pending",
            "dispatch_warning": "worker_dispatch_unavailable",
            "dispatch_error": "broker offline",
        }
        db.commit()
        return None

    monkeypatch.setattr(
        notice_wave_importer_service,
        "dispatch_worker_job",
        unavailable_dispatch,
    )
    with pytest.raises(RuntimeError, match="dispatch failed.*broker offline"):
        execute_notice_wave_plan(
            db_session,
            workspace=workspace,
            user=user,
            plan=plan,
            expected_plan_hash=plan.plan_hash,
        )

    db_session.expire_all()
    first_job = db_session.query(WorkerJob).one()
    source = db_session.query(KnowledgeCollectionSource).one()
    failed_deposit = db_session.query(DepositFile).filter_by(id=deposit.id).one()
    failed_collection = (
        db_session.query(KnowledgeCollection).filter_by(id=collection.id).one()
    )
    assert first_job.status == "failed"
    assert first_job.progress == 100
    assert first_job.error == "broker offline"
    assert first_job.result["stage"] == "dispatch_failed"
    assert first_job.result["dispatch_error"] == "broker offline"
    assert source.status == "error"
    assert source.last_error == "broker offline"
    assert failed_deposit.status == "received"
    assert failed_deposit.worker_job_id == first_job.id
    assert failed_deposit.promotion_result["status"] == "dispatch_failed"
    assert failed_deposit.promotion_result["indexing_status"] == "failed"
    assert failed_deposit.promotion_result["dispatch_status"] == "failed"
    assert failed_deposit.promotion_result["dispatch_error"] == "broker offline"
    assert failed_collection.status == "ready"
    assert failed_collection.document_names == []
    assert failed_collection.document_count == 0
    assert failed_collection.chunk_count == 12

    def successful_dispatch(_db, job, *, allow_inline_fallback=True):
        assert allow_inline_fallback is False
        job.celery_task_id = "celery-retry-task"
        return job.celery_task_id

    monkeypatch.setattr(
        notice_wave_importer_service,
        "dispatch_worker_job",
        successful_dispatch,
    )
    retried = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
    )

    db_session.expire_all()
    retried_source = db_session.query(KnowledgeCollectionSource).one()
    retried_deposit = db_session.query(DepositFile).filter_by(id=deposit.id).one()
    jobs = db_session.query(WorkerJob).all()
    assert retried["status"] == "queued"
    assert retried["celery_task_id"] == "celery-retry-task"
    assert retried["job_id"] != first_job.id
    assert {job.status for job in jobs} == {"failed", "queued"}
    assert retried_source.status == "queued"
    assert retried_source.last_error is None
    assert retried_deposit.status == "received"
    assert retried_deposit.worker_job_id == retried["job_id"]
    assert retried_deposit.promotion_result["status"] == "queued"
    assert retried_deposit.promotion_result["indexing_status"] == "queued"
    assert "dispatch_status" not in retried_deposit.promotion_result
    assert "dispatch_error" not in retried_deposit.promotion_result


def test_timed_out_unclaimed_job_is_atomically_rearmed(
    db_session,
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    workspace, user, link = _seed_operator(db_session)
    deposit = _add_deposit(
        db_session,
        workspace=workspace,
        link=link,
        file_id="timeout-61035",
        path=(
            "Notices_Techniques_Needlepunch/60000-69999/"
            "61035 Card/timeout.pdf"
        ),
    )
    collection = _add_authoritative_collection(db_session, workspace=workspace)
    db_session.commit()
    plan = build_notice_wave_plan(db_session, workspace=workspace, projects=["61035"])
    queued = execute_notice_wave_plan(
        db_session,
        workspace=workspace,
        user=user,
        plan=plan,
        expected_plan_hash=plan.plan_hash,
        dispatch=False,
    )

    rearmed = fail_queued_notice_job(
        db_session,
        workspace=workspace,
        collection=collection,
        job_id=queued["job_id"],
        wave_id=queued["wave_id"],
        actor=user.email,
        reason="worker_job_timeout:test",
    )

    db_session.expire_all()
    job = db_session.query(WorkerJob).filter_by(id=queued["job_id"]).one()
    source = db_session.query(KnowledgeCollectionSource).one()
    db_session.refresh(deposit)
    assert rearmed is True
    assert job.status == "failed"
    assert job.result["stage"] == "dispatch_timeout_rearmed"
    assert source.status == "error"
    assert deposit.status == "received"
    db_session.refresh(collection)
    assert collection.document_names == []
    assert collection.document_count == 0
    assert collection.chunk_count == 12
    assert (
        fail_queued_notice_job(
            db_session,
            workspace=workspace,
            collection=collection,
            job_id=job.id,
            wave_id=queued["wave_id"],
            actor=user.email,
            reason="again",
        )
        is False
    )
