"""Bundle small audited OCI metadata and tools; never layers, CA or credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

REPO = Path('/workspace/omnirag')
WORK = Path('/workspace/dataops-image-qualification')
ALLOW_ENV = {
    'PATH', 'LANG', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256',
    'DEBIAN_FRONTEND', 'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE',
    'PYTHONPATH', 'AGENTIUM_IMAGE_REVISION',
}
REPORT_NAMES = [
    'backend.build.json', 'worker.build.json',
    'backend.measurement.json', 'worker.measurement.json', 'images.measurement.json',
    'backend.import-smoke.build.json', 'worker.import-smoke.build.json',
    'backend.import-smoke.result.json', 'worker.import-smoke.result.json',
    'base-docker-inspect.json', 'builder-environment.json', 'builder-metrics.jsonl',
    'backend-layer-breakdown-corrected.json', 'backend-package-attribution.json',
    'backend-attribution-summary.json',
]
SCRIPT_NAMES = ['measure_oci.py', 'build.py', 'prepare_build.py', 'image_import_smoke.py', 'test_measure_oci.py', 'analyze_backend_layers.py']
INPUT_NAMES = [
    'docker/Dockerfile.agentium-backend', 'docker/Dockerfile.agentium-worker',
    'docker/Dockerfile.agentium-backend.dockerignore', 'docker/Dockerfile.agentium-worker.dockerignore',
    'backend/requirements.txt', 'backend/constraints-demo-app.txt',
    'backend/requirements_hf_rag.txt', 'backend/constraints-demo-ml-deep.txt',
    'backend/requirements_giskard.txt', 'backend/constraints-demo-giskard.txt',
    'scripts/agentium-image-budget.sh', 'scripts/agentium-vm-build.sh',
]


def small_copy(source, destination):
    if source.stat().st_size > 8 * 1024**2:
        raise ValueError('Unexpectedly large evidence file')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def descriptor_bytes(archive, descriptor):
    algorithm, digest = descriptor['digest'].split(':', 1)
    if algorithm != 'sha256' or descriptor['size'] > 8 * 1024**2:
        raise ValueError('Unexpected OCI metadata descriptor')
    with archive.extractfile('blobs/sha256/' + digest) as stream:
        raw = stream.read(8 * 1024**2 + 1)
    if len(raw) != descriptor['size'] or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('OCI metadata integrity mismatch')
    return raw


def export_metadata(source, destination, name, revision):
    result = {}
    with tarfile.open(source, 'r:') as archive:
        with archive.extractfile('index.json') as stream:
            raw_index = stream.read(8 * 1024**2 + 1)
        if len(raw_index) > 8 * 1024**2:
            raise ValueError('Oversized OCI index')
        index = json.loads(raw_index)
        if len(index['manifests']) != 1:
            raise ValueError('Expected one non-attested qualification image')
        descriptor = index['manifests'][0]
        raw_manifest = descriptor_bytes(archive, descriptor)
        manifest = json.loads(raw_manifest)
        raw_config = descriptor_bytes(archive, manifest['config'])
        config = json.loads(raw_config)
        # Exact config bytes are kept, so first verify that all environment
        # entries are the public base/release variables expected by Dockerfiles.
        env_names = {entry.split('=', 1)[0] for entry in config.get('config', {}).get('Env', [])}
        if not env_names <= ALLOW_ENV:
            raise ValueError('OCI config has unreviewed environment names; not bundled')
        if config.get('config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != revision:
            raise ValueError('OCI revision differs from requested evidence anchor')
        for raw in (raw_index, raw_manifest, raw_config):
            if re.search(rb'https?://[^/\s:@]+:[^/\s@]+@', raw) or b'PRIVATE KEY-----' in raw:
                raise ValueError('Credential-shaped metadata refused')
        destination.mkdir(parents=True, exist_ok=True)
        for suffix, raw in [('index', raw_index), ('manifest', raw_manifest), ('config', raw_config)]:
            path = destination / f'{name}.{suffix}.json'
            path.write_bytes(raw)
            result[suffix] = {'file': path.name, 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}
        result['environment_audit'] = {'allowed_public_names_only': True, 'names': sorted(env_names)}
        result['layer_count'] = len(manifest['layers'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--classification', choices=['diagnostic', 'final-measurement'], required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    for name in REPORT_NAMES:
        source = args.source / name
        if source.exists():
            small_copy(source, args.output / 'reports' / name)
    tooling = args.source / 'tooling' if (args.source / 'tooling').exists() else WORK
    for name in SCRIPT_NAMES:
        source = tooling / name
        if not source.exists():
            source = WORK / name
        small_copy(source, args.output / 'tools' / name)
    small_copy(Path(__file__), args.output / 'tools' / Path(__file__).name)
    small_copy(Path('/workspace/dataops-completion-2026-10-13/run_cgroup_benchmark.py'), args.output / 'tools' / 'run_cgroup_benchmark.py')
    for name in ('backend', 'worker'):
        for suffix in ('', '.dockerignore', '.import-smoke', '.import-smoke.dockerignore'):
            source = tooling / f'Dockerfile.{name}{suffix}'
            if source.exists():
                small_copy(source, args.output / 'qualification-dockerfiles' / source.name)
    for name in INPUT_NAMES:
        destination = args.output / 'source-inputs' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(subprocess.check_output(['git', 'show', args.revision + ':' + name], cwd=REPO))
    metadata = {}
    for name in ('backend', 'worker'):
        image = args.source / f'{name}.oci.tar'
        if image.exists():
            metadata[name] = export_metadata(image, args.output / 'oci-metadata', name, args.revision)
    files = {}
    for path in sorted(args.output.rglob('*')):
        if path.is_file():
            files[str(path.relative_to(args.output))] = {'size_bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {
        'classification': args.classification, 'source_revision': args.revision,
        'contains': 'Small reports, exact OCI index/manifest/config bytes, public source inputs and inspection/build scripts.',
        'excludes': ['OCI layer archives', 'CA trust bundles', 'Docker credential configuration', 'Terraform state', 'private runtime environment variables'],
        'oci_metadata': metadata, 'files': files,
        'reproduction': [
            'Obtain the complete source repository at source_revision; this bundle is not a full source checkout.',
            'Use a local dedicated BuildKit builder with fuse-overlayfs, effective 4GiB/no-swap and2CPU limits, and the public pinned Python base.',
            'Configure the session proxy and CA externally. No certificate or credential is bundled.',
            'Adapt external workspace paths in tooling if needed, then prepare_build.py and build.py generate the OCI archive without Docker load.',
            'Run measure_oci.py against that archive; it verifies compressed hashes and diff_ids, then separately counts compressed bytes, uncompressed tar bytes and hdr.Size payload bytes.',
            'The existing local Python base image can validate the same four diff_ids and exact Docker inspect.Size accounting without loading the application image.',
            'Import smokes are separate cache-only BuildKit targets; no FastAPI lifespan or external services are started.',
        ],
        'limits': [
            'Historical Docker choices being unchanged does not prove the size of a historical image.',
            'No byte-identical rebuild is promised: OS package repositories and generated timestamps are not fully frozen by Python constraints.',
            'This bundle does not imply VM deployment, all-image budget approval, or production/runtime qualification.',
            'Any arithmetic excluding layer/package bytes is not a measured replacement image.',
            'The benchmark wrapper is supplied as tooling; its presence alone is not evidence of an executed benchmark.',
        ],
    }
    (args.output / 'bundle-index.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'bundle': str(args.output), 'files': len(files)+1, 'bytes': sum(path.stat().st_size for path in args.output.rglob('*') if path.is_file()), 'images_with_exact_metadata': sorted(metadata)}))


if __name__ == '__main__':
    main()
