"""Real-process coverage of thread-safe launch, ceilings and descendant cleanup."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services.recipe_executions import _LIMITS_EXEC_PATH, supervise_harness


def _run(tmp_path, source, **kwargs):
    script = tmp_path / "user_code.py"
    script.write_text(source)
    return supervise_harness(
        [sys.executable, str(script)],
        venv_python=Path(sys.executable),
        scratch=tmp_path,
        timeout_s=kwargs.pop("timeout_s", 5),
        memory_limit_mb=kwargs.pop("memory_limit_mb", 256),
        cpu_limit_s=kwargs.pop("cpu_limit_s", 3),
        fsize_limit_mb=kwargs.pop("fsize_limit_mb", 1),
        **kwargs,
    )


def test_harness_starts_with_resource_limits_and_process_group(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERVISION_SECRET_PROBE", "must-not-reach-child")
    result = _run(
        tmp_path,
        """import json, os, resource
print(json.dumps({
    'cpu': resource.getrlimit(resource.RLIMIT_CPU),
    'memory': resource.getrlimit(resource.RLIMIT_AS),
    'file': resource.getrlimit(resource.RLIMIT_FSIZE),
    'own_group': os.getpid() == os.getpgrp() == os.getsid(0),
    'cwd': os.getcwd(),
    'secret': os.environ.get('SUPERVISION_SECRET_PROBE'),
}))
""",
    )
    assert result.exit_code == 0, result.stderr_tail
    values = json.loads(result.stdout_tail)
    assert values["cpu"] == [3, 8]
    assert values["memory"] == [256 * 1024**2] * 2
    assert values["file"] == [1024**2] * 2
    assert values["own_group"] is True
    assert values["cwd"] == str(tmp_path)
    assert values["secret"] is None


def test_memory_and_file_limits_are_enforced(tmp_path):
    result = _run(
        tmp_path,
        """import json
try:
    memory = bytearray(512 * 1024**2)
except MemoryError:
    memory_limited = True
else:
    memory_limited = False
try:
    with open('too-large.bin', 'wb') as output:
        output.write(b'x' * (2 * 1024**2))
except OSError:
    file_limited = True
else:
    file_limited = False
print(json.dumps([memory_limited, file_limited]))
""",
    )
    assert result.exit_code == 0, result.stderr_tail
    assert json.loads(result.stdout_tail) == [True, True]
    assert (tmp_path / "too-large.bin").stat().st_size <= 1024**2


def test_cpu_limit_is_enforced_before_wall_timeout(tmp_path):
    result = _run(tmp_path, "while True: pass\n", cpu_limit_s=1, timeout_s=8)
    assert result.status is None
    assert result.exit_code in {-signal.SIGXCPU, -signal.SIGKILL}


def test_invalid_limit_never_executes_user_code(tmp_path):
    result = _run(
        tmp_path,
        "from pathlib import Path\nPath('executed').touch()\n",
        memory_limit_mb=0,
    )
    assert result.exit_code == 126
    assert "process_limit_setup_or_exec_failed" in result.stderr_tail
    assert not (tmp_path / "executed").exists()


def test_bootstrap_keeps_stricter_inherited_limits(tmp_path):
    source = f"""import os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (128 * 1024**2, 128 * 1024**2))
resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
command = [sys.executable, '-I', '-S', {str(_LIMITS_EXEC_PATH)!r}, '256', '3', '1', '--',
           sys.executable, '-I', '-S', '-c',
           'import json, resource; print(json.dumps([resource.getrlimit(resource.RLIMIT_AS), resource.getrlimit(resource.RLIMIT_FSIZE)]))']
os.execv(sys.executable, command)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", source],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    assert json.loads(result.stdout) == [[128 * 1024**2] * 2, [65536] * 2]


def _alive(pid):
    try:
        status = Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return status != "Z"


@pytest.mark.skipif(sys.platform != "linux", reason="Checks descendant state through /proc")
@pytest.mark.parametrize("stop", ["timeout", "cancel"])
def test_stop_kills_harness_and_its_descendant(tmp_path, stop):
    pid_file = tmp_path / "descendant.pid"
    result = _run(
        tmp_path,
        """import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
Path('descendant.pid').write_text(str(child.pid))
time.sleep(30)
""",
        timeout_s=1 if stop == "timeout" else 8,
        should_cancel=(lambda: pid_file.exists()) if stop == "cancel" else None,
    )
    assert result.status == ("timed_out" if stop == "timeout" else "cancelled")
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _alive(pid)


@pytest.mark.skipif(sys.platform != "linux", reason="Uses /proc to clean a blocked fork")
def test_import_lock_in_another_thread_cannot_deadlock_launch(tmp_path):
    """Reproduce the old resource import deadlock in an externally bounded process."""
    backend = Path(__file__).resolve().parents[3]
    script = tmp_path / "threaded_parent.py"
    script.write_text(
        f"""import importlib._bootstrap as bootstrap
import sys, threading
from pathlib import Path
sys.path.insert(0, {str(backend)!r})
from app.services.recipe_executions import supervise_harness
sys.modules.pop('resource', None)
lock = bootstrap._get_module_lock('resource')
held = threading.Event()
def hold_import():
    lock.acquire()
    held.set()
    threading.Event().wait(30)
threading.Thread(target=hold_import, daemon=True).start()
assert held.wait(2)
result = supervise_harness(
    [sys.executable, '-I', '-S', '-c', "print('harness-reached')"],
    venv_python=Path(sys.executable), scratch=Path({str(tmp_path)!r}),
    timeout_s=2, memory_limit_mb=256, cpu_limit_s=3, fsize_limit_mb=1,
)
assert result.exit_code == 0, result.stderr_tail
assert result.stdout_tail.strip() == 'harness-reached'
print('launch-completed', flush=True)
"""
    )
    process = subprocess.Popen(
        [sys.executable, "-I", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        # The harness starts its own session before the old preexec callback;
        # killing only this test's parent group would leak that blocked child.
        children = Path(f"/proc/{process.pid}/task/{process.pid}/children")
        for child in children.read_text().split() if children.exists() else []:
            try:
                os.kill(int(child), signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=3)
        pytest.fail("launch blocked on an inherited import lock before supervision")
    assert process.returncode == 0, stderr
    assert "launch-completed" in stdout
