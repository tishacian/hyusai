"""Tiny synthetic OCI fixtures test only the measurement helper, not images."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from measure_oci import measure


def make_archive(destination, *, bad_diff_id=False):
    data = b'actual payload\n' * 100
    layer_buffer = io.BytesIO()
    with tarfile.open(fileobj=layer_buffer, mode='w') as layer:
        member = tarfile.TarInfo('app/example.txt')
        member.size = len(data)
        layer.addfile(member, io.BytesIO(data))
        directory = tarfile.TarInfo('data/')
        directory.type = tarfile.DIRTYPE
        layer.addfile(directory)
        link = tarfile.TarInfo('app/example-link')
        link.type = tarfile.SYMTYPE
        link.linkname = 'example.txt'
        layer.addfile(link)
    raw = layer_buffer.getvalue()
    compressed = gzip.compress(raw, mtime=0)
    blobs = {}
    def blob(content, media):
        digest = hashlib.sha256(content).hexdigest()
        blobs[f'blobs/sha256/{digest}'] = content
        return {'digest': 'sha256:' + digest, 'size': len(content), 'mediaType': media}
    layer = blob(compressed, 'application/vnd.oci.image.layer.v1.tar+gzip')
    config = blob(json.dumps({
        'os': 'linux', 'architecture': 'amd64',
        'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + ('0'*64 if bad_diff_id else hashlib.sha256(raw).hexdigest())]},
        'config': {'Labels': {'org.opencontainers.image.revision': 'synthetic-helper-test-only'}},
    }).encode(), 'application/vnd.oci.image.config.v1+json')
    manifest = blob(json.dumps({'schemaVersion': 2, 'config': config, 'layers': [layer]}).encode(), 'application/vnd.oci.image.manifest.v1+json')
    blobs['index.json'] = json.dumps({'schemaVersion': 2, 'manifests': [manifest]}).encode()
    blobs['oci-layout'] = b'{"imageLayoutVersion":"1.0.0"}'
    with tarfile.open(destination, mode='w') as archive:
        for name, content in blobs.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return len(data), len(raw), len(compressed)


class MeasurementTest(unittest.TestCase):
    def test_counts_actual_payload_separately_and_checks_all_layer_hashes(self):
        with tempfile.TemporaryDirectory(prefix='oci-helper-test-') as directory:
            path = Path(directory) / 'image.tar'
            payload, unpacked, compressed = make_archive(path)
            result = measure('backend', path)
            self.assertEqual(result['docker_graphdriver_comparable_size_bytes'], payload)
            self.assertEqual(result['uncompressed_layer_tar_bytes'], unpacked)
            self.assertEqual(result['compressed_layer_bytes'], compressed)
            self.assertEqual(result['layers'][0]['tar_entries'], 3)
            self.assertEqual(result['layers'][0]['integrity'], 'verified')
            self.assertGreater(unpacked, payload)

    def test_refuses_layer_diff_id_mismatch(self):
        with tempfile.TemporaryDirectory(prefix='oci-helper-test-') as directory:
            path = Path(directory) / 'image.tar'
            make_archive(path, bad_diff_id=True)
            with self.assertRaisesRegex(ValueError, 'diff_id mismatch'):
                measure('backend', path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
