"""External runners driven through the local transport: real detached processes."""

from __future__ import annotations

import time
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.models.remote_runner import RemoteRunnerJob
from app.models.workspace import Workspace
from app.services.remote_runners import catalog
from app.services.remote_runners import service as runners
from app.services.remote_runners.transport import job_script, parse_status, status_command


class _ResultParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word: str


WRITE_RESULT = catalog.register(
    catalog.CommandSpec(
        key="tests.write_result",
        title="Write a result and an artifact",
        risk="compute",
        mode="detached",
        params=_ResultParams,
        build=lambda p, _r: [
            "sh",
            "-c",
            'printf \'{"word": "%s"}\' "$1" > result.json && echo "$1" > out.txt && echo done',
            "sh",
            p.word,
        ],
        artifacts=("out.txt", "missing.txt"),
        timeout_s=60,
    )
)

FAIL = catalog.register(
    catalog.CommandSpec(
        key="tests.fail",
        title="Exit with an error",
        risk="compute",
        mode="detached",
        params=catalog._NoParams,
        build=lambda _p, _r: ["sh", "-c", "echo boom >&2; exit 3"],
        timeout_s=60,
    )
)


@pytest.fixture
def workspace(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "remote_runner_local_transport_enabled", True)
    monkeypatch.setattr(settings, "remote_runner_cancel_grace_s", 0)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    row = Workspace(id=str(uuid4()), name="runner fixture", slug=str(uuid4()), settings={})
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def runner(db_session, workspace, tmp_path):
    row = runners.create_runner(
        db_session,
        workspace_id=workspace.id,
        user_id="fixture",
        values={
            "slug": "local-box",
            "name": "Local box",
            "transport": "local",
            "host": "localhost",
            "username": "agentium",
            "host_key": "unused",
            "key_secret_ref": "secret://workspace/unused",
            "work_root": str(tmp_path / "runner"),
            "allowed_commands": ["agentium.sleep", "tests.write_result", "tests.fail"],
            "max_concurrent_jobs": 1,
        },
    )
    db_session.commit()
    return row


def submit(db, runner, command, params=None, **kwargs):
    job = runners.submit_job(
        db,
        workspace_id=runner.workspace_id,
        runner_id=runner.id,
        command=command,
        params=params,
        user_id="fixture",
        **kwargs,
    )
    db.commit()
    return job


def settle(db, job, *, until, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runners.tick(db)
        db.refresh(job)
        if job.status in until:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job stayed {job.status}")


def test_job_succeeds_with_result_and_artifacts(db_session, runner):
    job = submit(db_session, runner, "tests.write_result", {"word": "bonjour"})
    assert job.status == "queued"
    settle(db_session, job, until={"succeeded", "failed"})
    assert job.status == "succeeded", job.error_detail
    assert job.exit_code == 0
    assert job.result == {"word": "bonjour"}
    present = {item["path"]: item for item in job.artifacts}
    assert present["missing.txt"] == {"path": "missing.txt", "present": False}
    assert present["out.txt"]["present"] is True
    from app.services.object_store import get_object_store

    assert get_object_store().read_bytes(present["out.txt"]["key"]) == b"bonjour\n"
    assert "done" in job.log_tail


def test_nonzero_exit_fails_with_stderr(db_session, runner):
    job = settle(
        db_session, submit(db_session, runner, "tests.fail"), until={"failed", "succeeded"}
    )
    assert (job.status, job.exit_code, job.error_code) == ("failed", 3, "REMOTE_JOB_EXIT_NONZERO")
    assert "boom" in job.error_detail


def test_cancel_kills_the_process_group(db_session, runner):
    job = submit(db_session, runner, "agentium.sleep", {"seconds": 60})
    settle(db_session, job, until={"running"})
    pid = job.pid
    runners.cancel_job(db_session, job, user_id="fixture")
    db_session.commit()
    settle(db_session, job, until={"cancelled", "lost", "failed"})
    assert (job.status, job.error_code) == ("cancelled", "REMOTE_JOB_CANCELLED")
    import os

    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


def test_deadline_signals_and_times_out(db_session, runner):
    job = submit(db_session, runner, "agentium.sleep", {"seconds": 60})
    settle(db_session, job, until={"running"})
    job.deadline_at = job.created_at - timedelta(seconds=1)
    db_session.commit()
    settle(db_session, job, until={"timed_out", "cancelled", "lost"})
    assert (job.status, job.error_code) == ("timed_out", "REMOTE_JOB_TIMEOUT")


def test_concurrency_keeps_second_job_queued(db_session, runner):
    first = submit(db_session, runner, "agentium.sleep", {"seconds": 60})
    second = submit(db_session, runner, "agentium.sleep", {"seconds": 0})
    runners.tick(db_session)
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.status, second.status) == ("running", "queued")
    runners.cancel_job(db_session, first)
    db_session.commit()
    settle(db_session, first, until={"cancelled"})
    settle(db_session, second, until={"succeeded"})


