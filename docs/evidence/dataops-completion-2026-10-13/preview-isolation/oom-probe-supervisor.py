import json
import os
import subprocess
import time
from pathlib import Path

name = 'agentium-text-expansion-probe-' + str(os.getpid())
base = 'python:3.12-slim@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe'
repo = '/workspace/hyusai'
runtime = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python'
python = repo + '/.venv/bin/python'
report = Path('/tmp/dataops-text-expansion-actual.json')
log = Path('/tmp/dataops-text-expansion-actual.log')
if report.exists() or log.exists():
    raise SystemExit('Preserve previous probe results before running again')
env = dict(os.environ)
for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
    env.pop(key, None)
docker = ['docker', '--host=unix:///var/run/docker.sock']

def command(*args, **kwargs):
    return subprocess.run(docker + list(args), env=env, **kwargs)

def metrics():
    code = "import json,pathlib; p=pathlib.Path('/sys/fs/cgroup'); print(json.dumps({f:(p/f).read_text().strip() for f in ['memory.max','memory.peak','memory.events','memory.swap.max','cpu.max','cpu.stat']}))"
    result = command('exec', name, python, '-I', '-c', code, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(f'metrics failed: exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}')
    return json.loads(result.stdout)

result = {'name': name, 'image': base, 'memory_bytes': 192 * 1024**2, 'cpus': 0.5, 'network': 'none', 'mounts': 'repo/runtime/probe read-only', 'timeout_s': 30, 'duckdb_memory_limit': '16MB', 'threads': 1, 'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()}
created = False
started = time.monotonic()
try:
    command('run', '-d', '--name', name, '--pull=never', '--user', f'{os.getuid()}:{os.getgid()}', '--memory=192m', '--memory-swap=192m', '--cpus=0.5', '--pids-limit=32', '--network=none', '--read-only', '--shm-size=8m', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=8m', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--mount', f'type=bind,src={repo},dst={repo},readonly', '--mount', f'type=bind,src={runtime},dst={runtime},readonly', '--mount', 'type=bind,src=/tmp/dataops-text-expansion-actual-child.py,dst=/probe.py,readonly', '-e', 'OPENBLAS_NUM_THREADS=1', '-e', 'OMP_NUM_THREADS=1', '-e', 'PYTHONDONTWRITEBYTECODE=1', base, 'sleep', 'infinity', check=True, stdout=subprocess.DEVNULL, timeout=10)
    created = True
    result['before'] = metrics()
    assert result['before']['memory.max'] == str(192 * 1024**2)
    assert result['before']['memory.swap.max'] == '0'
    assert result['before']['cpu.max'] == '50000 100000'
    with log.open('w') as handle:
        try:
            proc = command('exec', name, python, '-I', '/probe.py', stdout=handle, stderr=subprocess.STDOUT, timeout=30)
            result['exit_code'] = proc.returncode
            result['status'] = 'returned'
        except subprocess.TimeoutExpired:
            result['status'] = 'host_timeout'
    result['after'] = metrics()
except BaseException as exc:
    result.update(status='error', error_type=type(exc).__name__, error=str(exc))
finally:
    if created:
        state = command('inspect', '--format', '{{json .State}}', name, capture_output=True, text=True, timeout=10)
        result['state'] = json.loads(state.stdout) if state.returncode == 0 else None
        removed = command('rm', '-f', name, capture_output=True, text=True, timeout=10)
        result['container_removed'] = removed.returncode == 0
    result['elapsed_seconds'] = time.monotonic() - started
    report.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
if log.exists():
    print(log.read_text())
