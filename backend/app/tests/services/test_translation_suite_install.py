"""Translation Suite installer: published event-chained Systems, pinned Skills, review app."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.experience import ExperienceRelease
from app.models.remote_runner import RemoteRunner
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.remote_runners.catalogs import translation_suite as commands
from app.services.run_engine import triggers
from app.services.translation_suite.install import REQUIRED_COMMANDS, InstallError, install


@pytest.fixture
def seeded(db_session, monkeypatch):
    monkeypatch.setattr(settings, "enable_event_triggers", True, raising=False)
    workspace = Workspace(id="ts-install", name="Showcase", slug="ts-install", settings={})
    user = User(id="ts-owner", username="ts-owner", email="ts-owner@example.invalid")
    db_session.add_all([workspace, user])
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            role_template="workspace_owner",
        )
    )
    runner = RemoteRunner(
        workspace_id=workspace.id,
        slug="gpu-vm",
        name="GPU VM",
        transport="ssh",
        host="vm.internal",
        port=22,
        username="agentium",
        host_key="ssh-ed25519 AAAA",
        key_secret_ref="secret://workspace/gpu-vm",
        work_root="/srv/agentium",
        allowed_commands=list(REQUIRED_COMMANDS),
        labels={key: f"/srv/{i}" for i, key in enumerate(commands.PATHS)},
        max_concurrent_jobs=1,
        enabled=True,
    )
    db_session.add(runner)
    db_session.commit()
    return workspace, user, runner


def test_install_publishes_three_chained_systems_and_the_review_app(db_session, seeded):
    workspace, user, runner = seeded
    try:
        result = install(db_session, workspace, user, runner_slug="gpu-vm")
    except Exception as exc:  # surface publication details
        pytest.fail(str(getattr(exc, "details", None) or exc))
    db_session.commit()
    assert result["channel"] == "pilot"
    chain = db_session.get(System, result["systems"]["chain"])
    version = db_session.get(SystemVersion, result["published_versions"]["chain"])
    ingress = version.execution_contract["ingresses"][0]
    assert ingress["ingress_id"] == "source.job"
    prepare = db_session.query(Skill).filter(Skill.slug == result["skills"]["prepare"]).one()
    frozen = prepare.executor["params"]["frozen_input"]
    assert frozen == {
        "runner": "gpu-vm",
        "command": "translation_suite.prepare",
        "param_keys": ["lot"],
        "notify_system_id": chain.id,
    }
    review_open = (
        db_session.query(Skill).filter(Skill.slug == result["skills"]["review_open"]).one()
    )
    assert (
        review_open.executor["params"]["frozen_input"]["notify_system_id"]
        == result["systems"]["feedback"]
    )
    registry = triggers.build_registry(db_session, workspace_id=workspace.id)
    assert registry[("remote_runner.job_finished", workspace.id)] == [chain.id]
    assert registry[("review_set.completed", workspace.id)] == [result["systems"]["feedback"]]
    assert registry[("deposit.promoted", workspace.id)] == [result["systems"]["launch"]]
    release = db_session.get(ExperienceRelease, result["release_id"])
    types = [c["type"] for page in release.pages["pages"] for c in page["components"]]
    assert types == ["review_workbench", "review_matrix"]
    with pytest.raises(InstallError, match="ALREADY_EXISTS"):
        install(db_session, workspace, user, runner_slug="gpu-vm")


def test_install_requires_a_runner_with_the_translation_commands(db_session, seeded):
    workspace, user, runner = seeded
    runner.allowed_commands = ["agentium.sleep"]
    db_session.commit()
    with pytest.raises(InstallError, match="RUNNER_COMMANDS_MISSING"):
        install(db_session, workspace, user, runner_slug="gpu-vm")
    with pytest.raises(InstallError, match="RUNNER_MISSING"):
        install(db_session, workspace, user, runner_slug="nope")


def test_a_finished_prepare_job_starts_the_translation(db_session, seeded, monkeypatch):
    """End to end inside Agentium: event → published chain System → pinned Skill → new job."""

    import asyncio
    from datetime import datetime, timedelta

    from app.models.remote_runner import RemoteRunnerJob
    from app.models.run import Run
    from app.services.remote_runners import service as runners
    from app.services.run_engine.dag import execute_run_dag

    workspace, user, runner = seeded
    result = install(db_session, workspace, user, runner_slug="gpu-vm")
    db_session.commit()
    executed = []

    def run_inline(run_id):
        executed.append(asyncio.run(execute_run_dag(run_id)))

    monkeypatch.setattr(triggers, "_dispatch_live_run", run_inline)
    now = datetime.utcnow()
    prepared = RemoteRunnerJob(
        workspace_id=workspace.id,
        runner_id=runner.id,
        command="translation_suite.prepare",
        params={"lot": "LOT-7"},
        status="succeeded",
        exit_code=0,
        result={"lot": "LOT-7"},
        inputs=[],
        artifacts=[],
        cancel_requested=False,
        created_at=now,
        deadline_at=now + timedelta(hours=1),
        finished_at=now,
        notify_system_id=result["systems"]["chain"],
        correlation_key="lot-7",
    )
    db_session.add(prepared)
    db_session.commit()
    assert runners.announce_finished(db_session) == 1
    db_session.expire_all()
    runs = db_session.query(Run).filter(Run.system_id == result["systems"]["chain"]).all()
    assert len(runs) == 1, executed
    if not executed:  # the published path hands the run to the dispatch outbox
        run_inline(runs[0].id)
        db_session.expire_all()
    assert runs[0].status == "completed", (runs[0].status, runs[0].error, executed)
    queued = (
        db_session.query(RemoteRunnerJob)
        .filter(RemoteRunnerJob.command == "translation_suite.translate")
        .one()
    )
    assert queued.params == {"lot": "LOT-7", "max_parallel": 2}
    assert queued.notify_system_id == result["systems"]["chain"]
    assert queued.run_id == runs[0].id


def test_exported_segments_open_review_sets_and_their_completion_waits_for_a_person(
    db_session, seeded, monkeypatch, tmp_path
):
    import asyncio
    import json
    from datetime import datetime, timedelta

    from app.models.remote_runner import RemoteRunnerJob
    from app.models.review_set import ReviewSet
    from app.models.run import Run
    from app.services import review_sets as rs
    from app.services.object_store import get_object_store
    from app.services.remote_runners import service as runners
    from app.services.run_engine.dag import execute_run_dag

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    workspace, user, runner = seeded
    result = install(db_session, workspace, user, runner_slug="gpu-vm")
    db_session.commit()

    def drain(system_id):
        for run in (
            db_session.query(Run).filter(Run.system_id == system_id, Run.status == "pending").all()
        ):
            asyncio.run(execute_run_dag(run.id))
        db_session.expire_all()

    monkeypatch.setattr(triggers, "_dispatch_live_run", lambda run_id: None)
    lines = [
        {
            "item_ref": "u1",
            "group": "de-DE",
            "tier": "P1",
            "weight": 3,
            "subject": {"source": "Frein", "candidate": "Bremse", "language": "de-DE"},
        },
        {
            "item_ref": "u2",
            "group": "it-IT",
            "tier": "P4",
            "weight": 2,
            "subject": {"source": "Roue", "candidate": "Ruota", "language": "it-IT"},
        },
    ]
    key = get_object_store().key("remote-runners", workspace.id, "export", "review.jsonl")
    get_object_store().write_bytes(key, "\n".join(json.dumps(line) for line in lines).encode())
    now = datetime.utcnow()
    db_session.add(
        RemoteRunnerJob(
            workspace_id=workspace.id,
            runner_id=runner.id,
            command="translation_suite.review_export",
            params={"lot": "LOT-7"},
            status="succeeded",
            exit_code=0,
            result={"items": 2},
            inputs=[],
            artifacts=[{"path": "review.jsonl", "present": True, "key": key}],
            cancel_requested=False,
            created_at=now,
            deadline_at=now + timedelta(hours=1),
            finished_at=now,
            notify_system_id=result["systems"]["chain"],
        )
    )
    db_session.commit()
    runners.announce_finished(db_session)
    drain(result["systems"]["chain"])
    sets = db_session.query(ReviewSet).order_by(ReviewSet.group_key).all()
    assert [(s.group_key, s.group_labels) for s in sets] == [
        ("LOT-7:de-DE", {"lot": "LOT-7", "language": "de-DE"}),
        ("LOT-7:it-IT", {"lot": "LOT-7", "language": "it-IT"}),
    ]
    german = sets[0]
    item = db_session.query(rs.ReviewItem).filter_by(set_id=german.id).one()
    rs.decide(
        db_session,
        german,
        item,
        user_id=user.id,
        revision=0,
        decision="correct",
        value="Bremsscheibe",
        annotations=[{"category": "WT", "severity": "minor"}],
    )
    db_session.commit()
    assert rs.announce_completed(db_session) == 1
    drain(result["systems"]["feedback"])
    feedback_run = (
        db_session.query(Run).filter(Run.system_id == result["systems"]["feedback"]).one()
    )
    assert feedback_run.status == "hitl_pending"
    assert (
        not db_session.query(RemoteRunnerJob)
        .filter_by(command="translation_suite.reinject")
        .first()
    )


def test_a_certify_profile_adds_certification_after_packaging(db_session, seeded):
    workspace, user, runner = seeded
    profile = {"source_dir": "/srv/k3/Topics/Source", "expected": {"locales": 39}}
    with pytest.raises(InstallError, match="RUNNER_COMMANDS_MISSING"):
        install(db_session, workspace, user, runner_slug="gpu-vm", certify_profile=profile)
    runner.allowed_commands = [*REQUIRED_COMMANDS, commands.CERTIFY.key]
    db_session.commit()
    result = install(db_session, workspace, user, runner_slug="gpu-vm", certify_profile=profile)
    db_session.commit()
    certify = db_session.query(Skill).filter(Skill.slug == result["skills"]["certify"]).one()
    frozen = certify.executor["params"]["frozen_input"]
    assert frozen["command"] == "translation_suite.certify"
    assert frozen["documents"] == {"certify_profile.json": profile}
    version = db_session.get(SystemVersion, result["published_versions"]["chain"])
    assert version is not None
    chain = db_session.get(System, result["systems"]["chain"])
    assert certify.id in chain.skill_ids


def test_a_finished_package_job_queues_the_certification(db_session, seeded, monkeypatch):
    import asyncio
    from datetime import datetime, timedelta

    from app.models.remote_runner import RemoteRunnerJob
    from app.models.run import Run
    from app.services.remote_runners import service as runners
    from app.services.run_engine.dag import execute_run_dag

    workspace, user, runner = seeded
    runner.allowed_commands = [*REQUIRED_COMMANDS, commands.CERTIFY.key]
    db_session.commit()
    result = install(
        db_session,
        workspace,
        user,
        runner_slug="gpu-vm",
        certify_profile={"expected": {"locales": 39}},
    )
    db_session.commit()
    monkeypatch.setattr(triggers, "_dispatch_live_run", lambda run_id: None)
    now = datetime.utcnow()
    db_session.add(
        RemoteRunnerJob(
            workspace_id=workspace.id,
            runner_id=runner.id,
            command="translation_suite.package",
            params={"lot": "LOT-7"},
            status="succeeded",
            exit_code=0,
            result={"verdict": "blocked"},
            inputs=[],
            artifacts=[],
            cancel_requested=False,
            created_at=now,
            deadline_at=now + timedelta(hours=1),
            finished_at=now,
            notify_system_id=result["systems"]["chain"],
        )
    )
    db_session.commit()
    assert runners.announce_finished(db_session) == 1
    run = db_session.query(Run).filter(Run.system_id == result["systems"]["chain"]).one()
    asyncio.run(execute_run_dag(run.id))
    db_session.expire_all()
    assert db_session.get(Run, run.id).status == "completed"
    queued = (
        db_session.query(RemoteRunnerJob)
        .filter(RemoteRunnerJob.command == "translation_suite.certify")
        .one()
    )
    assert queued.params == {"lot": "LOT-7"}
    assert [item.get("path") for item in queued.inputs] == ["inputs/certify_profile.json"]
