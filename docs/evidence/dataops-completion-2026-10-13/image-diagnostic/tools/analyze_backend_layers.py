"""Stream header sizes from existing diagnostic layers without extracting data."""
import collections
import gzip
import json
from pathlib import Path
import tarfile
import time

ROOT = Path('/workspace/dataops-image-qualification/diagnostic-64a10ba9')
PREFIX = 'usr/local/lib/python3.12/site-packages/'


def package_name(path):
    if not path.startswith(PREFIX):
        return None
    part = path[len(PREFIX):].split('/', 1)[0]
    for name in ('sqlglot', 'deltalake'):
        if part == name or part == name + '.libs' or (part.startswith(name + '-') and part.endswith('.dist-info')):
            return name
    if part == 'arro3' and path[len(PREFIX):].startswith('arro3/core/'):
        return 'arro3-core'
    if part.startswith('arro3_core-') and part.endswith('.dist-info'):
        return 'arro3-core'
    return None


def main():
    started = time.monotonic()
    measured = json.loads((ROOT / 'backend.measurement.json').read_text())['images'][0]
    results = []
    labels = {7: 'common_application_dependencies', 11: 'conditional_HF1_install', 15: 'COPY_context'}
    with tarfile.open(ROOT / 'backend.oci.tar', 'r:') as outer:
        for index, label in labels.items():
            descriptor = measured['layers'][index]
            blob = outer.extractfile('blobs/sha256/' + descriptor['digest'].split(':', 1)[1])
            native = collections.Counter()
            packages = collections.Counter()
            roots = collections.Counter()
            payload = files = terraform = 0
            with gzip.GzipFile(fileobj=blob) as decoded, tarfile.open(fileobj=decoded, mode='r|') as inner:
                while (entry := inner.next()) is not None:
                    path = entry.name.removeprefix('./')
                    payload += entry.size
                    files += 1
                    name = package_name(path)
                    if name:
                        native[name] += entry.size
                    if path.startswith(PREFIX):
                        packages[path[len(PREFIX):].split('/', 1)[0]] += entry.size
                    roots['/'.join(path.split('/')[:2])] += entry.size
                    if '/.terraform/' in '/' + path:
                        terraform += entry.size
                    # tarfile caches member metadata by default, even in stream
                    # mode; no later operation needs those objects here.
                    inner.members.clear()
            blob.close()
            if payload != descriptor['tar_entry_payload_bytes']:
                raise RuntimeError('Layer header sum differs from prior integrity-verified OCI measurement')
            result = {
                'layer_index': index, 'label': label, 'digest': descriptor['digest'],
                'diff_id': descriptor['diff_id'], 'tar_entry_payload_bytes': payload,
                'entries': files, 'dataops_distribution_bytes': dict(native),
                'terraform_cache_payload_bytes': terraform,
                'largest_site_packages_entries': [{'name': name, 'bytes': size} for name, size in packages.most_common(20)],
                'largest_root_prefixes': [{'prefix': name, 'bytes': size} for name, size in roots.most_common(12)],
            }
            results.append(result)
            print(json.dumps({'layer': index, 'payload_bytes': payload, 'dataops': dict(native), 'terraform_cache_bytes': terraform}), flush=True)
    dataops = sum(sum(layer['dataops_distribution_bytes'].values()) for layer in results)
    final = {
        'classification': 'diagnostic; no historical baseline image reconstructed',
        'source_revision': '64a10ba9e9329b5d8d203ecc786254bbdcee7e19',
        'method': 'Header payload-size sums in three existing verified gzip layers; no extraction and no package execution.',
        'layers': results, 'dataops_three_distribution_total_bytes': dataops,
        'dataops_attribution_scope': 'sqlglot, deltalake (including bundled libs), arro3.core module and their dist-info/bytecode; shared preexisting dependencies not charged twice.',
        'limits': ['Package byte attribution is not the result of rebuilding ad10dbc2.', 'Current pycache and installed wheel bytes are counted.', 'The Deprecated version pin can change a shared package; it is not claimed as a wholly new DataOps package.', 'Subtracting HF/context/package bytes is arithmetic on this image, not a qualified image with features removed.'],
        'seconds': round(time.monotonic() - started, 3),
    }
    (ROOT / 'backend-package-attribution.json').write_text(json.dumps(final, indent=2) + '\n')
    print(json.dumps({'dataops_three_distribution_total_bytes': dataops, 'seconds': final['seconds']}), flush=True)


if __name__ == '__main__':
    main()
