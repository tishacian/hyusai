"""How a runner is reached: one interface, an SSH transport and a local one.

A detached job lives in its own directory ``<work_root>/jobs/<job_id>``. Its
``run.sh`` records the session id, runs the catalogued argv with its output
redirected to ``stdout.log`` / ``stderr.log``, then writes ``exit_code``
atomically. The job runs in its own session, so cancelling signals the whole
process group and no child survives its job.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

Signal = Literal["TERM", "KILL"]


class TransportError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        super().__init__(detail or code)


@dataclass(frozen=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class JobProbe:
    state: Literal["running", "exited", "gone"]
    exit_code: int | None = None


def job_script(argv: list[str]) -> str:
    return (
        "#!/bin/sh\n"
        "echo $$ > pid\n"
        f"{shlex.join(argv)} > stdout.log 2> stderr.log < /dev/null\n"
        "code=$?\n"
        'echo "$code" > exit_code.tmp && mv exit_code.tmp exit_code\n'
    )


def job_dir(work_root: str, job_id: str) -> str:
    root = PurePosixPath(work_root)
    if not root.is_absolute() or ".." in root.parts:
        raise TransportError("REMOTE_RUNNER_WORK_ROOT_INVALID", work_root)
    return str(root / "jobs" / job_id)


def relative_in(job_path: str, relative: str) -> str:
    parts = relative.split("/")
    if not relative or relative.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise TransportError("REMOTE_RUNNER_PATH_INVALID", relative)
    return str(PurePosixPath(job_path) / relative)


def parse_status(output: str) -> JobProbe:
    line = output.strip().splitlines()[-1] if output.strip() else ""
    if line.startswith("exit "):
        try:
            return JobProbe("exited", int(line.split()[1]))
        except (IndexError, ValueError):
            return JobProbe("exited", None)
    if line == "alive":
        return JobProbe("running")
    return JobProbe("gone")


class Transport(Protocol):
    async def run(self, argv: list[str], *, timeout: float) -> CommandResult: ...

    async def start(self, path: str, argv: list[str]) -> int: ...

    async def status(self, path: str, pid: int) -> JobProbe: ...

    async def signal(self, pid: int, sig: Signal) -> None: ...

    async def read_tail(self, path: str, max_bytes: int) -> str | None: ...

    async def fetch(self, path: str, destination: Path, max_bytes: int) -> int | None: ...

    async def put(self, source: Path, path: str) -> None: ...

    async def close(self) -> None: ...


def status_command(path: str, pid: int) -> str:
    quoted = shlex.quote(path)
    return (
        f"cd {quoted} 2>/dev/null || {{ echo gone; exit 0; }}; "
        'if [ -f exit_code ]; then echo "exit $(cat exit_code)"; '
        f"elif kill -0 -- -{int(pid)} 2>/dev/null; then echo alive; else echo gone; fi"
    )


_LOCAL_CHILDREN: dict[int, subprocess.Popen] = {}


class LocalTransport:
    """Runs on the worker itself. Tests and development only (setting-gated)."""

    def __init__(self, work_root: str):
        self.work_root = work_root

    async def run(self, argv: list[str], *, timeout: float) -> CommandResult:
        Path(self.work_root).mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.work_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            process.kill()
            raise TransportError("REMOTE_RUNNER_COMMAND_TIMEOUT") from None
        return CommandResult(
            process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")
        )

    async def start(self, path: str, argv: list[str]) -> int:
        directory = Path(path)
        directory.mkdir(parents=True, exist_ok=True)
        if (directory / "run.sh").exists():
            raise TransportError("REMOTE_RUNNER_START_FAILED", "job directory already started")
        (directory / "run.sh").write_text(job_script(argv))
        # Kept so status() can reap it: a zombie would still answer killpg(pid, 0).
        process = subprocess.Popen(
            ["sh", "run.sh"],
            cwd=str(directory),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _LOCAL_CHILDREN[process.pid] = process
        return process.pid

    async def status(self, path: str, pid: int) -> JobProbe:
        exit_file = Path(path) / "exit_code"
        if exit_file.exists():
            try:
                return JobProbe("exited", int(exit_file.read_text().strip()))
            except ValueError:
                return JobProbe("exited", None)
        child = _LOCAL_CHILDREN.get(pid)
        if child is not None and child.poll() is not None:
            _LOCAL_CHILDREN.pop(pid, None)
            return JobProbe("gone")
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return JobProbe("gone")
        except PermissionError:
            return JobProbe("running")
        return JobProbe("running")

    async def signal(self, pid: int, sig: Signal) -> None:
        try:
            os.killpg(pid, signal.SIGTERM if sig == "TERM" else signal.SIGKILL)
        except ProcessLookupError:
            pass

    async def read_tail(self, path: str, max_bytes: int) -> str | None:
        file = Path(path)
        if not file.is_file():
            return None
        size = file.stat().st_size
        with file.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode(errors="replace")

    async def fetch(self, path: str, destination: Path, max_bytes: int) -> int | None:
        file = Path(path)
        if not file.is_file():
            return None
        size = file.stat().st_size
        if size > max_bytes:
            raise TransportError("REMOTE_RUNNER_ARTIFACT_TOO_LARGE", path)
        destination.write_bytes(file.read_bytes())
        return size

    async def put(self, source: Path, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    async def close(self) -> None:
        return None
