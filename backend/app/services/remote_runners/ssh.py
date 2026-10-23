"""SSH transport: pinned host keys, a key from the secret registry, optional bastion.

The connection trusts exactly the host key declared on the runner (and on its
bastion); there is no known_hosts file and no trust-on-first-use. Commands are
POSIX ``sh`` strings built from quoted argv, executed on Linux hosts.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import asyncssh

from app.services.remote_runners.transport import (
    CommandResult,
    JobProbe,
    Signal,
    TransportError,
    job_script,
    parse_status,
    status_command,
)


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    username: str
    host_key: str


def _known_hosts(host_key: str):
    try:
        key = asyncssh.import_public_key(host_key.strip())
    except (asyncssh.KeyImportError, ValueError):
        raise TransportError("REMOTE_RUNNER_HOST_KEY_INVALID") from None
    return ([key], [], [])


def _client_key(private_key: str):
    try:
        return asyncssh.import_private_key(private_key)
    except (asyncssh.KeyImportError, ValueError):
        raise TransportError("REMOTE_RUNNER_CLIENT_KEY_INVALID") from None


class SshTransport:
    def __init__(
        self,
        target: Endpoint,
        private_key: str,
        *,
        bastion: Endpoint | None = None,
        connect_timeout: float = 20,
    ):
        self.target = target
        self.bastion = bastion
        self._key = _client_key(private_key)
        self._timeout = connect_timeout
        self._conn: asyncssh.SSHClientConnection | None = None
        self._jump: asyncssh.SSHClientConnection | None = None

    async def _connection(self) -> asyncssh.SSHClientConnection:
        if self._conn is not None:
            return self._conn
        try:
            tunnel = ()
            if self.bastion is not None:
                self._jump = await asyncssh.connect(
                    self.bastion.host,
                    self.bastion.port,
                    username=self.bastion.username,
                    client_keys=[self._key],
                    known_hosts=_known_hosts(self.bastion.host_key),
                    connect_timeout=self._timeout,
                    agent_path=None,
                )
                tunnel = self._jump
            self._conn = await asyncssh.connect(
                self.target.host,
                self.target.port,
                tunnel=tunnel,
                username=self.target.username,
                client_keys=[self._key],
                known_hosts=_known_hosts(self.target.host_key),
                connect_timeout=self._timeout,
                agent_path=None,
            )
        except TransportError:
            raise
        except asyncssh.HostKeyNotVerifiable:
            await self.close()
            raise TransportError("REMOTE_RUNNER_HOST_KEY_MISMATCH") from None
        except asyncssh.PermissionDenied:
            await self.close()
            raise TransportError("REMOTE_RUNNER_AUTH_FAILED") from None
        except (OSError, asyncssh.Error, TimeoutError) as exc:
            await self.close()
            raise TransportError("REMOTE_RUNNER_UNREACHABLE", type(exc).__name__) from None
        return self._conn

    async def _sh(self, command: str, *, timeout: float, stdin: str | None = None):
        conn = await self._connection()
        try:
            result = await conn.run(command, input=stdin, check=False, timeout=timeout)
        except asyncssh.TimeoutError:
            raise TransportError("REMOTE_RUNNER_COMMAND_TIMEOUT") from None
        except (OSError, asyncssh.Error) as exc:
            raise TransportError("REMOTE_RUNNER_UNREACHABLE", type(exc).__name__) from None
        return CommandResult(
            int(result.exit_status if result.exit_status is not None else -1),
            str(result.stdout or ""),
            str(result.stderr or ""),
        )

    async def run(self, argv: list[str], *, timeout: float) -> CommandResult:
        return await self._sh(shlex.join(argv), timeout=timeout)

    async def start(self, path: str, argv: list[str]) -> int:
        quoted = shlex.quote(path)
        made = await self._sh(
            f"mkdir -p -- {quoted} && cd -- {quoted} && [ ! -e run.sh ] && cat > run.sh",
            timeout=30,
            stdin=job_script(argv),
        )
        if made.exit_status != 0:
            raise TransportError("REMOTE_RUNNER_START_FAILED", made.stderr[-500:])
        # A backgrounded child of a non-interactive shell is not a group leader,
        # so setsid makes it a session leader without forking: $! is the group.
        started = await self._sh(
            f"cd -- {quoted} || exit 1; setsid sh run.sh < /dev/null > /dev/null 2>&1 & echo $!",
            timeout=30,
        )
        try:
            return int(started.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            raise TransportError("REMOTE_RUNNER_START_FAILED", started.stderr[-500:]) from None

    async def status(self, path: str, pid: int) -> JobProbe:
        result = await self._sh(status_command(path, pid), timeout=30)
        return parse_status(result.stdout)

    async def signal(self, pid: int, sig: Signal) -> None:
        await self._sh(f"kill -{sig} -- -{int(pid)} 2>/dev/null; true", timeout=30)

    async def read_tail(self, path: str, max_bytes: int) -> str | None:
        quoted = shlex.quote(path)
        result = await self._sh(
            f"[ -f {quoted} ] && tail -c {int(max_bytes)} -- {quoted}", timeout=30
        )
        return result.stdout if result.exit_status == 0 else None

    async def fetch(self, path: str, destination: Path, max_bytes: int) -> int | None:
        conn = await self._connection()
        try:
            async with conn.start_sftp_client() as sftp:
                try:
                    attrs = await sftp.stat(path)
                except asyncssh.SFTPNoSuchFile:
                    return None
                if attrs.size is not None and attrs.size > max_bytes:
                    raise TransportError("REMOTE_RUNNER_ARTIFACT_TOO_LARGE", path)
                await sftp.get(path, str(destination))
        except TransportError:
            raise
        except (OSError, asyncssh.Error) as exc:
            raise TransportError("REMOTE_RUNNER_FETCH_FAILED", type(exc).__name__) from None
        size = destination.stat().st_size
        if size > max_bytes:
            destination.unlink(missing_ok=True)
            raise TransportError("REMOTE_RUNNER_ARTIFACT_TOO_LARGE", path)
        return size

    async def put(self, source: Path, path: str) -> None:
        parent = shlex.quote(str(PurePosixPath(path).parent))
        made = await self._sh(f"mkdir -p -- {parent}", timeout=30)
        if made.exit_status != 0:
            raise TransportError("REMOTE_RUNNER_PUT_FAILED", made.stderr[-500:])
        conn = await self._connection()
        try:
            async with conn.start_sftp_client() as sftp:
                await sftp.put(str(source), path)
        except (OSError, asyncssh.Error) as exc:
            raise TransportError("REMOTE_RUNNER_PUT_FAILED", type(exc).__name__) from None

    async def close(self) -> None:
        for conn in (self._conn, self._jump):
            if conn is not None:
                conn.close()
                try:
                    await conn.wait_closed()
                except Exception:  # noqa: BLE001 - closing is best effort
                    pass
        self._conn = self._jump = None
