"""Run the unchanged 3M test under a local, isolated Docker cgroup."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/workspace/agentium')
OUT = Path('/workspace/dataops-completion-2026-10-13')
EXPECTED_REVISION = '64a10ba9e9329b5d8d203ecc786254bbdcee7e19'
NAME = 'agentium-dataops-benchmark-3m'
BASE = 'python:3.12-slim@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe'
RUNTIME = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python'
REPORT = OUT / 'scoring-3m.json'
CGROUP_REPORT = OUT / 'scoring-3m-cgroup.json'
BENCH_TMP = OUT / 'scoring-3m-tmp'
BENCH_HOME = OUT / 'scoring-3m-home'
RESERVE = 4 * 1024**3
ENV = dict(os.environ)
for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
    ENV.pop(key, None)
DOCKER = ['docker', '--host=unix:///var/run/docker.sock']


def command(*args, **kwargs):
    return subprocess.run(DOCKER + list(args), env=ENV, **kwargs)


def output(*args):
    return subprocess.check_output(DOCKER + list(args), env=ENV, text=True)


def persist(result):
    staging = CGROUP_REPORT.with_suffix('.json.tmp')
    staging.write_text(json.dumps(result, indent=2) + '\n')
    staging.replace(CGROUP_REPORT)


def metrics():
    code = (
        "import json,pathlib; p=pathlib.Path('/sys/fs/cgroup'); "
        "print(json.dumps({f:(p/f).read_text().strip() for f in "
        "['memory.max','memory.peak','memory.events','memory.swap.max','cpu.max','cpu.stat']}))"
    )
    return json.loads(output('exec', NAME, str(ROOT / '.venv/bin/python'), '-c', code))


def main():
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if revision != EXPECTED_REVISION:
        raise SystemExit('Refusing benchmark: source revision differs from the frozen qualification revision')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise SystemExit('Refusing benchmark: source working tree is not clean')
    if REPORT.exists() or CGROUP_REPORT.exists():
        raise SystemExit('Preserve previous scoring reports before running a new qualification')
    if shutil.disk_usage(OUT).free < RESERVE:
        raise SystemExit('Insufficient local disk reserve for benchmark')
    BENCH_TMP.mkdir(mode=0o700, exist_ok=True)
    BENCH_HOME.mkdir(mode=0o700, exist_ok=True)
    started = time.monotonic()
    result = {
        'source_revision': revision, 'base': BASE,
        'docker_endpoint': 'unix:///var/run/docker.sock',
        'cgroup_limit_proof': True, 'network': 'none', 'cpu_limit': 2,
        'memory_limit_bytes': 4 * 1024**3, 'timeout_s': 900,
        'workspace_mount': 'read-only', 'container_user': f'{os.getuid()}:{os.getgid()}',
        'pytest_tmp_directory': str(BENCH_TMP), 'pytest_cache_provider': 'disabled',
        'disk_reserve_bytes': RESERVE,
        'disk_free_initial_bytes': shutil.disk_usage(OUT).free,
        'status': 'starting',
        'data': {'rows': 3000000, 'extra_columns': 28, 'varied_inputs': True, 'synthetic_input': True},
    }
    persist(result)
    created = False
    try:
        command(
            'run', '-d', '--name', NAME,
            '--memory', '4g', '--memory-swap', '4g', '--cpus', '2', '--pids-limit', '256',
            '--network', 'none', '--user', result['container_user'],
            '--workdir', str(ROOT / 'backend'),
            '--mount', f'type=bind,src={ROOT},dst={ROOT},readonly',
            '--mount', f'type=bind,src={OUT},dst={OUT}',
            '--mount', f'type=bind,src={RUNTIME},dst={RUNTIME},readonly',
            '-e', f'TMPDIR={BENCH_TMP}', '-e', f'HOME={BENCH_HOME}',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'AGENTIUM_DISABLE_DOTENV=1',
            '-e', 'AGENTIUM_VOLUME_BENCHMARK_ROWS=3000000',
            '-e', 'AGENTIUM_VOLUME_BENCHMARK_EXTRA_COLUMNS=28',
            '-e', 'AGENTIUM_VOLUME_BENCHMARK_VARIED=1',
            '-e', f'AGENTIUM_VOLUME_BENCHMARK_REPORT={REPORT}',
            BASE, 'sleep', 'infinity', check=True, stdout=subprocess.DEVNULL,
        )
        created = True
        result['before'] = metrics()
        if result['before']['memory.max'] != str(4 * 1024**3) or result['before']['memory.swap.max'] != '0' or result['before']['cpu.max'] != '200000 100000':
            raise RuntimeError('Effective cgroup limits do not match the qualification contract')
        result['status'] = 'running'
        persist(result)
        with (OUT / 'scoring-3m.log').open('w') as log:
            proc = subprocess.Popen(
                DOCKER + ['exec', NAME, str(ROOT / '.venv/bin/python'), '-m', 'pytest',
                          'app/tests/scripts/test_dataops_showcase.py::test_benchmark_uses_real_preparation_and_native_model',
                          '-q', '-p', 'no:cacheprovider'],
                env=ENV, stdout=log, stderr=subprocess.STDOUT,
            )
            test_started = time.monotonic()
            last_checkpoint = test_started
            while proc.poll() is None:
                now = time.monotonic()
                free = shutil.disk_usage(OUT).free
                if now - test_started > 900 or free < RESERVE:
                    result['status'] = 'timeout' if now - test_started > 900 else 'disk_guard'
                    result['disk_free_at_stop_bytes'] = free
                    result['after'] = metrics()
                    command('stop', '-t', '5', NAME, stdout=subprocess.DEVNULL)
                    break
                if now - last_checkpoint >= 15:
                    result['elapsed_seconds'] = now - started
                    result['latest_cgroup'] = metrics()
                    persist(result)
                    last_checkpoint = now
                time.sleep(2)
            result['exit_code'] = proc.wait(timeout=30)
        if 'after' not in result:
            result['after'] = metrics()
        result['elapsed_seconds'] = time.monotonic() - started
        if result['status'] == 'running':
            result['status'] = 'passed' if result['exit_code'] == 0 else 'failed'
        result['source_revision_after'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        result['working_tree_clean_after'] = not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip()
    except BaseException as exc:
        result.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'error',
                      error_type=type(exc).__name__, error=str(exc), elapsed_seconds=time.monotonic() - started)
        raise
    finally:
        if created:
            try:
                result['container_oom_killed'] = json.loads(output('inspect', '--format', '{{json .State.OOMKilled}}', NAME))
            except Exception:
                result['container_oom_killed'] = None
            command('rm', '-f', NAME, stdout=subprocess.DEVNULL)
            result['container_removed'] = True
        result['disk_free_final_bytes'] = shutil.disk_usage(OUT).free
        persist(result)
    print(json.dumps(result))
    return result.get('exit_code', 1)


if __name__ == '__main__':
    raise SystemExit(main())
