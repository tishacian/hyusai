"""The SSH transport end to end against an in-process asyncssh server.

The server executes each command with the local ``sh`` and serves SFTP from the
local file system, so the quoting, the detached launch, the status probe, the
group signal and the artifact fetch all run for real. Where the host has no
``setsid`` (macOS), a shim performs the same system call.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import sys
import threading
import time
from uuid import uuid4

import asyncssh
import pytest

from app.core.config import settings
from app.models.workspace import Workspace
from app.services.remote_runners import service as runners
from app.services.remote_runners.ssh import Endpoint, SshTransport
from app.services.remote_runners.transport import TransportError


class _Server:
    def __init__(self, tmp_path):
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.client_key = asyncssh.generate_private_key("ssh-ed25519")
        self.env = dict(os.environ)
        if shutil.which("setsid") is None:
            shim = tmp_path / "bin"
            shim.mkdir()
            (shim / "setsid").write_text(
                f"#!{sys.executable}\nimport os, sys\nos.setsid()\nos.execvp(sys.argv[1], sys.argv[1:])\n"
            )
            (shim / "setsid").chmod(0o755)
            self.env["PATH"] = f"{shim}:{self.env['PATH']}"
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        assert self.ready.wait(10)

    async def _handle(self, process):
        local = await asyncio.create_subprocess_shell(
            process.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )
        await process.redirect(stdin=local.stdin, stdout=local.stdout, stderr=local.stderr)
        process.exit(await local.wait())

    def _serve(self):
        asyncio.set_event_loop(self.loop)

        async def start():
            self.server = await asyncssh.listen(
                "127.0.0.1",
                0,
                server_host_keys=[self.host_key],
                authorized_client_keys=asyncssh.import_authorized_keys(
                    self.client_key.export_public_key().decode()
                ),
                process_factory=self._handle,
                sftp_factory=True,
                encoding=None,
            )
            self.port = self.server.sockets[0].getsockname()[1]
            self.ready.set()

        self.loop.run_until_complete(start())
        self.loop.run_forever()

    def public_host_key(self) -> str:
        return self.host_key.export_public_key().decode().strip()

    def private_client_key(self) -> str:
        return self.client_key.export_private_key().decode()

    def stop(self):
        self.loop.call_soon_threadsafe(self.server.close)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture
def server(tmp_path):
    srv = _Server(tmp_path)
    yield srv
    srv.stop()


def _endpoint(server, host_key=None):
    return Endpoint(
        "127.0.0.1",
        server.port,
        os.environ.get("USER", "agentium"),
        host_key or server.public_host_key(),
    )


def test_transport_detached_job_lifecycle(server, tmp_path):
    async def scenario():
        transport = SshTransport(_endpoint(server), server.private_client_key())
        try:
            ran = await transport.run(["echo", "a b", "$(id)"], timeout=10)
            assert (ran.exit_status, ran.stdout) == (0, "a b $(id)\n")
            path = str(tmp_path / "work" / "jobs" / "j1")
            pid = await transport.start(path, ["sh", "-c", "echo out > artifact.txt; sleep 30"])
            for _ in range(50):
                if (await transport.status(path, pid)).state == "running":
                    break
                await asyncio.sleep(0.1)
            assert (await transport.status(path, pid)).state == "running"
            await transport.signal(pid, "TERM")
            for _ in range(50):
                if (await transport.status(path, pid)).state == "gone":
                    break
                await asyncio.sleep(0.1)
            assert (await transport.status(path, pid)).state == "gone"
            target = tmp_path / "fetched.txt"
            assert await transport.fetch(f"{path}/artifact.txt", target, 1024) == 4
            assert target.read_text() == "out\n"
            assert await transport.fetch(f"{path}/absent.txt", target, 1024) is None
            with pytest.raises(TransportError) as big:
                await transport.fetch(f"{path}/run.sh", tmp_path / "x", 3)
            assert big.value.code == "REMOTE_RUNNER_ARTIFACT_TOO_LARGE"
            done = str(tmp_path / "work" / "jobs" / "j2")
            pid = await transport.start(done, ["sh", "-c", "exit 4"])
            for _ in range(50):
                probe = await transport.status(done, pid)
                if probe.state == "exited":
                    break
                await asyncio.sleep(0.1)
            assert (probe.state, probe.exit_code) == ("exited", 4)
            with pytest.raises(TransportError) as again:
                await transport.start(done, ["true"])
            assert again.value.code == "REMOTE_RUNNER_START_FAILED"
        finally:
            await transport.close()

    asyncio.run(scenario())


def test_wrong_host_key_is_refused(server):
    other = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()

    async def scenario():
        transport = SshTransport(_endpoint(server, other), server.private_client_key())
        try:
            await transport.run(["true"], timeout=5)
        finally:
            await transport.close()

    with pytest.raises(TransportError) as refused:
        asyncio.run(scenario())
    assert refused.value.code == "REMOTE_RUNNER_HOST_KEY_MISMATCH"


def test_service_drives_an_ssh_runner_with_a_registry_key(
    db_session, server, tmp_path, monkeypatch
):
    from app.services.secrets import registry

    monkeypatch.setattr(settings, "remote_runner_connect_timeout_s", 5)
    monkeypatch.setenv("SECRET_REGISTRY_FERNET_KEY", base64.urlsafe_b64encode(b"r" * 32).decode())
    workspace = Workspace(id=str(uuid4()), name="ssh runner", slug=str(uuid4()), settings={})
    db_session.add(workspace)
    db_session.commit()
    registry.create(
        db_session,
        scope="workspace",
        name="runner-key",
        value=server.private_client_key(),
        actor="fixture",
        workspace_id=workspace.id,
    )
    runner = runners.create_runner(
        db_session,
        workspace_id=workspace.id,
        user_id="fixture",
        values={
            "slug": "ssh-box",
            "name": "SSH box",
            "host": "127.0.0.1",
            "port": server.port,
            "username": os.environ.get("USER", "agentium"),
            "host_key": server.public_host_key(),
            "key_secret_ref": "secret://workspace/runner-key",
            "work_root": str(tmp_path / "ssh-runner"),
            "allowed_commands": ["agentium.sleep"],
        },
    )
    db_session.commit()
    probe = runners.probe_runner(db_session, runner)
    assert probe["reachable"] is True and probe["cpus"] > 0
    job = runners.submit_job(
        db_session,
        workspace_id=workspace.id,
        runner_id=runner.id,
        command="agentium.sleep",
        params={"seconds": 0},
    )
    db_session.commit()
    deadline = time.monotonic() + 45
    while job.status != "succeeded" and time.monotonic() < deadline:
        runners.tick(db_session)
        db_session.refresh(job)
        time.sleep(0.2)
    assert job.status == "succeeded", (job.status, job.error_code, job.error_detail)
    assert job.exit_code == 0
