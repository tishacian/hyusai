"""Three synthetic Golden verdict checks; no publication or human decision.

Run on carakai. Default preflight is read-only. --submit uses one fixed request
key; --poll only reads retained Runs. A timeout never causes a replacement Run.
"""
import argparse
import fcntl
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('/opt/agentium-protected-runner/repos/omnirag')
sys.path.insert(0, str(ROOT / 'scripts/qualification'))
from observability_live import Client
sys.path.insert(0, str(ROOT / 'backend'))
from scripts.showcase_operational_analysis import EXPECTED

SHA = '6f8f81696db0a736c2facfa32e97976d4d55db09'
SYSTEM = '15b05919-c93b-4648-8581-8a41cbe2fae6'
FLOW_SHA = 'f1cdd9b755357f0960c334129f09e9106c63c4a49d9fa1937829dc01ae59d14d'
REPORT = Path('/tmp/golden-verdicts-6f8f8169.json')
parser = argparse.ArgumentParser(description=__doc__)
mode = parser.add_mutually_exclusive_group()
mode.add_argument('--submit', action='store_true')
mode.add_argument('--poll', action='store_true')
args = parser.parse_args()
os.umask(0o077)
lock = REPORT.with_suffix('.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
client = Client('https://agentium.papai.ai/api/v1', '/root/.attestation-username', '/root/.attestation-password')
assert client.call('/build-info')['revision'] == SHA
state = json.loads(REPORT.read_text()) if REPORT.exists() else {'sha': SHA, 'system_id': SYSTEM}
assert state['sha'] == SHA and state['system_id'] == SYSTEM

def save():
    tmp = REPORT.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(REPORT)

if not args.poll:
    system = client.call(f'/systems/{SYSTEM}')
    assert system['workspace_id'] == 'e2ed9e40-5fa6-4e32-8948-3e1220134fd3'
    published = client.call(f'/systems/{SYSTEM}/flow-state')['published']
    assert published['version_id'] == 'e997f4e4-3b51-4eef-9481-389f3a9afae4'
    assert published['flow_sha256'] == FLOW_SHA
    request = {'acknowledge_real_side_effects': True,
        'flow_definition': published['flow_definition'], 'expected_flow_sha256': FLOW_SHA,
        'request_key': '6f8f8169-technical-golden-verdicts-1', 'ingress_id': 'src', 'kind': 'manual',
        'cases': [
            {'id': 'numerical-reference', 'input_ref': {}, 'expected': {'stats': EXPECTED, 'human_validated': False}},
            {'id': 'intentional-negative-control', 'input_ref': {}, 'expected': {'stats': {'overrun_minutes': -1}}},
            {'id': 'no-oracle', 'input_ref': {}},
        ]}
    assert state.get('request', request) == request
    state['request'] = request
    save()
    if not args.submit:
        print(json.dumps({'preflight': 'ready', 'report': str(REPORT)}))
        sys.exit(0)
    state['receipt'] = client.call(f'/systems/{SYSTEM}/flow-workbench/golden-runs', request)
    save()

assert state.get('receipt'), 'Missing receipt; replay --submit with the same request key, never replace it.'
expected_verdicts = {'numerical-reference': 'passed', 'intentional-negative-control': 'failed', 'no-oracle': 'unevaluated'}
deadline = time.monotonic() + 240
while True:
    runs = [client.call('/runs/' + row['id']) for row in state['receipt']['runs']]
    state['runs'] = runs
    save()
    if all(r['status'] not in {'created', 'queued', 'pending', 'running'} for r in runs):
        break
    if time.monotonic() >= deadline:
        raise RuntimeError('Still active; resume --poll, do not replace these Runs')
    time.sleep(3)
for run in runs:
    result = run.get('test_result') or {}
    assert run['status'] == 'completed', run['id']
    assert run['output_ref']['stats'] == EXPECTED, run['id']
    assert result['verdict'] == expected_verdicts[result['case_id']], result
    print(json.dumps({'run_id': run['id'], 'status': run['status'], 'test_result': result}), flush=True)
replay = client.call(f'/systems/{SYSTEM}/flow-workbench/golden-runs', state['request']) if args.submit else None
if replay:
    assert {r['id'] for r in replay['runs']} == {r['id'] for r in runs}
    state['idempotent_replay_verified'] = True
state['status'] = 'verified'
save()
