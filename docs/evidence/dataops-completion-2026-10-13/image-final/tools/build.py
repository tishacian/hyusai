"""Build one local OCI archive with bounded dedicated BuildKit resources."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

WORK = Path('/workspace/dataops-image-qualification')
ROOT = Path('/workspace/agentium')
BUILDER = 'agentium-dataops-review'
CONTAINER = 'buildx_buildkit_agentium-dataops-review0'
RESERVE = 4 * 1024**3
BASE = 'python:3.12-slim@sha256:ec948fa5f90f4f8907e89f4800cfd2d2e91e391a4bce4a6afa77ba265bc3a2fe'


def persist(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    temp.replace(path)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def source_fingerprint():
    # Runtime inputs; docs are reported separately in git status.
    names = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard',
         'backend', 'docker', 'scripts', 'run_celery.sh'], cwd=ROOT,
    ).split(b'\0')
    digest = hashlib.sha256()
    count = 0
    for raw in sorted(set(names)):
        if not raw:
            continue
        path = ROOT / os.fsdecode(raw)
        if not path.is_file():
            continue
        content = hashlib.sha256(path.read_bytes()).hexdigest().encode()
        digest.update(raw + b'\0' + content + b'\n')
        count += 1
    return {'sha256': digest.hexdigest(), 'files': count,
            'scope': 'tracked and unignored files: backend, docker, scripts, run_celery.sh'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=['backend', 'worker'])
    parser.add_argument('revision')
    parser.add_argument('--smoke', action='store_true', help='Run a separate offline import stage, with cache-only output.')
    parser.add_argument('--tested-revision', required=True)
    parser.add_argument('--suite-marker', type=Path, default=Path('/workspace/dataops-completion-2026-10-13/backend-final-isolated.coordinator.finished.json'))
    args = parser.parse_args()
    if git('rev-parse', 'HEAD') != args.revision:
        raise SystemExit('Source HEAD differs from the explicitly requested qualification revision.')
    if git('status', '--porcelain'):
        raise SystemExit('Source working tree must be clean before image qualification.')
    if not args.suite_marker.is_file():
        raise SystemExit('Full backend suite has not produced its completion marker.')
    suite_result = json.loads(args.suite_marker.read_text())
    if suite_result.get('exit_code') != 0 or suite_result.get('failed') != 0 or suite_result.get('collected', 0) <= 0:
        raise SystemExit('Full backend suite did not finish successfully.')
    changes_since_test = git('diff', '--name-only', args.tested_revision, args.revision).splitlines()
    if any(not path.startswith('docs/') for path in changes_since_test):
        raise SystemExit('Non-documentation changes exist after the tested code revision.')
    env = dict(os.environ)
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    docker = ['docker', '--host=unix:///var/run/docker.sock']
    config_path = Path.home() / '.docker/config.json'
    config = json.loads(config_path.read_text()).get('proxies', {}).get('default', {}) if config_path.exists() else {}
    for key, cfg in [('HTTP_PROXY', 'httpProxy'), ('HTTPS_PROXY', 'httpsProxy'), ('NO_PROXY', 'noProxy')]:
        if config.get(cfg):
            env[key] = config[cfg]
    inspect = json.loads(subprocess.check_output(
        docker + ['inspect', '--format', '{{json .HostConfig}}', CONTAINER], env=env,
    ))
    limits = {key: inspect.get(key) for key in ('Memory', 'MemorySwap', 'NanoCpus', 'CpuPeriod', 'CpuQuota', 'CgroupnsMode', 'CgroupParent')}
    two_cpus = limits['NanoCpus'] == 2_000_000_000 or (limits['CpuPeriod'], limits['CpuQuota']) == (100000, 200000)
    if (limits['Memory'], limits['MemorySwap']) != (4 * 1024**3, 4 * 1024**3) or not two_cpus:
        raise SystemExit('Dedicated builder must first be limited to 4 GiB, no swap, and 2 CPUs.')
    free = shutil.disk_usage(WORK).free
    if free < RESERVE:
        raise SystemExit('Local disk free space is below the unchanged 4 GiB reserve.')
    run_name = f'{args.name}.import-smoke' if args.smoke else args.name
    dockerfile = WORK / f'Dockerfile.{run_name}'
    output = WORK / f'{args.name}.oci.tar'
    if not args.smoke and output.exists():
        raise SystemExit('OCI archive already exists; preserve or explicitly remove the prior attempt first.')
    metadata = WORK / f'{run_name}.buildkit-metadata.json'
    command = docker + [
        'buildx', 'build', '--builder', BUILDER, '--progress', 'plain', '--provenance=false',
        '--platform', 'linux/amd64', '--metadata-file', str(metadata),
        '--secret', 'id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt',
        '--build-arg', f'PYTHON_BASE_IMAGE={BASE}',
        '--build-arg', 'PIP_INDEX_URL=https://pypi.org/simple',
        '--build-arg', 'INSTALL_HF_RAG=1',
        '--build-arg', f'AGENTIUM_IMAGE_REVISION={args.revision}',
    ]
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'):
        command.extend(['--build-arg', key])
    if args.name == 'worker':
        command.extend(['--build-arg', 'INSTALL_GISKARD_RAGET=true'])
    if args.smoke:
        command.extend([
            '--secret', f'id=image_import_smoke,src={WORK / "image_import_smoke.py"}',
            '--target', 'agentium_import_smoke', '--no-cache-filter', 'agentium_import_smoke',
            '--output', 'type=cacheonly',
        ])
    else:
        command.extend(['--output', f'type=oci,dest={output}', '-t', f'agentium-{args.name}:dataops-review'])
    command.extend(['-f', str(dockerfile), str(ROOT)])
    report_path = WORK / f'{run_name}.build.json'
    report = {
        'status': 'running', 'image': args.name, 'revision_label': args.revision,
        'tested_code_revision': args.tested_revision,
        'full_backend_suite_marker': str(args.suite_marker),
        'full_backend_suite_result': suite_result,
        'only_documentation_changes_after_tested_code': True,
        'source_head_start': git('rev-parse', 'HEAD'),
        'source_status_start': git('status', '--porcelain').splitlines(),
        'source_fingerprint_start': source_fingerprint(),
        'docker_endpoint': 'unix:///var/run/docker.sock',
        'builder': BUILDER, 'builder_limits': limits,
        'base_image': BASE, 'platform': 'linux/amd64',
        'output_format': 'cache-only separate offline import stage' if args.smoke else 'OCI archive; no Docker load',
        'import_smoke_only': args.smoke,
        'install_hf_rag': 1, 'install_giskard_raget': args.name == 'worker',
        'disk_reserve_bytes': RESERVE, 'disk_free_initial_bytes': free,
        'disk_free_minimum_bytes': free, 'disk_guard': None,
        'original_dockerfile_sha256': hashlib.sha256((ROOT / f'docker/Dockerfile.agentium-{args.name}').read_bytes()).hexdigest(),
        'qualification_dockerfile_sha256': hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
        'dockerfile_adaptation': 'Public proxy CA as BuildKit secret on RUN only; no trust bundle in final layers.',
        'runtime_qualification': False,
    }
    persist(report_path, report)
    started = time.monotonic()
    last_checkpoint = started
    if args.smoke:
        report['import_smoke_script_sha256'] = hashlib.sha256((WORK / 'image_import_smoke.py').read_bytes()).hexdigest()
    with (WORK / f'{run_name}.log').open('w') as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        report['build_client_pid'] = proc.pid
        persist(report_path, report)
        try:
            while proc.poll() is None:
                free = shutil.disk_usage(WORK).free
                report['disk_free_minimum_bytes'] = min(free, report['disk_free_minimum_bytes'])
                if free < RESERVE:
                    report['disk_guard'] = {'free_bytes': free, 'reserve_bytes': RESERVE}
                    os.killpg(proc.pid, signal.SIGINT)
                    break
                if time.monotonic() - last_checkpoint >= 15:
                    report['seconds'] = round(time.monotonic() - started, 3)
                    persist(report_path, report)
                    last_checkpoint = time.monotonic()
                time.sleep(2)
            try:
                code = proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                code = proc.wait()
        except BaseException:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGINT)
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            report.update(status='interrupted', seconds=round(time.monotonic() - started, 3))
            persist(report_path, report)
            raise
    report.update(
        exit_code=code, seconds=round(time.monotonic() - started, 3),
        status=('import_passed' if args.smoke else 'built') if code == 0 else 'failed',
        disk_free_final_bytes=shutil.disk_usage(WORK).free,
        source_head_end=git('rev-parse', 'HEAD'),
        source_fingerprint_end=source_fingerprint(),
        archive_bytes=output.stat().st_size if not args.smoke and output.exists() else None,
    )
    report['runtime_source_unchanged_during_build'] = report['source_fingerprint_start'] == report['source_fingerprint_end']
    persist(report_path, report)
    print(json.dumps(report))
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    raise SystemExit(main())
