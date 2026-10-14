"""Collect the final frozen-source test proof; never infer image/benchmark results."""
from collections import Counter
import hashlib
import importlib.metadata as md
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path('/workspace/agentium')
BASE = Path('/workspace/dataops-completion-2026-10-13')
ANCHOR = 'bd72404472bfd57c01cc2e4a9747ff5e3049814f'
PREFIX = 'backend-final-isolated'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def file_proof(name):
    path = BASE / name
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


finished = json.loads((BASE / f'{PREFIX}.coordinator.finished.json').read_text())
assert finished['exit_code'] == 0 and finished['failed'] == 0, finished
records = [json.loads(line) for line in (BASE / f'{PREFIX}.coordinator.jsonl').read_text().splitlines()]
counts = Counter(record['outcome'] for record in records)
assert counts.get('failed', 0) == 0 and sum(counts.values()) == finished['collected'], counts
assert len({record['nodeid'] for record in records}) == finished['collected']
log_text = (BASE / f'{PREFIX}.log').read_text()
summary = re.search(r'(\d+) passed, (\d+) skipped, .*? in ([\d.]+)s', log_text)
assert summary and int(summary[1]) == counts['passed'] and int(summary[2]) == counts['skipped']
assert not git('diff', ANCHOR, '--', '.', ':!docs'), 'Non-documentation source changed after qualification'
for stem, expected in [('compliance-isolated.log', 'Agentium compliance check passed'),
                       ('dependencies-isolated.log', 'All installed packages are compatible')]:
    assert expected in (BASE / stem).read_text(), stem

report = {
    'qualification_anchor': ANCHOR,
    'scope': 'Final Linux backend suite after isolated previews and deterministic RAG deadline test. Images and scoring are independently reported.',
    'source_note': 'Source frozen at this exact commit throughout the full test suite and subsequent image/benchmark qualification. Later proof-only documentation commits do not change runtime source.',
    'backend_tree': git('rev-parse', ANCHOR + ':backend'),
    'frontend_tree': git('rev-parse', ANCHOR + ':frontend-ng'),
    'backend': {
        'command': 'PYTHONPATH=/workspace/dataops-completion-2026-10-13:$PYTHONPATH QUALIFICATION_REPORT_PREFIX=/workspace/dataops-completion-2026-10-13/backend-final-isolated TMPDIR=/workspace/dataops-completion-2026-10-13/tmp ../.venv/bin/pytest -q -n 4 --dist=loadfile -p qualification_reporter',
        'cwd': str(ROOT / 'backend'),
        **finished, **dict(counts), 'seconds': float(summary[3]),
        'selected_exclusions': [],
        'logs': [file_proof(f'{PREFIX}.log'), file_proof(f'{PREFIX}.coordinator.jsonl'),
                 file_proof(f'{PREFIX}.coordinator.finished.json')],
        'skip_counts_by_file': dict(sorted(Counter(record['nodeid'].split('::')[0]
            for record in records if record['outcome'] == 'skipped').items())),
    },
    'checks': {
        'compliance': {'exit_code': 0, 'static_claims_verified': 16, 'total_claims': 22,
                       'log': file_proof('compliance-isolated.log')},
        'dependency_consistency': {'exit_code': 0, 'packages': 232,
                                   'log': file_proof('dependencies-isolated.log')},
        'kubernetes_scaffold': {
            'exit_code': 0, 'helm': True, 'terraform_validate': True, 'ansible_syntax': True, 'apply': False,
            'scope': 'Earlier completed check on unchanged deployment sources; not re-executed for the preview-only source changes.',
            'log': file_proof('k8s-final.log'),
        },
    },
    'dedicated_suites': {
        'compiler_flow_and_business_parity': 'compiler-flow.json',
        'samples_and_recovery': 'samples.json', 'multipart_minio_and_volume': 'd3-validation.json',
        'frontend_scope': 'frontend.json', 'corrected_regressions': 'regressions.json',
        'isolated_previews': 'preview-isolation.json', 'rag_deadline': 'rag-deadline.json',
    },
    'environment': {
        'os': platform.system(), 'arch': platform.machine(), 'python': sys.version.split()[0],
        'packages': {name: md.version(name) for name in ['pytest', 'pytest-xdist', 'duckdb',
            'pyarrow', 'deltalake', 'arro3-core', 'sqlglot', 'polars', 'scikit-learn', 'torch']},
    },
    'immutable_documents_sha256': {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ['docs/agentium-dataops-plan.md', 'docs/codex-review-dataops-typed-judge.md']
    },
    'limitations': [
        'SQLite and eager/local workers in the ordinary backend suite; no deployed PostgreSQL/RabbitMQ/HANA qualification.',
        'Skipped external-service, Helm and MinIO tests are enumerated; successful dedicated runs have their own source scope.',
        'Frontend full unit suite preceded the final recursive serializer correction; see final targeted/browser/build scopes in frontend.json.',
        'No HANA connection, VM deployment, build-info check, token revocation or Gemini/OpenRouter qualification.',
        'Full Alembic history from empty PostgreSQL still blocks at migration 013; earlier targeted 125-to-126 proof is unchanged.',
        'Original-plan acceptance criteria remain open; a passing suite does not close them.',
        'The preview child virtual-address-space guard does not attest a total API/cgroup RSS limit.',
    ],
}
(BASE / 'validation-final.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'anchor': ANCHOR, 'backend': {**finished, **dict(counts), 'seconds': float(summary[3])}}))