def test_queued_cancel_needs_no_machine(db_session, runner):
    job = submit(db_session, runner, "agentium.sleep", {"seconds": 1})
    runners.cancel_job(db_session, job)
    db_session.commit()
    assert (job.status, job.launched_at) == ("cancelled", None)


def test_only_listed_commands_and_valid_params(db_session, runner):
    with pytest.raises(runners.RunnerError) as denied:
        submit(db_session, runner, "agentium.probe")
    assert denied.value.code == "REMOTE_COMMAND_NOT_ALLOWED"
    with pytest.raises(runners.RunnerError) as invalid:
        submit(db_session, runner, "agentium.sleep", {"seconds": "rm -rf /"})
    assert invalid.value.code == "REMOTE_COMMAND_PARAMS_INVALID"
    with pytest.raises(runners.RunnerError) as extra:
        submit(db_session, runner, "agentium.sleep", {"seconds": 1, "shell": "true"})
    assert extra.value.code == "REMOTE_COMMAND_PARAMS_INVALID"
    assert db_session.query(RemoteRunnerJob).count() == 0


def test_runner_validation(db_session, workspace, monkeypatch):
    base = {
        "slug": "box",
        "name": "Box",
        "host": "10.0.0.1",
        "username": "u",
        "host_key": "ssh-ed25519 AAAA",
        "key_secret_ref": "secret://workspace/box-key",
        "work_root": "/srv/agentium",
    }
    for change, code in [
        ({"work_root": "relative/path"}, "REMOTE_RUNNER_WORK_ROOT_INVALID"),
        ({"work_root": "/"}, "REMOTE_RUNNER_WORK_ROOT_INVALID"),
        ({"key_secret_ref": "plain-key"}, "REMOTE_RUNNER_SECRET_REF_INVALID"),
        ({"allowed_commands": ["nope.command"]}, "REMOTE_COMMAND_UNKNOWN"),
        ({"slug": "Bad Slug"}, "REMOTE_RUNNER_SLUG_INVALID"),
        ({"password": "x"}, "REMOTE_RUNNER_FIELD_UNKNOWN"),
    ]:
        with pytest.raises(runners.RunnerError) as exc:
            runners.create_runner(
                db_session, workspace_id=workspace.id, user_id=None, values={**base, **change}
            )
        assert exc.value.code == code
    monkeypatch.setattr(settings, "remote_runner_local_transport_enabled", False)
    with pytest.raises(runners.RunnerError) as local:
        runners.create_runner(
            db_session,
            workspace_id=workspace.id,
            user_id=None,
            values={**base, "transport": "local"},
        )
    assert local.value.code == "REMOTE_RUNNER_LOCAL_DISABLED"


def test_script_and_status_parsing_quote_every_argument():
    script = job_script(["echo", "a b; rm -rf /", "$(id)"])
    assert "echo 'a b; rm -rf /' '$(id)' > stdout.log" in script
    assert parse_status("alive\n").state == "running"
    assert parse_status("exit 0").exit_code == 0
    assert parse_status("").state == "gone"
    assert "kill -0 -- -42" in status_command("/srv/x y", 42)
    assert "'/srv/x y'" in status_command("/srv/x y", 42)


