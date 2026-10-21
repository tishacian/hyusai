"""Real Celery worker/beat processes, local transport, and disposable PostgreSQL.

Opt in with RUN_MISSION_CELERY_INTEGRATION=1 and the PostgreSQL pytest database
guard. The model response adapter is deterministic; the production TaskEngine,
Celery tasks, dispatch, lease recovery, and checkpoints run unchanged. This is
not a RabbitMQ redelivery or real model-provider acceptance test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from uuid import uuid4

import pytest

from app.db.base import SessionLocal
from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.services.tasks.execution import resume_execution
from app.tests.integration.test_mission_execution_postgresql import _queued
from app.tests.integration.test_mission_execution_postgresql import mission as mission

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgresql,
    pytest.mark.skipif(
        os.getenv("RUN_MISSION_CELERY_INTEGRATION") != "1",
        reason="requires explicit isolated Celery process gate",
    ),
]


def _wait_until(predicate, message, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    pytest.fail(message)


def test_worker_kill_preserves_checkpoint_and_recovery_dispatches_resumed_attempt(
    db_session, mission, tmp_path
):
    from app.workers.celery_app import celery_app
    from app.workers.mission_tasks import recover_missions, run_mission

    execution_id = _queued(db_session, mission)
    for name in ("messages", "processed", "control"):
        (tmp_path / name).mkdir()
    queue = f"mission_recette_{uuid4().hex}"
    broker_options = {
        "data_folder_in": str(tmp_path / "messages"),
        "data_folder_out": str(tmp_path / "messages"),
        "store_processed": True,
        "processed_folder": str(tmp_path / "processed"),
        "control_folder": str(tmp_path / "control"),
        "polling_interval": 0.1,
    }
    original_conf = {
        name: celery_app.conf.get(name)
        for name in (
            "broker_url",
            "broker_transport_options",
            "result_backend",
            "task_default_queue",
            "task_ignore_result",
        )
    }
    celery_app.conf.update(
        broker_url="filesystem://",
        broker_transport_options=broker_options,
        result_backend="cache+memory://",
        task_default_queue=queue,
        task_ignore_result=True,
    )
    worker_file = tmp_path / "mission_worker.py"
    worker_file.write_text(
        textwrap.dedent(
            """\
            import asyncio
            import json
            import os
            from pathlib import Path

            import app.models
            from app.services.tasks import engine, execution
            from app.workers.celery_app import celery_app
            import app.workers.mission_tasks

            # Shorten only the time budget; use the actual lease implementation.
            execution.LEASE_SECONDS = 2
            class DeterministicModel:
                async def complete(self, *, prompt, **kwargs):
                    mode = os.environ['MISSION_TEST_MODE']
                    if prompt.startswith('You are a task planner'):
                        kind = 'plan'
                    elif 'Step: Evidence\\n' in prompt:
                        kind = 'evidence'
                    else:
                        kind = 'report'
                    with Path(os.environ['MISSION_TEST_CALLS']).open('a') as calls:
                        calls.write(f'{mode}:{kind}\\n')
                    if kind == 'plan':
                        return json.dumps([
                            {'title': 'Evidence', 'description': 'Read evidence', 'type': 'analysis'},
                            {'title': 'Report', 'description': 'Use evidence', 'type': 'synthesis'},
                        ])
                    if kind == 'evidence':
                        return 'retained evidence'
                    if mode == 'pause':
                        await asyncio.Event().wait()
                    assert 'retained evidence' in prompt
                    return 'report from retained evidence'

            instance = engine.TaskEngine()
            instance._llm = DeterministicModel()
            engine._engine = instance
            celery_app.conf.update(
                broker_url='filesystem://',
                broker_transport_options=json.loads(os.environ['MISSION_TEST_BROKER_OPTIONS']),
                result_backend='cache+memory://',
                task_default_queue=os.environ['MISSION_TEST_QUEUE'],
                task_ignore_result=True,
                include=['app.workers.mission_tasks'],
                imports=(),
                broker_connection_retry_on_startup=False,
                worker_enable_remote_control=False,
            )
            if os.environ['MISSION_TEST_MODE'] == 'beat':
                recovery = celery_app.conf.beat_schedule['mission-recovery-30s']
                assert recovery['task'] == 'agentium.recover_missions'
                assert recovery['schedule'] == 30.0
                # Retain the actual production entry and cadence, but never run
                # any of the other production schedules in this isolated gate.
                celery_app.conf.beat_schedule = {'mission-recovery-30s': recovery}
                celery_app.conf.result_expires = None
                celery_app.start([
                    'beat', '--loglevel=INFO', '--max-interval=1',
                    '--schedule=' + os.environ['MISSION_TEST_BEAT_STATE'],
                    '--pidfile=' + os.environ['MISSION_TEST_BEAT_PID'],
                ])
            else:
                celery_app.worker_main([
                    'worker', '--pool=solo', '--concurrency=1', '--without-gossip',
                    '--without-mingle', '--without-heartbeat', '--loglevel=INFO',
                    '--hostname=' + os.environ['MISSION_TEST_QUEUE'],
                ])
            """
        )
    )
    calls_file = tmp_path / "model-calls.txt"
    workers = []
    log_handles = []

    def start_worker(mode):
        env = {
            **os.environ,
            "CELERY_BROKER_URL": "filesystem://",
            "CELERY_RESULT_BACKEND": "cache+memory://",
            "CELERY_TASK_DEFAULT_QUEUE": queue,
            "MISSION_TEST_MODE": mode,
            "MISSION_TEST_CALLS": str(calls_file),
            "MISSION_TEST_QUEUE": queue,
            "MISSION_TEST_BROKER_OPTIONS": json.dumps(broker_options),
            "MISSION_TEST_BEAT_STATE": str(tmp_path / "beat-schedule"),
            "MISSION_TEST_BEAT_PID": str(tmp_path / "beat.pid"),
        }
        log = (tmp_path / f"worker-{mode}.log").open("w")
        log_handles.append(log)
        process = subprocess.Popen(
            [sys.executable, str(worker_file)],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        workers.append(process)
        return process

    def snapshot():
        with SessionLocal() as db:
            row = db.get(TaskExecution, execution_id)
            return row.status, row.steps, row.fence, row.lease_until, row.artifacts

    try:
        first = start_worker("pause")
        # No direct dispatch: the real beat entry must eventually publish the
        # recovery task, which must then publish this queued database row.
        beat_started = time.monotonic()
        beat = start_worker("beat")
        _wait_until(
            lambda: calls_file.exists() and "pause:report" in calls_file.read_text(),
            f"worker did not reach the second model call; see {tmp_path}",
            timeout=45,
        )
        assert time.monotonic() - beat_started >= 29
        beat.terminate()
        beat.wait(timeout=10)
        assert "Sending due task mission-recovery-30s" in (tmp_path / "worker-beat.log").read_text()
        status, steps, old_fence, lease_until, _ = snapshot()
        assert status == "running"
        assert steps[0]["status"] == "completed" and steps[0]["result"] == "retained evidence"
        assert first.poll() is None
        first.kill()
        first.wait(timeout=10)
        assert first.returncode < 0

        _wait_until(
            lambda: datetime.utcnow() > lease_until, "worker lease did not expire", timeout=5
        )
        start_worker("finish")
        recover_missions.apply_async(retry=False, queue=queue)
        _wait_until(
            lambda: snapshot()[0] == "interrupted", "recovery did not interrupt lost worker"
        )
        status, preserved, recovered_fence, _, artifacts = snapshot()
        assert preserved[0] == steps[0] and artifacts == {}
        assert recovered_fence > old_fence

        with SessionLocal() as db:
            resume_execution(db, db.get(Task, mission[0]), execution_id)
            db.commit()
        # Again omit the fast dispatch. Two recovery tasks redispatch the outbox;
        # a duplicate actual Celery delivery must not repeat a completed step.
        recover_missions.apply_async(retry=False, queue=queue)
        recover_missions.apply_async(retry=False, queue=queue)
        _wait_until(lambda: snapshot()[0] == "completed", "resumed attempt did not complete")
        run_mission.apply_async(args=[execution_id], retry=False, queue=queue)
        finish_log = tmp_path / "worker-finish.log"
        _wait_until(
            lambda: "already_claimed" in finish_log.read_text(),
            "duplicate Celery delivery was not observed",
        )
        status, finished, final_fence, _, artifacts = snapshot()
        assert status == "completed" and final_fence > recovered_fence
        assert finished[0] == steps[0]
        assert artifacts["report"] == "report from retained evidence"
        assert artifacts["completed_steps"] == 2
        calls = calls_file.read_text().splitlines()
        assert calls == ["pause:plan", "pause:evidence", "pause:report", "finish:report"]
        print(f"Celery worker logs and model-call evidence: {tmp_path}")
    finally:
        for process in workers:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for handle in log_handles:
            handle.close()
        celery_app.conf.update(**original_conf)