def test_probe_parsing():
    parsed = catalog.parse_probe(
        "Linux 6.8.0 x86_64\n64\n0, NVIDIA GeForce RTX 5090, 1024, 32607, 7\nbad line\n"
    )
    assert parsed["cpus"] == 64
    assert parsed["gpus"] == [
        {
            "index": 0,
            "name": "NVIDIA GeForce RTX 5090",
            "memory_used_mb": 1024,
            "memory_total_mb": 32607,
            "utilization_pct": 7,
        }
    ]


def test_finished_job_is_announced_once(db_session, runner, monkeypatch):
    from app.services.run_engine import triggers

    seen = []
    monkeypatch.setattr(
        triggers,
        "emit_event",
        lambda kind, ws, payload, **_: seen.append((kind, ws, payload)) or [],
    )
    job = submit(db_session, runner, "tests.write_result", {"word": "x"}, correlation_key="lot-42")
    settle(db_session, job, until={"succeeded"})
    runners.announce_finished(db_session)
    assert runners.announce_finished(db_session) == 0
    kinds = [
        (kind, ws, payload["job_id"], payload["correlation_key"]) for kind, ws, payload in seen
    ]
    assert kinds == [("remote_runner.job_finished", runner.workspace_id, job.id, "lot-42")]
    assert seen[0][2]["result"] == {"word": "x"}
    assert (
        triggers.TRIGGER_TYPE_TO_EVENT["source.remote_job_finished"] == "remote_runner.job_finished"
    )


def test_skill_submits_in_the_run_workspace(db_session, runner, workspace):
    import asyncio

    from app.services.skills_registry.wrappers.skills import _remote_job_submit_v1

    out = asyncio.run(
        _remote_job_submit_v1(
            {
                "runner": "local-box",
                "command": "agentium.sleep",
                "params": {"seconds": 0},
                "workspace_id": "someone-else",
            },
            {"workspace_id": workspace.id, "run_id": "run-1", "node_id": "n1"},
        )
    )
    job = db_session.get(RemoteRunnerJob, out["job_id"])
    assert (job.workspace_id, job.run_id, job.node_id, job.correlation_key) == (
        workspace.id,
        "run-1",
        "n1",
        "run-1",
    )
    with pytest.raises(ValueError, match="REMOTE_RUNNER_NOT_FOUND"):
        asyncio.run(
            _remote_job_submit_v1(
                {"runner": "local-box", "command": "agentium.sleep"}, {"workspace_id": str(uuid4())}
            )
        )
    with pytest.raises(ValueError, match="remote_job_workspace_required"):
        asyncio.run(_remote_job_submit_v1({"runner": "local-box", "command": "agentium.sleep"}, {}))


READ_INPUT = catalog.register(
    catalog.CommandSpec(
        key="tests.read_input",
        title="Count the bytes of the staged input",
        risk="compute",
        mode="detached",
        params=catalog._NoParams,
        build=lambda _p, _r: [
            "sh",
            "-c",
            'printf \'{"bytes": %s}\' "$(wc -c < inputs/pack.zip)" > result.json',
        ],
        timeout_s=60,
    )
)


def test_deposit_inputs_are_snapshotted_and_uploaded(
    db_session, runner, workspace, tmp_path, monkeypatch
):
    import hashlib

    from app.models.secure_deposit import DepositAccessLink, DepositFile
    from app.models.user import User

    root = tmp_path / "secure-deposit"
    monkeypatch.setattr(settings, "secure_deposit_storage_dir", str(root))
    runner.allowed_commands = [*runner.allowed_commands, "tests.read_input"]
    content = b"PK fake 4D pack"
    key = f"workspaces/{workspace.id}/secure-deposit/lot/pack.zip"
    (root / key).parent.mkdir(parents=True)
    (root / key).write_bytes(content)
    user = User(
        id=str(uuid4()), username=f"u-{uuid4().hex[:6]}", email=f"{uuid4().hex[:6]}@example.test"
    )
    link = DepositAccessLink(
        id=str(uuid4()),
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        label="4D",
        access_id=uuid4().hex,
        password_hash="h",
        allowed_extensions=[],
    )
    deposit = DepositFile(
        id=str(uuid4()),
        workspace_id=workspace.id,
        access_link_id=link.id,
        filename="lot/pack.zip",
        object_key=key,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        status="received",
    )
    db_session.add_all([user, link, deposit])
    db_session.commit()
    job = submit(db_session, runner, "tests.read_input", input_file_ids=[deposit.id])
    assert [item["path"] for item in job.inputs] == ["inputs/pack.zip"]
    (root / key).write_bytes(b"changed after submission")
    settle(db_session, job, until={"succeeded", "failed"})
    assert job.status == "succeeded", job.error_detail
    assert job.result == {"bytes": len(content)}
    other = Workspace(id=str(uuid4()), name="other", slug=str(uuid4()), settings={})
    db_session.add(other)
    db_session.commit()
    with pytest.raises(runners.RunnerError) as foreign:
        runners.submit_job(
            db_session,
            workspace_id=other.id,
            runner_id=runner.id,
            command="tests.read_input",
            input_file_ids=[deposit.id],
        )
    assert foreign.value.code == "REMOTE_RUNNER_NOT_FOUND"


def test_translation_commands_need_their_runner_paths(db_session, runner):
    from app.services.remote_runners import catalog as cat

    spec, _model, argv = cat.validate(
        "translation_suite.prepare",
        {"lot": "L-7", "targets": ["de-DE", "it-IT"]},
        {
            "translation.repo": "/srv/mt",
            "translation.python": "/srv/venv/bin/python",
            "translation.base_dir": "/srv/agentium-lots",
        },
    )
    assert argv[:6] == [
        "env",
        "PYTHONPATH=/srv/mt",
        "/srv/venv/bin/python",
        "-m",
        "ts.runner",
        "prepare",
    ]
    assert argv[-4:] == ["--target", "de-DE", "--target", "it-IT"]
    assert "--archive" not in argv
    with pytest.raises(cat.CatalogError) as missing:
        cat.validate(
            "translation_suite.translate", {"lot": "L-7"}, {"translation.repo": "relative"}
        )
    assert missing.value.code == "REMOTE_RUNNER_PATH_LABEL_MISSING"
    with pytest.raises(cat.CatalogError):
        cat.validate("translation_suite.prepare", {"lot": "../etc"}, {})
    runner.allowed_commands = [*runner.allowed_commands, "translation_suite.translate"]
    db_session.commit()
    with pytest.raises(runners.RunnerError) as refused:
        submit(db_session, runner, "translation_suite.translate", {"lot": "L-7"})
    assert refused.value.code == "REMOTE_RUNNER_PATH_LABEL_MISSING"


def test_documents_are_staged_as_inputs(db_session, runner):
    runner.allowed_commands = [*runner.allowed_commands, "tests.read_doc"]
    db_session.commit()
    job = submit(
        db_session,
        runner,
        "tests.read_doc",
        input_documents={"decisions.jsonl": [{"item_ref": "a"}, {"item_ref": "b"}]},
    )
    settle(db_session, job, until={"succeeded", "failed"})
    assert job.status == "succeeded", job.error_detail
    assert job.result == {"lines": 2}
    with pytest.raises(runners.RunnerError):
        submit(db_session, runner, "tests.read_doc", input_documents={"../x.json": {}})


READ_DOC = catalog.register(
    catalog.CommandSpec(
        key="tests.read_doc",
        title="Count the lines of a staged document",
        risk="compute",
        mode="detached",
        params=catalog._NoParams,
        build=lambda _p, _r: [
            "sh",
            "-c",
            'printf \'{"lines": %s}\' "$(wc -l < inputs/decisions.jsonl)" > result.json',
        ],
        timeout_s=60,
    )
)
